"""Consulta a base de conhecimento da Maya (RAG): produtos, politicas e casos ja atendidos.

Uso (da raiz):
    python codigo/consulta.py "Qual a validade do serum depois de aberto?"
    python codigo/consulta.py --casos "meu pedido nao chegou e o rastreio nao anda"
    python codigo/consulta.py --sem-llm "O creme e vegano?"
"""
import os
import sys

from dotenv import load_dotenv

load_dotenv()
sys.stdout.reconfigure(encoding="utf-8")

from gocolega import conhecimento, dados, duvida, llm  # noqa: E402


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = {a for a in sys.argv[1:] if a.startswith("--")}
    if not args:
        print(__doc__)
        return
    pergunta = " ".join(args)
    kb = conhecimento.base()
    print(f"Dados: {'amostra do repositorio' if dados.usando_amostra() else 'base completa'} | base de conhecimento: {kb.tamanho()}")
    print("Recuperacao: BM25 (lexical, sem embeddings)\n")

    if "--casos" in flags:
        p = kb.precedentes(pergunta)
        print(f"Casos parecidos ja atendidos: {p['n']} | etiquetas: {p['tags']} | o que o humano fez: {p['acoes_humanas']}")
        for r in kb.buscar(pergunta, "caso", k=3):
            print(f"  [{r.passagem.id}] cobertura {r.cobertura:.0%} | {r.passagem.titulo}")
        return

    resp, motivo = duvida.responder(pergunta, usar_llm=False if "--sem-llm" in flags else None)
    print("Passagens recuperadas:")
    for fonte in ("produto", "politica"):
        for r in kb.buscar(pergunta, fonte, k=2):
            print(f"  [{r.passagem.id}] score {r.score:.1f} | cobertura {r.cobertura:.0%} | {r.passagem.titulo}")
    print()
    if resp is None:
        print(f"SEM RESPOSTA: {motivo}. A Maya encaminharia a uma pessoa.")
    else:
        print(f"RESPOSTA ({resp.origem}): {resp.texto}")
        for a in resp.avisos:
            print(f"  aviso: {a}")
    if llm._uso_chat:
        print("\n💲 " + llm.linha_custo())


if __name__ == "__main__":
    main()
