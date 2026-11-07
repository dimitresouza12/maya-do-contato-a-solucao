"""Orquestrador do GoColega: triagem -> sub-agente -> guardioes -> acao (ou 'levantar a mao').

Modelos (ver modelos.py): Jev na triagem; modelo PRINCIPAL (terra) roteia casos ambiguos e resume para o
supervisor; modelo SUB (luna) julga a foto e escreve as respostas. O modelo PROPOE; o codigo VALIDA:
alcada, prazo, papel e segregacao ficam no Policy Engine. Sem token, tudo roda so com codigo.
"""
from dataclasses import dataclass, field
from datetime import datetime

from . import agentes, conhecimento, detetive, dialogo, duvida, llm, politica, rastreio
from .ferramentas import Ferramentas

CATEGORIA_POLITICA = {"Avaria": "avaria_vazamento", "Produto faltando": "item_faltante",
                      "Reclamacao produto": "avaria_vazamento"}
# Respostas FIXAS de proposito: suspeita e caso sensivel nunca passam por modelo
# (a politica manda nao acusar o cliente e a orientacao de saude nao pode variar).
RESPOSTA_NEUTRA = ("Recebemos seu contato e estamos analisando o seu caso com cuidado. "
                   "Voltamos com uma resposta em ate 24 horas.")
RESPOSTA_SENSIVEL = ("Lamentamos muito. Por seguranca, suspenda o uso do produto agora e procure atendimento "
                     "medico se o desconforto continuar. Nossa equipe tecnica ja foi acionada.")


# Abaixo disso o Jev e pouco confiavel (benchmark: 26% de acerto da categoria; 61% da rota).
LIMIAR_CONFIANCA = 0.70


def acao_de(categoria: str) -> tuple:
    """O que o GoColega FARIA com a categoria. Duas categorias com a mesma acao nao precisam de consenso exato
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
    desfecho: str = ""  # autonomo | aguardando_cliente | aguardando_supervisor | suspeita | sensivel | escalado | fora_da_politica
    passos: list[str] = field(default_factory=list)
    dossie: detetive.Dossie | None = None
    # a conversa entre os agentes neste caso: Guardiao, Redator e Verificador; o Detetive entra no pos-venda
    bus: "dialogo.Barramento" = field(default_factory=lambda: dialogo.montar())

    def p(self, texto: str):
        self.passos.append(texto)

    def conversa(self) -> list[str]:
        return self.bus.linhas()


def _texto(r: Resultado, situacao: str, fatos: str, fallback: str) -> str:
    """Resposta ao cliente. Com token: conversa Redator (modelo) <-> Verificador (codigo), ate 2 revisoes, senao texto fixo.
    Sem token: texto fixo."""
    if not agentes.disponivel():
        return fallback
    try:
        return dialogo.redigir(r.bus, situacao, fatos, fallback)
    except dialogo.LimiteDeMensagens:  # dialogo longo demais: nunca derruba o caso, cai no texto fixo
        r.p("AVISO: dialogo entre agentes passou do limite de mensagens; usei o texto fixo")
        return fallback


def tratar(conversation_id: str, agora: datetime | None = None, texto_override: str | None = None,
           ferr: Ferramentas | None = None) -> tuple[Resultado, Ferramentas]:
    """Trata uma conversa. 'texto_override' permite simular mensagens novas (ex.: teste de injecao)."""
    agentes.avisos.clear()
    r, ferr = _tratar(conversation_id, agora, texto_override, ferr)
    for a in agentes.avisos:
        r.p(f"AVISO: {a}")
    agentes.avisos.clear()
    return r, ferr


def _tratar(conversation_id, agora, texto_override, ferr):
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
    texto = texto_override or " ".join(m["texto"] for m in dados_conv["mensagens"] if m["autor"] == "cliente")
    order_id = conv.get("order_id")

    # 1) Triagem (Jev + regras)
    t = llm.triagem(texto)
    r.categoria = t["categoria"]
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
            r.p(f"Confianca baixa ({t['confianca']:.0%}) e sem consenso: {motivo}. Encaminhado a uma pessoa.")
            ferr.acionar_pessoa("atendimento", "Triagem sem consenso",
                                f"Conversa {conversation_id}: Jev disse '{t['categoria']}' com {t['confianca']:.0%}; "
                                f"segunda opiniao: '{seg['categoria'] if seg else 'sem resposta'}'. Motivo: {motivo}.", "normal")
            r.desfecho = "escalado"
            return r, ferr
        r.p(f"Confianca baixa ({t['confianca']:.0%}): segunda opiniao do modelo principal concorda na acao "
            f"('{seg['categoria']}'). Segue.")

    # 3c) Duvida de produto: consulta a base (RAG). Pode nao haver pedido, por isso vem antes dessa checagem.
    if t["categoria"] == "Duvida":
        return _duvida(r, ferr, conversation_id, texto)

    pedido = ferr.consultar_pedido(order_id) if order_id else None
    if not pedido:
        r.desfecho = "escalado"
        ferr.acionar_pessoa("supervisao", "Conversa sem pedido associado", f"Conversa {conversation_id}", "normal")
        r.p("Sem pedido associado: levantei a mao para uma pessoa.")
        return r, ferr

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

    r.desfecho = "escalado"
    ferr.acionar_pessoa("atendimento", f"Categoria '{t['categoria']}' fora do escopo da POC",
                        f"Conversa {conversation_id}", "normal")
    r.p(f"Categoria '{t['categoria']}' fora do escopo desta POC: encaminhado a uma pessoa.")
    return r, ferr


def _duvida(r: Resultado, ferr: Ferramentas, conversation_id: str, texto: str):
    """Responde duvida de produto com a base de conhecimento; sem fundamento suficiente, chama uma pessoa."""
    resp, motivo = duvida.responder(texto)
    if resp is None:
        r.p(f"Consulta a base: {motivo}. Encaminhado a uma pessoa.")
        ferr.acionar_pessoa("atendimento", "Duvida sem resposta fundamentada na base", f"Conversa {conversation_id}: {motivo}", "normal")
        r.desfecho = "escalado"
        return r, ferr
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

    bus = r.bus
    if not anexos:
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
        r.p(f"Reenvio de R$ {valor:.2f} executado sozinho, dentro da alcada.")
    elif d.resultado == "precisa_aprovacao":
        apr = ferr.solicitar_aprovacao("reenviar_produto", oid, valor, f"{d.motivo}. {_resumo(dos, pedido, texto, cid, agora)}")
        ferr.responder_cliente(cid, _texto(r,
            "informar que o caso foi encaminhado para aprovacao",
            "O caso depende de aprovacao interna. Nao ha prazo garantido alem de 'em breve'.",
            "Seu caso foi encaminhado para aprovacao e voltamos com a resposta em breve."))
        r.desfecho = "aguardando_supervisor"
        r.p(f"Acima da alcada: pedi aprovacao {apr} ao supervisor, com o dossie anexado.")
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
    plano = rastreio.decidir(sit, pedido)
    r.p(f"Rastreio ({sit.estado}): {plano.resumo}")

    if plano.tipo == "escalar":
        r.desfecho = "escalado"
        ferr.acionar_pessoa("atendimento", f"Pedido {sit.estado}", f"Pedido {oid}", "normal")
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
        r.p(f"Acima da alcada: pedi aprovacao {apr} ao supervisor.")
    else:
        ferr.acionar_pessoa("atendimento", f"Acao '{acao}' negada pela politica", f"Pedido {oid}: {d.motivo}", "normal")
        r.desfecho = "escalado"
    return r, ferr
