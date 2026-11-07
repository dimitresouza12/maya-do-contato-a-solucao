"""Verificacao de fundamentacao: todo numero e data de um texto gerado precisa existir nos fatos fornecidos.

E um filtro deterministico contra alucinacao: o modelo pode reformular, mas nao pode inventar valor, prazo ou data.
"""
import re

PADRAO_NUM = re.compile(r"\d+(?:[.,]\d+)?")
PROMESSA = re.compile(r"garant(imos|o|ido)|com certeza|sem falta|imediatamente|ainda hoje|amanha", re.I)


def numeros(texto: str) -> set[str]:
    return {n.replace(",", ".").rstrip("0").rstrip(".") if "." in n.replace(",", ".") else n
            for n in PADRAO_NUM.findall(texto or "")}


def numeros_sem_apoio(texto: str, fatos: str) -> list[str]:
    """Numeros presentes no texto mas ausentes dos fatos (candidatos a invencao)."""
    return sorted(numeros(texto) - numeros(fatos))


def promessas_indevidas(texto: str, fatos: str) -> list[str]:
    """Promessas ('garantimos', 'amanha'...) que NAO aparecem nos fatos."""
    return [m.group(0) for m in PROMESSA.finditer(texto or "") if m.group(0).lower() not in (fatos or "").lower()]


def termos_sem_apoio(texto: str, fatos: str, minimo: float = 0.6) -> list[str]:
    """Palavras do texto que nao aparecem nos fatos, SE menos de 'minimo' das palavras tiver apoio.
    Pega afirmacao qualitativa inventada ('cura acne') que o filtro de numeros nao ve. Reformular e permitido;
    afirmar algo cujas palavras nao estao na ficha, nao."""
    from .conhecimento import tokens
    palavras = [t for t in tokens(texto) if len(t) >= 4]
    if not palavras:
        return []
    base = set(tokens(fatos))
    sem = [t for t in palavras if t not in base]
    return sem if (1 - len(sem) / len(palavras)) < minimo else []


def verificar(texto: str, fatos: str) -> list[str]:
    """Lista de problemas (vazia = fundamentado). Cada item e uma frase pronta para devolver ao redator."""
    problemas = []
    sem_apoio = numeros_sem_apoio(texto, fatos)
    if sem_apoio:
        problemas.append(f"os numeros {', '.join(sem_apoio)} nao estao nos fatos fornecidos")
    prom = promessas_indevidas(texto, fatos)
    if prom:
        problemas.append(f"a promessa '{prom[0]}' nao esta nos fatos fornecidos")
    return problemas
