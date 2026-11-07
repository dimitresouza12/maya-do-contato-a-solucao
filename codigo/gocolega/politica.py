"""Policy Engine: regras de alcada, prazo e papel em CODIGO (nao confiadas ao LLM).

Fonte: politicas.csv / parametros.md do evento.
"""
from dataclasses import dataclass
from datetime import datetime

LIMITES = {
    "reenviar_produto": 200.0,
    "reimprimir_personalizacao": 200.0,
    "trocar_produto": 200.0,
    "reembolsar": 100.0,
}
PRAZO_DIAS_CORRIDOS = 7  # avaria, item faltante, erro de personalizacao
CATEGORIAS_COM_FOTO = {"avaria_vazamento", "item_faltante", "erro_personalizacao"}
ACOES_POR_CATEGORIA = {
    "avaria_vazamento": {"solicitar_foto", "reenviar_produto"},
    "item_faltante": {"solicitar_foto", "reenviar_produto"},
    "erro_personalizacao": {"solicitar_foto", "reimprimir_personalizacao"},
    "atraso_entrega": {"abrir_chamado_transportadora", "reenviar_produto", "reembolsar"},
    "onde_esta_pedido": {"informar_status", "abrir_chamado_transportadora"},
}


@dataclass
class Decisao:
    resultado: str  # "permitido" | "precisa_aprovacao" | "negado"
    motivo: str
    regra: str = ""

    @property
    def permitido(self) -> bool:
        return self.resultado == "permitido"


def avaliar_acao(
    acao: str,
    categoria: str,
    valor: float,
    data_entrega: datetime | None,
    agora: datetime,
    tem_foto: bool,
    trocas_no_pedido: int = 0,
    aprovacao_id: str | None = None,
) -> Decisao:
    if acao not in ACOES_POR_CATEGORIA.get(categoria, set()) and acao != "solicitar_foto":
        return Decisao("negado", f"'{acao}' nao e permitida para a categoria {categoria}", "categorias.acoes_permitidas")

    if categoria in CATEGORIAS_COM_FOTO and acao != "solicitar_foto" and not tem_foto:
        return Decisao("negado", "A politica exige foto antes de reenviar/reimprimir", f"{categoria}.exige_foto")

    if data_entrega is not None and categoria in CATEGORIAS_COM_FOTO:
        if not isinstance(data_entrega, datetime):  # o CSV traz so a data (date)
            data_entrega = datetime.combine(data_entrega, datetime.min.time())
        dias = (agora - data_entrega).days
        if dias > PRAZO_DIAS_CORRIDOS:
            return Decisao(
                "negado",
                f"Fora do prazo: {dias} dias desde a entrega (maximo {PRAZO_DIAS_CORRIDOS})",
                f"{categoria}.prazo_dias_corridos_do_recebimento",
            )

    if acao == "trocar_produto" and trocas_no_pedido >= 1:
        return Decisao("negado", "Ja existe 1 troca neste pedido (maximo 1 por pedido)", "troca.max_por_pedido")

    limite = LIMITES.get(acao)
    if limite is not None and valor > limite and not aprovacao_id:
        return Decisao(
            "precisa_aprovacao",
            f"Valor R$ {valor:.2f} acima da alcada do atendente (R$ {limite:.2f})",
            "limites_por_papel.atendente.acima_do_limite",
        )
    return Decisao("permitido", "Dentro da politica e da alcada", "ok")


def pode_aprovar(aprovador: str, solicitante: str) -> Decisao:
    """Segregacao de funcoes: ninguem aprova a propria acao."""
    if aprovador == solicitante:
        return Decisao("negado", "O supervisor nao aprova a propria acao", "limites_por_papel.supervisor.nao_aprova_a_propria_acao")
    return Decisao("permitido", "Aprovador diferente do solicitante", "ok")
