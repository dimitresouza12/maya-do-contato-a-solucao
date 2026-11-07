"""Os testes rodam OFFLINE e deterministicos: nunca usam o token do proxy nem a rede."""
import pytest


@pytest.fixture(autouse=True)
def sem_rede_nem_token(monkeypatch):
    monkeypatch.delenv("AI_PROXY_API_KEY", raising=False)
    # Os testes da cascata e do Jev simulam o Jev como triador; os do triador por modelo ligam "modelo" por conta propria.
    from gocolega import llm
    monkeypatch.setattr(llm, "TRIADOR", "jev")


@pytest.fixture
def rastrear(monkeypatch):
    """Roda o tratamento de rastreio com eventos e chamado INJETADOS (sem depender da base).
    uso: r, ferr = rastrear(eventos, agora, chamado=None, texto='', valor=120.0)   |   rastrear.ev(status, datetime)"""
    from datetime import date

    from gocolega import rastreio
    from gocolega.ferramentas import Ferramentas
    from gocolega.orquestrador import Resultado, _rastreio

    def executar(eventos, agora, chamado=None, texto="", **pedido_kw):
        pedido = {"order_id": "GCH9", "valor": 120.0, "transportadora": "Expressa Já", "status_entrega": "em_transito",
                  "data_prometida": date(2026, 8, 12), "codigo_rastreio": "X9", "data_entrega": None}
        pedido.update(pedido_kw)
        sit = rastreio.situacao(pedido, agora, eventos=eventos, chamado=chamado)
        monkeypatch.setattr(rastreio, "situacao", lambda p, a: sit)
        ferr = Ferramentas("atendente", "gocolega", agora)
        return _rastreio(Resultado("ATX"), ferr, pedido, texto)

    executar.ev = lambda status, quando, previsao=date(2026, 8, 12): {
        "status": status, "data_hora_evento": quando, "local": "unidade", "previsao_entrega": previsao}
    return executar


@pytest.fixture
def base_completa():
    """Alguns testes medem a base inteira. Sem ela (so a amostra do repositorio), eles sao pulados."""
    from gocolega import dados
    if dados.usando_amostra():
        pytest.skip("precisa da base completa em dados/atendimento/ (ver dados/LEIAME.md)")


@pytest.fixture
def cenario(monkeypatch):
    """Simula o Jev (categoria e confianca) e o modelo principal (resposta da segunda opiniao), sem rede.
    Devolve um contador de quantas vezes a segunda opiniao foi pedida."""
    from gocolega import llm

    def montar(conf, cat_jev, resposta_segunda, p_sens=0.0, p_inj=0.0):
        monkeypatch.setenv("AI_PROXY_API_KEY", "gw-tok-teste")
        monkeypatch.setattr(llm, "_triagem_jev", lambda t: {
            "categoria": cat_jev, "confianca": conf, "p_sensivel": p_sens, "p_injecao": p_inj, "fonte": "jev-teste"})
        chamadas = {"segunda": 0}

        def chat(modelo, sistema, usuario, **k):
            if "Classifique a mensagem" in sistema:
                chamadas["segunda"] += 1
                if isinstance(resposta_segunda, Exception):
                    raise resposta_segunda
                return resposta_segunda
            return "Texto de teste."

        monkeypatch.setattr(llm, "chat", chat)
        return chamadas
    return montar
