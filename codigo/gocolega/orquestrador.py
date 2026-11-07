"""Orquestrador da Maya: triagem -> sub-agente -> guardioes -> acao (ou 'levantar a mao').

Modelos (ver modelos.py): Jev na triagem; modelo PRINCIPAL (terra) roteia casos ambiguos e resume para o
supervisor; modelo SUB (luna) julga a foto e escreve as respostas. O modelo PROPOE; o codigo VALIDA:
limite, prazo, papel e segregacao ficam no Policy Engine. Sem token, tudo roda so com codigo.
"""
import re
from dataclasses import dataclass, field
from datetime import datetime

from . import agentes, conhecimento, dados, detetive, dialogo, duvida, llm, politica, rastreio, rotas_gerais
from .ferramentas import Ferramentas, mascarar_pii
from .rotas_gerais import elegivel_brinde  # noqa: F401  (reexportado: testes e demo importam daqui)

# Segundo assunto na mesma mensagem ("Ah, e...", "Aproveitando,", "Outra coisa:"). A base marca ~9% das conversas assim.
SEGUNDO_ASSUNTO = re.compile(r"\bah,?\s+e\b|\boutra coisa\b|\boutra d[uú]vida\b|\baproveitando\b|\bmais uma (?:coisa|pergunta|d[uú]vida)\b|"
                             r"\bal[eé]m disso\b|\bps:?\s", re.I)
# Quem ja recebeu uma acao de dinheiro nesta conversa nao ganha outra no segundo assunto sem uma pessoa ver.
ACOES_DINHEIRO = {"reenviar_produto", "reembolsar", "trocar_produto", "cancelar_pedido", "reimprimir_personalizacao"}
# Financeiro (cobranca em duplicidade) fica de fora: a rota ja confere o gateway e so devolve o valor cobrado a mais, que e outra transacao.
CATEGORIAS_DINHEIRO = {"Avaria", "Produto faltando", "Reclamacao produto", "Troca", "Cancelamento"}
# Do mais grave ao menos grave: o desfecho da conversa e o pior dos dois assuntos.
ORDEM_DESFECHO = ["sensivel", "suspeita", "escalado", "aguardando_supervisor", "aguardando_aprovacao",
                  "aguardando_cliente", "fora_da_politica", "autonomo"]
# SLA de primeira resposta humana por canal (parametros.md): o cliente sabe QUANDO uma pessoa responde.
PRAZO_HUMANO = {"whatsapp": "em ate 30 minutos (atendemos das 8h as 20h)", "email": "em ate 24 horas",
                "reclame_aqui": "em ate 48 horas"}
ESTILO_CANAL = {"whatsapp": "WhatsApp: mensagem curta e informal, no maximo 3 frases",
                "email": "e-mail: cordial e um pouco mais completa",
                "reclame_aqui": "Reclame Aqui: tom formal e institucional, a resposta e publica, sem dados pessoais"}

FOTO_ANEXADA = re.compile(r"\[foto anexada\]|\[imagem\]", re.I)
TRANSITO = re.compile(r"em tr[aâ]nsito|rastre|onde est[aá]|status do pedido|previs[aã]o de entrega|n[aã]o anda|parado", re.I)
DEFEITO = re.compile(r"quebrad|amassad|danific|rachad|trincad|estourad|vazou|vazando|defeito|rasgad|descascand|zíper|ziper", re.I)
CATEGORIA_POLITICA = {"Avaria": "avaria_vazamento", "Produto faltando": "item_faltante",
                      "Reclamacao produto": "avaria_vazamento"}
# Respostas FIXAS de proposito: suspeita e caso sensivel nunca passam por modelo
# (a politica manda nao acusar o cliente e a orientacao de saude nao pode variar).
RESPOSTA_NEUTRA = ("Recebemos seu contato e estamos analisando o seu caso com cuidado. "
                   "Voltamos com uma resposta em ate 24 horas.")
RESPOSTA_ESPERA_DUVIDA = ("Obrigado pela pergunta! Ainda nao tenho essa informacao com seguranca, entao ja pedi a uma pessoa "
                          "da equipe para te responder {prazo}.")
RESPOSTA_ESPERA_SAUDE = ("Obrigado pela pergunta! Por ser uma questao de saude, ela precisa de uma pessoa especializada, que "
                         "ja foi acionada e te responde {prazo}. Enquanto isso, na duvida, consulte um profissional de saude antes de usar.")
RESPOSTA_ESPERA_GERAL = ("Recebi a sua mensagem e ja passei o seu caso, com o resumo do que aconteceu, para uma pessoa da "
                         "equipe, que te responde {prazo}. Voce nao precisa repetir nada.")
RESPOSTA_SENSIVEL = ("Lamentamos muito. Por seguranca, suspenda o uso do produto agora e procure atendimento "
                     "medico se o desconforto continuar. Nossa equipe tecnica ja foi acionada.")


# Abaixo disso o Jev e pouco confiavel (benchmark: 26% de acerto da categoria; 61% da rota).
LIMIAR_CONFIANCA = 0.70


def acao_de(categoria: str) -> tuple:
    """O que A Maya FARIA com a categoria. Duas categorias com a mesma acao nao precisam de consenso exato
    (ex.: Rastreio e Atraso). Avaria e Produto faltando seguem politicas diferentes, entao divergem."""
    if CATEGORIA_POLITICA.get(categoria):
        return ("pos_venda", CATEGORIA_POLITICA[categoria])
    if categoria in ("Rastreio", "Atraso"):
        return ("rastreio", None)
    return ("outras", None)  # qualquer outra vai para uma pessoa


@dataclass
class Resultado:
    conversation_id: str
    categoria: str = ""
    desfecho: str = ""  # autonomo | aguardando_cliente | aguardando_supervisor | aguardando_aprovacao (RA) | suspeita | sensivel | escalado | fora_da_politica
    passos: list[str] = field(default_factory=list)
    dossie: detetive.Dossie | None = None
    # a conversa entre os agentes neste caso: Guardiao, Redator e Verificador; o Detetive entra no pos-venda
    bus: "dialogo.Barramento" = field(default_factory=lambda: dialogo.montar())
    cliente: str = ""  # a mensagem do cliente: so para o TOM da resposta (acolhimento), nunca como fonte de fatos
    canal: str = ""  # whatsapp | email | reclame_aqui: ajusta o estilo do texto
    segundo: str | None = None  # texto do segundo assunto da mesma mensagem, tratado depois do primeiro

    def p(self, texto: str):
        self.passos.append(texto)

    def conversa(self) -> list[str]:
        return self.bus.linhas()


def _texto(r: Resultado, situacao: str, fatos: str, fallback: str) -> str:
    """Resposta ao cliente. Com token: conversa Redator (modelo) <-> Verificador (codigo), ate 2 revisoes, senao texto fixo.
    Sem token: texto fixo."""
    if not agentes.disponivel():
        return fallback
    estilo = ESTILO_CANAL.get(r.canal)
    if estilo:  # o estilo muda conforme o canal; os fatos continuam os mesmos
        situacao = f"{situacao} (estilo, {estilo})"
    try:
        return dialogo.redigir(r.bus, situacao, fatos, fallback, cliente=r.cliente)
    except dialogo.LimiteDeMensagens:  # dialogo longo demais: nunca derruba o caso, cai no texto fixo
        r.p("AVISO: dialogo entre agentes passou do limite de mensagens; usei o texto fixo")
        return fallback


def tratar(conversation_id: str, agora: datetime | None = None, texto_override: str | None = None,
           ferr: Ferramentas | None = None) -> tuple[Resultado, Ferramentas]:
    """Trata uma conversa. 'texto_override' permite simular mensagens novas (ex.: teste de injecao)."""
    agentes.avisos.clear()
    r, ferr = _tratar(conversation_id, agora, texto_override, ferr)
    # Segundo assunto na mesma mensagem: tratado pelo mesmo caminho (triagem, guardioes, politica), depois do primeiro.
    # Caso sensivel ou suspeito nao recebe um segundo assunto resolvido sozinho: uma pessoa ve o caso inteiro.
    if r.segundo and r.desfecho not in ("sensivel", "suspeita"):
        r2, _ = _tratar(conversation_id, agora, r.segundo, ferr, secundaria=True, anterior=r)
        r = _juntar(r, r2)
    for a in agentes.avisos:
        r.p(f"AVISO: {a}")
    agentes.avisos.clear()
    # Reclame Aqui: a resposta publica sai SEM aprovacao previa (decisao do projeto; DIARIO 33). O desfecho vale como nos outros canais.
    if any(e["ferramenta"] == "responder_cliente" and e.get("publico") for e in ferr.log):
        r.p("Resposta publica do Reclame Aqui enviada sem aprovacao previa (simulado); o texto passou pelo Verificador e pelo filtro de PII.")
    return r, ferr


def _dividir(texto: str) -> tuple[str, str | None]:
    """Separa o segundo assunto ('Ah, e nao veio o brinde'). Sem marcador claro ou com pouco texto antes/depois, nao divide."""
    m = SEGUNDO_ASSUNTO.search(texto)
    if not m or m.start() < 25:
        return texto, None
    primeiro = texto[:m.start()].strip()
    segundo = re.sub(r"^[\s,.:;\-—]*(?:e\s+)?", "", texto[m.end():], flags=re.I).strip()
    if len(segundo) < 15:
        return texto, None
    return primeiro, segundo


def _juntar(a: Resultado, b: Resultado) -> Resultado:
    """Une os dois assuntos: o desfecho e o PIOR dos dois (se um precisa de pessoa, a conversa precisa)."""
    a.p(f"--- Segundo assunto na mesma mensagem: '{b.categoria}' ---")
    a.passos += b.passos
    a.categoria = a.categoria if a.categoria == b.categoria else f"{a.categoria} + {b.categoria}"
    pior = min((a.desfecho, b.desfecho), key=lambda d: ORDEM_DESFECHO.index(d) if d in ORDEM_DESFECHO else 0)
    a.desfecho = pior
    a.dossie = a.dossie or b.dossie
    a.bus.transcricao += b.bus.transcricao
    return a


def _encaminhar(r: Resultado, ferr: Ferramentas, cid: str, area: str, assunto: str, contexto: str, urgencia: str = "normal",
                pedido: dict | None = None, espera: str | None = None):
    """Passa o caso a uma pessoa SEM deixar o cliente no vacuo: ele recebe o prazo do canal e a pessoa recebe o contexto e um
    rascunho de resposta para revisar (a pessoa so aprova ou ajusta). O rascunho nao e enviado ao cliente."""
    prazo = PRAZO_HUMANO.get(r.canal, "em breve")
    ferr.responder_cliente(cid, (espera or RESPOSTA_ESPERA_GERAL).format(prazo=prazo))
    fatos = f"Assunto: {assunto}. {contexto}"
    fallback = "Ola! Ja estou analisando o seu caso e volto com uma posicao."
    if pedido:
        fatos += (f" Pedido {pedido['order_id']} ({pedido.get('descricao_produto')}), status da entrega {pedido.get('status_entrega')}, "
                  f"entregue em {pedido.get('data_entrega')}.")
        fallback = f"Ola! Ja estou analisando o seu pedido {pedido['order_id']} e volto com uma posicao."
    rascunho = _texto(r, "rascunho de resposta para um atendente humano revisar antes de enviar; nao prometa reembolso, reenvio nem prazo",
                      fatos, fallback)
    return ferr.acionar_pessoa(area, assunto, f"{contexto}\n[rascunho sugerido, revisar antes de enviar] {rascunho}", urgencia)


def _esclarecer(r: Resultado, ferr: Ferramentas, cid: str, motivo: str, fatos: str | None = None, fallback: str | None = None):
    """Quando falta clareza, o agente PERGUNTA ao cliente em vez de chamar uma pessoa. Uma pessoa so entra em caso serio
    (saude, suspeita de fraude, valor acima do limite); ver DIARIO 36."""
    fatos = fatos or ("Nao ficou claro o que o cliente precisa. Pedir que conte com um pouco mais de detalhe o que aconteceu "
                      "e informe o numero do pedido, se tiver.")
    fallback = fallback or ("Quero te ajudar direitinho, mas nao consegui entender bem o que voce precisa. Pode me contar com mais "
                            "detalhes o que aconteceu e, se tiver, o numero do pedido?")
    ferr.responder_cliente(cid, _texto(r, "pedir mais detalhes ao cliente", fatos, fallback))
    r.desfecho = "aguardando_cliente"
    r.p(f"{motivo}: pedi mais detalhes ao cliente, sem chamar uma pessoa.")
    return r, ferr


def _tratar(conversation_id, agora, texto_override, ferr, secundaria: bool = False, anterior: "Resultado | None" = None):
    ferr = ferr or Ferramentas("atendente", "gocolega", agora)
    r = Resultado(conversation_id)

    dados_conv = ferr.ler_conversa(conversation_id)
    conv = dados_conv["conversa"]
    if conv is None:
        r.desfecho = "escalado"
        r.p(f"Conversa {conversation_id} nao encontrada")
        return r, ferr
    agora = agora or conv["data_abertura"]
    ferr.agora = agora
    ferr.canal = conv.get("canal")
    texto = texto_override or " ".join(m["texto"] for m in dados_conv["mensagens"] if m["autor"] == "cliente")
    r.canal = conv.get("canal") or ""
    if not secundaria:
        texto, r.segundo = _dividir(texto)
        if r.segundo:
            r.p(f"Duas demandas na mesma mensagem: trato a primeira e depois a segunda ('{r.segundo[:60]}...').")
    order_id = conv.get("order_id")

    # 1) Triagem (Jev + regras)
    t = llm.triagem(texto)
    r.categoria = t["categoria"]
    r.cliente = ferr.cliente = texto  # para o tom da resposta (modelo e acolhimento dos textos fixos)
    ferr.categoria_conversa = t["categoria"]
    r.p(f"Triagem ({t['fonte']}): {t['categoria']} (confianca {t['confianca']:.0%}); sensivel={t['sensivel']}; injecao={t['injecao']}")
    if t.get("aviso"):
        r.p(f"AVISO: {t['aviso']}")
    ferr.classificar_conversa(conversation_id, t["categoria"])

    # 2) Guardioes de entrada
    if t["injecao"]:
        r.p("GUARDIAO: o texto do cliente tenta dar ordens ao sistema. Tratado como DADO e ignorado; "
            "o caso segue pela politica normal.")
        ferr.acionar_pessoa("supervisao", "Possivel tentativa de manipulacao do atendimento",
                            f"Conversa {conversation_id}: o cliente tentou dar instrucoes ao sistema.", "baixa")

    # 3) Sensivel (prazo de 24h; so cosmeticos/suplementos GoBeaute; texto FIXO)
    if t["sensivel"] and str(conv.get("marca", "")).lower() != "gocase":
        ferr.responder_cliente(conversation_id, RESPOSTA_SENSIVEL)
        ferr.acionar_pessoa("supervisao", "Registrar cosmetovigilancia em ate 24h",
                            f"Conversa {conversation_id}, pedido {order_id}. Produto e lote no pedido. "
                            "Trocar o produto NAO substitui o registro.", "alta")
        r.desfecho = "sensivel"
        r.p("Caso sensivel: cliente orientado a suspender o uso; supervisor acionado com prazo de 24h para registrar.")
        return r, ferr

    # 3b) Cascata: confianca baixa do Jev -> segunda opiniao do modelo PRINCIPAL. Sem consenso, vai para uma pessoa.
    #     Nao se aplica a triagem por regras (sem Jev) e vem DEPOIS dos caminhos de seguranca acima.
    if str(t["fonte"]).startswith("jev") and t["confianca"] < LIMIAR_CONFIANCA and agentes.disponivel():
        seg = agentes.segunda_opiniao(texto)
        if seg is None:
            motivo = "a segunda opiniao nao respondeu de forma valida"
        elif acao_de(seg["categoria"]) != acao_de(t["categoria"]):
            motivo = f"o modelo principal discorda: '{seg['categoria']}' leva a outra acao"
        else:
            motivo = None
        if motivo:
            return _esclarecer(r, ferr, conversation_id,
                               f"Confianca baixa ({t['confianca']:.0%}) e sem consenso ({motivo})")
        r.p(f"Confianca baixa ({t['confianca']:.0%}): segunda opiniao do modelo principal concorda na acao "
            f"('{seg['categoria']}'). Segue.")

    # 3b1) Segundo assunto que mexeria em dinheiro de novo (outro reenvio, reembolso, troca...) depois de o primeiro ja ter
    #      executado uma acao: nao duplica sozinho; uma pessoa decide se e outro problema ou o mesmo.
    if secundaria and t["categoria"] in CATEGORIAS_DINHEIRO and any(e["ferramenta"] in ACOES_DINHEIRO for e in ferr.log):
        return _esclarecer(r, ferr, conversation_id,
                           f"Segundo assunto ('{t['categoria']}') pediria outra acao de dinheiro no mesmo pedido, depois de uma ja executada: "
                           "nao duplico sozinho",
                           "O primeiro assunto da mensagem ja foi resolvido neste pedido. O segundo pedido parece ser outra solicitacao no "
                           "mesmo pedido: perguntar se e um problema diferente (outro item) e qual item.",
                           "Ja resolvi o primeiro ponto do seu pedido. Sobre o outro ponto, e um problema com outro item do mesmo pedido? "
                           "Se for, me diga qual item que eu verifico.")

    # 3b2) "Troca" com defeito no texto ("zipper quebrado, quero outro") e avaria, nao troca de fragrancia (galeria de respostas).
    if t["categoria"] == "Troca" and DEFEITO.search(texto):
        t["categoria"], r.categoria = "Avaria", "Avaria"
        r.p("Triagem disse Troca, mas o texto relata defeito (quebrado, amassado...): tratado como avaria.")

    # 3c) Duvida: pergunta sobre o pedido ("em transito, e normal?") e rastreio; prazo de entrega a politica responde;
    #     o resto consulta a base (RAG). Pode nao haver pedido, por isso vem antes dessa checagem.
    if t["categoria"] == "Duvida" and order_id and TRANSITO.search(texto):
        t["categoria"], r.categoria = "Rastreio", "Rastreio"
        r.p("Triagem disse Duvida, mas a pergunta e sobre o pedido (transito, rastreio): tratado como rastreio.")
    if t["categoria"] == "Duvida":
        if rotas_gerais.PRAZO.search(texto):
            return rotas_gerais.prazo_entrega(r, ferr, conversation_id, texto, _texto)
        return _duvida(r, ferr, conversation_id, texto)

    # 3d) Rotas que nao dependem de um pedido: elogio e promocao/cupom.
    if t["categoria"] == "Elogio":
        return rotas_gerais.elogio(r, ferr, conversation_id, _texto)
    pedido = ferr.consultar_pedido(order_id) if order_id else None
    if t["categoria"] == "Promocao":
        return rotas_gerais.promocao(r, ferr, conversation_id, pedido, texto, ferr.agora, _texto)
    if not pedido:
        # Sem pedido: pergunta o numero em vez de chamar uma pessoa (so quando a categoria precisa de pedido).
        if t["categoria"] in rotas_gerais.CATEGORIAS_COM_PEDIDO:
            return rotas_gerais.pedir_pedido(r, ferr, conversation_id, _texto, t["categoria"])
        return _esclarecer(r, ferr, conversation_id, "Sem pedido associado e categoria sem rota")

    # 3e) Rotas do dia a dia (politicas.csv, secao 'categorias'): cancelamento, endereco, financeiro, troca.
    if t["categoria"] == "Cancelamento":
        return rotas_gerais.cancelamento(r, ferr, conversation_id, pedido, texto, ferr.agora, _texto)
    if t["categoria"] == "Endereco":
        return rotas_gerais.endereco(r, ferr, conversation_id, pedido, ferr.agora, _texto)
    if t["categoria"] == "Financeiro":
        return rotas_gerais.financeiro(r, ferr, conversation_id, pedido, texto, ferr.agora, _texto)
    if t["categoria"] == "Troca":
        return rotas_gerais.troca(r, ferr, conversation_id, pedido, texto, ferr.agora, _texto)

    # 4) Rota. Categorias CLARAS seguem a regra. Ambiguas: o modelo PRINCIPAL propoe; o codigo valida.
    cat_pol = CATEGORIA_POLITICA.get(t["categoria"])
    rota = "pos_venda" if cat_pol else ("rastreio" if t["categoria"] in ("Rastreio", "Atraso") else None)
    if rota is None and agentes.disponivel():
        prop = agentes.rotear(texto, t, pedido)
        if prop:
            r.p(f"Orquestrador (modelo principal) propos '{prop['rota']}': {prop['motivo']}")
            if prop["rota"] == "pos_venda" and prop["categoria_politica"]:
                rota, cat_pol = "pos_venda", prop["categoria_politica"]
            elif prop["rota"] == "rastreio":
                rota = "rastreio"
    if rota == "pos_venda":
        return _pos_venda(r, ferr, conv, pedido, cat_pol, agora, texto)
    if rota == "rastreio":
        return _rastreio(r, ferr, pedido, texto)

    return _esclarecer(r, ferr, conversation_id, f"Categoria '{t['categoria']}' sem rota propria")


def _duvida(r: Resultado, ferr: Ferramentas, conversation_id: str, texto: str):
    """Responde duvida de produto com a base de conhecimento; sem fundamento suficiente, chama uma pessoa."""
    resp, motivo = duvida.responder(texto)
    if resp is None:
        if "saude" in motivo:  # pergunta de saude e coisa seria: uma pessoa especializada responde
            r.p(f"Consulta a base: {motivo}. Encaminhado a uma pessoa.")
            _encaminhar(r, ferr, conversation_id, "atendimento", "Duvida de saude sem resposta na base",
                        f"Conversa {conversation_id}: {motivo}. A pergunta: {mascarar_pii(texto[:300])}", urgencia="alta",
                        espera=RESPOSTA_ESPERA_SAUDE)
            r.desfecho = "escalado"
            return r, ferr
        # Duvida comum sem fundamento na base: nao inventa e nao chama uma pessoa; diz o que falta e pede o detalhe.
        r.p(f"Lacuna na base de conhecimento (pergunta sem resposta fundamentada): {mascarar_pii(texto[:120])}")
        return _esclarecer(r, ferr, conversation_id, f"Consulta a base: {motivo}",
                           "Nao ha informacao segura na base para responder esta pergunta. Dizer com honestidade que nao tem a informacao "
                           "exata, sem inventar, e pedir que o cliente conte qual produto ou pedido e a duvida para buscar a resposta certa.",
                           "Boa pergunta! Ainda nao tenho essa informacao com seguranca para te responder certo. Pode me contar de qual "
                           "produto ou pedido se trata? Assim eu busco a resposta mais exata.")
    for a in resp.avisos:
        r.p(f"AVISO: {a}")
    r.p(f"Consulta a base (BM25, cobertura {resp.cobertura:.0%}): {motivo}. Fontes: {', '.join(resp.fontes)}.")
    ferr.responder_cliente(conversation_id, resp.texto)
    r.desfecho = "autonomo"
    return r, ferr


def _precedentes(texto: str, cid: str | None, agora: datetime | None) -> str:
    """Casos parecidos JA atendidos antes desta conversa e o que o humano fez (contexto para o supervisor)."""
    try:
        p = conhecimento.base().precedentes(texto, excluir=cid, antes_de=agora)
    except Exception:
        return ""
    if p["n"] < 2:
        return ""
    return f" Casos parecidos ja atendidos: {p['n']}; o que o humano fez: {p['acoes_humanas']}."


def _resumo(dos: detetive.Dossie, pedido: dict, texto: str = "", cid: str | None = None, agora: datetime | None = None) -> str:
    """Dossie estruturado (sempre) + casos parecidos (RAG) + resumo do modelo principal (quando houver)."""
    base = dos.resumo() + _precedentes(texto, cid, agora)
    if not agentes.disponivel():
        return base
    fatos = (f"Pedido {pedido['order_id']} ({pedido.get('marca')}), valor R$ {float(pedido['valor']):.2f}, "
             f"status {pedido.get('status_entrega')}, entregue em {pedido.get('data_entrega')}.")
    resumo = agentes.resumo_supervisor(base, fatos)
    return f"{resumo}\n[dossie] {base}" if resumo else base


def _pos_venda(r: Resultado, ferr: Ferramentas, conv: dict, pedido: dict, cat_pol: str, agora: datetime, texto: str = ""):
    cid, oid = conv["conversation_id"], pedido["order_id"]
    valor = float(pedido["valor"])
    anexos = ferr.ver_anexos(conversation_id=cid)
    entrega = pedido.get("data_entrega")
    # A plataforma marca "[foto anexada]" na mensagem quando o cliente enviou uma foto, mesmo sem registro em anexos
    # (sem EXIF nem hash). Conta como foto recebida (a politica exige foto); so "mandei as fotos" sem marca NAO conta.
    foto_alegada = bool(FOTO_ANEXADA.search(texto)) and not anexos

    # Brinde de campanha: so tem direito quem comprou dentro das regras da campanha (GoBeauté, >= R$ 129, 13/10 a 04/11).
    # Se o pedido tem o brinde nos itens, o direito esta provado e segue o fluxo normal (foto, Detetive, politica).
    if cat_pol == "item_faltante" and rotas_gerais.BRINDE.search(texto) and not rotas_gerais.elegivel_brinde(pedido):
        tem_item = dados.uma("select count(*) n from itens_pedido where order_id = ? and tipo_item = 'brinde'", [oid])
        if not (tem_item and int(tem_item["n"])):
            motivo = rotas_gerais.motivo_sem_brinde(pedido)
            ferr.negar_por_politica(cid, "brinde_fora_da_campanha")
            ferr.responder_cliente(cid, _texto(r,
                "explicar com gentileza que este pedido nao tinha direito ao brinde da campanha",
                f"O pedido {oid} nao tinha direito ao brinde: {motivo}. Nao ha reenvio de brinde para este pedido.",
                f"Entendo a sua expectativa com o brinde. Pela regra da campanha, {motivo}, "
                "por isso nao conseguimos enviar o brinde neste pedido."))
            r.desfecho = "fora_da_politica"
            r.p(f"Brinde: o pedido nao tinha direito ({motivo}). Negado pela politica, sem pedir foto.")
            return r, ferr
        r.p("Brinde: fora da regra da campanha, mas o pedido traz o brinde nos itens; segue o fluxo normal.")

    bus = r.bus
    if foto_alegada:
        r.p("Foto anexada segundo a plataforma, mas sem metadados (EXIF, hash): o Detetive nao tem o que verificar na imagem.")
    if not anexos and not foto_alegada:
        v = bus.enviar("PosVenda", "Guardiao", "consultar", acao="reenviar_produto", categoria=cat_pol, valor=valor,
                       entrega=entrega, agora=agora, tem_foto=False)
        if v.ato == "negado" and "foto" not in v.conteudo["motivo"].lower():
            r.desfecho = "fora_da_politica"
            r.p(f"Politica: {v.conteudo['motivo']}")
            return r, ferr
        ferr.solicitar_foto(cid, "produto/embalagem")
        ferr.responder_cliente(cid, _texto(r,
            "pedir foto do produto e da embalagem para seguir com a solucao",
            "O cliente relatou um problema com o pedido. Falta a foto do produto e da embalagem.",
            "Sinto muito pelo ocorrido. Para seguir com a solucao, pode enviar uma foto do produto e da embalagem?"))
        r.desfecho = "aguardando_cliente"
        r.p("A politica exige foto: pedi ao cliente e aguardo a resposta.")
        return r, ferr

    # Detetive de Procedencia (+ juiz da foto, modelo SUB, quando houver token)
    det = bus.registrar(dialogo.AgenteDetetive(cid, oid, usar_juiz=agentes.disponivel()))
    parecer = bus.enviar("PosVenda", "Detetive", "propor", acao="reenviar_produto", valor=valor, pedido=oid)
    dos = det.dossie
    r.dossie = dos
    r.p(f"Detetive ({parecer.ato}): {dos.resumo()}")
    if parecer.ato == "contestar":  # o PosVenda nao age: encaminha ao supervisor
        ferr.sinalizar_suspeita(cid, _resumo(dos, pedido, texto, cid, agora), [s.nome for s in dos.sinais])
        ferr.responder_cliente(cid, RESPOSTA_NEUTRA)
        r.desfecho = "suspeita"
        r.p("Reclamacao SINALIZADA: reenvio suspenso e dossie enviado ao supervisor. O cliente recebeu resposta neutra, sem acusacao.")
        return r, ferr

    # Guardiao de politica
    v = bus.enviar("PosVenda", "Guardiao", "consultar", acao="reenviar_produto", categoria=cat_pol, valor=valor,
                   entrega=entrega, agora=agora, tem_foto=True)
    d = politica.Decisao(v.ato, v.conteudo["motivo"], v.conteudo["regra"])
    r.p(f"Politica (Guardiao): {d.resultado} ({d.motivo})")
    if d.resultado == "permitido":
        ferr.reenviar_produto(oid, valor, cat_pol)
        ferr.responder_cliente(cid, _texto(r,
            "informar que o reenvio foi aprovado",
            "Reenvio sem custo aprovado e executado. O rastreio sera informado assim que o pedido sair.",
            "Resolvido! Vamos reenviar o seu pedido sem custo e te avisamos assim que sair. Obrigado pela paciencia."))
        r.desfecho = "autonomo"
        r.p(f"Reenvio de R$ {valor:.2f} executado sozinho, dentro do limite.")
    elif d.resultado == "precisa_aprovacao":
        apr = ferr.solicitar_aprovacao("reenviar_produto", oid, valor, f"{d.motivo}. {_resumo(dos, pedido, texto, cid, agora)}")
        ferr.responder_cliente(cid, _texto(r,
            "informar que o caso foi encaminhado para aprovacao",
            "O caso depende de aprovacao interna. Nao ha prazo garantido alem de 'em breve'.",
            "Seu caso foi encaminhado para aprovacao e voltamos com a resposta em breve."))
        r.desfecho = "aguardando_supervisor"
        r.p(f"Acima do limite: pedi aprovacao {apr} ao supervisor, com o dossie anexado.")
    else:
        ferr.responder_cliente(cid, "Analisamos o seu pedido e, pela nossa politica, nao conseguimos seguir com esse reenvio. "
                                    f"Motivo: {d.motivo}.")
        r.desfecho = "fora_da_politica"
        r.p(f"Fora da politica: {d.motivo}")
    return r, ferr


def _fallback_rastreio(plano: rastreio.Plano, sit: rastreio.Situacao, pedido: dict) -> str:
    """Texto fixo (sem modelo) para cada situacao de rastreio. Usado quando nao ha token ou o redator falha."""
    oid, transp = pedido["order_id"], sit.transportadora or "transportadora"
    previsao = rastreio._br(sit.previsao or sit.prometida)
    if plano.tipo == "informar_entregue":
        return f"O pedido {oid} consta como entregue. Se voce nao recebeu, e so nos avisar."
    if plano.tipo == "informar_no_prazo":
        if sit.estado == "aguardando_postagem":
            return f"Seu pedido {oid} esta sendo preparado para envio. Previsao de entrega: {previsao}."
        return f"Seu pedido {oid} esta com a {transp} e segue dentro do prazo. Previsao de entrega: {previsao}."
    if plano.tipo == "aguardando_postagem":
        return f"Estamos verificando o seu pedido {oid} com a nossa logistica e voltamos com uma posicao em breve."
    if plano.oferecer_opcoes:
        acionou = "Ja acionamos a nossa logistica. " if plano.acionar_logistica else ""
        return (f"Lamentamos o problema com o pedido {oid}. {acionou}"
                "Para resolver, voce prefere o reenvio do produto ou o reembolso?")
    chamado = ("Ja temos um chamado aberto com a" if sit.chamado else "Abrimos um chamado com a")
    return f"Vimos que o seu pedido {oid} esta com problema no rastreio. {chamado} {transp} e te avisamos assim que houver retorno."


def _rastreio(r: Resultado, ferr: Ferramentas, pedido: dict, texto: str = ""):
    """Rastreio e atraso conforme a politica: informa, abre chamado, ou oferece reenvio/reembolso."""
    cid, oid = r.conversation_id, pedido["order_id"]
    valor = float(pedido.get("valor") or 0)
    sit = rastreio.situacao(pedido, ferr.agora)
    for a in getattr(sit, "avisos", []):
        r.p(f"AVISO: {a}")
    plano = rastreio.decidir(sit, pedido)
    r.p(f"Rastreio ({sit.estado}): {plano.resumo}")

    if plano.tipo == "escalar":
        # Pedido cancelado ou devolvido: nao ha o que rastrear. O agente informa o que consta no sistema e abre a porta
        # para o cliente dizer se isso nao era o esperado (sem chamar uma pessoa).
        ferr.responder_cliente(cid, _texto(r, "informar a situacao do pedido, que esta cancelado ou devolvido",
                                           f"O pedido {oid} consta como {sit.estado} no sistema. Perguntar se isso nao era o esperado e "
                                           "pedir que o cliente conte o que aconteceu.",
                                           f"Consta no sistema que o pedido {oid} esta {sit.estado}. Se isso nao era o que voce esperava, "
                                           "me conte o que aconteceu que eu verifico."))
        r.desfecho = "aguardando_cliente"
        r.p(f"Pedido {sit.estado}: informei o que consta e perguntei ao cliente, sem chamar uma pessoa.")
        return r, ferr
    if plano.abrir_chamado:
        ferr.abrir_chamado_transportadora(oid, plano.motivo_chamado)
    if plano.acionar_logistica:
        ferr.acionar_pessoa("logistica", "Pedido com problema de entrega", f"{oid} - {sit.transportadora}: {plano.resumo}", "alta")

    fallback = _fallback_rastreio(plano, sit, pedido)
    if not plano.oferecer_opcoes:
        ferr.responder_cliente(cid, _texto(r,"informar a situacao do pedido", plano.fatos, fallback))
        r.desfecho = "autonomo"
        return r, ferr

    # Mais de 7 dias uteis de atraso, ou extravio: reenvio ou reembolso, A ESCOLHA DO CLIENTE (nunca nossa).
    pref = rastreio.preferencia_do_cliente(texto)
    acao = {"reenvio": "reenviar_produto", "reembolso": "reembolsar"}.get(pref)
    if acao is None:
        ferr.responder_cliente(cid, _texto(r,"oferecer reenvio ou reembolso e perguntar a preferencia", plano.fatos, fallback))
        r.desfecho = "aguardando_cliente"
        r.p("A politica permite reenvio ou reembolso, a escolha do cliente: ofereci as duas opcoes e aguardo.")
        return r, ferr

    d = politica.avaliar_acao(acao, "atraso_entrega", valor, None, ferr.agora, tem_foto=False)
    r.p(f"Cliente escolheu {pref}. Politica: {d.resultado} ({d.motivo})")  # o valor vem do PEDIDO, nunca do texto
    if d.permitido:
        if acao == "reenviar_produto":
            ferr.reenviar_produto(oid, valor, "atraso_entrega")
            msg = f"Vamos reenviar o seu pedido {oid} sem custo e te avisamos assim que sair."
        else:
            ferr.reembolsar(oid, valor, "atraso_entrega")
            msg = f"Vamos reembolsar o valor do pedido {oid}. Voce recebera a confirmacao em seguida."
        ferr.responder_cliente(cid, msg)
        r.desfecho = "autonomo"
    elif d.resultado == "precisa_aprovacao":
        apr = ferr.solicitar_aprovacao(acao, oid, valor, f"{d.motivo}. {plano.resumo}")
        ferr.responder_cliente(cid, "Registramos a sua escolha e ela foi encaminhada para aprovacao. Voltamos em breve.")
        r.desfecho = "aguardando_supervisor"
        r.p(f"Acima do limite: pedi aprovacao {apr} ao supervisor.")
    else:
        ferr.negar_por_politica(cid, f"{acao}.{d.regra}")
        ferr.responder_cliente(cid, _texto(r, "explicar com gentileza que a politica nao permite essa acao agora",
                                           f"A politica nao permite {acao} no pedido {oid} agora: {d.motivo}.",
                                           f"Analisei o pedido {oid} e, pela nossa politica, nao consigo seguir com isso agora. "
                                           f"Motivo: {d.motivo}."))
        r.desfecho = "fora_da_politica"
    return r, ferr
