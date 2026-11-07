"""Gera os slides do GoColega (PPTX editavel) a partir do brandbook do Gogroup.

Reaproveita os fundos e o logotipo do proprio brandbook (nao redesenha nada da marca) e escreve o conteudo
com formas e texto nativos, na paleta e na tipografia (Poppins) da marca. Regras do toolkit: ate 3 elementos por
slide, 10 slides, ultimo slide = o que fazer na segunda-feira.

Uso:  python codigo/ferramentas_dev/gerar_slides.py "<caminho do brandbook .pptx>" [saida.pptx]
Os numeros vem do dicionario NUM abaixo (cada um com a origem anotada).
"""
import copy
import sys

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Emu, Inches, Pt

AZUL, LIMA, CREME = RGBColor(0x26, 0x59, 0xA5), RGBColor(0xD7, 0xD9, 0x00), RGBColor(0xFB, 0xF4, 0xEE)
BRANCO, GRAFITE = RGBColor(0xFF, 0xFF, 0xFF), RGBColor(0x3B, 0x3B, 0x3B)

# cada numero: de onde vem. Nada aqui e estimativa nova; tudo foi medido nos scripts de codigo/benchmarks.
NUM = {
    "reenvio_ofertas": "148 de 148",   # validar_rastreio.py: ofertas de reenvio/reembolso que o humano tambem reenviou
    "lote_sem_humano": "SEM_HUMANO",   # rodar_lote.py + analisar_lote.py (preenchido pelo lote final)
    "lote_so_informa": "93%",          # idem: dos resolvidos sem humano, os que so informaram o cliente
    "mediana_s": "3,5 s",              # idem: tempo de processamento por caso
    "incidente": "29% contra 10%",     # causa_raiz.detectar, corte 10/10: Expressa Ja em 5 UFs
}


def clonar(prs, indice):
    """Copia o slide `indice` do brandbook (fundo, imagens e formas) para um slide novo no fim."""
    src = prs.slides[indice]
    dst = prs.slides.add_slide(src.slide_layout)
    for shp in list(dst.shapes):
        shp._element.getparent().remove(shp._element)
    mapa = {}
    for rid, rel in src.part.rels.items():
        if "notesSlide" in rel.reltype or "slideLayout" in rel.reltype:
            continue
        mapa[rid] = dst.part.rels.get_or_add(rel.reltype, rel._target) if not rel.is_external else \
            dst.part.rels.get_or_add_ext_rel(rel.reltype, rel._target)
    # fundo do slide (<p:bg>), se houver
    bg = src._element.cSld.find("{http://schemas.openxmlformats.org/presentationml/2006/main}bg")
    if bg is not None:
        dst._element.cSld.insert(0, copy.deepcopy(bg))
    for shp in src.shapes:
        dst.shapes._spTree.append(copy.deepcopy(shp._element))
    ns_r = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
    for el in dst._element.iter():
        for atr in ("embed", "link", "id"):
            v = el.get(ns_r + atr)
            if v in mapa:
                el.set(ns_r + atr, mapa[v])
    return dst


def remover_slides(prs, quantos):
    """Apaga os `quantos` primeiros slides (os do brandbook), soltando suas relacoes."""
    lista = prs.slides._sldIdLst
    for sld in list(lista)[:quantos]:
        prs.part.drop_rel(sld.rId)
        lista.remove(sld)


def texto(slide, x, y, w, h, runs, tam=12, cor=GRAFITE, negrito=False, alinha=PP_ALIGN.LEFT, ancora=MSO_ANCHOR.TOP):
    """Caixa de texto. `runs`: string ou lista de (texto, {tam, cor, negrito}) em paragrafos separados por \\n."""
    cx = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = cx.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = ancora
    tf.margin_left = tf.margin_right = Inches(0.05)
    tf.margin_top = tf.margin_bottom = Inches(0.03)
    paragrafos = [runs] if isinstance(runs, str) else runs
    for i, item in enumerate(paragrafos):
        t, est = (item, {}) if isinstance(item, str) else item
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = alinha
        r = p.add_run()
        r.text = t
        r.font.size = Pt(est.get("tam", tam))
        r.font.color.rgb = est.get("cor", cor)
        r.font.name = "Poppins ExtraBold" if est.get("negrito", negrito) else "Poppins"
    return cx


def cartao(slide, x, y, w, h, cor_fundo, partes, contorno=None):
    """Cartao de cantos arredondados com texto por cima. `partes`: lista de (texto, tam, cor, negrito)."""
    f = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(x), Inches(y), Inches(w), Inches(h))
    f.adjustments[0] = 0.12
    f.fill.solid()
    f.fill.fore_color.rgb = cor_fundo
    if contorno is not None:
        f.line.color.rgb = contorno
        f.line.width = Pt(2.25)
    else:
        f.line.fill.background()
    f.shadow.inherit = False
    runs = [(t, {"tam": tam, "cor": c, "negrito": neg}) for t, tam, c, neg in partes]
    texto(slide, x + 0.12, y + 0.1, w - 0.24, h - 0.2, runs)
    return f


def titulo(slide, t):
    """Reaproveita a caixa de titulo do slide-modelo (Poppins ExtraBold azul) e a alarga."""
    caixas = [s for s in slide.shapes if s.has_text_frame and s.text_frame.text.strip().startswith("T")]
    cx = caixas[0]
    cx.left, cx.top, cx.width, cx.height = Inches(0.7), Inches(1.0), Inches(8.6), Inches(0.55)
    for s in list(slide.shapes):
        if s.has_text_frame and s.text_frame.text.startswith("texto texto") :
            s._element.getparent().remove(s._element)
    p = cx.text_frame.paragraphs[0]
    p.alignment = PP_ALIGN.LEFT
    p.runs[0].text = t
    for extra in p.runs[1:]:
        extra.text = ""
    p.runs[0].font.size = Pt(20)
    cx.text_frame.word_wrap = True


def tres_cartoes(slide, itens, y=1.75, h=2.75):
    """Tres cartoes lado a lado. itens: [(cor_fundo, cor_texto, grande, texto)]."""
    w, gap = 2.7, 0.2
    for i, (fundo, ctexto, grande, corpo) in enumerate(itens):
        x = 0.75 + i * (w + gap)
        contorno = AZUL if fundo == BRANCO else None
        cartao(slide, x, y, w, h, fundo, [
            (grande, 32 if len(grande) <= 8 else 22, ctexto if fundo != BRANCO else AZUL, True),
            ("", 5, ctexto, False),
            (corpo, 14, ctexto if fundo != BRANCO else GRAFITE, False)], contorno)


def montar(caminho_brandbook, saida):
    prs = Presentation(caminho_brandbook)
    n_marca = len(prs.slides)
    IND_CAPA, IND_CONTEUDO = 14, 16  # slides 15 e 17 do brandbook

    # 1. Capa
    s = clonar(prs, IND_CAPA)
    for sh in s.shapes:
        if sh.has_text_frame and sh.text_frame.text.strip() == "Título aqui":
            sh.text_frame.paragraphs[0].runs[0].text = "GoColega"
        elif sh.has_text_frame and sh.text_frame.text.strip().startswith("S U B"):
            sh.left, sh.width = Inches(1.0), Inches(8.0)
            sh.text_frame.paragraphs[0].runs[0].text = "O COLEGA DE IA DO ATENDIMENTO"
            for r in sh.text_frame.paragraphs[0].runs[1:]:
                r.text = ""
    texto(s, 1.5, 4.55, 7.0, 0.3, "GoHacks Talent 2026  ·  Desafio 1: Atendimento ao Cliente", 10, BRANCO, False, PP_ALIGN.CENTER)

    # 2. A dor
    s = clonar(prs, IND_CONTEUDO); titulo(s, "O dia do Diego: 130 conversas e vários sistemas")
    tres_cartoes(s, [
        (AZUL, BRANCO, "~4 mil", "conversas por mês, por WhatsApp, e-mail e Reclame Aqui"),
        (LIMA, AZUL, "2 a 4", "sistemas abertos em 70% dos contatos. São ~10 min no WhatsApp e ~22 min no Reclame Aqui"),
        (AZUL, BRANCO, "45%", "do valor do pedido é o custo de reenviar uma avaria que não era verdadeira")])

    # 3. Fluxo atual
    s = clonar(prs, IND_CONTEUDO); titulo(s, "Hoje, o Diego decide sozinho se a reclamação procede")
    tres_cartoes(s, [
        (AZUL, BRANCO, "1  Lê e busca", "Abre a central, o ERP, o gateway e o portal da transportadora, um por vez"),
        (LIMA, AZUL, "2  Confere", "Compara foto, pedido, entrega e histórico do cliente, de cabeça"),
        (AZUL, BRANCO, "3  Marina aprova", "O que passa da alçada (R$ 100 a 200) vai para ela, sem o dossiê pronto")])

    # 4. Solução
    s = clonar(prs, IND_CONTEUDO); titulo(s, "GoColega: o colega de IA que age dentro da política")
    cartao(s, 0.75, 1.75, 8.6, 1.2, AZUL, [
        ("Um agente que lê a conversa, confere pedido, foto e histórico e age, para que Diego e Marina cuidem só do que é decisão de pessoa.", 14, BRANCO, False)])
    for i, (rot, fundo, ct) in enumerate([("Age sozinho", LIMA, AZUL), ("Pede aprovação", AZUL, BRANCO),
                                          ("Sinaliza suspeita", AZUL, BRANCO), ("Chama uma pessoa", AZUL, BRANCO)]):
        x = 0.75 + i * 2.17
        pill = s.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(x), Inches(3.2), Inches(2.05), Inches(0.55))
        pill.adjustments[0] = 0.5
        pill.fill.solid(); pill.fill.fore_color.rgb = fundo; pill.line.fill.background(); pill.shadow.inherit = False
        texto(s, x, 3.2, 2.05, 0.55, rot, 12, ct, True, PP_ALIGN.CENTER, MSO_ANCHOR.MIDDLE)
    texto(s, 0.75, 3.95, 8.6, 0.5, "Em cada caso, o dossiê vai pronto: o que o modelo viu, o que a política diz e o custo de errar.", 11.5, GRAFITE)

    # 5. Como funciona
    s = clonar(prs, IND_CONTEUDO); titulo(s, "O modelo propõe, o código decide")
    tres_cartoes(s, [
        (LIMA, AZUL, "A IA entende", "Classifica a conversa, confere a foto, resume o caso e escreve a resposta"),
        (AZUL, BRANCO, "O código decide", "Alçada (R$ 200 e R$ 100), prazo de 7 dias e quem pode aprovar: regras testadas, não um prompt"),
        (BRANCO, GRAFITE, "A pessoa decide o dela", "Suspeita, valor acima da alçada e caso sensível chegam com o dossiê pronto")])

    # 6. Demonstração
    s = clonar(prs, IND_CONTEUDO); titulo(s, "Ao vivo: três casos reais da base")
    tres_cartoes(s, [
        (AZUL, BRANCO, "Avaria suspeita", "Foto reutilizada, risco de 86%. O supervisor recebe o dossiê e o cliente nunca é acusado"),
        (LIMA, AZUL, "Atraso", "O cliente escolhe o reembolso e o GoColega executa R$ 75,91, dentro da alçada, com log de auditoria"),
        (AZUL, BRANCO, "Causa raiz", "Uma transportadora em 5 estados com " + NUM["incidente"] + " de conversas-problema, antes de o cliente escrever")])

    # 7. Resultados medidos
    s = clonar(prs, IND_CONTEUDO); titulo(s, "Resultados medidos em conversas reais")
    tres_cartoes(s, [
        (AZUL, BRANCO, NUM["reenvio_ofertas"], "ofertas de reenvio por atraso batem com o que a equipe fez (1.082 conversas)"),
        (LIMA, AZUL, NUM["lote_sem_humano"], "de 210 conversas resolvidas sem humano; " + NUM["lote_so_informa"] + " delas só informam o cliente"),
        (AZUL, BRANCO, NUM["mediana_s"], "mediana por caso, com modelos reais. Sem falha de modelo no lote")])

    # 8. Segurança e limites
    s = clonar(prs, IND_CONTEUDO); titulo(s, "O que protege e o que ainda falta")
    tres_cartoes(s, [
        (AZUL, BRANCO, "Na dúvida, humano", "Confiança baixa, suspeita ou assunto sensível vão para uma pessoa. O cliente nunca é acusado"),
        (LIMA, AZUL, "Texto é dado", "Ordem escondida na mensagem é ignorada; CPF, cartão e telefone são mascarados antes de ir ao modelo"),
        (BRANCO, GRAFITE, "Limites", "Ações simuladas, abertura de chamado com 29% de precisão e 5 das 11 frentes do plano")])

    # 9. Impacto
    s = clonar(prs, IND_CONTEUDO); titulo(s, "O que muda no dia a dia")
    tres_cartoes(s, [
        (AZUL, BRANCO, "Diego", "Deixa de abrir 2 a 4 sistemas nos casos de rotina. Teto: 870 min nas 70 conversas resolvidas sozinhas"),
        (LIMA, AZUL, "Marina", "Recebe o dossiê com o custo de errar para cada lado, em vez de aprovar às cegas"),
        (AZUL, BRANCO, "O time", "Vê o problema da transportadora antes das reclamações: 45% dos pedidos no escopo abriram conversa, contra 22%")])

    # 10. Segunda-feira
    s = clonar(prs, IND_CONTEUDO); titulo(s, "Segunda-feira: três passos")
    tres_cartoes(s, [
        (AZUL, BRANCO, "1  Acessos", "Somente leitura em central, ERP, gateway e portais. E escolher onde a Marina aprova"),
        (LIMA, AZUL, "2  Calibrar", "~200 casos já decididos por supervisores para ajustar o chamado e o Detetive"),
        (AZUL, BRANCO, "3  Modo sombra", "Duas semanas: o GoColega decide, ninguém recebe, e medimos a concordância")])

    remover_slides(prs, n_marca)
    prs.save(saida)
    return len(prs.slides)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    saida = sys.argv[2] if len(sys.argv) > 2 else "docs/GoColega_slides.pptx"
    print(montar(sys.argv[1], saida), "slides em", saida)
