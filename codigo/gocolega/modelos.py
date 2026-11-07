"""Quem usa qual modelo (AI Proxy do evento). Tudo configuravel por variavel de ambiente.

  principal  -> Orquestrador: decide a rota em casos ambiguos e escreve o resumo para o supervisor
  sub        -> Sub-agentes: juiz da foto (a foto bate com o pedido?) e Redator (resposta ao cliente)
  triagem    -> Jev (decisao tipada, ~0,5 s)

Medido em 07/11: gpt-5.6-terra 2,6 s, gpt-5.6-luna 2,8 s, gpt-6-luna 6,2 s. 'gpt-6-terra' NAO existe.
"""
import os

PRINCIPAL = os.environ.get("GOCOLEGA_MODELO_PRINCIPAL", "gpt-5.6-terra")
SUB = os.environ.get("GOCOLEGA_MODELO_SUB", "gpt-5.6-luna")
TRIAGEM = "jev-latest"


def validar(modelo: str) -> str:
    """deepseek-* e proibido no evento, mesmo que o proxy liste ou alguem configure."""
    if modelo.lower().startswith("deepseek"):
        raise ValueError(f"Modelo '{modelo}' e proibido no evento")
    return modelo
