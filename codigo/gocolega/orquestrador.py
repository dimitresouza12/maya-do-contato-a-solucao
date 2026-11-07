"""Orquestrador do GoColega: triagem -> sub-agente -> guardioes -> acao (ou 'levantar a mao').

Modelos (ver modelos.py): Jev na triagem; modelo PRINCIPAL (terra) roteia casos ambiguos e resume para o
supervisor; modelo SUB (luna) julga a foto e escreve as respostas. O modelo PROPOE; o codigo VALIDA:
alcada, prazo, papel e segregacao ficam no Policy Engine. Sem token, tudo roda so com codigo.
"""
from dataclasses import dataclass, field
from datetime import datetime

from . import agentes, detetive, llm, politica
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

    def p(self, texto: str):
        self.passos.append(texto)


def _texto(situacao: str, fatos: str, fallback: str) -> str:
    """Resposta ao cliente: modelo SUB se houver token, com validacao; senao o texto fixo."""
    return agentes.redator(situacao, fatos, fallback) if agentes.disponivel() else fallback


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

    pedido = ferr.consultar_pedido(order_id) if order_id else None
    if not pedido:
        r.desfecho = "escalado"
        ferr.acionar_pessoa("supervisao", "Conversa sem pedido associado", f"Conversa {conversation_id}", "normal")
        r.p("Sem pedido associado: levantei a mao para uma pessoa.")
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
        return _pos_venda(r, ferr, conv, pedido, cat_pol, agora)
    if rota == "rastreio":
        return _rastreio(r, ferr, pedido)

    r.desfecho = "escalado"
    ferr.acionar_pessoa("atendimento", f"Categoria '{t['categoria']}' fora do escopo da POC",
                        f"Conversa {conversation_id}", "normal")
    r.p(f"Categoria '{t['categoria']}' fora do escopo desta POC: encaminhado a uma pessoa.")
    return r, ferr


def _resumo(dos: detetive.Dossie, pedido: dict) -> str:
    """Dossie estruturado (sempre) + resumo do modelo principal (quando houver)."""
    base = dos.resumo()
    if not agentes.disponivel():
        return base
    fatos = (f"Pedido {pedido['order_id']} ({pedido.get('marca')}), valor R$ {float(pedido['valor']):.2f}, "
             f"status {pedido.get('status_entrega')}, entregue em {pedido.get('data_entrega')}.")
    resumo = agentes.resumo_supervisor(base, fatos)
    return f"{resumo}\n[dossie] {base}" if resumo else base


def _pos_venda(r: Resultado, ferr: Ferramentas, conv: dict, pedido: dict, cat_pol: str, agora: datetime):
    cid, oid = conv["conversation_id"], pedido["order_id"]
    valor = float(pedido["valor"])
    anexos = ferr.ver_anexos(conversation_id=cid)
    entrega = pedido.get("data_entrega")

    if not anexos:
        d = politica.avaliar_acao("reenviar_produto", cat_pol, valor, entrega, agora, tem_foto=False)
        if d.resultado == "negado" and "foto" not in d.motivo.lower():
            r.desfecho = "fora_da_politica"
            r.p(f"Politica: {d.motivo}")
            return r, ferr
        ferr.solicitar_foto(cid, "produto/embalagem")
        ferr.responder_cliente(cid, _texto(
            "pedir foto do produto e da embalagem para seguir com a solucao",
            "O cliente relatou um problema com o pedido. Falta a foto do produto e da embalagem.",
            "Sinto muito pelo ocorrido. Para seguir com a solucao, pode enviar uma foto do produto e da embalagem?"))
        r.desfecho = "aguardando_cliente"
        r.p("A politica exige foto: pedi ao cliente e aguardo a resposta.")
        return r, ferr

    # Detetive de Procedencia (+ juiz da foto, modelo SUB, quando houver token)
    dos = detetive.analisar(cid, oid, juiz=agentes.juiz_foto if agentes.disponivel() else None)
    r.dossie = dos
    r.p(f"Detetive: {dos.resumo()}")
    if dos.sinalizar:
        ferr.sinalizar_suspeita(cid, _resumo(dos, pedido), [s.nome for s in dos.sinais])
        ferr.responder_cliente(cid, RESPOSTA_NEUTRA)
        r.desfecho = "suspeita"
        r.p("Reclamacao SINALIZADA: reenvio suspenso e dossie enviado ao supervisor. O cliente recebeu resposta neutra, sem acusacao.")
        return r, ferr

    # Guardiao de politica
    d = politica.avaliar_acao("reenviar_produto", cat_pol, valor, entrega, agora, tem_foto=True)
    r.p(f"Politica: {d.resultado} ({d.motivo})")
    if d.resultado == "permitido":
        ferr.reenviar_produto(oid, valor, cat_pol)
        ferr.responder_cliente(cid, _texto(
            "informar que o reenvio foi aprovado",
            "Reenvio sem custo aprovado e executado. O rastreio sera informado assim que o pedido sair.",
            "Resolvido! Vamos reenviar o seu pedido sem custo e te avisamos assim que sair. Obrigado pela paciencia."))
        r.desfecho = "autonomo"
        r.p(f"Reenvio de R$ {valor:.2f} executado sozinho, dentro da alcada.")
    elif d.resultado == "precisa_aprovacao":
        apr = ferr.solicitar_aprovacao("reenviar_produto", oid, valor, f"{d.motivo}. {_resumo(dos, pedido)}")
        ferr.responder_cliente(cid, _texto(
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


def _rastreio(r: Resultado, ferr: Ferramentas, pedido: dict):
    cid, oid = r.conversation_id, pedido["order_id"]
    status = pedido["status_entrega"]
    prometida = pedido.get("data_prometida")
    if status == "entregue":
        ferr.responder_cliente(cid, _texto(
            "informar que o pedido consta como entregue",
            f"Pedido {oid} entregue em {pedido['data_entrega']}. Se o cliente nao recebeu, deve avisar.",
            f"O pedido {oid} consta como entregue em {pedido['data_entrega']}. Se nao recebeu, nos avise."))
        r.desfecho = "autonomo"
        r.p("Pedido ja entregue: informado ao cliente.")
    elif status in ("em_transito", "aguardando_separacao"):
        ferr.responder_cliente(cid, _texto(
            "informar o status e a previsao do pedido",
            f"Pedido {oid}, status {status}, transportadora {pedido['transportadora']}, previsao {prometida}.",
            f"Seu pedido {oid} esta '{status}' com a {pedido['transportadora']}. Previsao: {prometida}."))
        r.desfecho = "autonomo"
        r.p("Status informado ao cliente com a previsao.")
    elif status == "extraviado":
        ferr.abrir_chamado_transportadora(oid, "extravio")
        ferr.acionar_pessoa("logistica", "Pedido extraviado", f"{oid} - {pedido['transportadora']}", "alta")
        r.desfecho = "escalado"
        r.p("Extravio: chamado aberto e logistica acionada.")
    else:
        r.desfecho = "escalado"
        ferr.acionar_pessoa("atendimento", f"Status '{status}'", f"Pedido {oid}", "normal")
        r.p(f"Status '{status}': encaminhado a uma pessoa.")
    return r, ferr
