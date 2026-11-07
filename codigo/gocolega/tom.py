"""Tom das respostas: acolhimento. Retribui o cumprimento do cliente, chama pelo primeiro nome quando ele se identificou e
reconhece o sentimento (repeticao, urgencia, frustracao, ansiedade) com UMA frase curta, sem culpar ninguem.

Dois caminhos usam isto:
  1. o Redator (modelo) recebe a mensagem do cliente como DADO e e instruido a acolher (ver agentes.redator_rascunho);
  2. os textos FIXOS (suspeita, caso sensivel, regras da politica, fallback) recebem a abertura por `acolher`, que e
     deterministica e nao repete o que o texto ja traz.
Nada aqui decide ou afirma fato: so da tom. Os fatos continuam vindo do sistema e passando pelo Verificador.
"""
import re
import zlib

SAUDACAO = re.compile(r"\b(bom dia|boa tarde|boa noite)\b", re.I)
OLA = re.compile(r"\b(ol[aá]|oi+e?|oie)\b", re.I)
TUDO_BEM = re.compile(r"tudo (bem|bom|certo)\b", re.I)
# primeiro nome depois de uma despedida ("Att, Fernanda", "Obrigada, Ingrid"); letra maiuscula obrigatoria
NOME = re.compile(r"(?i:att\.?|atenciosamente|obrigad[oa]|abra[cç]os?|grat[oa])[,.]?\s+([A-ZÀ-Ý][a-zà-ÿ]{2,})")
NAO_E_NOME = {"Meu", "Minha", "Pedido", "Pode", "Podem", "Quero", "Queria", "Gostaria", "Ainda", "Estou", "Voces", "Vocês",
              "Segue", "Preciso", "Não", "Nao", "Mas", "Como", "Qual", "Quando", "Onde", "Boa", "Bom", "Por", "Pela", "Pelo",
              "Equipe", "Time", "Prezados", "Olá", "Ola", "Outra", "Outro", "Tenho", "Fiz", "Comprei", "Recebi", "Cadê", "Cade"}

REPETICAO = re.compile(r"j[aá] [eé] a \d|\d[ªa] vez|segunda vez|de novo|voltando|n[aã]o resolveram|ningu[eé]m (me )?respond|"
                       r"sem solu|j[aá] entrei em contato|j[aá] falei", re.I)
URGENCIA = re.compile(r"urgente|presente|anivers|casamento|viagem|viajar|preciso (at[eé]|pra|para)|data que eu precisava", re.I)
RAIVA = re.compile("😡|🙄|absurdo|descaso|desrespeit|vergonha|vou abrir reclama|reclame aqui|golpe|nota 10|que servi[cç]o", re.I)
ANSIEDADE = re.compile(r"ansios|nervos|preocupad|com medo|fiquei com medo", re.I)
PROBLEMA = {"Avaria": "Sinto muito pelo ocorrido.", "Produto faltando": "Sinto muito pelo ocorrido.",
            "Reclamacao produto": "Sinto muito pelo ocorrido.", "Atraso": "Sinto muito pela demora.",
            "Financeiro": "Entendo a preocupação com a cobrança.", "Cancelamento": "Sem problema, vou te ajudar com isso."}
# o texto ja acolhe? (nao duplica)
JA_ACOLHE = re.compile(r"sinto muito|lamento|lamentamos|entendo|desculp|obrigad|que bom|ol[aá]\b|oi\b|bom dia|boa tarde|boa noite|"
                       r"agradecemos|sem problema", re.I)


def nome_do_cliente(cliente: str) -> str | None:
    for m in NOME.finditer(cliente or ""):
        n = m.group(1)
        if n not in NAO_E_NOME:
            return n
    return None


# Variantes: a mesma frase em todas as respostas soa robotica. A escolha e DETERMINISTICA (depende do texto do cliente),
# entao o mesmo caso sempre gera a mesma resposta (testavel e auditavel). Reclame Aqui e publico: tom institucional.
VARIANTES = {
    "repeticao": ["Sinto muito por você ter precisado voltar a falar com a gente.",
                  "Peço desculpas por você ter que entrar em contato de novo.",
                  "Lamento que você precise insistir nesse assunto."],
    "raiva": ["Sinto muito por essa experiência e entendo a sua frustração.",
              "Entendo o seu incômodo e lamento que isso tenha acontecido.",
              "Entendo a sua insatisfação e sinto muito por isso."],
    "urgencia": ["Entendo que isso é urgente para você.",
                 "Sei que você precisa disso logo, vamos agilizar.",
                 "Entendo a pressa, vou direto ao ponto."],
    "ansiedade": ["Entendo a sua preocupação e vou te ajudar.",
                  "Pode contar comigo, vou te ajudar com isso.",
                  "Imagino a sua preocupação, vamos resolver."],
}
PROBLEMA_VARIANTE = {"Sinto muito pelo ocorrido.": ["Sinto muito pelo ocorrido.", "Lamento o que aconteceu.", "Poxa, sinto muito por isso."],
                     "Sinto muito pela demora.": ["Sinto muito pela demora.", "Peço desculpas pela espera.", "Lamento a demora."]}
# Reclame Aqui e publico e institucional: primeira pessoa do plural, sem coloquialismo ("Poxa", "Pode contar comigo").
FORMAL_RA = {"Poxa, sinto muito": "Lamentamos", "Pode contar comigo, vou": "Vamos", "Sinto muito": "Lamentamos",
             "Peço desculpas": "Pedimos desculpas", "Lamento": "Lamentamos", "Entendo": "Entendemos", "Sei que": "Sabemos que",
             "Imagino": "Entendemos"}


def _escolhe(opcoes: list[str], c: str) -> str:
    return opcoes[zlib.crc32((c or "").encode("utf-8")) % len(opcoes)]


def _formal(frase: str) -> str:
    for k, v in FORMAL_RA.items():  # ordem importa: as frases mais longas vem primeiro
        if frase.startswith(k):
            return (v + frase[len(k):]).replace(" e entendo ", " e entendemos ").replace(" e lamento ", " e lamentamos ").replace(" e sinto muito ", " e lamentamos ")
    return frase


def _empatia(c: str, categoria: str | None) -> str:
    for chave, rx in (("repeticao", REPETICAO), ("raiva", RAIVA), ("urgencia", URGENCIA), ("ansiedade", ANSIEDADE)):
        if rx.search(c):
            return _escolhe(VARIANTES[chave], c)
    base = PROBLEMA.get(categoria or "", "")
    return _escolhe(PROBLEMA_VARIANTE[base], c) if base in PROBLEMA_VARIANTE else base


def abertura(cliente: str, categoria: str | None = None, canal: str | None = None) -> str:
    c = cliente or ""
    nome = nome_do_cliente(c)
    m = SAUDACAO.search(c)
    sau = m.group(1).capitalize() if m else ("Olá" if OLA.search(c) else "")
    ra = canal == "reclame_aqui"
    fim = "." if (ra or canal == "email") else "!"  # WhatsApp: exclamacao; e-mail e Reclame Aqui: ponto
    partes = []
    if sau:
        partes.append(f"{sau}, {nome}{fim}" if nome else f"{sau}{fim}")
    elif nome:
        partes.append(f"Olá, {nome}{fim}")
    if TUDO_BEM.search(c) and not ra:
        partes.append("Tudo bem por aqui, obrigado por perguntar!")
    emp = _empatia(c, categoria)
    if emp:
        partes.append(_formal(emp) if ra else emp)
    return " ".join(partes)


def acolher(cliente: str | None, resposta: str, categoria: str | None = None, canal: str | None = None) -> str:
    """Prefixa a abertura quando a resposta ainda nao acolhe. Sem a mensagem do cliente, devolve a resposta como esta."""
    if not cliente or not resposta or JA_ACOLHE.search(resposta[:140]):
        return resposta
    ab = abertura(cliente, categoria, canal)
    return f"{ab} {resposta}" if ab else resposta
