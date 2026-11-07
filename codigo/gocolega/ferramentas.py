"""Ferramentas simuladas (mock) com os MESMOS nomes de ferramentas.csv.

- Permissao por papel vem de ferramentas.csv (atendente / analista / supervisor).
- Leituras consultam os CSVs. Acoes NAO alteram os CSVs: ficam num log de auditoria.
- responder_cliente aplica filtro de PII (CPF, cartao, telefone).
"""
import json
import re
from datetime import datetime

from . import dados

PII = [
    (re.compile(r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b"), "[CPF omitido]"),
    (re.compile(r"\b(?:\d[ -]?){13,16}\b"), "[cartao omitido]"),
    (re.compile(r"\(?\b\d{2}\)?\s?9?\d{4}[-\s]?\d{4}\b"), "[telefone omitido]"),
]


def mascarar_pii(texto: str) -> str:
    for rx, sub in PII:
        texto = rx.sub(sub, texto)
    return texto


class SemPermissao(Exception):
    pass


class Ferramentas:
    def __init__(self, papel: str, usuario: str, agora: datetime | None = None):
        self.papel, self.usuario, self.agora = papel, usuario, agora or datetime.now()
        self.log: list[dict] = []
        self._perm = {
            r["ferramenta"]: {p.strip() for p in str(r["papeis_permitidos"]).split(";")}
            for r in dados.consulta("select ferramenta, papeis_permitidos from ferramentas")
        }

    # --- infraestrutura ---
    def _exige(self, nome: str):
        if self.papel not in self._perm.get(nome, set()):
            raise SemPermissao(f"O papel '{self.papel}' nao pode usar '{nome}'")

    def _registra(self, nome: str, **kw):
        ev = {"quando": self.agora.isoformat(timespec="seconds"), "papel": self.papel,
              "usuario": self.usuario, "ferramenta": nome, **kw}
        self.log.append(ev)
        return ev

    # --- leitura ---
    def ler_conversa(self, conversation_id: str) -> dict:
        self._exige("ler_conversa")
        # Duas buscas em vez de UNION: com a fila vazia o DuckDB promove as colunas a texto e a data vira str.
        conv = dados.uma("select * from historico_conversas where conversation_id = ?", [conversation_id])
        if conv is None:
            conv = dados.uma(
                "select conversation_id, customer_id, order_id, marca, canal, data_abertura, "
                "null as tag_agente, status, n_interacoes, atendente_id, data_primeira_resposta, "
                "null as data_encerramento, assunto, null as csat "
                "from fila_aberta where conversation_id = ?", [conversation_id])
        msgs = dados.consulta(
            "select autor, timestamp, texto from historico_mensagens where conversation_id = ? order by timestamp",
            [conversation_id])
        return {"conversa": conv, "mensagens": msgs}

    def consultar_pedido(self, order_id: str) -> dict | None:
        self._exige("consultar_pedido")
        return dados.uma("select * from pedidos where order_id = ?", [order_id])

    def consultar_cliente(self, customer_id: str) -> dict | None:
        self._exige("consultar_cliente")
        c = dados.uma("select customer_id, n_pedidos, receita_acumulada, n_trocas_12m, n_contatos_12m "
                      "from clientes where customer_id = ?", [customer_id])
        return c

    def ver_anexos(self, conversation_id: str | None = None, order_id: str | None = None) -> list[dict]:
        self._exige("ver_anexos")
        if conversation_id:
            return dados.consulta("select * from anexos_conversas where conversation_id = ?", [conversation_id])
        return dados.consulta("select * from anexos_conversas where order_id = ?", [order_id])

    def trocas_do_pedido(self, order_id: str) -> int:
        self._exige("consultar_pedido")
        r = dados.uma("select count(*) n from trocas_reenvios where order_id_original = ? and tipo = 'troca'", [order_id])
        return int(r["n"]) if r else 0

    # --- acao ---
    def classificar_conversa(self, conversation_id: str, categoria: str):
        self._exige("classificar_conversa")
        return self._registra("classificar_conversa", conversation_id=conversation_id, categoria=categoria)

    def solicitar_foto(self, conversation_id: str, do_que: str = "produto"):
        self._exige("solicitar_foto")
        return self._registra("solicitar_foto", conversation_id=conversation_id, do_que=do_que)

    def responder_cliente(self, conversation_id: str, texto: str):
        self._exige("responder_cliente")
        return self._registra("responder_cliente", conversation_id=conversation_id, texto=mascarar_pii(texto))

    def reenviar_produto(self, order_id: str, valor: float, motivo: str, aprovacao_id: str | None = None):
        self._exige("reenviar_produto")
        return self._registra("reenviar_produto", order_id=order_id, valor=valor, motivo=motivo, aprovacao_id=aprovacao_id)

    def reembolsar(self, order_id: str, valor: float, motivo: str, aprovacao_id: str | None = None):
        self._exige("reembolsar")
        return self._registra("reembolsar", order_id=order_id, valor=valor, motivo=motivo, aprovacao_id=aprovacao_id)

    def reimprimir_personalizacao(self, order_id: str, valor: float, aprovacao_id: str | None = None):
        self._exige("reimprimir_personalizacao")
        return self._registra("reimprimir_personalizacao", order_id=order_id, valor=valor, aprovacao_id=aprovacao_id)

    def sinalizar_suspeita(self, conversation_id: str, evidencias: str, sinais: list[str]):
        self._exige("sinalizar_suspeita")
        return self._registra("sinalizar_suspeita", conversation_id=conversation_id,
                              sinais=sinais, evidencias=evidencias, efeito="reenvio/troca/reembolso suspensos ate decisao")

    def solicitar_aprovacao(self, acao: str, order_id: str, valor: float, justificativa: str) -> str:
        self._exige("solicitar_aprovacao")
        aprovacao_id = f"APR-{len([e for e in self.log if e['ferramenta'] == 'solicitar_aprovacao']) + 1:03d}"
        self._registra("solicitar_aprovacao", aprovacao_id=aprovacao_id, acao=acao, order_id=order_id,
                       valor=valor, justificativa=justificativa)
        return aprovacao_id

    def acionar_pessoa(self, area: str, assunto: str, contexto: str, urgencia: str = "normal"):
        self._exige("acionar_pessoa")
        return self._registra("acionar_pessoa", area=area, assunto=assunto, contexto=contexto, urgencia=urgencia)

    def encerrar_conversa(self, conversation_id: str, motivo: str = ""):
        self._exige("encerrar_conversa")
        return self._registra("encerrar_conversa", conversation_id=conversation_id, motivo=motivo)

    def abrir_chamado_transportadora(self, order_id: str, motivo: str):
        self._exige("abrir_chamado_transportadora")
        return self._registra("abrir_chamado_transportadora", order_id=order_id, motivo=motivo)

    # --- supervisor ---
    def decidir_suspeita(self, conversation_id: str, decisao: str, justificativa: str, sinalizado_por: str):
        self._exige("decidir_suspeita")
        if sinalizado_por == self.usuario:
            raise SemPermissao("Quem sinalizou nao decide o que ele mesmo sinalizou")
        return self._registra("decidir_suspeita", conversation_id=conversation_id, decisao=decisao, justificativa=justificativa)

    def salvar_log(self, caminho: str):
        with open(caminho, "w", encoding="utf-8") as f:
            for e in self.log:
                f.write(json.dumps(e, ensure_ascii=False, default=str) + "\n")
