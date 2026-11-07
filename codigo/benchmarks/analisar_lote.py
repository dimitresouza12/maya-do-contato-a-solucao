"""Analisa codigo/benchmarks/lote_resultados.csv (gerado por rodar_lote.py): o que o GoColega fez em cada caso,
de que rota veio, e quanto concorda com o que o atendente humano FEZ de fato nas conversas do historico.

Uso (da raiz, com a base completa):  python codigo/benchmarks/analisar_lote.py
"""
import csv
import os
import sys
from collections import Counter, defaultdict

RAIZ = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(RAIZ, "codigo"))
sys.stdout.reconfigure(encoding="utf-8")
from gocolega import dados  # noqa: E402

linhas = list(csv.DictReader(open(os.path.join(RAIZ, "codigo", "benchmarks", "lote_resultados.csv"), encoding="utf-8")))
hist = [l for l in linhas if l["origem"] == "historico"]
print(f"Casos: {len(linhas)} (fila {sum(l['origem'] == 'fila' for l in linhas)}, historico {len(hist)})")

print("\n## Desfecho por categoria da triagem (todos)")
por = defaultdict(Counter)
for l in linhas:
    por[l["categoria"]][l["desfecho"]] += 1
for cat, c in sorted(por.items(), key=lambda x: -sum(x[1].values())):
    print(f"  {cat:20s} n={sum(c.values()):3d}  " + ", ".join(f"{d}={q}" for d, q in c.most_common()))

print("\n## O que 'autonomo' significou (acoes executadas)")
auto = [l for l in linhas if l["desfecho"] == "autonomo"]
tipos = Counter()
for l in auto:
    a = l["acoes"]
    tipos["reenvio executado" if "reenviar_produto" in a else "so informou ao cliente" if "responder_cliente" in a else "outro"] += 1
for t, q in tipos.most_common():
    print(f"  {t:26s} {q:3d} ({100 * q / len(auto):.0f}% dos autonomos)")

print("\n## Por que 'escalado' (36% dos casos)")
esc = [l for l in linhas if l["desfecho"] == "escalado"]
motivo = Counter()
for l in esc:
    if l["sem_consenso"] == "True":
        motivo["cascata sem consenso"] += 1
    elif l["categoria"] in ("Avaria", "Produto faltando", "Reclamacao produto", "Rastreio", "Atraso"):
        motivo["rota executada, mas pedido sem condicao (ex.: sem pedido, extravio, status)"] += 1
    else:
        motivo["categoria fora do escopo da POC"] += 1
for m, q in motivo.most_common():
    print(f"  {m:70s} {q:3d}")

print("\n## Concordancia com o atendente HUMANO (so historico: o humano deixou registro em trocas_reenvios)")
ids = ",".join(f"'{l['conversation_id']}'" for l in hist)
humano = {r["conversation_id"]: r["tipo"] for r in dados.consulta(
    f"select conversation_id, tipo from trocas_reenvios where conversation_id in ({ids})")}
m = Counter()
for l in hist:
    gc = "reenvia" if "reenviar_produto" in l["acoes"] else "nao reenvia"
    hm = "reenviou/trocou" if l["conversation_id"] in humano else "nao"
    m[(gc, hm)] += 1
print("                         humano reenviou/trocou | humano nao")
print(f"  GoColega reenvia       {m[('reenvia', 'reenviou/trocou')]:12d}          | {m[('reenvia', 'nao')]:5d}")
print(f"  GoColega nao reenvia   {m[('nao reenvia', 'reenviou/trocou')]:12d}          | {m[('nao reenvia', 'nao')]:5d}")
conc = m[('reenvia', 'reenviou/trocou')] + m[('nao reenvia', 'nao')]
print(f"  concordancia simples: {conc}/{len(hist)} = {100 * conc / len(hist):.0f}%")
com_reenvio_humano = [l for l in hist if l["conversation_id"] in humano]
print(f"  conversas em que o humano reenviou/trocou: {len(com_reenvio_humano)}; destas, o GoColega: " +
      ", ".join(f"{d}={q}" for d, q in Counter(l['desfecho'] for l in com_reenvio_humano).most_common()))

print("\n## Falhas de modelo (cada AVISO e uma chamada que caiu para o caminho deterministico)")
print(f"  casos com aviso: {sum(int(l['avisos'] or 0) > 0 for l in linhas)}; total de avisos: {sum(int(l['avisos'] or 0) for l in linhas)}; "
      f"na fila: {sum(int(l['avisos'] or 0) for l in linhas if l['origem'] == 'fila')}")

print("\n## Tempo humano nas conversas do historico que o GoColega resolveu sozinho (TETO, nao economia)")
a_h = [l["conversation_id"] for l in hist if l["desfecho"] == "autonomo"]
t = dados.uma(f"select count(*) n, round(sum(minutos_trabalhados), 0) minutos, round(avg(minutos_trabalhados), 1) media "
              f"from tempo_por_conversa where conversation_id in ({','.join(repr(x) for x in a_h)})")
print(f"  {len(a_h)} conversas autonomas no historico; {t['n']} com tempo registrado: {t['minutos']} min no total, media {t['media']} min")
tot = dados.uma("select round(sum(minutos_trabalhados), 0) minutos, count(*) n from tempo_por_conversa")
print(f"  base inteira: {tot['n']} conversas, {tot['minutos']} min de trabalho humano ({tot['minutos'] / 60:.0f} h)")

print("\n## Tempo de processamento por caso (segundos)")
seg = sorted(float(l["segundos"]) for l in linhas if l["segundos"])
print(f"  mediana {seg[len(seg) // 2]:.1f}s | p90 {seg[int(0.9 * (len(seg) - 1))]:.1f}s | max {seg[-1]:.1f}s")

print("\n## Por canal (todos os casos)")
pc = defaultdict(Counter)
for l in linhas:
    pc[l["canal"]][l["desfecho"]] += 1
for canal, c in pc.items():
    n = sum(c.values())
    print(f"  {canal:14s} n={n:3d}  autonomo {100 * c['autonomo'] / n:3.0f}% | escalado {100 * c['escalado'] / n:3.0f}% | "
          f"aguardando_cliente {100 * c['aguardando_cliente'] / n:3.0f}% | outros {100 * (n - c['autonomo'] - c['escalado'] - c['aguardando_cliente']) / n:3.0f}%")
