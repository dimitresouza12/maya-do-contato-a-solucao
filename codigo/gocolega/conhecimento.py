"""Base de conhecimento com busca (RAG): recuperacao lexical BM25 sobre tres fontes.

  produto   fichas de produto (composicao, modo de uso, advertencias, validade...)   -> responder duvidas
  politica  regras da politica de atendimento                                         -> citar a regra exata
  caso      conversas ja atendidas (texto do cliente, etiqueta e o que o humano fez) -> precedentes para o supervisor

SEM EMBEDDINGS: o AI Proxy do evento nao expoe endpoint de embeddings (testado: 404). A busca e lexical (BM25 com
normalizacao simples de acento e plural), logo nao entende sinonimos. Em troca e determinista, rapida e auditavel.
RAG aqui e uma FERRAMENTA de apoio (o desafio diz que "uma IA que so consulta textos" nao e o agente): a decisao
continua no Policy Engine, e a resposta so sai se for fundamentada nas passagens recuperadas.
"""
import math
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from functools import lru_cache

from . import dados

K1, B = 1.5, 0.75
STOP = {
    "de", "da", "do", "das", "dos", "para", "por", "com", "sem", "uma", "uns", "umas", "que", "qual", "quais", "como",
    "esta", "este", "essa", "esse", "isso", "meu", "minha", "meus", "minhas", "tem", "ter", "pode", "posso", "voce",
    "voces", "ola", "bom", "boa", "dia", "tarde", "noite", "obrigad", "favor", "sobre", "mais", "muito", "tambem",
    "quando", "onde", "ser", "foi", "sao", "estou", "tenho", "gostaria", "saber", "queria", "ainda", "mas", "nao",
    "depois", "antes", "algum", "alguma", "qualquer", "vcs", "hoje", "agora", "aqui", "obrigada", "obrigado",
    "diga", "favor", "tudo", "bem", "oii", "ola",
}


def tokens(texto: str) -> list[str]:
    t = unicodedata.normalize("NFKD", (texto or "").lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    saida = []
    for w in re.findall(r"[a-z0-9]+", t):
        if len(w) < 3 or w in STOP:
            continue
        if len(w) > 4 and w.endswith("s"):
            w = w[:-1]  # plural simples
        saida.append(w)
    return saida


@dataclass
class Passagem:
    id: str
    fonte: str
    titulo: str
    texto: str
    meta: dict = field(default_factory=dict)


@dataclass
class Resultado:
    passagem: Passagem
    score: float
    cobertura: float  # fracao do peso (idf) dos termos da pergunta que a passagem contem, de 0 a 1


class Indice:
    def __init__(self, passagens: list[Passagem]):
        self.p = passagens
        self.tf = [Counter(tokens(p.titulo + " " + p.texto)) for p in passagens]
        self.len = [max(1, sum(c.values())) for c in self.tf]
        self.avg = (sum(self.len) / len(self.len)) if self.len else 1.0
        df = Counter()
        for c in self.tf:
            df.update(c.keys())
        n = len(passagens)
        self.idf = {t: math.log(1 + (n - d + 0.5) / (d + 0.5)) for t, d in df.items()}

    def buscar(self, consulta: str, k: int = 3, filtro=None, pesos: dict[str, float] | None = None) -> list[Resultado]:
        """pesos: peso de cada termo da pergunta (conhecido por QUALQUER indice). Serve de denominador da cobertura:
        sem isso, um indice que so conhece 1 dos 5 termos reportaria 100% de cobertura (enganoso)."""
        termos = [t for t in dict.fromkeys(tokens(consulta)) if t in self.idf]
        if not termos:
            return []
        peso = (lambda t: pesos.get(t, self.idf[t])) if pesos else (lambda t: self.idf[t])
        total = sum(pesos.values()) if pesos else sum(self.idf[t] for t in termos)
        achados = []
        for i, p in enumerate(self.p):
            if filtro and not filtro(p):
                continue
            tf, score, cob = self.tf[i], 0.0, 0.0
            for t in termos:
                f = tf.get(t, 0)
                if f:
                    score += self.idf[t] * f * (K1 + 1) / (f + K1 * (1 - B + B * self.len[i] / self.avg))
                    cob += peso(t)
            if score > 0:
                achados.append(Resultado(p, score, min(1.0, cob / total) if total else 0.0))
        achados.sort(key=lambda r: -r.score)
        return achados[:k]


ROTULOS_PRODUTO = [
    ("apresentacao", "Apresentacao"), ("conteudo", "Conteudo"), ("composicao", "Composicao"),
    ("modo_de_uso", "Modo de uso"), ("notas_olfativas", "Notas olfativas"), ("fixacao", "Fixacao"),
    ("advertencias", "Advertencias"), ("validade_meses_fechado", "Validade fechado (meses)"),
    ("validade_apos_aberto", "Validade apos aberto"), ("vegano", "Vegano"), ("cruelty_free", "Cruelty free"),
    ("sem_gluten_sem_lactose", "Sem gluten e sem lactose"), ("liberado_low_poo", "Liberado para low poo"),
    ("registro_anvisa", "Registro Anvisa"), ("modelo_compativel", "Modelo compativel"),
    ("compativel_magsafe", "Compativel com MagSafe"), ("personalizavel", "Personalizavel"),
    ("tipo_personalizacao", "Tipo de personalizacao"), ("prazo_producao_dias_uteis", "Prazo de producao (dias uteis)"),
    ("peso_g", "Peso (g)"), ("dimensoes_cm", "Dimensoes (cm)"),
]


def _vazio(v) -> bool:
    return v is None or str(v).strip() in ("", "nan", "NaN", "None")


def _produtos() -> list[Passagem]:
    try:
        linhas = dados.consulta("select * from produtos")
    except Exception:
        return []
    out = []
    for r in linhas:
        cab = f"{r.get('nome')} ({r.get('marca')}, {r.get('categoria')})"
        corpo = [f"Produto: {cab}"] + [f"{rot}: {r[c]}" for c, rot in ROTULOS_PRODUTO if c in r and not _vazio(r[c])]
        out.append(Passagem(f"produto:{r['sku']}", "produto", cab, "\n".join(corpo), {"sku": r["sku"], "marca": r.get("marca")}))
    return out


def _politicas() -> list[Passagem]:
    try:
        linhas = dados.consulta("select secao, regra, valor from politicas")
    except Exception:
        return []
    grupos: dict[str, list[str]] = {}
    for r in linhas:
        if _vazio(r["valor"]):
            continue
        chave = r["regra"].split(".")[0] if r["secao"] == "categorias" else r["secao"]
        grupos.setdefault(chave, []).append(f"{r['regra']}: {r['valor']}")
    return [Passagem(f"politica:{k}", "politica", k.replace("_", " "), "\n".join(v)) for k, v in grupos.items()]


def _casos() -> list[Passagem]:
    try:
        linhas = dados.consulta("""
            select c.conversation_id, c.tag_agente, c.canal, c.data_abertura,
                   string_agg(m.texto, ' ' order by m.timestamp) texto
            from historico_conversas c join historico_mensagens m using(conversation_id)
            where m.autor = 'cliente' and c.tag_agente is not null group by 1, 2, 3, 4""")
        humano = {r["conversation_id"]: r["tipo"] for r in dados.consulta("select conversation_id, tipo from trocas_reenvios")}
    except Exception:
        return []
    return [Passagem(f"caso:{r['conversation_id']}", "caso", r["tag_agente"], r["texto"] or "",
                     {"tag": r["tag_agente"], "canal": r["canal"], "data": r["data_abertura"],
                      "acao_humana": humano.get(r["conversation_id"])}) for r in linhas]


class Conhecimento:
    def __init__(self):
        self.indices = {"produto": Indice(_produtos()), "politica": Indice(_politicas()), "caso": Indice(_casos())}
        valores = sorted(v for i in self.indices.values() for v in i.idf.values())
        self.idf_mediano = valores[len(valores) // 2] if valores else 1.0

    def tamanho(self) -> dict[str, int]:
        return {f: len(i.p) for f, i in self.indices.items()}

    def buscar(self, consulta: str, fonte: str, k: int = 3, filtro=None) -> list[Resultado]:
        # A cobertura e medida contra TODOS os termos da pergunta. Termo que NENHUMA fonte conhece pesa como o mais
        # informativo e NAO e coberto: uma pergunta quase toda fora do vocabulario nao pode parecer "100% coberta"
        # so porque sobrou uma palavra comum (ex.: 'produto' em "DROP TABLE produtos").
        termos = list(dict.fromkeys(tokens(consulta)))
        if not termos:
            return []
        # (peso do termo desconhecido = idf MEDIANO: pesar como o maximo mandaria para uma pessoa o cliente educado que
        #  escreve "obrigada, bom dia"; o mediano ainda derruba perguntas feitas quase so de palavras estranhas.)
        pesos = {t: (max((i.idf.get(t, 0.0) for i in self.indices.values()), default=0.0) or self.idf_mediano) for t in termos}
        return self.indices[fonte].buscar(consulta, k, filtro, pesos)

    def precedentes(self, texto: str, excluir: str | None = None, antes_de: datetime | None = None, k: int = 10) -> dict:
        """Casos parecidos JA atendidos (so os anteriores a 'antes_de', para nao vazar o futuro) e o que o humano fez."""
        def ok(p: Passagem) -> bool:
            if excluir and p.id == f"caso:{excluir}":
                return False
            return antes_de is None or (p.meta.get("data") is not None and p.meta["data"] < antes_de)

        achados = [r for r in self.buscar(texto, "caso", k, ok) if r.cobertura >= 0.5]
        acoes = Counter(r.passagem.meta.get("acao_humana") or "nenhuma" for r in achados)
        return {"n": len(achados), "acoes_humanas": dict(acoes),
                "tags": dict(Counter(r.passagem.meta["tag"] for r in achados)),
                "ids": [r.passagem.id for r in achados[:3]]}


@lru_cache(maxsize=1)
def base() -> Conhecimento:
    return Conhecimento()


def limpar_cache():
    base.cache_clear()
