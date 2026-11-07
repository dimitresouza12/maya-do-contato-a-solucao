"""Ferramentas simuladas (mock) com os MESMOS nomes de ferramentas.csv.

- Permissao por papel vem de ferramentas.csv (atendente / analista / supervisor).
- Leituras consultam os CSVs. Acoes NAO alteram os CSVs: ficam num log de auditoria.
- responder_cliente aplica filtro de PII (CPF, cartao, telefone).
"""
import json
import re
from datetime import datetime

from . import dados, tom

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
        self.canal: str | None = None  # canal da conversa em tratamento (o orquestrador preenche)
        self.cliente: str | None = None  # mensagem do cliente, so para o tom da resposta
        self.categoria_conversa: str | None = None
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
        # So trocas ANTERIORES ao momento da conversa: a troca que o atendente fez NESTA conversa e registrada na base
        # e, sem este filtro, o agente a veria como "ja feita" e negaria a troca (vazamento do futuro, DIARIO 34).
        r = dados.uma("select count(*) n from trocas_reenvios where order_id_original = ? and tipo = 'troca' "
                      "and data_solicitacao < ?", [order_id, self.agora])
        return int(r["n"]) if r else 0

    # --- acao ---
    def classificar_conversa(self, conversation_id: str, categoria: str):
        self._exige("classificar_conversa")
        return self._registra("classificar_conversa", conversation_id=conversation_id, categoria=categoria)

    def solicitar_foto(self, conversation_id: str, do_que: str = "produto"):
        self._exige("solicitar_foto")
        return self._registra("solicitar_foto", conversation_id=conversation_id, do_que=do_que)

    def responder_cliente(self, conversation_id: str, texto: str):
        """Envia a resposta (simulado). No Reclame Aqui ela e PUBLICA e sai sem aprovacao previa (decisao do projeto, DIARIO 33);
        por isso o registro leva publico=True e o texto passa pelos mesmos filtros (PII mascarada, Verificador, sem acusacao)."""
        self._exige("responder_cliente")
        texto = mascarar_pii(texto).replace("**", "")  # WhatsApp e e-mail nao renderizam negrito em markdown
        # Acolhimento: retribui o cumprimento, usa o primeiro nome e reconhece o sentimento, se o texto ainda nao fizer isso.
        texto = tom.acolher(self.cliente, texto, self.categoria_conversa, self.canal)
        extra = {"publico": True} if self.canal == "reclame_aqui" else {}
        return self._registra("responder_cliente", conversation_id=conversation_id, texto=texto, **extra)

    def responder_colaborador(self, pedido_id: str, resposta: str):
        """Canal do time (Slack, simulado): a resposta vai para o log, como as demais acoes. PII mascarada."""
        self._exige("responder_colaborador")
        return self._registra("responder_colaborador", pedido_id=pedido_id, resposta=mascarar_pii(resposta))

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

    # --- rotas do dia a dia (cancelamento, troca, financeiro, cupom) ---
    def cancelar_pedido(self, order_id: str, motivo: str = ""):
        """So antes da separacao (a regra e conferida por quem chama): estorno integral automatico."""
        self._exige("cancelar_pedido")
        return self._registra("cancelar_pedido", order_id=order_id, motivo=motivo, efeito="estorno integral automatico")

    def trocar_produto(self, order_id: str, sku_novo: str, valor: float, aprovacao_id: str | None = None):
        self._exige("trocar_produto")
        return self._registra("trocar_produto", order_id=order_id, sku_novo=sku_novo, valor=valor, aprovacao_id=aprovacao_id)

    def agradecer(self, conversation_id: str):
        self._exige("agradecer")
        return self._registra("agradecer", conversation_id=conversation_id)

    def negar_por_politica(self, conversation_id: str, regra: str):
        self._exige("negar_por_politica")
        return self._registra("negar_por_politica", conversation_id=conversation_id, regra=regra)

    def verificar_pagamento(self, order_id: str, ate: datetime | None = None) -> list[dict]:
        """Transacoes do pedido no gateway ate o momento `ate` (sem enxergar o futuro)."""
        self._exige("verificar_pagamento")
        ate = ate or self.agora
        return dados.consulta(
            "select transacao_id, metodo, status, valor, valor_estornado, data_hora_criacao from pagamentos_gateway "
            "where order_id = ? and data_hora_criacao <= ? order by data_hora_criacao", [order_id, ate])

    def validar_cupom(self, codigo: str) -> dict | None:
        self._exige("validar_cupom")
        return dados.uma("select * from cupons where upper(codigo) = upper(?)", [codigo])

    # --- analista ---
    def abrir_incidente(self, tipo: str, escopo: dict, evidencias: str):
        self._exige("abrir_incidente")
        return self._registra("abrir_incidente", tipo=tipo, escopo=escopo, evidencias=evidencias)

    def notificar_clientes(self, order_ids: list[str], tipo_aviso: str, texto: str):
        """Aviso proativo. Teto de 300 clientes por dia (parametros.md), somando as chamadas do dia."""
        self._exige("notificar_clientes")
        dia = self.agora.date().isoformat()
        ja = sum(len(e["order_ids"]) for e in self.log
                 if e["ferramenta"] == "notificar_clientes" and e["quando"][:10] == dia)
        if ja + len(order_ids) > 300:
            raise SemPermissao(f"Teto de 300 notificacoes por dia: ja enviadas {ja}, pedido de {len(order_ids)}")
        return self._registra("notificar_clientes", order_ids=list(order_ids), tipo_aviso=tipo_aviso,
                              texto=mascarar_pii(texto))

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
