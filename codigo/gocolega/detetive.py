"""Detetive de Procedencia: sinais de reclamacao suspeita + decisao por valor esperado.

ATENCAO (honestidade): os pesos abaixo sao HEURISTICOS, escolhidos a mao a partir dos
sinais descritos em parametros.md. Nao ha rotulos de verdade nos dados, entao nao ha
calibracao estatistica. O score ordena risco; a decisao final e sempre de uma pessoa.
"""
import math
import re
from dataclasses import dataclass, field

from . import dados

CUSTO_REENVIO_INDEVIDO = 0.45  # fracao do valor do pedido (parametros.md)
CUSTO_SINALIZAR_VERDADEIRA = 6.0  # R$ tempo do supervisor (parametros.md)

CATEGORIAS = {
    "case": ["case", "capinha"],
    "copo": ["copo"],
    "garrafa": ["garrafa"],
    "necessaire": ["necessaire"],
    "bolsa": ["bolsa", "tote"],
    "mala": ["mala"],
}
PESOS = {
    "foto_reutilizada_anterior": 3.0,
    "foto_reutilizada_posterior": 1.5,
    "foto_antes_da_entrega": 3.0,
    "produto_nao_confere": 2.0,
    "historico_de_trocas": 0.8,
    "software_de_edicao": 0.5,
    "etiqueta_do_pedido_visivel": -1.5,  # contraprova: a foto mostra o numero do pedido
}
INTERCEPTO = -3.5


@dataclass
class Sinal:
    nome: str
    detalhe: str


@dataclass
class Dossie:
    conversation_id: str
    order_id: str
    valor: float
    sinais: list[Sinal] = field(default_factory=list)
    p_falsa: float = 0.0
    custo_agir_se_falsa: float = 0.0
    custo_sinalizar_se_verdadeira: float = CUSTO_SINALIZAR_VERDADEIRA
    sinalizar: bool = False

    def resumo(self) -> str:
        if not self.sinais:
            sinais = "nenhum sinal de alerta"
        else:
            sinais = "; ".join(f"{s.nome} ({s.detalhe})" for s in self.sinais)
        return (
            f"Risco {self.p_falsa:.0%} | sinais: {sinais} | "
            f"custo esperado de reenviar se falsa R$ {self.p_falsa * self.custo_agir_se_falsa:.2f} "
            f"vs custo de sinalizar se verdadeira R$ {(1 - self.p_falsa) * self.custo_sinalizar_se_verdadeira:.2f}"
        )


def _categoria_do_texto(texto: str) -> set[str]:
    t = (texto or "").lower()
    return {c for c, palavras in CATEGORIAS.items() if any(p in t for p in palavras)}


def _item_pedido(order_id: str) -> tuple[str, str]:
    itens = dados.consulta(
        "select descricao, personalizacao, texto_personalizacao from itens_pedido "
        "where order_id = ? and tipo_item = 'venda'", [order_id])
    desc = "; ".join(i["descricao"] for i in itens if i["descricao"])
    pers = "; ".join(f"{i['personalizacao']}: {i['texto_personalizacao']}" for i in itens if i["personalizacao"])
    return desc, pers


def analisar(conversation_id: str, order_id: str, juiz=None) -> Dossie:
    """juiz: funcao opcional (descricao_visual, item, personalizacao) -> {'confere': bool, 'motivo': str} | None.
    E um agente com modelo; so ENTRA quando as palavras-chave nao acharam divergencia, e so ADICIONA sinal."""
    pedido = dados.uma("select * from pedidos where order_id = ?", [order_id]) or {}
    cliente = dados.uma("select * from clientes where customer_id = ?", [pedido.get("customer_id")]) or {}
    anexos = dados.consulta("select * from anexos_conversas where conversation_id = ?", [conversation_id])
    valor = float(pedido.get("valor") or 0)
    d = Dossie(conversation_id, order_id, valor)
    z = INTERCEPTO

    for a in anexos:
        h = a["hash_perceptual"]
        outros = dados.consulta(
            "select order_id, customer_id, enviado_em from anexos_conversas "
            "where hash_perceptual = ? and order_id <> ?", [h, order_id])
        if outros:
            anteriores = [o for o in outros if o["enviado_em"] < a["enviado_em"]]
            clientes_dist = {o["customer_id"] for o in outros}
            nome = "foto_reutilizada_anterior" if anteriores else "foto_reutilizada_posterior"
            d.sinais.append(Sinal(nome, f"mesma imagem em {len(outros)} outro(s) pedido(s) de {len(clientes_dist)} cliente(s)"))
            z += PESOS[nome]

        cap, ent = a.get("exif_data_captura"), pedido.get("data_entrega")
        if cap is not None and ent is not None and str(cap) != "NaT" and cap.date() < ent:
            dias = (ent - cap.date()).days
            d.sinais.append(Sinal("foto_antes_da_entrega", f"capturada {dias} dia(s) antes da entrega"))
            z += PESOS["foto_antes_da_entrega"]

        if a.get("exif_software"):
            d.sinais.append(Sinal("software_de_edicao", str(a["exif_software"])))
            z += PESOS["software_de_edicao"]

        descr = a.get("descricao_visual") or ""
        cat_foto = _categoria_do_texto(descr)
        cat_pedido = _categoria_do_texto(pedido.get("descricao_produto", ""))
        if cat_foto and cat_pedido and not (cat_foto & cat_pedido):
            d.sinais.append(Sinal("produto_nao_confere", f"foto mostra {sorted(cat_foto)}, pedido e {sorted(cat_pedido)}"))
            z += PESOS["produto_nao_confere"]
        elif juiz is not None and descr:
            item, pers = _item_pedido(order_id)
            veredito = juiz(descr, item or pedido.get("descricao_produto", ""), pers)
            if veredito and veredito["confere"] is False:
                d.sinais.append(Sinal("produto_nao_confere_juiz", veredito["motivo"] or "o juiz nao viu coerencia"))
                z += PESOS["produto_nao_confere"]

        if re.search(rf"{re.escape(order_id)}", descr):
            d.sinais.append(Sinal("etiqueta_do_pedido_visivel", "a foto mostra o numero do pedido (contraprova)"))
            z += PESOS["etiqueta_do_pedido_visivel"]

    if (cliente.get("n_trocas_12m") or 0) >= 2:
        d.sinais.append(Sinal("historico_de_trocas", f"{cliente['n_trocas_12m']} trocas/reenvios em 12 meses"))
        z += PESOS["historico_de_trocas"]

    d.p_falsa = 1 / (1 + math.exp(-z))
    d.custo_agir_se_falsa = CUSTO_REENVIO_INDEVIDO * valor
    d.sinalizar = d.p_falsa * d.custo_agir_se_falsa > (1 - d.p_falsa) * d.custo_sinalizar_se_verdadeira
    return d
