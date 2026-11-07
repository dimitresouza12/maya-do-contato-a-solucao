# Maya · Do Contato à Solução

**Agente de IA para o atendimento da Gocase e da GoBeauté: responde sozinho o que a política permite, confere se a reclamação procede antes de agir e só chama uma pessoa em caso sério.**

*(Maya é o nome do agente; só o pacote Python por dentro mantém o nome interno `gocolega`.)*

GoHacks Talent 2026, Desafio 1. Feito por uma pessoa em um dia, com as bases fictícias do evento. Projeto de hackathon, não um produto do Gogroup.

## Como funciona
```
Mensagem → triagem (gpt-5.6-terra; reserva Jev e regras) → rota
   ├─ avaria / produto faltando → Detetive (confere foto e histórico) → Policy Engine (código) → reenvia | pede aprovação | sinaliza suspeita
   ├─ rastreio / atraso · cancelamento · endereço · financeiro · troca · cupom · elogio → regras da política
   ├─ dúvida de produto → busca na ficha (BM25), responde só com fonte citada
   ├─ pedido de colega no canal do time (Slack simulado) → consulta agregada, nunca dado pessoal
   └─ saúde · suspeita de fraude · valor acima do limite → PESSOA, com contexto e rascunho
Toda resposta passa por um Verificador (números e promessas precisam de apoio nos fatos).
```
- **O modelo propõe, o código decide.** Limite, prazo, privacidade e segregação ficam em código testável, não em prompt.
- Agentes (Detetive, Guardião, Redator, Verificador) conversam por um barramento de mensagens ([`dialogo.py`](codigo/gocolega/dialogo.py)).
- Quando falta informação, o agente **pergunta ao cliente** em vez de chamar uma pessoa.

## Rodar
```
pip install -r requirements.txt
python -m pytest                     # 232 testes com a base completa; só com a amostra, 218 passam e 14 são pulados
python codigo/demo.py                # 11 cenas no terminal
python codigo/app/servidor.py        # monitor local: http://127.0.0.1:8765
```
Python 3.12+. A amostra de dados já está em `dados/amostra/`. Para usar os modelos, copie `.env.example` para `.env` e preencha `AI_PROXY_API_KEY`. **Nunca versione o `.env`.**

O **monitor** mostra as conversas chegando, a Maya respondendo sozinha e, em vermelho, os casos que precisam de uma pessoa (com motivo, contexto e rascunho). A pessoa assume, responde e resolve pela tela. A aba **Feedback** reúne o que a Maya faz bem, onde pode melhorar (cada ponto com a evidência) e as avaliações 👍/👎 dos atendentes.

## Resultado medido
Lote de **60 conversas reais** (20 da fila aberta + 40 do histórico), modelos reais, código final:

| | |
|---|---|
| Resolvidas pelo agente (inclui negativas com a regra da política) | **63%** |
| Sem humano (soma as que aguardam resposta do cliente) | **92%** |
| Precisam de uma pessoa | **8%** (saúde, suspeita, acima do limite) |
| Tempo do agente por conversa | **7 s** em média (humano: mediana de 16 min no WhatsApp) |

Outros números: o Detetive sinalizou 10% das conversas com foto; a causa raiz acha a transportadora com problema por estado; 232 testes comuns, difíceis e estranhos.

## Limites (honestos)
- **Tudo é simulado:** reenviar, reembolsar e responder gravam num log; nenhum sistema real é alterado. Slack, WhatsApp e Reclame Aqui são canais simulados.
- **Amostra pequena (60).** "Sem humano" conta quem recebeu uma pergunta do agente: sem conversa em vários turnos não sabemos quantos terminam resolvidos.
- **Respostas não passaram por revisão humana em escala.** Validação contra as ações da equipe (40 conversas): [`docs/validacao_rotas.md`](docs/validacao_rotas.md).
- **Resposta pública do Reclame Aqui sai sem aprovação**, por decisão do time; os documentos do desafio não exigem nem proíbem.
- **Abrir chamado** na transportadora concorda pouco com a prática humana (precisão 29%); o Detetive e os limiares são heurísticos, sem rótulo de verdade na base.
- A conversa é de **uma mensagem por vez** (sem ciclo de réplicas); a busca é lexical, sem embeddings.

## Próximos passos
1. Conversa em vários turnos (o cliente responde e o agente continua).
2. Trocar as ferramentas simuladas por integrações reais (ERP, gateway, transportadoras, Slack).
3. Modo sombra por 2 semanas: o agente propõe, a pessoa decide, medimos a concordância.
4. Calibrar o Detetive com casos que o supervisor já decidiu.

## Mapa do repositório
```
codigo/gocolega/     o agente (orquestrador, política, Detetive, rotas, RAG, canal do time)
codigo/app/          monitor local (servidor + tela)
codigo/tests/        232 testes: comuns, difíceis, estranhos
codigo/benchmarks/   lote de ponta a ponta, benchmark de modelos, validação contra a equipe
dados/amostra/       amostra dos dados (a base completa fica fora do git)
docs/                benchmark da triagem e validação das rotas
DIARIO.md            erros, decisões e correções (37 entradas), para quem quiser o caminho
```
