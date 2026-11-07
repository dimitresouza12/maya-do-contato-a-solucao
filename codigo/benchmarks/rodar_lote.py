"""Roda o GoColega em lote (fila aberta + amostra do historico) com os modelos reais e resume o que aconteceu.

O lote e SEQUENCIAL de proposito: o registro de avisos do agente e global, e um token compartilhado tem
limite de 250 requisicoes por minuto.

Uso (da raiz, com a base completa):  python codigo/benchmarks/rodar_lote.py [N_HISTORICO=150] [SEMENTE=42]
Saida: codigo/benchmarks/lote_resultados.csv (sem o texto do cliente) e o resumo no terminal.
"""
import csv
import os
import random
import statistics
import sys
import time
from collections import Counter

RAIZ = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(RAIZ, "codigo"))
from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(RAIZ, ".env"))
sys.stdout.reconfigure(encoding="utf-8")

from gocolega import dados, llm, modelos  # noqa: E402
from gocolega.orquestrador import tratar  # noqa: E402

N_HIST = int(sys.argv[1]) if len(sys.argv) > 1 else 150
SEMENTE = int(sys.argv[2]) if len(sys.argv) > 2 else 42
SAIDA = os.path.join(RAIZ, "codigo", "benchmarks", "lote_resultados.csv")


def escolher() -> list[tuple[str, str]]:
    com_texto = "exists (select 1 from historico_mensagens m where m.conversation_id = {t}.conversation_id and m.autor = 'cliente')"
    fila = dados.consulta(f"select conversation_id from fila_aberta f where {com_texto.format(t='f')} order by 1")
    hist = dados.consulta(f"select conversation_id from historico_conversas c where {com_texto.format(t='c')} order by 1")
    ids = [h["conversation_id"] for h in hist]
    random.Random(SEMENTE).shuffle(ids)
    return [("fila", f["conversation_id"]) for f in fila] + [("historico", i) for i in ids[:N_HIST]]


def main():
    alvo = escolher()
    print(f"Lote: {sum(o == 'fila' for o, _ in alvo)} da fila + {sum(o == 'historico' for o, _ in alvo)} do historico "
          f"| modelos: Jev, {modelos.PRINCIPAL}, {modelos.SUB}", flush=True)
    linhas, ini = [], time.time()
    for k, (origem, cid) in enumerate(alvo, 1):
        t0 = time.time()
        try:
            r, ferr = tratar(cid)
            conv = dados.uma("select canal, marca from historico_conversas where conversation_id = ? "
                             "union all select canal, marca from fila_aberta where conversation_id = ?", [cid, cid]) or {}
            passos = " | ".join(r.passos)
            linhas.append({
                "origem": origem, "conversation_id": cid, "canal": conv.get("canal"), "marca": conv.get("marca"),
                "categoria": r.categoria, "desfecho": r.desfecho,
                "p_falsa": round(r.dossie.p_falsa, 3) if r.dossie else "",
                "sinais": ";".join(s.nome for s in r.dossie.sinais) if r.dossie else "",
                "cascata": "Confianca baixa" in passos,
                "sem_consenso": "sem consenso" in passos,
                "avisos": passos.count("AVISO:"),
                "avisos_texto": " || ".join(p for p in r.passos if p.startswith("AVISO")),
                "n_mensagens": len(r.bus.transcricao),
                "acoes": ";".join(e["ferramenta"] for e in ferr.log if e["ferramenta"] != "classificar_conversa"),
                "segundos": round(time.time() - t0, 1), "erro": "",
            })
        except Exception as e:  # um caso ruim nao derruba o lote
            linhas.append({"origem": origem, "conversation_id": cid, "desfecho": "ERRO", "erro": f"{type(e).__name__}: {str(e)[:80]}",
                           "segundos": round(time.time() - t0, 1)})
        if k % 10 == 0 or k == len(alvo):
            print(f"  {k}/{len(alvo)} ({time.time() - ini:.0f}s)", flush=True)

    campos = ["origem", "conversation_id", "canal", "marca", "categoria", "desfecho", "p_falsa", "sinais", "cascata",
              "sem_consenso", "avisos", "avisos_texto", "n_mensagens", "acoes", "segundos", "erro"]
    with open(SAIDA, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=campos)
        w.writeheader()
        w.writerows(linhas)

    def resumo(rotulo, g):
        n = len(g)
        if not n:
            return
        c = Counter(x["desfecho"] for x in g)
        print(f"\n### {rotulo} (n={n})")
        for d, q in c.most_common():
            print(f"  {d:22s} {q:4d}  {100 * q / n:5.1f}%")
        casc = [x for x in g if x.get("cascata")]
        if casc:
            nc = sum(bool(x.get("sem_consenso")) for x in casc)
            print(f"  cascata acionada em {len(casc)} ({100 * len(casc) / n:.0f}%); sem consenso em {nc} desses ({100 * nc / len(casc):.0f}%)")
        flag = [x for x in g if x["desfecho"] == "suspeita"]
        print(f"  suspeitas sinalizadas: {len(flag)}")
        av = sum(int(x.get("avisos") or 0) for x in g)
        print(f"  avisos de falha de modelo: {av} em {sum(int(x.get('avisos') or 0) > 0 for x in g)} casos; erros do lote: {sum(x['desfecho'] == 'ERRO' for x in g)}")

    resumo("TODOS", linhas)
    resumo("FILA ABERTA", [x for x in linhas if x["origem"] == "fila"])
    resumo("HISTORICO (amostra)", [x for x in linhas if x["origem"] == "historico"])

    # Teto de tempo humano nas conversas que o GoColega trataria sozinho (so historico, que tem tempo_por_conversa)
    auto = [x["conversation_id"] for x in linhas if x["origem"] == "historico" and x["desfecho"] == "autonomo"]
    if auto:
        lista = ",".join(f"'{a}'" for a in auto)
        t = dados.uma(f"select count(*) n, round(sum(minutos_trabalhados), 0) minutos, round(avg(minutos_trabalhados), 1) media "
                      f"from tempo_por_conversa where conversation_id in ({lista})")
        print(f"\nTempo humano gasto nas {len(auto)} conversas do historico que o GoColega resolveu sozinho: "
              f"{t['n']} com tempo registrado, {t['minutos']} min no total (media {t['media']} min). "
              f"E um TETO, nao uma economia garantida.")
    seg = [x["segundos"] for x in linhas if x.get("segundos") is not None]
    print(f"\nTempo por conversa: media {statistics.mean(seg):.1f}s, maximo {max(seg):.1f}s | total {time.time() - ini:.0f}s")
    print("\n" + llm.linha_custo())


if __name__ == "__main__":
    main()
