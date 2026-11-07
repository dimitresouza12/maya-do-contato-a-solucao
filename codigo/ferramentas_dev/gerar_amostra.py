"""Gera dados/amostra/ a partir da base completa, para a demo rodar SEM baixar o zip do Drive.

A amostra traz apenas as linhas das conversas da demo (e das fotos que elas compartilham com outros
pedidos), das mesmas tabelas que o codigo le. Sao dados FICTICIOS do evento, so um recorte minimo.

Uso (da raiz, com a base completa em dados/atendimento/ ou em GOCOLEGA_DATA_DIR):
    python codigo/ferramentas_dev/gerar_amostra.py
"""
import os
import sys

RAIZ = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(RAIZ, "codigo"))

from gocolega import dados  # noqa: E402

CONVERSAS = ["AT105180", "AT108528", "AT108179", "AT107296", "AT105718", "AT105041", "AT104736"]  # cenas da demo e dos testes
DESTINO = os.path.join(RAIZ, "dados", "amostra")


def main():
    con = dados.conexao()
    os.makedirs(DESTINO, exist_ok=True)
    lista = ",".join(f"'{c}'" for c in CONVERSAS)
    con.execute(f"create temp table conv as select * from historico_conversas where conversation_id in ({lista})")
    con.execute("create temp table ped as select p.* from pedidos p where order_id in (select order_id from conv)")
    # fotos das conversas da demo + fotos de outros pedidos com a MESMA imagem (sinal de foto reutilizada)
    con.execute(f"""create temp table anx as select * from anexos_conversas
        where conversation_id in ({lista})
           or hash_perceptual in (select hash_perceptual from anexos_conversas where conversation_id in ({lista}))""")
    saidas = {
        "historico_conversas": "select * from conv",
        "historico_mensagens": f"select * from historico_mensagens where conversation_id in ({lista})",
        "fila_aberta": "select * from fila_aberta limit 0",
        "pedidos": "select * from ped",
        "itens_pedido": "select * from itens_pedido where order_id in (select order_id from ped)",
        "clientes": "select * from clientes where customer_id in (select customer_id from conv)",
        "anexos_conversas": "select * from anx",
        "trocas_reenvios": "select * from trocas_reenvios where order_id_original in (select order_id from ped)",
        "ferramentas": "select * from ferramentas",
        # rastreio e chamados dos pedidos da demo (sem eles, as cenas de atraso e rastreio mudam de resultado)
        "rastreio_portais_transportadoras": "select * from rastreio_portais_transportadoras "
                                            "where codigo_rastreio in (select codigo_rastreio from ped)",
        "chamados_transportadora": "select * from chamados_transportadora where order_id in (select order_id from ped)",
        # base de conhecimento (RAG): fichas de produto e politicas completas (sao pequenas)
        "produtos": "select * from produtos",
        "politicas": "select * from politicas",
    }
    for nome, sql in saidas.items():
        arq = os.path.join(DESTINO, f"{nome}.csv").replace("\\", "/")
        con.execute(f"copy ({sql}) to '{arq}' (header, delimiter ',')")
        n = con.execute(f"select count(*) from ({sql})").fetchone()[0]
        print(f"{nome:22s} {n:3d} linhas")


if __name__ == "__main__":
    main()
