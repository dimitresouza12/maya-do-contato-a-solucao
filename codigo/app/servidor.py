"""Interface local da Maya (so para demonstrar): monitor de atendimento, canal do time e resultados.

Uso (da raiz):  python codigo/app/servidor.py [porta=8765]   ->   http://127.0.0.1:8765

- Aba Atendimento = MONITOR. As conversas da fila aberta "chegam" uma a uma (simulado) e o agente responde sozinho; a tela
  so acompanha e destaca quando uma PESSOA precisa assumir (com o motivo, o contexto e um rascunho de resposta).
- A pessoa pode assumir, responder e resolver pela tela (tudo simulado, vai para o log; nenhum canal real e usado).
- Servidor da biblioteca padrao. Um trava unica (LOCK) protege a conexao DuckDB, que nao e thread-safe: o agente e as consultas
  nunca rodam ao mesmo tempo. O estado do monitor fica em memoria, com outra trava, para a tela nunca esperar o agente.
- Escuta so em 127.0.0.1.
"""
import csv
import json
import os
import random
import re
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.abspath(os.path.join(AQUI, "..", ".."))
sys.path.insert(0, os.path.join(RAIZ, "codigo"))
from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(RAIZ, ".env"))
sys.stdout.reconfigure(encoding="utf-8")

from gocolega import agentes, colega, dados, modelos  # noqa: E402
from gocolega.ferramentas import mascarar_pii  # noqa: E402
from gocolega.orquestrador import PRAZO_HUMANO, tratar  # noqa: E402

PORTA = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
ROTULO = {"autonomo": "Resolvido pelo agente", "aguardando_cliente": "Aguardando resposta do cliente", "fora_da_politica": "Negado pela política, com a regra",
          "aguardando_supervisor": "Acima do limite: aprovação do supervisor", "aguardando_aprovacao": "Resposta pública: aguarda aprovação",
          "suspeita": "Sinalizado como suspeita", "sensivel": "Caso sensível (saúde)", "escalado": "Passou para uma pessoa"}
RESOLVIDAS, AGUARDA, PESSOA = {"autonomo", "fora_da_politica"}, {"aguardando_cliente"}, {"escalado", "aguardando_supervisor", "aguardando_aprovacao", "suspeita", "sensivel"}
INTERNAS = {"classificar_conversa", "responder_cliente", "rascunho_resposta_publica"}
MARCA_RASCUNHO = "[rascunho sugerido, revisar antes de enviar] "
MOTIVO = {"aguardando_supervisor": "O valor passa do limite do agente: o supervisor precisa aprovar.",
          "suspeita": "Reclamação sinalizada pelo Detetive de Procedência: o supervisor decide, o cliente recebeu resposta neutra.",
          "sensivel": "Possível reação adversa (saúde): registrar cosmetovigilância em até 24 h. O cliente já foi orientado a suspender o uso."}

LOCK = threading.RLock()        # DuckDB e o agente
ESTADO_LOCK = threading.Lock()  # estado do monitor (rapido)
MON = {"rodando": False, "intervalo": 4.0, "itens": [], "fila": [], "prox": 0, "ocupado": None, "gen": 0}


def _mensagens(cid: str) -> str:
    ms = dados.consulta("select texto from historico_mensagens where conversation_id = ? and autor = 'cliente' order by timestamp", [cid])
    return mascarar_pii(" / ".join(m["texto"] for m in ms))


def _limpo(txt: str) -> str:
    """So para EXIBIR: tira o '[assunto]' do inicio e os dados que a plataforma anexa ('Compra feita em..., produto: ...')."""
    txt = re.sub(r"^\s*\[[^\]]+\]\s*", "", txt)
    return re.split(r"\s*Compra feita em", txt)[0].strip()


def _preparar_fila():
    with LOCK:
        fila = dados.consulta("select conversation_id from fila_aberta order by conversation_id")
        ids = [f["conversation_id"] for f in fila if _mensagens(f["conversation_id"])]
    random.Random(7).shuffle(ids)  # mistura os canais: a fila ordenada comeca so com Reclame Aqui
    MON["fila"] = ids


# ---------------------------------------------------------------- monitor
def processar(cid: str) -> dict:
    """Roda o agente numa conversa da fila e monta o item do monitor. O agente responde SOZINHO; a pessoa so entra se preciso."""
    meta = dados.uma("select canal, marca, assunto from fila_aberta where conversation_id = ?", [cid]) or {}
    cliente = _limpo(_mensagens(cid))
    t0 = time.time()
    r, ferr = tratar(cid)
    envios = [e for e in ferr.log if e["ferramenta"] in ("responder_cliente", "rascunho_resposta_publica")]
    acoes = [{"ferramenta": e["ferramenta"], **{k: v for k, v in e.items() if k not in ("quando", "papel", "usuario", "ferramenta", "texto")}}
             for e in ferr.log if e["ferramenta"] not in INTERNAS]
    precisa = r.desfecho in PESSOA
    contexto, rascunho, area, urgencia, assunto = "", "", "", "normal", ""
    for e in ferr.log:
        if e["ferramenta"] == "acionar_pessoa" and "manipulacao" not in e.get("assunto", ""):
            area, urgencia, assunto = e.get("area", ""), e.get("urgencia", "normal"), e.get("assunto", "")
            ctx = e.get("contexto", "")
            if MARCA_RASCUNHO in ctx:
                ctx, rascunho = ctx.split(MARCA_RASCUNHO, 1)
            contexto = ctx.strip()
    # o contexto especifico (aprovacao, suspeita) vale mais que o aviso generico do Reclame Aqui ("o rascunho esta no log")
    for e in ferr.log:
        if e["ferramenta"] == "solicitar_aprovacao":
            contexto = f"{e.get('acao')} de R$ {float(e.get('valor') or 0):.2f} no pedido {e.get('order_id')}. {e.get('justificativa', '')}"
        elif e["ferramenta"] == "sinalizar_suspeita":
            contexto = f"Sinais: {', '.join(e.get('sinais', []))}. {e.get('evidencias', '')}"
    if r.desfecho == "sensivel":
        urgencia = "alta"
    prazo = "24 horas" if r.desfecho == "sensivel" else PRAZO_HUMANO.get(meta.get("canal"), "").replace("em ate ", "")
    return {
        "id": cid, "canal": meta.get("canal"), "marca": meta.get("marca"), "assunto": meta.get("assunto"), "cliente": cliente,
        "categoria": r.categoria, "desfecho": r.desfecho, "desfecho_rotulo": ROTULO.get(r.desfecho, r.desfecho),
        "mensagens": [{"texto": e["texto"], "publico": bool(e.get("publico"))} for e in envios],
        "acoes": acoes, "passos": r.passos, "agentes": r.conversa(), "segundos": round(time.time() - t0, 1),
        "tratado_em": time.strftime("%H:%M:%S"), "precisa_humano": precisa,
        "status": "fila_humana" if precisa else "agente",
        "motivo": (MOTIVO.get(r.desfecho) or (f"{assunto}." if assunto else "Uma pessoa precisa olhar este caso.")) if precisa else "",
        "contexto": contexto[:900], "rascunho": rascunho, "area": area, "urgencia": urgencia, "prazo": prazo if precisa else "",
        "humano": [], "avaliacao": None,
    }


def _worker():
    while True:
        time.sleep(0.4)
        with ESTADO_LOCK:
            if not MON["rodando"] or MON["prox"] >= len(MON["fila"]):
                continue
            cid, gen = MON["fila"][MON["prox"]], MON["gen"]
            MON["ocupado"] = cid
        try:
            with LOCK:
                item = processar(cid)
        except Exception as e:  # um caso que quebra aparece no monitor, nao derruba o servidor
            item = {"id": cid, "canal": "", "marca": "", "assunto": "", "cliente": "", "categoria": "erro", "desfecho": "erro",
                    "desfecho_rotulo": f"Erro: {type(e).__name__}: {str(e)[:120]}", "mensagens": [], "acoes": [], "passos": [], "agentes": [],
                    "segundos": 0, "tratado_em": time.strftime("%H:%M:%S"), "precisa_humano": True, "status": "fila_humana",
                    "motivo": "O agente falhou nesta conversa: uma pessoa precisa atender.", "contexto": "", "rascunho": "", "area": "",
                    "urgencia": "alta", "prazo": "", "humano": []}
        with ESTADO_LOCK:
            if MON["gen"] == gen:  # nao reinsere se a demonstracao foi reiniciada no meio
                MON["itens"].insert(0, item)
                MON["prox"] += 1
            MON["ocupado"] = None
            espera = MON["intervalo"]
        fim = time.time() + espera
        while time.time() < fim:
            time.sleep(0.3)
            with ESTADO_LOCK:
                if not MON["rodando"]:
                    break


def _resumo(it: dict) -> dict:
    ag = it["mensagens"][0]["texto"] if it["mensagens"] else ""
    return {k: it[k] for k in ("id", "canal", "marca", "categoria", "desfecho", "desfecho_rotulo", "status", "precisa_humano", "motivo",
                              "urgencia", "tratado_em", "segundos")} | {"cliente": it["cliente"][:150], "agente": ag[:150]}


def monitor() -> dict:
    with ESTADO_LOCK:
        itens = MON["itens"]
        n = len(itens)
        c = {"tratadas": n,
             "agente": sum(1 for i in itens if i["desfecho"] in RESOLVIDAS),
             "aguardando_cliente": sum(1 for i in itens if i["desfecho"] in AGUARDA),
             "fila_humana": sum(1 for i in itens if i["status"] == "fila_humana"),
             "com_humano": sum(1 for i in itens if i["status"] == "humano"),
             "resolvido_humano": sum(1 for i in itens if i["status"] == "resolvido"),
             "total": len(MON["fila"]), "ocupado": MON["ocupado"]}
        c["sem_humano"] = (c["agente"] + c["aguardando_cliente"]) / n if n else None
        return {"rodando": MON["rodando"], "intervalo": MON["intervalo"], "contadores": c, "itens": [_resumo(i) for i in itens]}


def controlar(corpo: dict) -> dict:
    acao = corpo.get("acao")
    with ESTADO_LOCK:
        if "intervalo" in corpo:
            MON["intervalo"] = max(0.0, min(30.0, float(corpo["intervalo"])))
        if acao == "iniciar":
            MON["rodando"] = True
        elif acao == "pausar":
            MON["rodando"] = False
        elif acao == "reiniciar":
            MON.update(rodando=False, itens=[], prox=0, gen=MON["gen"] + 1)
    return monitor()


def humano(corpo: dict) -> dict:
    """A pessoa assume, responde e resolve. Tudo simulado: fica registrado no item, nenhum canal real e usado."""
    with ESTADO_LOCK:
        it = next((i for i in MON["itens"] if i["id"] == corpo.get("id")), None)
        if not it:
            raise ValueError("conversa nao encontrada")
        acao, quando = corpo.get("acao"), time.strftime("%H:%M:%S")
        if acao == "assumir":
            it["status"] = "humano"
            it["humano"].append({"quem": "Atendente", "tipo": "evento", "texto": "assumiu o atendimento", "quando": quando})
        elif acao == "responder":
            texto = mascarar_pii(str(corpo.get("texto", "")).strip())[:1200]
            if not texto:
                raise ValueError("escreva a resposta")
            it["status"] = "humano" if it["status"] == "fila_humana" else it["status"]
            it["humano"].append({"quem": "Atendente", "tipo": "mensagem", "texto": texto, "quando": quando,
                                 "publico": it["canal"] == "reclame_aqui"})
        elif acao == "resolver":
            it["status"] = "resolvido"
            it["humano"].append({"quem": "Atendente", "tipo": "evento", "texto": "marcou como resolvido", "quando": quando})
        else:
            raise ValueError("acao desconhecida")
        return it


# ---------------------------------------------------------------- feedback
ARQ_FEEDBACK = os.path.join(RAIZ, "saida", "feedback.json")  # saida/ fica fora do git
MOTIVOS_RUINS = ["Resposta errada", "Tom ruim", "Poderia ter resolvido sozinha", "Não precisava de humano", "Faltou informação", "Outro"]
AVALIACOES: list[dict] = []
try:
    with open(ARQ_FEEDBACK, encoding="utf-8") as _f:
        AVALIACOES = json.load(_f)
except (OSError, ValueError):
    AVALIACOES = []


def avaliar(corpo: dict) -> dict:
    """O atendente avalia o que a Maya fez numa conversa. Guardado em memoria e em saida/feedback.json (fora do git)."""
    nota = corpo.get("nota")
    if nota not in ("bom", "ruim"):
        raise ValueError("nota deve ser 'bom' ou 'ruim'")
    with ESTADO_LOCK:
        it = next((i for i in MON["itens"] if i["id"] == corpo.get("id")), None)
        if not it:
            raise ValueError("conversa nao encontrada")
        av = {"id": it["id"], "categoria": it["categoria"], "desfecho": it["desfecho_rotulo"], "canal": it["canal"], "nota": nota,
              "motivo": str(corpo.get("motivo", ""))[:60] if nota == "ruim" else "", "comentario": mascarar_pii(str(corpo.get("comentario", "")))[:400],
              "quando": time.strftime("%H:%M:%S")}
        AVALIACOES[:] = [a for a in AVALIACOES if a["id"] != av["id"]] + [av]  # uma avaliacao por conversa (a ultima vale)
        it["avaliacao"] = {"nota": nota, "motivo": av["motivo"], "comentario": av["comentario"]}
        os.makedirs(os.path.dirname(ARQ_FEEDBACK), exist_ok=True)
        with open(ARQ_FEEDBACK, "w", encoding="utf-8") as f:
            json.dump(AVALIACOES, f, ensure_ascii=False, indent=1)
        return av


def feedback() -> dict:
    """Painel de feedback: desempenho desta sessao, o que a Maya faz bem, onde pode melhorar (com a evidencia de cada ponto) e as
    avaliacoes dos atendentes. Tudo calculado dos dados reais da sessao; os pontos fixos citam a fonte."""
    with ESTADO_LOCK:
        itens = list(MON["itens"])
        avs = list(AVALIACOES)
    n = len(itens)
    por = lambda f: [i for i in itens if f(i)]
    pessoa = por(lambda i: i["precisa_humano"])
    aguarda = por(lambda i: i["desfecho"] in AGUARDA)
    lacunas = por(lambda i: any("Lacuna na base" in p for p in i["passos"]))
    dois = por(lambda i: any("Segundo assunto" in p for p in i["passos"]))
    tempo = [i["segundos"] for i in itens if i["segundos"]]
    pc = lambda k: f"{round(100 * k / n)}%" if n else "–"
    ruins = [a for a in avs if a["nota"] == "ruim"]
    desempenho = {"conversas": n, "sem_humano": pc(len(itens) - len(pessoa)), "precisam_humano": len(pessoa), "aguardando_cliente": len(aguarda),
                  "tempo_medio": round(sum(tempo) / len(tempo), 1) if tempo else None,
                  "avaliacoes": len(avs), "aprovacao": f"{round(100 * (len(avs) - len(ruins)) / len(avs))}%" if avs else "–"}
    fortes = []
    if n:
        fortes.append(f"Atendeu {n} conversas respondendo sozinha em {desempenho['tempo_medio']} s em média, sem fila: {desempenho['sem_humano']} sem humano.")
        if pessoa:
            fortes.append(f"Chamou uma pessoa só em {len(pessoa)} casos ({pc(len(pessoa))}), todos por motivo sério: "
                          + "; ".join(sorted({i['desfecho_rotulo'] for i in pessoa})) + ".")
        if dois:
            fortes.append(f"Tratou {len(dois)} mensagens com dois assuntos na mesma conversa.")
    fortes += ["Não repete CPF, telefone nem cartão e ignora ordens escritas pelo cliente (testado).",
               "Não acusa o cliente: suspeita e saúde usam texto fixo e vão para uma pessoa.",
               "Cada resposta é conferida por um Verificador (números e promessas precisam de apoio nos fatos)."]
    mel = []
    if aguarda:
        cats = {}
        for i in aguarda:
            cats[i["categoria"]] = cats.get(i["categoria"], 0) + 1
        top = ", ".join(f"{k} ({v})" for k, v in sorted(cats.items(), key=lambda x: -x[1])[:3])
        mel.append({"prioridade": "alta", "titulo": "Continuar a conversa quando o cliente responde",
                    "evidencia": f"Em {len(aguarda)} das {n} conversas ({pc(len(aguarda))}) a Maya pediu algo ao cliente (foto, pedido, detalhe): {top}. "
                                 "Hoje a conversa é de uma mensagem por vez, então não sabemos quantas terminam resolvidas.",
                    "sugestao": "Ciclo de vários turnos: receber a réplica, retomar a ação pendente (reenvio depois da foto, por exemplo).", "esforco": "alto"})
    if lacunas:
        mel.append({"prioridade": "média", "titulo": "Completar a base de conhecimento",
                    "evidencia": f"{len(lacunas)} perguntas não tiveram resposta fundamentada na base (a Maya não inventa; pede o detalhe).",
                    "sugestao": "Incluir essas perguntas e respostas na ficha dos produtos ou nas políticas.", "esforco": "baixo"})
    if ruins:
        motivos = {}
        for a in ruins:
            motivos[a["motivo"] or "sem motivo"] = motivos.get(a["motivo"] or "sem motivo", 0) + 1
        mel.append({"prioridade": "alta", "titulo": "Corrigir o que os atendentes marcaram como ruim",
                    "evidencia": f"{len(ruins)} avaliações negativas de {len(avs)}: " + ", ".join(f"{k} ({v})" for k, v in motivos.items()) + ".",
                    "sugestao": "Abrir cada caso avaliado, achar a causa (política, tom, triagem) e transformar em teste.", "esforco": "médio"})
    mel += [
        {"prioridade": "média", "titulo": "Abrir chamado na transportadora com mais precisão",
         "evidencia": "Na validação contra 1.082 conversas de rastreio/atraso, a regra escrita acerta 29% dos chamados que a equipe abre (DIARIO, entrada 23).",
         "sugestao": "Calibrar o gatilho com a prática da equipe, em modo sombra.", "esforco": "médio"},
        {"prioridade": "média", "titulo": "Executar a troca de endereço",
         "evidencia": "Hoje a Maya pede o endereço completo e para: não lê a resposta nem altera o pedido.",
         "sugestao": "Extrair o endereço da réplica e chamar alterar_endereco antes da separação.", "esforco": "médio"},
        {"prioridade": "baixa", "titulo": "Provar o valor do acolhimento",
         "evidencia": "Na base, a abertura com empatia não elevou o CSAT (3,71 contra 3,84, com confusão); o que mais pesa é a velocidade: primeira resposta acima de 30 min cai para 3,07.",
         "sugestao": "Medir CSAT das respostas da Maya em modo sombra antes de afirmar ganho.", "esforco": "baixo"},
        {"prioridade": "média", "titulo": "Revisão humana das respostas em escala",
         "evidencia": "O texto da Maya passa por Verificador e filtros, mas só uma amostra pequena foi lida por uma pessoa.",
         "sugestao": "Usar esta aba: 👍/👎 com motivo em cada caso, e revisar semanalmente os 👎.", "esforco": "baixo"},
    ]
    return {"desempenho": desempenho, "fortes": fortes, "melhorias": mel, "avaliacoes": list(reversed(avs)), "motivos_ruins": MOTIVOS_RUINS}


# ---------------------------------------------------------------- outras abas
def estado() -> dict:
    metricas = None
    arq = os.path.join(RAIZ, "codigo", "benchmarks", "lote_resultados.csv")
    if os.path.exists(arq):
        with open(arq, encoding="utf-8") as f:
            linhas = [r for r in csv.DictReader(f) if r.get("desfecho") and r["desfecho"] != "ERRO"]
        n = len(linhas) or 1
        cont = {}
        for r in linhas:
            cont[r["desfecho"]] = cont.get(r["desfecho"], 0) + 1
        seg = [float(r["segundos"]) for r in linhas if r.get("segundos")]
        metricas = {"n": len(linhas), "desfechos": {ROTULO.get(k, k): v for k, v in sorted(cont.items(), key=lambda x: -x[1])},
                    "resolvidas": sum(v for k, v in cont.items() if k in RESOLVIDAS) / n,
                    "sem_humano": sum(v for k, v in cont.items() if k in RESOLVIDAS | AGUARDA) / n,
                    "pessoa": sum(v for k, v in cont.items() if k in PESSOA) / n,
                    "segundos_mediana": sorted(seg)[len(seg) // 2] if seg else None}
    return {"token": agentes.disponivel(), "modelos": {"triagem": modelos.PRINCIPAL, "redator": modelos.SUB},
            "colega": colega.EXEMPLOS, "motivos": MOTIVOS_RUINS, "metricas": metricas, "base": "amostra" if dados.usando_amostra() else "completa"}


def falar_com_colega(texto: str, area: str, autor: str) -> dict:
    t0 = time.time()
    with LOCK:
        r, ferr = colega.tratar_colega(f"COL-{int(t0) % 100000}", area, texto, autor=autor or "colega")
    return {"intencao": r.intencao, "desfecho": r.desfecho, "resposta": r.resposta, "passos": r.passos,
            "acoes": [{"ferramenta": e["ferramenta"], **{k: v for k, v in e.items() if k in ("aprovacao_id", "acao", "valor", "area", "assunto")}}
                      for e in ferr.log if e["ferramenta"] != "responder_colaborador"],
            "segundos": round(time.time() - t0, 1)}


class Handler(BaseHTTPRequestHandler):
    def _json(self, obj, status=200):
        corpo = json.dumps(obj, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(corpo)))
        self.end_headers()
        self.wfile.write(corpo)

    def do_HEAD(self):  # verificacao de saude (o painel de preview usa HEAD)
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()

    def do_GET(self):
        u = urlparse(self.path)
        if u.path == "/api/estado":
            with LOCK:
                return self._json(estado())
        if u.path == "/api/monitor":
            return self._json(monitor())
        if u.path == "/api/feedback":
            return self._json(feedback())
        if u.path == "/api/item":
            cid = parse_qs(u.query).get("id", [""])[0]
            with ESTADO_LOCK:
                it = next((i for i in MON["itens"] if i["id"] == cid), None)
                return self._json(it) if it else self._json({"erro": "nao encontrada"}, 404)
        if u.path in ("/", "/index.html"):
            corpo = open(os.path.join(AQUI, "index.html"), "rb").read()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(corpo)))
            self.end_headers()
            return self.wfile.write(corpo)
        self.send_error(404)

    def do_POST(self):
        try:
            n = int(self.headers.get("Content-Length") or 0)
            corpo = json.loads(self.rfile.read(n) or b"{}")
            if self.path == "/api/monitor/controle":
                return self._json(controlar(corpo))
            if self.path == "/api/humano":
                return self._json(humano(corpo))
            if self.path == "/api/avaliar":
                return self._json(avaliar(corpo))
            if self.path == "/api/colega":
                return self._json(falar_com_colega(str(corpo["texto"])[:600], str(corpo.get("area", "")), str(corpo.get("autor", ""))))
            self.send_error(404)
        except Exception as e:  # a tela mostra o erro, nao some
            self._json({"erro": f"{type(e).__name__}: {str(e)[:200]}"}, 500)

    def log_message(self, fmt, *args):
        if "/api/monitor" not in (args[0] if args else ""):  # o monitor consulta a cada 1,5 s: nao polui o log
            print("[app]", fmt % args, flush=True)


if __name__ == "__main__":
    _preparar_fila()
    threading.Thread(target=_worker, daemon=True).start()
    print(f"Maya (interface local): http://127.0.0.1:{PORTA}  | base {'amostra' if dados.usando_amostra() else 'completa'} | "
          f"token {'sim' if agentes.disponivel() else 'NAO (so regras)'} | fila de {len(MON['fila'])} conversas (monitor parado ate iniciar)", flush=True)
    ThreadingHTTPServer(("127.0.0.1", PORTA), Handler).serve_forever()
