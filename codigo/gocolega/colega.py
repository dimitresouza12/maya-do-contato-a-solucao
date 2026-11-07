"""Canal do time (Slack, simulado): pedidos de colegas de outras areas (logistica, qualidade, marketing, comercial, supervisao).

parametros.md: "o ambiente entrega esses pedidos e o agente responde com `responder_colaborador`. Pedido de colaborador nao muda a
politica: o que passa da alcada continua precisando de aprovacao."

Principios (os mesmos do atendimento): o CODIGO consulta a base e decide; o texto sai com numeros EXATOS da consulta (sem modelo,
sem invencao). Consultas devolvem so agregados, nunca CPF, telefone ou cartao. Pedido para EXECUTAR dinheiro (reembolso,
reenvio, troca) nao e executado a pedido de colega: vira solicitacao de aprovacao do supervisor, com quem pediu registrado.

Honestidade: nao ha Slack real nem pedidos de exemplo na base. O canal e simulado (a resposta vai para o log de auditoria, como
as demais acoes) e os pedidos de `EXEMPLOS` foram escritos por nos para demonstrar cada rota; nao sao do ambiente.
"""
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime

from . import dados
from .ferramentas import Ferramentas, mascarar_pii

LOTE = re.compile(r"\bLT\d{4}-[A-Z]\b", re.I)
PEDIDO = re.compile(r"\bG[BC]H\d{5,7}\b", re.I)
VALOR = re.compile(r"R\$\s*([\d.]+(?:,\d{2})?)")
DADO_PESSOAL = re.compile(r"\bcpf\b|telefone|celular|cart[aã]o|e-?mail do cliente|endere[cç]o (completo )?d[oe]s? cliente|dados (pessoais|do cliente)", re.I)
EXECUTAR = re.compile(r"\b(reembols|reenvi|troca[rm]?\b|libera[rm]?\b|aprov[ae]|autoriz|estorn)", re.I)
NOTIFICAR = re.compile(r"\b(avis[aeo]s?|notific\w*|comunic\w*|mand[ae] (uma )?mensagem)\b.{0,60}\bclientes?\b|\bclientes?\b.{0,60}\b(avis|notific|comunic)", re.I)
VOLUME = re.compile(r"motivos? de contato|mais contato|volume|assuntos?|o que (mais )?(os )?clientes|top \d|principais", re.I)
CHAMADOS = re.compile(r"chamados?|transportadora|extravi|atrasad|em tr[aâ]nsito|entregas?", re.I)
AGORA_AMBIENTE = datetime(2026, 11, 2, 8, 0)  # parametros.md: "agora" do ambiente; os dados vao ate essa data

EXEMPLOS = [  # escritos por nos para demonstrar cada rota (NAO sao do ambiente)
    {"pedido_id": "COL-001", "area": "qualidade", "autor": "Rafael (Qualidade)",
     "texto": "Quantas reclamações já chegaram do lote LT2607-B? Tem algo estranho com ele?"},
    {"pedido_id": "COL-002", "area": "logistica", "autor": "Bruna (Logística)",
     "texto": "Como estão os chamados abertos com a Expressa Já? Algum vencido?"},
    {"pedido_id": "COL-003", "area": "marketing", "autor": "Diego (Marketing)",
     "texto": "O cupom BEMVINDA10 está dando problema? Quantos usos recusados e por quê?"},
    {"pedido_id": "COL-004", "area": "comercial", "autor": "Helena (Comercial)",
     "texto": "Quais os principais motivos de contato da última semana? Quero ajustar a campanha."},
    {"pedido_id": "COL-005", "area": "supervisao", "autor": "Lucas (Supervisão)",
     "texto": "Pode reembolsar R$ 340 do pedido GBH318543? O cliente está bravo."},
    {"pedido_id": "COL-006", "area": "marketing", "autor": "Diego (Marketing)",
     "texto": "Manda um aviso para todos os clientes com pedido atrasado pedindo desculpas?"},
    {"pedido_id": "COL-007", "area": "comercial", "autor": "Helena (Comercial)",
     "texto": "Me passa o CPF e o telefone da cliente do pedido GBH318543 pra eu ligar."},
    {"pedido_id": "COL-008", "area": "logistica", "autor": "Bruna (Logística)",
     "texto": "Qual a previsão de chegada da nova coleção de verão?"},
]


@dataclass
class RespostaColega:
    pedido_id: str
    area: str
    intencao: str = ""
    resposta: str = ""
    desfecho: str = ""  # respondido | aprovacao_solicitada | recusado | encaminhado
    passos: list[str] = field(default_factory=list)

    def p(self, t: str):
        self.passos.append(t)


def _norm(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s or "") if not unicodedata.combining(c)).lower()


def _n(x) -> str:
    return f"{int(x):,}".replace(",", ".")


def _brl(v: float) -> str:
    return "R$ " + f"{float(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _valor_do_texto(texto: str) -> float | None:
    m = VALOR.search(texto)
    return float(m.group(1).replace(".", "").replace(",", ".")) if m else None


# ---------------------------------------------------------------- consultas (so agregados)
def _qualidade(r: RespostaColega, texto: str) -> str:
    m = LOTE.search(texto)
    if not m:
        return "Para olhar a qualidade preciso do código do lote (ex.: LT2603-C). Qual lote você quer ver?"
    lote = m.group(0).upper()
    info = dados.uma("select descricao_produto, marca, status_qualidade, quantidade_produzida from lotes_producao where lote = ?", [lote])
    if not info:
        return f"Não encontrei o lote {lote} na base de produção."
    ped = dados.uma("select count(*) n from pedidos where lote_produto = ?", [lote])["n"]
    tags = dados.consulta("select coalesce(c.tag_agente,'sem etiqueta') tag, count(*) n from historico_conversas c "
                          "join pedidos p on p.order_id = c.order_id where p.lote_produto = ? group by 1 order by 2 desc", [lote])
    total = sum(t["n"] for t in tags)
    r.p(f"Consulta: lote {lote}, {_n(ped)} pedidos, {total} conversas.")
    if not total:
        return (f"Lote {lote} ({info['descricao_produto']}, {info['marca']}, qualidade: {info['status_qualidade']}): "
                f"{_n(ped)} pedidos na base e nenhuma conversa de atendimento até agora.")
    taxa = total / ped * 100 if ped else 0
    top = ", ".join(f"{t['tag']} {t['n']}" for t in tags[:4])
    return (f"Lote {lote} ({info['descricao_produto']}, {info['marca']}, qualidade: {info['status_qualidade']}): {_n(ped)} pedidos e "
            f"{total} conversas ({taxa:.1f}% dos pedidos). Principais assuntos: {top}. Isso é só uma contagem: para saber se o lote destoa "
            "do esperado é preciso comparar com os demais, e a análise de causa raiz faz isso com teste estatístico.")


def _logistica(r: RespostaColega, texto: str, agora: datetime) -> str:
    nomes = [x["transportadora"] for x in dados.consulta("select distinct transportadora from pedidos")]
    citadas = [n for n in nomes if _norm(n) in _norm(texto)] or nomes
    ab = {x["transportadora"]: x["n"] for x in dados.consulta(
        "select transportadora, count(*) n from chamados_transportadora where status <> 'encerrado' group by 1")}
    # vencido = a transportadora NAO respondeu e o prazo (prazo_resposta) ja passou; 'respondido' mas nao encerrado nao e vencido
    ven = {x["transportadora"]: x["n"] for x in dados.consulta(
        "select transportadora, count(*) n from chamados_transportadora where data_resposta is null and prazo_resposta < ? group by 1",
        [min(agora, AGORA_AMBIENTE)])}
    ext = {x["transportadora"]: x["n"] for x in dados.consulta(
        "select transportadora, count(*) n from pedidos where status_entrega = 'extraviado' group by 1")}
    tra = {x["transportadora"]: x["n"] for x in dados.consulta(
        "select transportadora, count(*) n from pedidos where status_entrega = 'em_transito' group by 1")}
    r.p(f"Consulta: chamados e pedidos de {', '.join(citadas)}.")
    linhas = [f"{n}: {_n(ab.get(n, 0))} chamados ainda não encerrados ({_n(ven.get(n, 0))} sem resposta da transportadora e com prazo vencido), "
              f"{_n(tra.get(n, 0))} pedidos em trânsito, {_n(ext.get(n, 0))} extraviados." for n in citadas]
    return "\n".join(linhas)


def _marketing(r: RespostaColega, texto: str) -> str:
    codigos = [x["codigo"] for x in dados.consulta("select codigo from cupons")]
    achado = next((c for c in codigos if c.lower() in texto.lower()), None)
    if not achado:
        return "Qual cupom você quer ver? Passe o código (ex.: BEMVINDA10)."
    cup = dados.uma("select * from cupons where codigo = ?", [achado])
    uso = dados.consulta("select status, coalesce(motivo_recusa,'-') motivo, count(*) n from uso_cupons where codigo = ? group by 1,2 order by 3 desc", [achado])
    r.p(f"Consulta: cupom {achado}, {sum(u['n'] for u in uso)} usos na base.")
    ap = sum(u["n"] for u in uso if u["status"] == "aplicado")
    rec = [u for u in uso if u["status"] != "aplicado"]
    cab = (f"{achado} ({cup['descricao']}), status {cup['status']}, vigência até {cup['fim_vigencia']:%d/%m/%Y}, "
           f"limite por cliente {cup['limite_uso_por_cliente']}. Aplicados: {_n(ap)}.")
    if not rec:
        return cab + " Nenhum uso recusado."
    return cab + " Recusados: " + "; ".join(f"{u['motivo']} ({u['n']})" for u in rec) + "."


def _volume(r: RespostaColega) -> str:
    base = dados.uma("select max(data_abertura) f from historico_conversas")["f"]
    rows = dados.consulta("select coalesce(tag_agente,'sem etiqueta') tag, count(*) n from historico_conversas "
                          "where data_abertura > ? - interval 7 day group by 1 order by 2 desc limit 5", [base])
    tot = dados.uma("select count(*) n from historico_conversas where data_abertura > ? - interval 7 day", [base])["n"]
    r.p(f"Consulta: ultimos 7 dias da base (ate {base:%d/%m}), {tot} conversas (amostra de 1 em cada 4 clientes).")
    return (f"Nos 7 dias até {base:%d/%m} (amostra de 1 em cada 4 clientes, então o volume real é cerca de 4x): "
            + ", ".join(f"{x['tag']} {x['n']} ({x['n'] / tot * 100:.0f}%)" for x in rows) + f". Total na amostra: {_n(tot)}.")


# ---------------------------------------------------------------- roteamento
def tratar_colega(pedido_id: str, area: str, texto: str, ferr: Ferramentas | None = None, autor: str = "colega"):
    ferr = ferr or Ferramentas("atendente", "gocolega")
    r = RespostaColega(pedido_id, area)
    texto = mascarar_pii(texto)

    # 1) Dado pessoal: nunca sai pelo canal do time (o cliente nao consentiu esse uso; a politica manda mascarar PII).
    if DADO_PESSOAL.search(texto):
        r.intencao, r.desfecho = "dado_pessoal", "recusado"
        r.resposta = ("Não passo CPF, telefone, cartão nem endereço de cliente pelo canal do time. Se você precisa falar com a cliente, "
                      "me diga o pedido e eu abro o contato pelo atendimento, ou peça pelo sistema com a permissão adequada.")
        r.p("Pedido de dado pessoal: recusado, sem expor nada.")
    # 2) Executar dinheiro: nao executa a pedido de colega; vira aprovacao.
    elif EXECUTAR.search(texto) and (PEDIDO.search(texto) or VALOR.search(texto)):
        r.intencao = "executar_acao"
        m = PEDIDO.search(texto)
        oid = m.group(0).upper() if m else None
        ped = ferr.consultar_pedido(oid) if oid else None
        if not ped:
            r.desfecho = "encaminhado"
            r.resposta = "Para eu abrir a aprovação preciso do número do pedido (GCH ou GBH). Pode mandar?"
            r.p("Pedido para executar acao sem pedido valido: pedi o numero.")
        else:
            valor = float(ped["valor"])  # o valor vem do PEDIDO, nunca do texto
            pedido_txt = _valor_do_texto(texto)
            acao = "reembolsar" if re.search(r"reembols|estorn", texto, re.I) else "reenviar_produto"
            apr = ferr.solicitar_aprovacao(acao, ped["order_id"], valor, f"Pedido de colaborador ({autor}, {area}) no canal do time: {texto[:200]}")
            r.desfecho = "aprovacao_solicitada"
            nota = f" (você citou {_brl(pedido_txt)}; vale o valor do pedido)" if pedido_txt and abs(pedido_txt - valor) > 0.01 else ""
            r.resposta = (f"Pedido de colega não muda a política, então não executo direto: abri a aprovação {apr} do supervisor para "
                          f"{'reembolsar' if acao == 'reembolsar' else 'reenviar'} {_brl(valor)} do pedido {ped['order_id']}{nota}. "
                          "Quem aprova não pode ser quem pediu.")
            r.p(f"Acao de dinheiro pedida por colega: {acao} de {_brl(valor)} NAO executada; aprovacao {apr} solicitada.")
    # 3) Aviso em massa: so prepara, depende de aprovacao, teto de 300 por dia.
    elif NOTIFICAR.search(texto):
        r.intencao, r.desfecho = "aviso_em_massa", "aprovacao_solicitada"
        ferr.acionar_pessoa("supervisao", "Aviso proativo pedido pelo canal do time",
                            f"{autor} ({area}) pediu: {texto[:200]}. Preparar lista e texto; enviar so apos aprovacao (teto de 300 clientes por dia).", "normal")
        r.resposta = ("Posso preparar a lista e o texto, mas o envio só sai depois da aprovação do supervisor e respeita o teto de "
                      "300 clientes por dia. Já avisei a supervisão.")
        r.p("Aviso em massa: nada enviado; supervisao acionada.")
    # 4) Consultas (somente leitura, agregadas)
    elif LOTE.search(texto) or re.search(r"qualidade|lote", texto, re.I):
        r.intencao, r.desfecho, r.resposta = "consulta_qualidade", "respondido", _qualidade(r, texto)
    elif re.search(r"cupom", texto, re.I) or any(c.lower() in texto.lower() for c in [x["codigo"] for x in dados.consulta("select codigo from cupons")]):
        r.intencao, r.desfecho, r.resposta = "consulta_cupom", "respondido", _marketing(r, texto)
    elif CHAMADOS.search(texto) and not re.search(r"previs[aã]o de chegada|cole[cç][aã]o|lan[cç]amento", texto, re.I):
        r.intencao, r.desfecho, r.resposta = "consulta_logistica", "respondido", _logistica(r, texto, ferr.agora)
    elif VOLUME.search(texto):
        r.intencao, r.desfecho, r.resposta = "consulta_volume", "respondido", _volume(r)
    else:
        # Sem rota segura: nao inventa. Diz o que nao sabe e passa a quem sabe.
        r.intencao, r.desfecho = "fora_do_escopo", "encaminhado"
        ferr.acionar_pessoa("supervisao", "Pedido de colaborador sem resposta segura",
                            f"{autor} ({area}) perguntou: {texto[:200]}", "normal")
        r.resposta = "Essa eu não consigo responder com segurança com os dados que tenho, então passei para a supervisão responder você."
        r.p("Sem rota segura nos dados: nao inventei resposta; encaminhado.")

    ferr.responder_colaborador(pedido_id, r.resposta)
    r.p(f"Intencao: {r.intencao}. Desfecho: {r.desfecho}.")
    return r, ferr
