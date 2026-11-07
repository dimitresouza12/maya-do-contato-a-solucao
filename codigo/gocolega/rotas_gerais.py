"""Rotas do dia a dia que antes iam todas para uma pessoa: elogio, cancelamento, endereco, financeiro,
cupom e promocao, troca. Cada uma segue a regra de politicas.csv (secao 'categorias') e so chama um humano
quando a politica exige (valor acima do limite) ou quando falta informacao que so uma pessoa tem.

Principios (os mesmos do resto da Maya): o codigo decide, o modelo so redige; nunca age sem pedido claro do
cliente (cancelar, reembolsar e trocar exigem a intencao explicita no texto); sem o dado que falta, PERGUNTA ao
cliente em vez de chamar uma pessoa; texto fixo de fallback com os fatos exatos.
"""
import re
import zlib
from datetime import date, datetime

from . import dados

PRAZO_ARREPENDIMENTO_DIAS = 7   # politicas: arrependimento_cancelamento.prazo_dias_corridos_do_recebimento
PRAZO_TROCA_DIAS = 30           # troca_fragrancia.prazo_dias_corridos_do_recebimento
LIMITE_REEMBOLSO = 100.0        # limites_por_papel.atendente.reembolso_max_rs
LIMITE_TROCA = 200.0            # limites_por_papel.atendente.troca_max_rs

INTENCAO_CANCELAR = re.compile(r"cancel|desist|arrepend|devolv|devolu|n[aã]o quero mais|estorn|reembols|dinheiro de volta", re.I)
DUPLICADA = re.compile(r"(duas|2|dois)\s+(vezes|cobran[cç]as?|d[eé]bitos?|pix)|em dobro|duplicad|dobro|cobraram\s+(duas|2)", re.I)
COBRANCA = re.compile(r"cobra[rdm]|d[eé]bit|fatura|extrato|cart[aã]o", re.I)
PENDENTE = re.compile(r"pendente|n[aã]o (foi )?(confirmad|aprovad|compensad)|dinheiro (j[aá] )?saiu|pix .*n[aã]o", re.I)
USO_DECLARADO = re.compile(r"(usei|usado|usada).{0,25}(\d+|uma|duas|tr[eê]s|s[oó]|pouco)", re.I)
BLACK_FRIDAY = re.compile(r"black\s*friday", re.I)
FRETE = re.compile(r"frete\s*gr[aá]tis", re.I)
PRIMEIRA = re.compile(r"primeira compra|cupom", re.I)
STOP_PRODUTO = {"troca", "trocar", "outra", "outro", "fragr", "perfume", "quero", "pelo", "pela", "para", "esse", "essa", "pedido",
                "ainda", "pode", "posso", "seria", "gostei", "cheiro", "usei", "vezes", "onde", "muito", "mesmo", "voltando",
                "obrigado", "obrigada", "ok", "certo", "boa", "tarde", "noite", "bom", "dia", "prezados", "ola", "oi"}


CATEGORIAS_COM_PEDIDO = {"Cancelamento", "Endereco", "Financeiro", "Troca", "Avaria", "Produto faltando",
                         "Reclamacao produto", "Rastreio", "Atraso"}


# ---------- campanha vigente (brinde): politicas.csv, secao 'campanha_vigente' ----------
BRINDE = re.compile(r"brinde|necessaire|mimo", re.I)
CAMPANHA = {"nome": "Mimo de Outubro GoBeauté", "valor_minimo": 129.0, "inicio": date(2026, 10, 13), "fim": date(2026, 11, 4)}


def _campanha() -> dict:
    """Le a campanha da base (politicas.csv); se faltar, usa o valor conhecido acima."""
    c = dict(CAMPANHA)
    try:
        linhas = {x["regra"]: x["valor"] for x in dados.consulta("select regra, valor from politicas where secao='campanha_vigente'")}
        c["nome"] = linhas.get("nome", c["nome"])
        c["valor_minimo"] = float(linhas.get("valor_minimo_rs", c["valor_minimo"]))
        c["inicio"] = date.fromisoformat(str(linhas.get("inicio", c["inicio"]))[:10])
        c["fim"] = date.fromisoformat(str(linhas.get("fim", c["fim"]))[:10])
    except Exception:  # base sem a secao: valores conhecidos
        pass
    return c


def elegivel_brinde(pedido: dict) -> bool:
    """O pedido tinha direito ao brinde? So GoBeauté (nao Gocase), compra de produtos >= R$ 129 e pedido dentro da campanha."""
    c = _campanha()
    if str(pedido.get("marca", "")).strip().lower() == "gocase":
        return False
    dia = _dia(pedido.get("data_pedido"))
    if isinstance(dia, str):
        dia = date.fromisoformat(dia[:10])
    if dia is None or not (c["inicio"] <= dia <= c["fim"]):
        return False
    return float(pedido.get("valor_produtos") or 0) >= c["valor_minimo"]


def motivo_sem_brinde(pedido: dict) -> str:
    """Frase com o motivo EXATO (regra da campanha) pelo qual o pedido nao tinha direito ao brinde."""
    c = _campanha()
    if str(pedido.get("marca", "")).strip().lower() == "gocase":
        return f"a campanha {c['nome']} vale apenas para compras GoBeauté"
    dia = _dia(pedido.get("data_pedido"))
    if dia is None or not (c["inicio"] <= dia <= c["fim"]):
        return f"o pedido foi feito fora do periodo da campanha ({c['inicio']:%d/%m} a {c['fim']:%d/%m})"
    return f"a campanha exige compra de produtos a partir de {_brl(c['valor_minimo'])} e este pedido ficou abaixo disso"


def _brl(v: float) -> str:
    return "R$ " + f"{float(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _dia(x) -> date | None:
    if x is None:
        return None
    return x.date() if isinstance(x, datetime) else x


def _separado(pedido: dict, agora: datetime) -> bool:
    sep = pedido.get("data_separacao")
    return sep is not None and sep <= agora


def _dias_desde_entrega(pedido: dict, agora: datetime) -> int | None:
    ent = _dia(pedido.get("data_entrega"))
    return None if ent is None or ent > agora.date() else (agora.date() - ent).days


def _fim(r, desfecho: str, passo: str):
    r.desfecho = desfecho
    r.p(passo)


# ---------- pedir o que falta (em vez de chamar uma pessoa) ----------
def pedir_pedido(r, ferr, cid, escrever, categoria: str):
    fatos = (f"O cliente fez um contato sobre '{categoria}', mas a conversa nao tem pedido associado. "
             "Precisamos do numero do pedido, que comeca com GCH ou GBH.")
    fallback = "Para te ajudar, preciso do numero do pedido (ele comeca com GCH ou GBH). Pode me enviar?"
    ferr.responder_cliente(cid, escrever(r, "pedir o numero do pedido", fatos, fallback))
    _fim(r, "aguardando_cliente", "Sem pedido associado: pedi o numero do pedido ao cliente (sem chamar uma pessoa).")
    return r, ferr


def pedir_esclarecimento(r, ferr, cid, escrever, assunto: str, o_que: str):
    ferr.responder_cliente(cid, escrever(r, f"perguntar {o_que}", f"Assunto: {assunto}. Falta saber {o_que}.",
                                         f"Para eu seguir, pode me dizer {o_que}?"))
    _fim(r, "aguardando_cliente", f"{assunto}: faltou {o_que}; perguntei ao cliente.")
    return r, ferr


# ---------- elogio ----------
def elogio(r, ferr, cid, escrever):
    ferr.agradecer(cid)
    # Varia o texto fixo (escolha deterministica pelo id da conversa) para o elogio nao receber sempre a mesma resposta.
    variantes = ["Que bom saber disso! Agradecemos o carinho e ficamos por aqui para o que precisar.",
                 "Muito obrigado pelas palavras, elas fazem o nosso dia! Qualquer coisa, e so chamar.",
                 "Ficamos felizes demais com o seu retorno! Obrigado por escolher a gente.",
                 "Que mensagem boa de receber, obrigado! Conte com a gente sempre que precisar."]
    ferr.responder_cliente(cid, escrever(r, "agradecer o elogio", "O cliente elogiou o produto ou o atendimento.",
                                         variantes[zlib.crc32(cid.encode()) % len(variantes)]))
    _fim(r, "autonomo", "Elogio: agradeci ao cliente.")
    return r, ferr


# ---------- cancelamento / arrependimento ----------
def _reembolso_ou_aprovacao(r, ferr, cid, pedido, escrever, motivo: str, valor: float, situacao: str):
    oid = pedido["order_id"]
    if valor <= LIMITE_REEMBOLSO:
        ferr.reembolsar(oid, valor, motivo)
        fatos = f"{situacao} Reembolso de {_brl(valor)} registrado para o pedido {oid}."
        ferr.responder_cliente(cid, escrever(r, "informar o reembolso", fatos,
                                             f"Pronto, vamos reembolsar {_brl(valor)} do pedido {oid}. Voce recebera a confirmacao em seguida."))
        _fim(r, "autonomo", f"Reembolso de {_brl(valor)} executado (dentro do limite de {_brl(LIMITE_REEMBOLSO)}).")
    else:
        aprov = ferr.solicitar_aprovacao("reembolso", oid, valor, f"{motivo}: {situacao}")
        ferr.responder_cliente(cid, escrever(r, "informar que o reembolso foi encaminhado para aprovacao",
                                             f"{situacao} O valor de {_brl(valor)} passa do limite e precisa de aprovacao.",
                                             "Registrei o seu pedido de reembolso e ele foi encaminhado para aprovacao. Voltamos em breve."))
        _fim(r, "aguardando_supervisor", f"Reembolso de {_brl(valor)} acima do limite ({_brl(LIMITE_REEMBOLSO)}): pedi aprovacao ({aprov}).")
    return r, ferr


def cancelamento(r, ferr, cid, pedido, texto, agora, escrever):
    oid, valor = pedido["order_id"], float(pedido.get("valor") or 0)
    if not INTENCAO_CANCELAR.search(texto):
        return pedir_esclarecimento(r, ferr, cid, escrever, "Cancelamento", "se voce quer cancelar o pedido ou receber o reembolso")
    if not _separado(pedido, agora):
        ferr.cancelar_pedido(oid, "arrependimento")
        ferr.responder_cliente(cid, escrever(r, "informar o cancelamento", f"O pedido {oid} ainda nao tinha sido separado e foi cancelado, com estorno integral.",
                                             f"Cancelamos o pedido {oid}. O estorno sera integral, conforme o seu meio de pagamento."))
        _fim(r, "autonomo", "Pedido ainda nao separado: cancelado com estorno integral (sem limite de valor).")
        return r, ferr
    dias = _dias_desde_entrega(pedido, agora)
    if dias is None:
        ferr.negar_por_politica(cid, "arrependimento_cancelamento")
        ferr.responder_cliente(cid, escrever(r, "explicar que o pedido ja foi separado e a regra de arrependimento",
                                             f"O pedido {oid} ja foi separado e esta a caminho, entao nao da para cancelar. Depois de receber, o cliente tem ate {PRAZO_ARREPENDIMENTO_DIAS} dias para pedir o reembolso integral.",
                                             f"O pedido {oid} ja foi separado e esta a caminho, por isso nao da mais para cancelar. Quando voce receber, pode pedir o reembolso integral em ate {PRAZO_ARREPENDIMENTO_DIAS} dias."))
        _fim(r, "autonomo", "Pedido ja separado e a caminho: expliquei a regra (reembolso em ate 7 dias do recebimento).")
        return r, ferr
    if dias <= PRAZO_ARREPENDIMENTO_DIAS:
        return _reembolso_ou_aprovacao(r, ferr, cid, pedido, escrever, "arrependimento", valor,
                                       f"Pedido {oid} recebido ha {dias} dia(s), dentro dos {PRAZO_ARREPENDIMENTO_DIAS} dias de arrependimento.")
    ferr.negar_por_politica(cid, "arrependimento_cancelamento")
    ferr.responder_cliente(cid, escrever(r, "explicar que o prazo de arrependimento passou",
                                         f"O pedido {oid} foi recebido ha {dias} dias e o prazo de arrependimento e de {PRAZO_ARREPENDIMENTO_DIAS} dias.",
                                         f"O pedido {oid} foi recebido ha {dias} dias e o prazo de arrependimento e de {PRAZO_ARREPENDIMENTO_DIAS} dias, entao nao consigo seguir com o reembolso."))
    _fim(r, "fora_da_politica", f"Recebido ha {dias} dias (prazo de {PRAZO_ARREPENDIMENTO_DIAS}): negado pela politica, com explicacao.")
    return r, ferr


# ---------- endereco ----------
def endereco(r, ferr, cid, pedido, agora, escrever):
    oid = pedido["order_id"]
    if not _separado(pedido, agora):
        return pedir_esclarecimento(r, ferr, cid, escrever, "Alteracao de endereco",
                                    "o endereco completo correto (rua, numero, complemento, bairro, cidade e CEP)")
    ferr.negar_por_politica(cid, "alteracao_endereco")
    ferr.responder_cliente(cid, escrever(r, "explicar que o endereco so muda antes da separacao",
                                         f"O pedido {oid} ja foi separado. A alteracao de endereco so e possivel antes da separacao.",
                                         f"O pedido {oid} ja foi separado, e o endereco so pode ser alterado antes da separacao. Sinto muito por isso."))
    _fim(r, "fora_da_politica", "Pedido ja separado: endereco so muda antes da separacao (politica).")
    return r, ferr


# ---------- financeiro ----------
def financeiro(r, ferr, cid, pedido, texto, agora, escrever):
    oid = pedido["order_id"]
    pags = ferr.verificar_pagamento(oid, ate=agora)
    confirmados = [p for p in pags if p["status"] in ("capturada", "paga")]
    # Reclamacao de COBRANCA ("cobraram no cartao tambem", "debitou", "fatura") tambem confere duplicidade, em vez de
    # responder so que o pagamento esta confirmado (que nao responde ao cliente; achado na galeria de respostas).
    if DUPLICADA.search(texto) or (COBRANCA.search(texto) and not PENDENTE.search(texto)):
        if len(confirmados) >= 2:
            valores = sorted(float(p["valor"]) for p in confirmados)
            extra = round(sum(valores) - valores[0], 2)
            prazo = "5 dias uteis" if str(confirmados[0].get("metodo", "")).startswith("pix") else "2 faturas"
            return _reembolso_ou_aprovacao(r, ferr, cid, pedido, escrever, "cobranca_duplicada", extra,
                                           f"Conferi o gateway: o pedido {oid} tem {len(confirmados)} cobrancas confirmadas e a duplicidade e de {_brl(extra)}. "
                                           f"O estorno sai em ate {prazo}.")
        total = _brl(sum(float(p["valor"]) for p in confirmados)) if confirmados else "nenhuma"
        fatos = (f"Conferi o gateway para o pedido {oid}: consta {'uma unica cobranca confirmada de ' + total if confirmados else 'nenhuma cobranca confirmada'}. "
                 "Nao encontrei duplicidade. Se o extrato mostra outra cobranca, pedir o comprovante.")
        ferr.responder_cliente(cid, escrever(r, "informar que nao ha duplicidade e pedir o comprovante", fatos,
                                             f"Conferi aqui e, para o pedido {oid}, consta apenas uma cobranca confirmada ({total}). "
                                             "Se no seu extrato aparece outra, me envie o comprovante para eu verificar."))
        _fim(r, "aguardando_cliente", "Sem duplicidade no gateway: informei e pedi o comprovante.")
        return r, ferr
    if PENDENTE.search(texto) or not confirmados:
        status = pags[-1]["status"] if pags else "sem registro"
        fatos = (f"Pagamento do pedido {oid}: situacao no gateway '{status}'. Regra: pix compensa em ate 30 minutos; boleto em ate 2 dias uteis.")
        ferr.responder_cliente(cid, escrever(r, "informar a situacao do pagamento", fatos,
                                             f"Conferi o pagamento do pedido {oid}: situacao '{status}'. O pix compensa em ate 30 minutos e o boleto em ate 2 dias uteis."))
        _fim(r, "autonomo", f"Pagamento consultado no gateway ({status}): situacao e prazo informados.")
        return r, ferr
    fatos = f"Pagamento do pedido {oid} confirmado no gateway ({_brl(sum(float(p['valor']) for p in confirmados))})."
    ferr.responder_cliente(cid, escrever(r, "informar que o pagamento esta confirmado", fatos,
                                         f"O pagamento do pedido {oid} esta confirmado. Se algo no seu extrato parecer diferente, me conte o que viu."))
    _fim(r, "autonomo", "Pagamento confirmado no gateway: informado ao cliente.")
    return r, ferr


# ---------- prazo de entrega (pergunta geral, sem pedido) ----------
PRAZO = re.compile(r"quanto tempo (demora|leva|para chegar|pra chegar|de entrega)|prazo de entrega|demora (pra|para) chegar|"
                   r"em quantos dias (chega|entrega)|tempo de entrega", re.I)
ESTADOS = {"acre": "AC", "alagoas": "AL", "amapa": "AP", "amazonas": "AM", "bahia": "BA", "ceara": "CE", "distrito federal": "DF",
           "espirito santo": "ES", "goias": "GO", "maranhao": "MA", "mato grosso do sul": "MS", "mato grosso": "MT",
           "minas gerais": "MG", "paraiba": "PB", "parana": "PR", "pernambuco": "PE", "piaui": "PI",
           "rio de janeiro": "RJ", "rio grande do norte": "RN", "rio grande do sul": "RS", "rondonia": "RO", "roraima": "RR",
           "santa catarina": "SC", "sao paulo": "SP", "sergipe": "SE", "tocantins": "TO"}
REGIAO = {"N": "Norte", "NE": "Nordeste", "CO": "Centro-Oeste", "SE": "Sudeste", "S": "Sul"}


def _uf(texto: str) -> str | None:
    import unicodedata
    sem = "".join(c for c in unicodedata.normalize("NFKD", texto.lower()) if not unicodedata.combining(c))
    for nome in sorted(ESTADOS, key=len, reverse=True):
        if re.search(rf"\b{nome}\b", sem):
            return ESTADOS[nome]
    m = re.search(r"\b(?:em|para|pra|no|na)\s+([A-Z]{2})\b", texto)
    return m.group(1) if m and m.group(1) in ESTADOS.values() else None


def prazo_entrega(r, ferr, cid, texto, escrever):
    """Prazo estimado por estado, direto da politica (preparo + SLA de cada transportadora, em dias uteis)."""
    uf = _uf(texto)
    if not uf:
        return pedir_esclarecimento(r, ferr, cid, escrever, "Prazo de entrega", "para qual estado voce quer saber o prazo")
    reg = (dados.uma("select valor from politicas where secao='prazos_entrega' and regra = ?", [f"regiao_por_uf.{uf}"]) or {}).get("valor")
    sla = [int(x["valor"]) for x in dados.consulta(
        "select valor from politicas where secao='prazos_entrega' and regra like ?", [f"sla_transportadora_dias_uteis.%.{reg}"])] if reg else []
    if not sla:
        return pedir_esclarecimento(r, ferr, cid, escrever, "Prazo de entrega", "para qual estado voce quer saber o prazo")
    lo, hi = min(sla), max(sla)
    faixa = f"{lo}" if lo == hi else f"{lo} a {hi}"
    fatos = (f"Para {uf} ({REGIAO.get(reg, reg)}), o prazo de transporte e de {faixa} dias uteis, conforme a transportadora. "
             "Soma-se 1 dia util de preparo (3 dias uteis para produtos personalizados da Gocase). O prazo exato aparece no pedido.")
    ferr.responder_cliente(cid, escrever(r, "informar o prazo de entrega por estado", fatos,
                                         f"Para {uf} ({REGIAO.get(reg, reg)}), o transporte leva {faixa} dias uteis, conforme a transportadora, "
                                         "mais 1 dia util de preparo (3 para produtos personalizados da Gocase)."))
    _fim(r, "autonomo", f"Prazo de entrega para {uf}: {faixa} dias uteis (politicas.csv), mais o preparo.")
    return r, ferr


# ---------- cupom e promocao ----------
def _vigencia(c: dict) -> str:
    return f"{_dia(c['inicio_vigencia']):%d/%m} a {_dia(c['fim_vigencia']):%d/%m/%Y}"


def _motivo_cupom(c: dict, pedido: dict | None, agora: datetime, uso: dict | None) -> str | None:
    """Por que o cupom nao vale (None se vale). Usa o motivo da propria plataforma quando ha registro."""
    if uso and uso.get("status") == "recusado":
        m = uso.get("motivo_recusa")
        return {"nao_acumula_com_outra_promocao": "ele nao acumula com outra promocao ja aplicada ao pedido",
                "fora_da_vigencia": f"ele estava fora da vigencia ({_vigencia(c)})",
                "exclusivo_primeira_compra": "ele e exclusivo para a primeira compra",
                "valor_minimo_nao_atingido": f"o pedido precisava ter no minimo {_brl(c['valor_minimo_pedido'])}"}.get(m, f"a plataforma recusou ({m})")
    hoje = agora.date()
    if c["status"] != "ativo" or not (_dia(c["inicio_vigencia"]) <= hoje <= _dia(c["fim_vigencia"])):
        return f"ele nao esta valido hoje (vigencia {_vigencia(c)})"
    if pedido and c["marcas_validas"] not in ("todas", pedido.get("marca")):
        return f"ele vale so para a marca {c['marcas_validas']}"
    if pedido and float(pedido.get("valor") or 0) < float(c["valor_minimo_pedido"] or 0):
        return f"o pedido precisava ter no minimo {_brl(c['valor_minimo_pedido'])}"
    return None


def promocao(r, ferr, cid, pedido, texto, agora, escrever):
    codigos = [c for c in dict.fromkeys(re.findall(r"\b[A-Z][A-Z0-9]{3,}\b", texto)) if not re.match(r"^(GCH|GBH)\d", c)]
    for cod in codigos:
        cup = ferr.validar_cupom(cod)
        if cup is None:
            continue
        uso = dados.uma("select status, motivo_recusa, valor_desconto from uso_cupons where order_id = ? and codigo = ? "
                        "order by data_hora desc limit 1", [pedido["order_id"], cod]) if pedido else None
        motivo = _motivo_cupom(cup, pedido, agora, uso)
        if motivo:
            fatos = f"O cupom {cod} nao foi aplicado porque {motivo}."
            fallback = f"O cupom {cod} nao foi aplicado porque {motivo}."
        elif uso and uso.get("status") == "aplicado":
            fatos = f"O cupom {cod} foi aplicado ao pedido, com desconto de {_brl(uso['valor_desconto'])}."
            fallback = fatos
        else:
            fatos = f"O cupom {cod} e valido (vigencia {_vigencia(cup)}). Pedir o aviso de erro que apareceu, se houver."
            fallback = f"O cupom {cod} esta valido ({_vigencia(cup)}). Se aparecer alguma mensagem de erro ao usar, me conte qual."
        ferr.responder_cliente(cid, escrever(r, "explicar a situacao do cupom", fatos, fallback))
        _fim(r, "autonomo", f"Cupom {cod} conferido na plataforma: {motivo or 'valido'}.")
        return r, ferr
    marca = (pedido or {}).get("marca")
    if FRETE.search(texto):
        cup = ferr.validar_cupom("FRETEGRATIS")
        if cup and not _motivo_cupom(cup, pedido, agora, None):
            fatos = (f"O frete gratis vale com o cupom FRETEGRATIS (vigencia {_vigencia(cup)}, sem valor minimo, ate {cup['limite_uso_por_cliente']} usos por cliente). "
                     "Pedir para conferir se o cupom foi digitado no carrinho.")
            ferr.responder_cliente(cid, escrever(r, "explicar como usar o frete gratis", fatos,
                                                 "O frete gratis vale com o cupom FRETEGRATIS. Confira se ele foi digitado no carrinho; se der erro, me conte a mensagem."))
            _fim(r, "autonomo", "Frete gratis: expliquei o cupom FRETEGRATIS, validado na plataforma.")
            return r, ferr
    if BLACK_FRIDAY.search(texto):
        fatos = "A campanha da Black Friday vai de 20 a 30/11, com o dia 27/11. A lista de produtos e descontos ainda nao foi informada ao atendimento."
        ferr.responder_cliente(cid, escrever(r, "informar as datas da Black Friday", fatos,
                                             "A campanha da Black Friday vai de 20 a 30/11, com o dia 27/11. Ainda nao tenho a lista de produtos e descontos."))
        _fim(r, "autonomo", "Black Friday: informei as datas da campanha (a lista de descontos nao existe na base).")
        return r, ferr
    if PRIMEIRA.search(texto):
        validos = [c for c in dados.consulta("select * from cupons where primeira_compra = 'sim'")
                   if not _motivo_cupom(c, pedido, agora, None) and c["marcas_validas"] in ("todas", marca or c["marcas_validas"])]
        if validos:
            lista = "; ".join(f"{c['codigo']} ({c['percentual_desconto']}% de desconto)" for c in validos)
            fatos = f"Cupons de primeira compra validos hoje: {lista}."
            ferr.responder_cliente(cid, escrever(r, "informar os cupons de primeira compra", fatos, f"Os cupons de primeira compra validos hoje sao: {lista}."))
            _fim(r, "autonomo", "Cupom de primeira compra: listei os validos hoje na plataforma.")
            return r, ferr
    return pedir_esclarecimento(r, ferr, cid, escrever, "Promocao", "qual cupom ou promocao voce quer saber (e o numero do pedido, se houver)")


# ---------- troca de fragrancia (e arrependimento da Gocase) ----------
def _produto_citado(texto: str, marca: str, sku_atual: str) -> tuple[list[dict], str]:
    """Produtos da MESMA marca cujo nome aparece no texto. Retorna (candidatos, token)."""
    tokens = [t for t in re.findall(r"[A-Za-zÀ-ÿ]{4,}", texto) if t.lower() not in STOP_PRODUTO]
    for tok in tokens:
        achados = dados.consulta("select sku, nome, preco_venda from produtos where marca = ? and sku <> ? and lower(nome) like ?",
                                 [marca, sku_atual, f"%{tok.lower()}%"])
        if 0 < len(achados) <= 3:
            return achados, tok
    return [], ""


def troca(r, ferr, cid, pedido, texto, agora, escrever):
    oid, marca = pedido["order_id"], pedido.get("marca")
    if str(marca).lower() == "gocase":  # a troca por fragrancia e da GoBeaute; na Gocase vale o arrependimento
        if not INTENCAO_CANCELAR.search(texto):
            return pedir_esclarecimento(r, ferr, cid, escrever, "Troca (Gocase)", "se voce quer devolver o produto e receber o reembolso")
        return cancelamento(r, ferr, cid, pedido, texto, agora, escrever)
    dias = _dias_desde_entrega(pedido, agora)
    if dias is None:
        return pedir_esclarecimento(r, ferr, cid, escrever, "Troca", "se o pedido ja chegou (a troca vale depois do recebimento)")
    if dias > PRAZO_TROCA_DIAS or ferr.trocas_do_pedido(oid) >= 1:
        motivo = f"o pedido foi recebido ha {dias} dias (prazo de {PRAZO_TROCA_DIAS})" if dias > PRAZO_TROCA_DIAS else "cada pedido tem direito a 1 troca e ela ja foi feita"
        ferr.negar_por_politica(cid, "troca_fragrancia")
        ferr.responder_cliente(cid, escrever(r, "explicar por que a troca nao e possivel", f"Troca do pedido {oid} negada pela politica: {motivo}.",
                                             f"Nao consigo fazer a troca do pedido {oid}: {motivo}."))
        _fim(r, "fora_da_politica", f"Troca negada pela politica: {motivo}.")
        return r, ferr
    if not USO_DECLARADO.search(texto):
        return pedir_esclarecimento(r, ferr, cid, escrever, "Troca de fragrancia",
                                    "quanto do produto voce usou (a troca vale com no maximo 20% usado) e por qual fragrancia quer trocar")
    achados, tok = _produto_citado(texto, marca, pedido.get("sku", ""))
    if len(achados) != 1:
        return pedir_esclarecimento(r, ferr, cid, escrever, "Troca de fragrancia", "por qual produto ou fragrancia voce quer trocar")
    novo = achados[0]
    valor = float(pedido.get("valor") or 0)
    if valor > LIMITE_TROCA:
        aprov = ferr.solicitar_aprovacao("troca", oid, valor, f"Troca por {novo['nome']}")
        ferr.responder_cliente(cid, escrever(r, "informar que a troca foi encaminhada para aprovacao", f"A troca do pedido {oid} passa do limite e precisa de aprovacao.",
                                             "Registrei a sua troca e ela foi encaminhada para aprovacao. Voltamos em breve."))
        _fim(r, "aguardando_supervisor", f"Troca de {_brl(valor)} acima do limite ({_brl(LIMITE_TROCA)}): pedi aprovacao ({aprov}).")
        return r, ferr
    ferr.trocar_produto(oid, novo["sku"], valor)
    fatos = f"Troca do pedido {oid} aprovada: {novo['nome']}, dentro do prazo, com uso declarado de ate 20%, 1 troca por pedido."
    ferr.responder_cliente(cid, escrever(r, "informar a troca", fatos, f"Troca aprovada! Vamos enviar {novo['nome']} no lugar do produto do pedido {oid}."))
    _fim(r, "autonomo", f"Troca por '{novo['nome']}' executada (1 troca por pedido, {dias} dias, uso declarado pelo cliente).")
    return r, ferr
