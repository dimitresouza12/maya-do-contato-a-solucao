"""Galeria de respostas: roda o agente em conversas reais da base e grava, para cada uma, a mensagem do cliente,
o que o GoColega fez (ferramentas), a resposta enviada e o desfecho. Inclui os casos que vao para uma pessoa.

Uso (da raiz, com a base completa e o token):  python codigo/ferramentas_dev/galeria_respostas.py [N por categoria=3] [semente=11]
Saida: docs/galeria_respostas.md. Nada e escolhido a dedo: o sorteio e por semente e as categorias sao as da etiqueta humana.
"""
import os
import random
import sys
import unicodedata

RAIZ = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(RAIZ, "codigo"))
from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(RAIZ, ".env"))
sys.stdout.reconfigure(encoding="utf-8")

from gocolega import dados, llm  # noqa: E402
from gocolega.ferramentas import mascarar_pii  # noqa: E402
from gocolega.orquestrador import tratar  # noqa: E402

N = int(sys.argv[1]) if len(sys.argv) > 1 else 3
SEMENTE = int(sys.argv[2]) if len(sys.argv) > 2 else 11
CATEGORIAS = ["Rastreio", "Atraso", "Avaria", "Produto faltando", "Troca", "Cancelamento", "Endereco", "Financeiro",
              "Promocao", "Duvida", "Elogio", "Reclamacao produto"]
ROTULO = {"autonomo": "Resolvido pelo agente", "aguardando_cliente": "Perguntou ao cliente", "fora_da_politica": "Negou pela política, com a regra",
          "aguardando_supervisor": "Pediu aprovação (acima da alçada)", "aguardando_aprovacao": "Rascunho público (Reclame Aqui)",
          "suspeita": "Sinalizou suspeita", "sensivel": "Caso sensível", "escalado": "Foi para uma pessoa"}


def norm(s):
    return "".join(c for c in unicodedata.normalize("NFKD", s or "") if not unicodedata.combining(c)).strip()


def main():
    tags = {norm(r["tag_agente"]): r["tag_agente"] for r in dados.consulta(
        "select distinct tag_agente from historico_conversas where tag_agente is not null")}
    linhas = ["# Galeria de respostas do GoColega", "",
              "Conversas **reais da base** (dados fictícios do evento), sorteadas por semente, sem escolha a dedo. "
              "Cada caso mostra a mensagem do cliente, o que o agente fez e a resposta que enviou (simulada: vai para o log, "
              "não para um WhatsApp real). Os casos que vão para uma pessoa também estão aqui.", "",
              f"Gerado por `python codigo/ferramentas_dev/galeria_respostas.py {N} {SEMENTE}` com os modelos reais.", ""]
    resumo = {}
    for cat in CATEGORIAS:
        real = tags.get(cat)
        if not real:
            continue
        ids = [r["conversation_id"] for r in dados.consulta(
            "select conversation_id from historico_conversas where tag_agente = ? order by conversation_id", [real])]
        random.Random(SEMENTE).shuffle(ids)
        linhas += [f"## {real} (etiqueta do atendente)", ""]
        for cid in ids[:N]:
            msgs = dados.consulta("select autor, texto from historico_mensagens where conversation_id = ? and autor='cliente' order by timestamp", [cid])
            cliente = mascarar_pii(" / ".join(m["texto"] for m in msgs))[:420]
            try:
                r, ferr = tratar(cid)
            except Exception as e:  # um caso que quebra aparece na galeria, nao e escondido
                linhas += [f"### {cid}", "", f"**Erro:** `{type(e).__name__}: {str(e)[:160]}`", ""]
                resumo[cat] = resumo.get(cat, []) + ["erro"]
                continue
            envios = [e for e in ferr.log if e["ferramenta"] == "responder_cliente"]
            acoes = [e["ferramenta"] for e in ferr.log if e["ferramenta"] not in ("classificar_conversa", "responder_cliente")]
            resposta = envios[-1]["texto"] if envios else "(nenhuma mensagem ao cliente: foi para uma pessoa)"
            linhas += [f"### {cid} · {ROTULO.get(r.desfecho, r.desfecho)}", "",
                       f"> **Cliente:** {cliente}", "",
                       f"**GoColega** (triagem: *{r.categoria}*; ações: {', '.join(acoes) or 'nenhuma'}):", "",
                       f"> {resposta}", ""]
            avisos = [p for p in r.passos if p.startswith("AVISO")]
            if avisos:
                linhas += [f"*{avisos[0]}*", ""]
            resumo.setdefault(cat, []).append(r.desfecho)
            print(f"{cat:20s} {cid} {r.desfecho}")
    todos = [d for v in resumo.values() for d in v]
    linhas += ["---", "", f"**Resumo desta galeria ({len(todos)} conversas):** " +
               ", ".join(f"{ROTULO.get(k, k)} {todos.count(k)}" for k in dict.fromkeys(todos)), "",
               "Esta amostra é pequena e serve para ver o comportamento; os números medidos estão no README.", ""]
    destino = os.path.join(RAIZ, "docs", "galeria_respostas.md")
    open(destino, "w", encoding="utf-8").write("\n".join(linhas))
    print("gravado", destino)
    print(llm.linha_custo())


if __name__ == "__main__":
    main()
