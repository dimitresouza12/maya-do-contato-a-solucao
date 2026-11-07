"""Interface local do GoColega (so para demonstrar): monitor de atendimento, canal do time e resultados.

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
          "aguardando_supervisor": "Acima da alçada: aprovação do supervisor", "aguardando_aprovacao": "Resposta pública: aguarda aprovação",
          "suspeita": "Sinalizado como suspeita", "sensivel": "Caso sensível (saúde)", "escalado": "Passou para uma pessoa"}
RESOLVIDAS, AGUARDA, PESSOA = {"autonomo", "fora_da_politica"}, {"aguardando_cliente"}, {"escalado", "aguardando_supervisor", "aguardando_aprovacao", "suspeita", "sensivel"}
INTERNAS = {"classificar_conversa", "responder_cliente", "rascunho_resposta_publica"}
MARCA_RASCUNHO = "[rascunho sugerido, revisar antes de enviar] "
MOTIVO = {"aguardando_supervisor": "O valor passa da alçada do agente: o supervisor precisa aprovar.",
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
        "humano": [],
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
            "colega": colega.EXEMPLOS, "metricas": metricas, "base": "amostra" if dados.usando_amostra() else "completa"}


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
    print(f"GoColega (interface local): http://127.0.0.1:{PORTA}  | base {'amostra' if dados.usando_amostra() else 'completa'} | "
          f"token {'sim' if agentes.disponivel() else 'NAO (so regras)'} | fila de {len(MON['fila'])} conversas (monitor parado ate iniciar)", flush=True)
    ThreadingHTTPServer(("127.0.0.1", PORTA), Handler).serve_forever()
