"""Agentes que conversam: barramento de mensagens estruturadas, com atos de fala definidos e dialogo limitado.

Cada mensagem tem remetente, destinatario, ATO (propor, aprovar, contestar, consultar, revisar, corrigir...) e conteudo
estruturado. O agente que pergunta DECIDE o proximo passo pelo ato da resposta (ex.: se o Detetive CONTESTA, o
PosVenda sinaliza; se o Guardiao responde 'precisa_aprovacao', pede aprovacao). O barramento:
  - grava TODA a conversa (transcricao), marcando quem e codigo e quem e modelo de IA;
  - limita o numero de mensagens (nao ha laco infinito) e as rodadas de revisao do redator;
  - nao deixa nenhum agente agir por conta propria: dinheiro e politica continuam no Guardiao (codigo).

Honestidade: o dialogo e sincrono (pergunta e resposta), nao um enxame assincrono. O que ele entrega e controle de fluxo
dirigido por mensagens, auditavel e testavel (da para trocar um agente por um dublê e ver o fluxo mudar).
"""
import re
from dataclasses import dataclass, field

from . import agentes, detetive, fundamentacao, politica
from .ferramentas import mascarar_pii

LIMITE_MENSAGENS = 24
MAX_REVISOES = 2


class LimiteDeMensagens(Exception):
    pass


@dataclass
class Mensagem:
    de: str
    para: str
    ato: str
    conteudo: dict = field(default_factory=dict)


class Agente:
    nome = "?"
    tipo = "codigo"  # 'codigo' | 'modelo'

    def receber(self, msg: Mensagem, bus: "Barramento") -> Mensagem | None:  # pragma: no cover
        raise NotImplementedError

    def responder(self, msg: Mensagem, ato: str, **conteudo) -> Mensagem:
        return Mensagem(self.nome, msg.de, ato, conteudo)


class Barramento:
    def __init__(self, limite: int = LIMITE_MENSAGENS):
        self.agentes: dict[str, Agente] = {}
        self.transcricao: list[Mensagem] = []
        self.limite = limite

    def registrar(self, agente: Agente) -> Agente:
        self.agentes[agente.nome] = agente
        return agente

    def enviar(self, de: str, para: str, ato: str, **conteudo) -> Mensagem | None:
        if len(self.transcricao) >= self.limite:
            raise LimiteDeMensagens(f"mais de {self.limite} mensagens: dialogo interrompido")
        msg = Mensagem(de, para, ato, conteudo)
        self.transcricao.append(msg)
        destino = self.agentes.get(para)
        if destino is None:
            return None
        resp = destino.receber(msg, self)
        if resp is not None:
            self.transcricao.append(resp)
        return resp

    def linhas(self) -> list[str]:
        def resumo(c: dict) -> str:
            partes = []
            for k, v in c.items():
                s = ", ".join(map(str, v)) if isinstance(v, (list, tuple)) else str(v)
                partes.append(f"{k}={s[:70]}")
            return "; ".join(partes)[:200]

        def tag(nome: str) -> str:
            a = self.agentes.get(nome)
            return f"{nome}{'*' if a is not None and a.tipo == 'modelo' else ''}"

        return [f"[{tag(m.de)} -> {tag(m.para)}] {m.ato}: {resumo(m.conteudo)}" for m in self.transcricao]


# ---------------------------------------------------------------- agentes
class AgenteDetetive(Agente):
    nome, tipo = "Detetive", "modelo"  # os sinais sao codigo; o juiz da foto e um modelo (quando ha token)

    def __init__(self, cid: str, oid: str, usar_juiz: bool):
        self.cid, self.oid, self.usar_juiz, self.dossie = cid, oid, usar_juiz, None

    def receber(self, msg, bus):
        self.dossie = detetive.analisar(self.cid, self.oid, juiz=agentes.juiz_foto if self.usar_juiz else None)
        d = self.dossie
        base = dict(risco=f"{d.p_falsa:.0%}", sinais=[s.nome for s in d.sinais])
        return self.responder(msg, "contestar" if d.sinalizar else "aprovar", **base)


class AgenteGuardiao(Agente):
    """Policy Engine como agente: so codigo. Ninguem age sem passar por ele."""
    nome, tipo = "Guardiao", "codigo"

    def receber(self, msg, bus):
        c = msg.conteudo
        d = politica.avaliar_acao(c["acao"], c["categoria"], c["valor"], c.get("entrega"), c["agora"], c.get("tem_foto", False),
                                  c.get("trocas", 0), c.get("aprovacao_id"))
        return self.responder(msg, d.resultado, motivo=d.motivo, regra=d.regra)


class AgenteRedator(Agente):
    nome, tipo = "Redator", "modelo"

    def receber(self, msg, bus):
        c = msg.conteudo
        cliente = c.get("cliente", "")
        if msg.ato == "redigir":
            texto = agentes.redator_rascunho(c["situacao"], c["fatos"], cliente=cliente) if agentes.disponivel() else None
        else:  # corrigir: o Verificador devolveu problemas concretos
            texto = agentes.redator_rascunho(c["situacao"], c["fatos"], c["problemas"], c["texto"], cliente=cliente) if agentes.disponivel() else None
        return self.responder(msg, "rascunho", texto=texto or c["fallback"], origem="modelo" if texto else "texto fixo")


class AgenteVerificador(Agente):
    nome, tipo = "Verificador", "codigo"

    def receber(self, msg, bus):
        texto, fatos = msg.conteudo["texto"], msg.conteudo["fatos"]
        problemas = []
        if msg.conteudo.get("origem") == "modelo":  # texto fixo nao precisa de verificacao de fundamentacao
            problemas += fundamentacao.verificar(texto, fatos)
            if agentes.ACUSACAO.search(texto):
                problemas.append("o texto acusa ou insinua fraude do cliente, o que a politica proibe")
            if len(texto) > 600 or not texto.strip():
                problemas.append("o texto esta vazio ou longo demais")
            if mascarar_pii(texto) != texto:
                problemas.append("o texto contem CPF, cartao ou telefone")
        return self.responder(msg, "corrigir" if problemas else "aprovar", problemas=problemas)


def montar(cid: str | None = None, oid: str | None = None, usar_juiz: bool = False) -> Barramento:
    bus = Barramento()
    for ag in (AgenteGuardiao(), AgenteRedator(), AgenteVerificador()):
        bus.registrar(ag)
    if cid:
        bus.registrar(AgenteDetetive(cid, oid, usar_juiz))
    return bus


def redigir(bus: Barramento, situacao: str, fatos: str, fallback: str, cliente: str = "") -> str:
    """Conversa Redator <-> Verificador: rascunho, critica concreta, revisao (ate MAX_REVISOES), senao texto fixo.
    `cliente` e a mensagem do cliente, usada so para dar tom (acolhimento)."""
    # O conteudo vai INTEIRO ao agente; o recorte para leitura acontece so em Barramento.linhas().
    m = bus.enviar("Orquestrador", "Redator", "redigir", situacao=situacao, fatos=fatos, fallback=fallback, cliente=cliente)
    texto, origem = m.conteudo["texto"], m.conteudo["origem"]
    for rodada in range(MAX_REVISOES + 1):
        v = bus.enviar("Redator", "Verificador", "revisar", texto=texto, fatos=fatos, origem=origem)
        if v.ato == "aprovar":
            return texto
        if rodada == MAX_REVISOES:
            bus.transcricao.append(Mensagem("Verificador", "Orquestrador", "usar_texto_fixo", {"motivo": "revisoes esgotadas"}))
            return fallback
        m = bus.enviar("Verificador", "Redator", "corrigir", situacao=situacao, fatos=fatos, texto=texto,
                       problemas=v.conteudo["problemas"], fallback=fallback, cliente=cliente)
        texto, origem = m.conteudo["texto"], m.conteudo["origem"]
    return fallback
