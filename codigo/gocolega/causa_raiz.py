"""Causa raiz e aviso proativo (frentes 8 e 9 do plano).

Procura concentracoes de problemas que um atendente, conversa a conversa, nao enxerga:
transportadora+UF (atraso/rastreio), impressora (reimpressao/avaria) e lote (reclamacao de produto).
Um grupo vira INCIDENTE so quando a taxa de problemas e bem maior que a do resto da base E a
diferenca e estatisticamente clara (teste z de duas proporcoes). Nao ha LLM aqui: e contagem e estatistica.

Como e so um alerta ao analista, a regra e conservadora: tamanho minimo, razao minima e z minimo.
"""
import math
from dataclasses import dataclass, field
from datetime import date, datetime
from statistics import NormalDist

from . import dados

MIN_PEDIDOS = 30      # grupos menores sao ruido
MIN_CASOS = 5         # poucos problemas num grupo pequeno nao provam nada (visto num falso alarme de 2 casos em 38 pedidos)
MIN_RAZAO = 1.5       # taxa do grupo / taxa do resto
ALFA = 0.01           # chance de falso alarme, dividida pelo numero de grupos testados (Bonferroni)
MAX_NOTIFICACOES_DIA = 300  # parametros.md: o analista notifica ate 300 clientes por dia

# tags que contam como "problema" em cada dimensao
PROBLEMAS = {
    "transportadora_uf": ("Atraso", "Rastreio"),
    "maquina": ("Avaria", "Reclamacao produto", "Troca"),
    "lote": ("Avaria", "Reclamacao produto"),
}


@dataclass
class Incidente:
    dimensao: str
    escopo: dict
    pedidos: int
    com_problema: int
    taxa: float
    taxa_resto: float
    razao: float
    z: float
    em_aberto: list[str] = field(default_factory=list)  # pedidos do escopo ainda a caminho, sem conversa

    def resumo(self) -> str:
        return (f"{self.dimensao} {self.escopo}: {self.com_problema}/{self.pedidos} pedidos geraram problema "
                f"({self.taxa:.0%}) contra {self.taxa_resto:.0%} no resto da base "
                f"(razao {self.razao:.1f}x, z={self.z:.1f})")


def _z(k1: int, n1: int, k2: int, n2: int) -> float:
    if n1 == 0 or n2 == 0:
        return 0.0
    p = (k1 + k2) / (n1 + n2)
    var = p * (1 - p) * (1 / n1 + 1 / n2)
    return 0.0 if var == 0 else (k1 / n1 - k2 / n2) / math.sqrt(var)


def _normaliza(tag: str | None) -> str:
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFKD", tag or "") if not unicodedata.combining(c)).strip()


def _base(corte: datetime) -> list[dict]:
    """Um registro por pedido, com a marca de 'gerou conversa-problema' usando so conversas ate o corte."""
    return dados.consulta("""
        select p.order_id, p.transportadora, p.uf, p.maquina_personalizacao maquina, p.lote_produto lote,
               p.status_entrega, p.data_pedido, p.data_entrega,
               list(distinct c.tag_agente) filter (where c.data_abertura <= ?) tags,
               count(c.conversation_id) filter (where c.data_abertura <= ?) n_conversas
        from pedidos p left join historico_conversas c on c.order_id = p.order_id
        where p.data_pedido <= ?
        group by 1,2,3,4,5,6,7,8""", [corte, corte, corte])


def _tem_problema(linha: dict, dimensao: str) -> bool:
    tags = {_normaliza(t) for t in (linha["tags"] or [])}
    return bool(tags & set(PROBLEMAS[dimensao]))


def _chave(linha: dict, dimensao: str):
    if dimensao == "transportadora_uf":
        return (linha["transportadora"], linha["uf"]) if linha["transportadora"] and linha["uf"] else None
    return linha["maquina"] if dimensao == "maquina" and linha["maquina"] else (
        linha["lote"] if dimensao == "lote" and linha["lote"] else None)


def _a_caminho(linha: dict, corte: datetime) -> bool:
    entregue = linha["data_entrega"]
    ainda = entregue is None or (isinstance(entregue, (date, datetime)) and
                                 datetime.combine(entregue, datetime.min.time()) > corte
                                 if not isinstance(entregue, datetime) else entregue > corte)
    return ainda and linha["status_entrega"] not in ("cancelado", "devolvido", "extraviado")


def _z_limite(grupos_testados: int, alfa: float = ALFA) -> float:
    """Bonferroni: quanto mais grupos se testa, mais alto o z exigido (senao alguns 'acham' sorte)."""
    return NormalDist().inv_cdf(1 - alfa / max(1, grupos_testados))


def detectar(corte: datetime, min_pedidos: int = MIN_PEDIDOS, min_razao: float = MIN_RAZAO,
             z_min: float | None = None) -> list[Incidente]:
    """Incidentes visiveis usando SOMENTE conversas ate `corte` (sem enxergar o futuro).
    z_min=None usa o limite de Bonferroni pelo numero de grupos testados em cada dimensao."""
    base = _base(corte)
    saida: list[Incidente] = []
    for dim in PROBLEMAS:
        grupos: dict = {}
        for l in base:
            k = _chave(l, dim)
            if k is not None:
                grupos.setdefault(k, []).append(l)
        total_n = sum(len(v) for v in grupos.values())
        total_k = sum(_tem_problema(l, dim) for v in grupos.values() for l in v)
        achados = []
        testados = sum(1 for v in grupos.values() if len(v) >= min_pedidos)
        limite = z_min if z_min is not None else _z_limite(testados)
        for k, v in grupos.items():
            n, kk = len(v), sum(_tem_problema(l, dim) for l in v)
            if n < min_pedidos or kk < MIN_CASOS:
                continue
            n2, k2 = total_n - n, total_k - kk
            taxa, resto = kk / n, (k2 / n2 if n2 else 0.0)
            razao = taxa / resto if resto else float("inf")
            z = _z(kk, n, k2, n2)
            if razao >= min_razao and z >= limite:
                achados.append((k, v, n, kk, taxa, resto, razao, z))
        if dim == "transportadora_uf":  # um incidente por transportadora, com as UFs afetadas
            por_transp: dict = {}
            for a in achados:
                por_transp.setdefault(a[0][0], []).append(a)
            for transp, itens in por_transp.items():
                pedidos = [l for a in itens for l in a[1]]
                n, kk = len(pedidos), sum(_tem_problema(l, dim) for l in pedidos)
                n2, k2 = total_n - n, total_k - kk
                resto = k2 / n2 if n2 else 0.0
                saida.append(Incidente(
                    dim, {"transportadora": transp, "ufs": sorted(a[0][1] for a in itens)}, n, kk, kk / n, resto,
                    (kk / n) / resto if resto else float("inf"), _z(kk, n, k2, n2),
                    sorted(l["order_id"] for l in pedidos if _a_caminho(l, corte) and not l["n_conversas"])))
        else:
            for k, v, n, kk, taxa, resto, razao, z in achados:
                saida.append(Incidente(dim, {dim: k}, n, kk, taxa, resto, razao, z,
                                       sorted(l["order_id"] for l in v if _a_caminho(l, corte) and not l["n_conversas"])))
    return sorted(saida, key=lambda i: -i.z)


TEXTO_AVISO = ("Oi! Seu pedido {pedido} esta a caminho com a transportadora {transp} e pode chegar um pouco depois "
               "do previsto. Ja estamos acompanhando com a transportadora e avisamos assim que tivermos novidades.")


def preparar_aviso(incidente: Incidente) -> dict:
    """Prepara a notificacao proativa (nao envia). So vale para incidente de transportadora."""
    transp = incidente.escopo.get("transportadora")
    if not transp:
        return {"pedidos": [], "texto": "", "motivo": "aviso proativo so existe para incidente de transportadora"}
    return {"pedidos": incidente.em_aberto, "texto": TEXTO_AVISO.format(pedido="{pedido}", transp=transp),
            "motivo": f"{transp} concentra atraso/rastreio em {', '.join(incidente.escopo['ufs'])}"}


def tratar(ferr, corte: datetime, aprovado: bool = False) -> list[dict]:
    """Abre os incidentes e prepara os avisos. O envio em massa depende de aprovacao de uma pessoa
    (aprovado=True) e respeita o teto diario de 300 clientes."""
    resultados = []
    for inc in detectar(corte):
        ferr.abrir_incidente(inc.dimensao, inc.escopo, inc.resumo())
        aviso = preparar_aviso(inc)
        enviados = 0
        if aviso["pedidos"]:
            if aprovado:
                lote = aviso["pedidos"][:MAX_NOTIFICACOES_DIA]
                ferr.notificar_clientes(lote, "atraso_provavel", aviso["texto"])
                enviados = len(lote)
            else:
                ferr.acionar_pessoa("logistica", "Aprovar aviso proativo de atraso",
                                    f"{inc.resumo()}. {len(aviso['pedidos'])} pedidos a caminho, sem conversa aberta.", "normal")
        resultados.append({"incidente": inc, "preparados": len(aviso["pedidos"]), "enviados": enviados,
                           "restante_para_amanha": max(0, len(aviso["pedidos"]) - enviados) if aprovado else 0})
    return resultados


def retroteste(corte: datetime, fim: datetime | None = None) -> dict:
    """O alerta teria acertado? Detecta com dados ATE o corte e mede o que aconteceu DEPOIS:
    dos pedidos a caminho no corte, quantos do escopo do incidente abriram conversa-problema depois,
    contra os demais pedidos a caminho. A situacao do pedido no corte e aproximada pelas datas
    (pedido feito ate o corte e ainda nao entregue)."""
    incs = [i for i in detectar(corte) if i.dimensao == "transportadora_uf"]
    fim = fim or datetime(2026, 11, 2, 8, 0)
    probl = PROBLEMAS["transportadora_uf"]
    linhas = dados.consulta("""
        select p.order_id, p.transportadora, p.uf,
               count(c.conversation_id) filter (where c.data_abertura > ? and c.data_abertura <= ?
                                                 and c.tag_agente in ('Atraso','Rastreio')) depois,
               count(c.conversation_id) filter (where c.data_abertura <= ?) antes
        from pedidos p left join historico_conversas c on c.order_id = p.order_id
        where p.data_pedido <= ? and (p.data_entrega is null or p.data_entrega > ?)
          and p.status_entrega not in ('cancelado','devolvido')
        group by 1,2,3""", [corte, fim, corte, corte, corte])
    alvo = {(i.escopo["transportadora"], uf) for i in incs for uf in i.escopo["ufs"]}
    dentro = [l for l in linhas if (l["transportadora"], l["uf"]) in alvo and not l["antes"]]
    fora = [l for l in linhas if (l["transportadora"], l["uf"]) not in alvo and not l["antes"]]
    f = lambda g: (sum(1 for l in g if l["depois"]) / len(g)) if g else 0.0
    return {"corte": corte.date().isoformat(), "incidentes": [i.resumo() for i in incs],
            "avisados": len(dentro), "dentro_taxa": f(dentro), "fora_n": len(fora), "fora_taxa": f(fora),
            "problemas": probl}
