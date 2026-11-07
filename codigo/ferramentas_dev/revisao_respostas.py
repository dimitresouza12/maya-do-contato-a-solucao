"""Folha de revisao de respostas: 20 conversas reais, sorteadas por semente e distribuidas pelos desfechos, com a mensagem do
cliente, a resposta do agente, verificacoes AUTOMATICAS objetivas e uma grade para uma PESSOA dar nota.

As verificacoes automaticas pegam so o que e objetivo (cumprimento nao retribuido, PII, acusacao, mensagem de espera sem prazo,
texto longo demais, resposta vazia). Quem avalia tom e correcao e a pessoa: a coluna de notas vem em branco de proposito.

Uso (da raiz, com base completa e token):  python codigo/ferramentas_dev/revisao_respostas.py [N=20] [semente=7]
Saida: docs/revisao_respostas.md
"""
import os
import random
import re
import sys

RAIZ = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(RAIZ, "codigo"))
from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(RAIZ, ".env"))
sys.stdout.reconfigure(encoding="utf-8")

from gocolega import agentes, dados  # noqa: E402
from gocolega.ferramentas import mascarar_pii  # noqa: E402
from gocolega.orquestrador import tratar  # noqa: E402

N = int(sys.argv[1]) if len(sys.argv) > 1 else 20
SEMENTE = int(sys.argv[2]) if len(sys.argv) > 2 else 7
SAUDA = re.compile(r"\b(bom dia|boa tarde|boa noite|ol[aá]|oi+)\b", re.I)
RETRIBUI = re.compile(r"\b(bom dia|boa tarde|boa noite|ol[aá]|oi+)\b", re.I)
PRAZO = re.compile(r"\d+\s*(minutos|horas)|24 ?h|48 ?h", re.I)
LONGO = 600


def _checagens(cliente: str, resposta: str, desfecho: str) -> list[str]:
    f = []
    if not resposta or resposta.startswith("("):
        return ["sem mensagem ao cliente"] if desfecho != "escalado" else ["escalado sem mensagem de espera"]
    if SAUDA.search(cliente) and not RETRIBUI.search(resposta[:120]):
        f.append("cliente cumprimentou e o agente nao retribuiu")
    if mascarar_pii(resposta) != resposta:
        f.append("PII na resposta")
    if agentes.ACUSACAO.search(resposta):
        f.append("palavra de acusacao")
    if len(resposta) > LONGO:
        f.append(f"longa ({len(resposta)} caracteres)")
    if desfecho == "escalado" and not PRAZO.search(resposta):
        f.append("encaminhou para pessoa sem dizer o prazo")
    return f


def main():
    ids = [r["conversation_id"] for r in dados.consulta("select conversation_id from historico_conversas order by conversation_id")]
    random.Random(SEMENTE).shuffle(ids)
    casos, por_desfecho = [], {}
    for cid in ids:
        if len(casos) >= N * 2:  # amostra o dobro e depois equilibra por desfecho
            break
        try:
            r, ferr = tratar(cid)
        except Exception as e:
            casos.append((cid, "", "erro", f"{type(e).__name__}: {e}", [], r"erro"))
            continue
        msgs = dados.consulta("select texto from historico_mensagens where conversation_id=? and autor='cliente' order by timestamp", [cid])
        cliente = mascarar_pii(" / ".join(m["texto"] for m in msgs))[:420]
        envios = [e for e in ferr.log if e["ferramenta"] == "responder_cliente"]
        resposta = " || ".join(e["texto"] for e in envios) if envios else "(nenhuma mensagem ao cliente)"
        acoes = [e["ferramenta"] for e in ferr.log if e["ferramenta"] not in ("classificar_conversa", "responder_cliente")]
        casos.append((cid, cliente, r.desfecho, resposta, acoes, r.categoria))
        por_desfecho.setdefault(r.desfecho, []).append(len(casos) - 1)
        print(f"{cid} {r.desfecho}")
    # equilibra: round-robin pelos desfechos, para a revisao ver todo tipo de resposta, nao so as autonomas
    escolhidos, filas = [], {k: list(v) for k, v in por_desfecho.items()}
    while len(escolhidos) < N and any(filas.values()):
        for k in list(filas):
            if filas[k] and len(escolhidos) < N:
                escolhidos.append(filas[k].pop(0))
    out = ["# Revisão de respostas (folha para avaliação humana)", "",
           f"{len(escolhidos)} conversas reais sorteadas (semente {SEMENTE}) e distribuídas entre os desfechos. As **verificações automáticas** "
           "são só as objetivas; **tom e correção são julgados por uma pessoa** (colunas em branco).", "",
           "Nota de 1 a 5: **Tom** (acolhedor, natural, adequado ao canal) e **Correção** (o que diz bate com a política e com os fatos do pedido). "
           "Marque **Mandaria?** com sim, ajustaria ou não.", ""]
    flags_total = 0
    for i, ix in enumerate(escolhidos, 1):
        cid, cliente, desfecho, resposta, acoes, cat = casos[ix]
        f = _checagens(cliente, resposta, desfecho)
        flags_total += bool(f)
        out += [f"## {i}. {cid} · {cat} · {desfecho}", "", f"> **Cliente:** {cliente}", "", f"> **GoColega:** {resposta}", "",
                f"Ações: {', '.join(acoes) or 'nenhuma'}  ", f"Verificações automáticas: {'; '.join(f) if f else 'nenhum problema objetivo'}", "",
                "| Tom (1-5) | Correção (1-5) | Mandaria? | Observação |", "|---|---|---|---|", "|   |   |   |   |", ""]
    out.insert(2, f"Verificações automáticas: **{flags_total} de {len(escolhidos)}** respostas com algum alerta objetivo.\n")
    destino = os.path.join(RAIZ, "docs", "revisao_respostas.md")
    open(destino, "w", encoding="utf-8").write("\n".join(out))
    print("gravado", destino, "| alertas:", flags_total, "de", len(escolhidos))


if __name__ == "__main__":
    main()
