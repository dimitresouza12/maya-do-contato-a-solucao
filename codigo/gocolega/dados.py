"""Acesso aos CSVs de atendimento via DuckDB (somente leitura)."""
import os
from functools import lru_cache

import duckdb

TABELAS = [
    "historico_conversas", "historico_mensagens", "fila_aberta", "pedidos", "clientes",
    "anexos_conversas", "trocas_reenvios", "itens_pedido", "produtos", "ferramentas",
    "equipe_atendimento", "chamados_transportadora", "rastreio_portais_transportadoras",
    "pagamentos_gateway", "estornos", "politicas", "tempo_por_conversa",
    "avaliacoes_csat", "reclame_aqui", "lotes_producao", "maquinas_personalizacao", "cupons", "uso_cupons",
]


def pasta_dados() -> str:
    # Ordem: GOCOLEGA_DATA_DIR > dados/atendimento (base completa) > dados/amostra (vem no repositorio).
    # Este arquivo fica em <raiz>/codigo/gocolega/
    dados_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "dados")
    completa = os.path.join(dados_dir, "atendimento")
    amostra = os.path.join(dados_dir, "amostra")
    if os.environ.get("GOCOLEGA_DATA_DIR"):
        p = os.path.abspath(os.environ["GOCOLEGA_DATA_DIR"])
    elif os.path.exists(os.path.join(completa, "pedidos.csv")):
        p = os.path.abspath(completa)
    else:
        p = os.path.abspath(amostra)
    if not os.path.isdir(p):
        raise FileNotFoundError(
            f"Pasta de dados nao encontrada: {p}. Veja dados/LEIAME.md ou defina GOCOLEGA_DATA_DIR."
        )
    return p.replace("\\", "/")


def usando_amostra() -> bool:
    return os.path.basename(pasta_dados().rstrip("/")) == "amostra"


@lru_cache(maxsize=1)
def conexao() -> duckdb.DuckDBPyConnection:
    d = pasta_dados()
    con = duckdb.connect()
    for t in TABELAS:
        arq = f"{d}/{t}.csv"
        if os.path.exists(arq):
            con.execute(
                f"create view {t} as select * from read_csv_auto('{arq}', header=true, sample_size=-1)"
            )
    return con


def consulta(sql: str, params: list | None = None) -> list[dict]:
    """Executa SQL parametrizado e devolve lista de dicts."""
    cur = conexao().execute(sql, params or [])
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, linha)) for linha in cur.fetchall()]


def uma(sql: str, params: list | None = None) -> dict | None:
    r = consulta(sql, params)
    return r[0] if r else None
