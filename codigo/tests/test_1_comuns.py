"""SITUACOES COMUNS: o dia a dia da central. O GoColega precisa acertar sem esforco."""
from datetime import date, datetime

import pytest

from gocolega import llm, politica
from gocolega.ferramentas import Ferramentas, SemPermissao, mascarar_pii
from gocolega.orquestrador import _rastreio, tratar

pytestmark = pytest.mark.comum
AGORA = datetime(2026, 8, 10, 10, 0)


def test_reenvio_dentro_da_alcada_e_do_prazo():
    d = politica.avaliar_acao("reenviar_produto", "avaria_vazamento", 150, date(2026, 8, 8), AGORA, tem_foto=True)
    assert d.permitido


def test_acima_da_alcada_precisa_de_aprovacao():
    d = politica.avaliar_acao("reenviar_produto", "avaria_vazamento", 250, date(2026, 8, 8), AGORA, tem_foto=True)
    assert d.resultado == "precisa_aprovacao"


def test_com_aprovacao_o_valor_alto_passa():
    d = politica.avaliar_acao("reenviar_produto", "avaria_vazamento", 250, date(2026, 8, 8), AGORA, True, aprovacao_id="APR-001")
    assert d.permitido


def test_sem_foto_nao_reenvia():
    d = politica.avaliar_acao("reenviar_produto", "avaria_vazamento", 100, date(2026, 8, 8), AGORA, tem_foto=False)
    assert d.resultado == "negado"


@pytest.mark.parametrize("texto,categoria", [
    ("Meu pedido chegou quebrado, quero o reenvio", "Avaria"),
    ("O produto veio com um rasgo no tecido", "Avaria"),
    ("Onde esta meu pedido? O rastreio nao anda", "Rastreio"),
    ("Meu pedido esta atrasado, o prazo era dia 20", "Atraso"),
    ("Quero cancelar a compra, me arrependi", "Cancelamento"),
    ("O brinde nao veio no pedido", "Produto faltando"),
    ("O cupom nao funcionou", "Promocao"),
    ("Posso trocar o numero da casa no endereco?", "Endereco"),
])
def test_triagem_reconhece_assuntos_comuns(texto, categoria):
    assert llm._triagem_regras(texto)["categoria"] == categoria


def test_caso_legitimo_e_resolvido_sozinho():
    """AT105180: serum amassado, foto tirada depois da entrega, R$ 112,80, sem historico."""
    r, ferr = tratar("AT105180")
    assert r.desfecho == "autonomo"
    assert [e["ferramenta"] for e in ferr.log if e["ferramenta"] == "reenviar_produto"]


def test_sem_foto_o_tato_pede_a_foto(monkeypatch):
    """Sem anexo, a politica exige foto: o GoColega pede ao cliente e espera."""
    from gocolega import dados
    f = Ferramentas("atendente", "gocolega", AGORA)
    monkeypatch.setattr(f, "ver_anexos", lambda **kw: [])
    # usa pedido real recem-entregue para nao cair no prazo
    pedido = dados.uma("select * from pedidos where status_entrega='entregue' limit 1")
    from gocolega.orquestrador import Resultado, _pos_venda
    r = Resultado("AT_TESTE")
    conv = {"conversation_id": "AT_TESTE"}
    agora = datetime.combine(pedido["data_entrega"], datetime.min.time())
    r, f = _pos_venda(r, f, conv, pedido, "avaria_vazamento", agora)
    assert r.desfecho == "aguardando_cliente"
    assert any(e["ferramenta"] == "solicitar_foto" for e in f.log)


def test_pedido_entregue_e_informado_ao_cliente():
    f = Ferramentas("atendente", "gocolega", AGORA)
    pedido = {"order_id": "GCH1", "status_entrega": "entregue", "data_entrega": date(2026, 8, 5),
              "transportadora": "ViaLog", "data_prometida": date(2026, 8, 6)}
    from gocolega.orquestrador import Resultado
    r, f = _rastreio(Resultado("AT1"), f, pedido)
    assert r.desfecho == "autonomo"
    assert any(e["ferramenta"] == "responder_cliente" for e in f.log)


def _ev(status, quando, local="CD", previsao=date(2026, 8, 12)):
    return {"status": status, "data_hora_evento": quando, "local": local, "previsao_entrega": previsao}


def _pedido(**kw):
    base = {"order_id": "GCH2", "valor": 120.0, "transportadora": "Expressa Já", "status_entrega": "em_transito",
            "data_prometida": date(2026, 8, 12), "codigo_rastreio": "X1", "data_entrega": None}
    base.update(kw)
    return base


def test_pedido_extraviado_aciona_logistica_e_oferece_opcoes(monkeypatch):
    from gocolega import rastreio
    from gocolega.orquestrador import Resultado
    f = Ferramentas("atendente", "gocolega", AGORA)
    sit = rastreio.situacao(_pedido(), AGORA, eventos=[_ev("coletado", datetime(2026, 8, 5, 9)),
                                                       _ev("extraviado", datetime(2026, 8, 9, 9))], chamado=None)
    monkeypatch.setattr(rastreio, "situacao", lambda p, a: sit)
    r, f = _rastreio(Resultado("AT2"), f, _pedido())
    nomes = [e["ferramenta"] for e in f.log]
    assert "acionar_pessoa" in nomes and "abrir_chamado_transportadora" not in nomes
    assert r.desfecho == "aguardando_cliente"  # oferece reenvio ou reembolso, a escolha do cliente


def test_dias_uteis_pulam_fim_de_semana_e_feriado():
    from gocolega import rastreio
    # sexta 04/09/2026 -> terca 08/09/2026: seg 07/09 e feriado, sobra so a terca
    assert rastreio.dias_uteis_entre(date(2026, 9, 4), date(2026, 9, 8)) == 1
    assert rastreio.dias_uteis_entre(date(2026, 8, 7), date(2026, 8, 10)) == 1  # sexta -> segunda
    assert rastreio.dias_uteis_entre(date(2026, 8, 10), date(2026, 8, 10)) == 0


def test_em_transito_dentro_do_prazo_so_informa_sem_abrir_chamado():
    from gocolega import rastreio
    ag = datetime(2026, 8, 10, 10)
    sit = rastreio.situacao(_pedido(), ag, eventos=[_ev("em_transferencia", datetime(2026, 8, 10, 8))], chamado=None)
    plano = rastreio.decidir(sit, _pedido())
    assert plano.tipo == "informar_no_prazo" and not plano.abrir_chamado and not plano.oferecer_opcoes


def _jev_falso(p_sens, p_inj):
    return lambda texto: {"categoria": "Avaria", "confianca": 0.9, "p_sensivel": p_sens,
                          "p_injecao": p_inj, "fonte": "jev-teste"}


def test_jev_inseguro_nao_gera_alarme_falso(monkeypatch):
    """Achado com o LLM real: probabilidade de 0,6 nao pode virar 'sensivel' nem 'injecao'."""
    monkeypatch.setenv("AI_PROXY_API_KEY", "gw-tok-teste")
    monkeypatch.setattr(llm, "_triagem_jev", _jev_falso(0.60, 0.60))
    r = llm.triagem("O serum chegou amassado e vazando")
    assert not r["sensivel"] and not r["injecao"]


def test_jev_muito_seguro_gera_alarme(monkeypatch):
    monkeypatch.setenv("AI_PROXY_API_KEY", "gw-tok-teste")
    monkeypatch.setattr(llm, "_triagem_jev", _jev_falso(0.95, 0.95))
    r = llm.triagem("texto neutro")
    assert r["sensivel"] and r["injecao"]


def test_modelos_padrao_sao_terra_e_luna():
    from gocolega import modelos
    assert modelos.PRINCIPAL == "gpt-5.6-terra" and modelos.SUB == "gpt-5.6-luna"


def test_redator_usa_o_texto_do_modelo_quando_valido(monkeypatch):
    from gocolega import agentes
    monkeypatch.setattr(llm, "chat", lambda *a, **k: "Sentimos muito pelo transtorno. Vamos reenviar seu pedido sem custo.")
    t = agentes.redator("reenvio aprovado", "reenvio sem custo", "TEXTO FIXO")
    assert t.startswith("Sentimos muito") and t != "TEXTO FIXO"


def test_orquestrador_aceita_rota_valida_do_modelo(monkeypatch):
    from gocolega import agentes
    monkeypatch.setattr(llm, "chat", lambda *a, **k: '{"rota":"rastreio","categoria_politica":"nenhuma","motivo":"pergunta onde esta"}')
    r = agentes.rotear("onde esta?", {"categoria": "Outros", "confianca": 0.4}, {"marca": "Gocase", "status_entrega": "em_transito"})
    assert r["rota"] == "rastreio"


def test_confianca_alta_nao_pede_segunda_opiniao(cenario):
    chamadas = cenario(0.95, "Avaria", '{"categoria":"Rastreio"}')
    r, _ = tratar("AT105180")
    assert chamadas["segunda"] == 0 and r.desfecho == "autonomo"


def test_confianca_baixa_com_consenso_segue_normalmente(cenario):
    chamadas = cenario(0.43, "Avaria", '{"categoria":"Avaria"}')
    r, ferr = tratar("AT105180")
    assert chamadas["segunda"] == 1 and r.desfecho == "autonomo"
    assert any("segunda opiniao" in p.lower() for p in r.passos)


def test_a_conversa_entre_os_agentes_fica_gravada():
    """Pos-venda legitimo: o PosVenda propoe ao Detetive, que aprova, e consulta o Guardiao, que permite."""
    r, _ = tratar("AT105180")
    linhas = "\n".join(r.conversa())
    assert "[PosVenda -> Detetive*] propor" in linhas and "[Detetive* -> PosVenda] aprovar" in linhas
    assert "[PosVenda -> Guardiao] consultar" in linhas and "[Guardiao -> PosVenda] permitido" in linhas


def test_busca_normaliza_acento_e_plural():
    from gocolega import conhecimento
    assert "serum" in conhecimento.tokens("Sérum") and "hidratante" in conhecimento.tokens("Hidratantes")


def test_rag_encontra_a_ficha_certa_do_produto():
    from gocolega import conhecimento
    r = conhecimento.base().buscar("validade do serum de niacinamida depois de aberto", "produto", k=1)
    assert r and r[0].passagem.id == "produto:KSH-5002" and r[0].cobertura >= 0.5


def test_duvida_responde_com_a_linha_da_ficha_e_cita_a_fonte():
    from gocolega import duvida
    resp, _ = duvida.responder("Qual a validade do serum de niacinamida depois de aberto?", usar_llm=False)
    assert resp is not None and resp.origem == "extrativa"
    assert "Validade apos aberto" in resp.texto and resp.fontes == ["produto:KSH-5002"]


def test_duvida_de_produto_e_respondida_pelo_fluxo_completo():
    r, ferr = tratar("AT105180", texto_override="Qual a validade do serum de niacinamida depois de aberto?")
    assert r.desfecho == "autonomo"
    resposta = next(e["texto"] for e in ferr.log if e["ferramenta"] == "responder_cliente")
    assert "Fonte: produto:" in resposta


def test_pii_comum_e_mascarada():
    t = mascarar_pii("CPF 123.456.789-09, cartao 4111 1111 1111 1111, tel (85) 99999-8888")
    assert "123.456.789" not in t and "4111" not in t and "99999-8888" not in t


def test_atendente_nao_usa_ferramenta_de_supervisor():
    with pytest.raises(SemPermissao):
        Ferramentas("atendente", "gocolega", AGORA).decidir_suspeita("AT1", "improcedente", "x", "outro")
