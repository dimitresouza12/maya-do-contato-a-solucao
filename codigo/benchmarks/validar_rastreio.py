"""Valida a regra de Rastreio e Atraso contra o que os atendentes HUMANOS fizeram (so base completa).

Para cada conversa que o humano etiquetou como Rastreio ou Atraso, calcula o que A Maya decidiria com os dados
disponiveis NA DATA DA CONVERSA (sem vazar o futuro) e compara com:
  - chamado na transportadora aberto pelo humano nessa conversa (chamados_transportadora.conversation_id)
  - reenvio/troca por atraso ou extravio registrado pelo humano (trocas_reenvios, motivo atraso_ou_extravio)
Nao usa modelo de linguagem: so a logica de politica (rastreio.py).

Uso (da raiz):  python codigo/benchmarks/validar_rastreio.py
"""
import os
import sys
from collections import Counter

RAIZ = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(RAIZ, "codigo"))
sys.stdout.reconfigure(encoding="utf-8")
from gocolega import dados, rastreio  # noqa: E402

convs = dados.consulta("""
    select c.conversation_id, c.tag_agente, c.data_abertura, p.*
    from historico_conversas c join pedidos p using(order_id)
    where c.tag_agente in ('Rastreio', 'Atraso')""")
chamado_humano = {r["conversation_id"] for r in dados.consulta("select distinct conversation_id from chamados_transportadora")}
reenvio_humano = {r["conversation_id"] for r in dados.consulta(
    "select distinct conversation_id from trocas_reenvios where motivo_registrado = 'atraso_ou_extravio'")}

tipos, m_chamado, m_opc = Counter(), Counter(), Counter()
exemplos_perdidos, exemplos_extras = [], []
for c in convs:
    pedido = {k: v for k, v in c.items() if k not in ("tag_agente", "data_abertura")}
    pedido["data_prometida"] = c["data_prometida"]
    sit = rastreio.situacao(pedido, c["data_abertura"])
    plano = rastreio.decidir(sit, pedido)
    tipos[plano.tipo] += 1
    gc = "chamado" if plano.abrir_chamado or sit.chamado else "sem chamado"
    hm = "chamado" if c["conversation_id"] in chamado_humano else "sem chamado"
    m_chamado[(gc, hm)] += 1
    if hm == "chamado" and gc == "sem chamado" and len(exemplos_perdidos) < 3:
        exemplos_perdidos.append((c["conversation_id"], plano.tipo, sit.dias_parado, sit.atraso_du, sit.estado))
    if hm == "sem chamado" and gc == "chamado" and len(exemplos_extras) < 3:
        exemplos_extras.append((c["conversation_id"], plano.tipo, sit.dias_parado, sit.atraso_du, sit.estado))
    m_opc[("oferece" if plano.oferecer_opcoes else "nao", "reenvio humano" if c["conversation_id"] in reenvio_humano else "sem reenvio")] += 1

n = len(convs)
print(f"Conversas Rastreio/Atraso (etiqueta humana) com pedido: {n}\n")
print("## O que A Maya decidiria")
for t, q in tipos.most_common():
    print(f"  {t:22s} {q:4d} ({100 * q / n:4.1f}%)")

print("\n## Abrir chamado na transportadora: Maya x humano")
tp, fp, fn, tn = m_chamado[("chamado", "chamado")], m_chamado[("chamado", "sem chamado")], m_chamado[("sem chamado", "chamado")], m_chamado[("sem chamado", "sem chamado")]
print(f"                        humano abriu | humano nao abriu")
print(f"  Maya abriria      {tp:10d}  | {fp:10d}")
print(f"  Maya nao abriria  {fn:10d}  | {tn:10d}")
print(f"  precisao {100 * tp / max(1, tp + fp):.0f}% | cobertura {100 * tp / max(1, tp + fn):.0f}% | concordancia {100 * (tp + tn) / n:.0f}%")
print(f"  base: o humano abriu chamado em {tp + fn} de {n} conversas ({100 * (tp + fn) / n:.0f}%)")

print("\n## Oferecer reenvio/reembolso (atraso > 7 du ou extravio): Maya x humano que reenviou por atraso/extravio")
print(f"  Maya oferece: {m_opc[('oferece', 'reenvio humano')] + m_opc[('oferece', 'sem reenvio')]} conversas | "
      f"destas, o humano reenviou em {m_opc[('oferece', 'reenvio humano')]}")
print(f"  Maya nao oferece: {m_opc[('nao', 'reenvio humano')] + m_opc[('nao', 'sem reenvio')]} | "
      f"destas, o humano reenviou em {m_opc[('nao', 'reenvio humano')]}")

print("\n## Exemplos em que o humano abriu chamado e A Maya nao (conversa, plano, dias parado, atraso du, estado)")
for e in exemplos_perdidos:
    print("  ", e)
print("## Exemplos em que A Maya abriria chamado e o humano nao")
for e in exemplos_extras:
    print("  ", e)
