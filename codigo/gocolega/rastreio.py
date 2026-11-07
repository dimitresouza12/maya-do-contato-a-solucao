"""Rastreio e atraso conforme a politica (politicas.csv): situacao da entrega NA DATA DA CONVERSA + decisao.

Regras da politica:
  - onde_esta_pedido: dentro do prazo, informar status e previsao. Rastreio parado ha 3 dias uteis ou mais: abrir chamado.
  - atraso_entrega: ate 7 dias uteis de atraso: abrir chamado. Acima de 7 dias uteis, ou extravio confirmado:
    reenviar ou reembolsar, a escolha do cliente.

IMPORTANTE: a situacao e calculada so com eventos ate 'agora' (a data da conversa). Usar o status final do pedido
(posicao de 02/11) numa conversa antiga seria vazar o futuro.
"""
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from . import dados

FERIADOS_PADRAO = {date(2026, 9, 7), date(2026, 10, 12), date(2026, 11, 2), date(2026, 11, 15),
                   date(2026, 11, 20), date(2026, 12, 25), date(2027, 1, 1)}
DIAS_PARADO_PARA_CHAMADO = 3
DIAS_ATRASO_PARA_REENVIO = 7


def feriados() -> set[date]:
    """Feriados da politica; sem a tabela (ex.: amostra), usa a lista padrao."""
    try:
        linha = dados.uma("select valor from politicas where regra = 'feriados_nacionais'")
        if linha and linha["valor"]:
            return {date.fromisoformat(x.strip()) for x in str(linha["valor"]).split(";") if x.strip()}
    except Exception:
        pass
    return set(FERIADOS_PADRAO)


def dias_uteis_entre(inicio: date, fim: date, feriados_: set[date] | None = None) -> int:
    """Dias uteis em (inicio, fim]: segunda a sexta, exceto feriados nacionais. 0 se fim <= inicio."""
    fer = feriados() if feriados_ is None else feriados_
    n, d = 0, inicio
    while d < fim:
        d += timedelta(days=1)
        if d.weekday() < 5 and d not in fer:
            n += 1
    return n


@dataclass
class Situacao:
    estado: str  # entregue | extraviado | em_transito | aguardando_postagem | cancelado | devolvido
    ultimo_evento: str | None = None
    ultimo_evento_em: datetime | None = None
    local: str | None = None
    dias_parado: int = 0  # dias uteis desde o ultimo evento
    atraso_du: int = 0  # dias uteis alem da data prometida
    prometida: date | None = None
    previsao: date | None = None
    chamado: dict | None = None  # chamado ja aberto e ainda nao encerrado na data da conversa
    transportadora: str | None = None


@dataclass
class Plano:
    tipo: str  # informar_entregue | informar_no_prazo | abrir_chamado | atraso_grave | extravio | aguardando_postagem | escalar
    abrir_chamado: bool
    motivo_chamado: str
    oferecer_opcoes: bool  # reenvio ou reembolso, a escolha do cliente
    acionar_logistica: bool
    fatos: str
    resumo: str


def _dt(x) -> datetime | None:
    if x is None or str(x) == "NaT":
        return None
    return x if isinstance(x, datetime) else datetime.combine(x, datetime.min.time())


def _d(x) -> date | None:
    if x is None or str(x) == "NaT":
        return None
    return x.date() if isinstance(x, datetime) else x


def situacao(pedido: dict, agora: datetime, eventos: list[dict] | None = None, chamado: dict | None = None) -> Situacao:
    """eventos e chamado podem ser injetados (testes); sem isso, vem dos portais e da tabela de chamados."""
    cod = pedido.get("codigo_rastreio")
    if eventos is None:
        try:
            eventos = dados.consulta(
                "select status, data_hora_evento, local, previsao_entrega from rastreio_portais_transportadoras "
                "where codigo_rastreio = ? and data_hora_evento <= ? order by data_hora_evento", [cod, agora]) if cod else []
        except Exception:
            eventos = []
    if chamado is None:
        try:
            chamado = dados.uma(
                "select chamado_id, data_abertura, motivo, status, nova_previsao_entrega from chamados_transportadora "
                "where order_id = ? and data_abertura <= ? and (data_encerramento is null or data_encerramento > ?) "
                "order by data_abertura desc limit 1", [pedido.get("order_id"), agora, agora])
        except Exception:
            chamado = None

    prometida = _d(pedido.get("data_prometida"))
    s = Situacao(estado="em_transito", prometida=prometida, chamado=chamado, transportadora=pedido.get("transportadora"))
    status_vistos = {e["status"] for e in eventos}
    entregue_em = _d(pedido.get("data_entrega"))

    if pedido.get("status_entrega") in ("cancelado", "devolvido"):
        s.estado = pedido["status_entrega"]
    elif "entregue" in status_vistos or (entregue_em and entregue_em <= agora.date()):
        s.estado = "entregue"
    elif "extraviado" in status_vistos:
        s.estado = "extraviado"
    elif not eventos:
        s.estado = "aguardando_postagem"

    if eventos:
        ult = eventos[-1]
        s.ultimo_evento, s.ultimo_evento_em, s.local = ult["status"], _dt(ult["data_hora_evento"]), ult.get("local")
        s.dias_parado = dias_uteis_entre(s.ultimo_evento_em.date(), agora.date())
        previsoes = [_d(e.get("previsao_entrega")) for e in eventos if e.get("previsao_entrega") is not None]
        s.previsao = previsoes[-1] if previsoes else None
    if prometida and agora.date() > prometida:
        s.atraso_du = dias_uteis_entre(prometida, agora.date())
    return s


def _br(d: date | None) -> str:
    return d.strftime("%d/%m/%Y") if d else "sem data"


def decidir(s: Situacao, pedido: dict) -> Plano:
    oid, transp = pedido.get("order_id"), s.transportadora or "transportadora"
    ja = (f" Ja existe um chamado aberto desde {_br(_d(s.chamado['data_abertura']))}." if s.chamado else "")
    base = f"Pedido {oid}, transportadora {transp}, previsao original {_br(s.prometida)}."

    if s.estado == "entregue":
        return Plano("informar_entregue", False, "", False, False,
                     f"{base} Consta como entregue. Se o cliente nao recebeu, deve avisar.", "pedido ja entregue")
    if s.estado in ("cancelado", "devolvido"):
        return Plano("escalar", False, "", False, False, base, f"pedido {s.estado}: uma pessoa precisa olhar")
    # Acima de 7 du de atraso e em extravio a POLITICA manda reenviar ou reembolsar (nao cita chamado). Validado: os
    # atendentes humanos abriram chamado em 0% dos 70 casos com mais de 7 du de atraso. Por isso nao abrimos.
    if s.estado == "extraviado":
        return Plano("extravio", False, "", True, True,
                     f"{base} A transportadora registrou extravio. A politica permite reenvio ou reembolso, a escolha do cliente.",
                     "extravio confirmado: logistica acionada e opcoes ao cliente")
    if s.estado == "aguardando_postagem":
        if s.atraso_du > 0:
            return Plano("aguardando_postagem", False, "", False, True,
                         f"{base} Ainda sem evento de rastreio, e o prazo ja passou ({s.atraso_du} dias uteis).",
                         f"sem postagem e {s.atraso_du} du de atraso: logistica acionada")
        return Plano("informar_no_prazo", False, "", False, False,
                     f"{base} O pedido ainda esta sendo preparado para envio.", "em preparacao, dentro do prazo")

    # em transito
    previsao = f" Previsao atual: {_br(s.previsao)}." if s.previsao else ""
    ultimo = f" Ultimo evento: {s.ultimo_evento} em {s.local}, {_br(_d(s.ultimo_evento_em))}." if s.ultimo_evento else ""
    if s.atraso_du > DIAS_ATRASO_PARA_REENVIO:
        return Plano("atraso_grave", False, "", True, False,
                     f"{base}{ultimo} Atraso de {s.atraso_du} dias uteis. A politica permite reenvio ou reembolso, a escolha do cliente.",
                     f"atraso de {s.atraso_du} du (> {DIAS_ATRASO_PARA_REENVIO}): opcoes de reenvio ou reembolso ao cliente")
    if s.atraso_du > 0 or s.dias_parado >= DIAS_PARADO_PARA_CHAMADO:
        motivo = "atraso_entrega" if s.atraso_du > 0 else "rastreio_sem_atualizacao"
        razao = (f"atraso de {s.atraso_du} du" if s.atraso_du > 0 else f"rastreio parado ha {s.dias_parado} du")
        return Plano("abrir_chamado", s.chamado is None, motivo, False, False,
                     f"{base}{ultimo}{previsao} {razao.capitalize()}.{ja}" + ("" if s.chamado else " Abrimos um chamado com a transportadora."),
                     f"{razao}: " + ("chamado ja existente" if s.chamado else "chamado aberto"))
    return Plano("informar_no_prazo", False, "", False, False, f"{base}{ultimo}{previsao} Dentro do prazo.", "em transito, dentro do prazo")


def preferencia_do_cliente(texto: str) -> str | None:
    """'reembolso', 'reenvio' ou None. So le o que o cliente DISSE; nunca decide por ele."""
    t = (texto or "").lower()
    reemb = re.search(r"reembols|dinheiro de volta|estorn|devolvam o (valor|dinheiro)", t)
    reenv = re.search(r"reenvi|reenvio|mandar (outro|de novo)|enviar (outro|de novo)|novo pedido", t)
    if reemb and not reenv:
        return "reembolso"
    if reenv and not reemb:
        return "reenvio"
    return None
