"""Valida as rotas da Maya contra o que a equipe HUMANA fez nas mesmas conversas (acoes_executadas_sistemas.csv).

Entrada: lote_resultados.csv (gerado por analisar_lote/lote), so as conversas do historico (a fila aberta nao tem desfecho).
Saida: docs/validacao_rotas.md, com, por acao de efeito (reenviar, reembolsar, trocar, cancelar, chamado, endereco...):
  - concordou: agente e humano fizeram a acao;
  - so o humano: o agente perguntou, negou ou chamou uma pessoa (conservador; custo: menos resolucao);
  - so o agente: o agente fez e o humano nao fez (RISCO: pode ser generosidade indevida ou caso que o humano negou).
A ultima coluna e a que importa para risco. Nao mede qualidade do texto (ver revisao_respostas.md).
Uso:  python codigo/benchmarks/validar_rotas.py
"""
import collections
import csv
import os
import sys

import duckdb

AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.abspath(os.path.join(AQUI, "..", ".."))
ACOES_EFEITO = ["reenviar_produto", "reembolsar", "trocar_produto", "cancelar_pedido", "abrir_chamado_transportadora",
                "reimprimir_personalizacao", "alterar_endereco"]
# o agente ainda nao executa estas (so pergunta ou encaminha): aparecem como "so o humano" por construcao
SO_HUMANO_POR_DESENHO = {"alterar_endereco", "reimprimir_personalizacao"}


def _acoes_humanas() -> dict[str, set[str]]:
    pasta = os.environ.get("GOCOLEGA_DATA_DIR") or os.path.join(RAIZ, "dados", "atendimento")
    arq = os.path.join(pasta, "acoes_executadas_sistemas.csv").replace("\\", "/")
    if not os.path.exists(arq):
        sys.exit(f"Base completa nao encontrada ({arq}); esta validacao precisa de acoes_executadas_sistemas.csv")
    con = duckdb.connect()
    por_conv = collections.defaultdict(set)
    for cid, acao in con.execute(f"select conversation_id, acao from read_csv_auto('{arq}')").fetchall():
        por_conv[cid].add(acao)
    return por_conv


def main():
    humanas = _acoes_humanas()
    with open(os.path.join(AQUI, "lote_resultados.csv"), encoding="utf-8") as f:
        linhas = [r for r in csv.DictReader(f) if r["origem"] == "historico" and not r.get("erro")]
    tab = {a: collections.Counter() for a in ACOES_EFEITO}
    exemplos = collections.defaultdict(list)
    for r in linhas:
        ag = {a for a in r["acoes"].split(";") if a}
        hu = humanas.get(r["conversation_id"], set())
        for a in ACOES_EFEITO:
            if a in ag and a in hu:
                tab[a]["concordou"] += 1
            elif a in hu:
                tab[a]["so_humano"] += 1
            elif a in ag:
                tab[a]["so_agente"] += 1
                exemplos[a].append((r["conversation_id"], r["categoria"], r["desfecho"]))
    out = ["# Validação das rotas contra as ações da equipe humana", "",
           f"Conversas do histórico no lote: **{len(linhas)}**. Fonte humana: `acoes_executadas_sistemas.csv`.", "",
           "| Ação | Agente e humano fizeram | Só o humano fez | Só o agente fez (risco) |", "|---|---:|---:|---:|"]
    for a in ACOES_EFEITO:
        c = tab[a]
        nota = " (o agente só pergunta/encaminha, por desenho)" if a in SO_HUMANO_POR_DESENHO else ""
        out.append(f"| `{a}`{nota} | {c['concordou']} | {c['so_humano']} | {c['so_agente']} |")
    out += ["", "Leitura: **só o agente fez** é o número a explicar caso a caso (pode ser um caso que o humano negou ou encaminhou). "
            "**Só o humano fez** é resolução que o agente ainda deixa para uma pessoa ou para o cliente responder.", ""]
    for a, lst in exemplos.items():
        out.append(f"## Casos de `{a}` só do agente ({len(lst)})")
        out += [f"- {c} · categoria {cat} · desfecho {d}" for c, cat, d in lst[:15]] + [""]
    caminho = os.path.join(RAIZ, "docs", "validacao_rotas.md")
    with open(caminho, "w", encoding="utf-8") as f:
        f.write("\n".join(out))
    print("\n".join(out[:16]))
    print(f"\nEscrito em {caminho}")


if __name__ == "__main__":
    main()
