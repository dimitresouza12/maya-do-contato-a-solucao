# Roteiro do pitch (5 minutos) e sabatina

Segue o toolkit do evento: narrativa, não apresentação; **mostre, não descreva**; se algo tiver que cortar, **corte texto, não a demonstração**. Máximo de 3 elementos por slide. Plano B obrigatório.

## Linha do tempo

| Tempo | Slide | O que dizer (e o que mostrar) |
|---|---|---|
| 0:00 a 0:15 | 1. Capa | "Eu sou [nome] e este é o GoColega, a minha resposta ao Desafio 1." |
| 0:15 a 0:50 | 2. A dor · 3. Fluxo atual | "O Diego atende uns 130 contatos por dia e, em cada um, abre de dois a quatro sistemas. E nem toda reclamação de avaria é verdadeira: reenviar uma falsa custa 45% do pedido. A Marina aprova sem o dossiê pronto." |
| 0:50 a 1:20 | 4. A solução · 5. Como funciona | "Minha solução é o GoColega: um agente de IA que lê a conversa, confere pedido, foto e histórico e age dentro da política, para que o Diego e a Marina cuidem só do que é decisão de pessoa. O modelo propõe, o código decide. **Deixa eu mostrar como isso funciona na prática.**" |
| 1:20 a 3:50 | 6. Demonstração | Três casos ao vivo (comandos abaixo). Só 2 frases de explicação por caso; o resto é a tela. |
| 3:50 a 4:20 | 7. Resultados · 8. Limites | Os três números e os limites, **ditos por mim antes de a banca perguntar**. |
| 4:20 a 5:00 | 9. O que muda · 10. Segunda-feira | O que muda para o Diego e a Marina, a primeira dependência e o passo 1. Fechar com os três passos. |

## Demonstração (2 min 30 s)

Rode antes, na máquina da apresentação, para esquentar a conexão: `python codigo/demo.py 2` (qualquer cena).

1. **Avaria suspeita** (`python codigo/demo.py 2`, uns 15 s): mostre a linha do Detetive ("Risco 86% | foto reutilizada | foto 21 dias antes da entrega | custo de reenviar se falsa R$ 33,91 contra R$ 0,85") e a resposta neutra ao cliente. Frase: "Ele nunca acusa o cliente, e o supervisor recebe o dossiê pronto."
2. **Atraso com reembolso** (`python codigo/demo.py 8`): "O cliente escolheu o reembolso; R$ 75,91 está dentro da alçada de R$ 100, então o GoColega executa e registra no log." Se sobrar tempo, a cena 7 antes mostra a oferta das duas opções.
3. **Causa raiz** (`python codigo/demo.py 11`, precisa da base completa): "Só com conversas até 10 de outubro, ele achou a Expressa Já em cinco estados: 29% de conversas-problema contra 10%. Preparou o aviso a 89 pedidos e **espera a aprovação de uma pessoa**."

**Plano B** (se a rede ou o proxy falhar): `docs/demo_saida.txt` tem a saída completa de todas as cenas com os modelos reais. Abra o arquivo e percorra as cenas 2, 8 e 11. Diga: "A conexão caiu; esta é a saída gravada da mesma execução." O ideal é também ter prints dessas três cenas no celular ou em um slide extra.

## Números que posso citar (e o que cada um não prova)

| Número | Origem | Cuidado |
|---|---|---|
| 148 de 148 | `validar_rastreio.py`, 1.082 conversas | Cobre 85% dos reenvios por atraso da equipe; **o chamado tem só 29% de precisão** |
| {SEM_HUMANO} sem humano, 93% só informam | `rodar_lote.py`, 210 conversas | Não é "{SEM_HUMANO} autônomo": quase tudo é informar o status |
| {MEDIANA} de mediana | mesmo lote | Com modelos reais, sem falha de modelo |
| 29% contra 10%; 45% contra 22% | `causa_raiz.py` e retroteste (corte 10/10) | A situação do pedido no corte é aproximada; mede reclamação, não a causa |
| 870 min | 70 conversas resolvidas sozinhas | **Teto**, não economia medida |
| Jev 62%, terra 71% | `BENCHMARK_TRIAGEM.md`, 100 conversas | O acerto é a concordância com um atendente; na rota, 88% contra 92% |

## Sabatina (5 min): perguntas prováveis

Regras do toolkit: "Boa pergunta…" compra 2 segundos; responda o que foi perguntado; se não souber, "não cheguei lá ainda, mas o próximo passo seria…"; nunca contradiga a banca, redirecione.

1. **Como isso funciona tecnicamente?** "O modelo classifica e escreve; o código aplica a política (alçada, prazo, quem pode aprovar). Se o modelo propõe algo fora da política, o código nega." Mostre a conversa entre os agentes na cena 2.
2. **Quem usaria isso?** "O Diego, atendente, que hoje abre vários sistemas, e a Marina, supervisora, que hoje aprova sem dossiê."
3. **O que impede a IA de inventar?** "O texto ao cliente passa por um verificador que barra número, promessa e termo sem apoio nos fatos. Em dúvida de produto, só responde com a ficha, citando a fonte. Suspeita e caso sensível usam texto fixo."
4. **E se o cliente tentar enganar o sistema?** "O que o cliente escreve é dado, não ordem: a cena 4 mostra uma ordem escondida sendo ignorada e a supervisão avisada."
5. **O que falta para funcionar de verdade?** "As ações são simuladas. Falta ligar central, ERP, gateway e portais em modo leitura, e calibrar com casos que os supervisores já decidiram." (Seja honesto: este é o passo 1.)
6. **Como medir o sucesso?** "Processo: tempo de resposta e concordância com o atendente em modo sombra. Negócio: conversas evitadas, avisos proativos e reenvios falsos evitados."
7. **Por que o terra e não o Jev na triagem?** "Medi nas mesmas 100 conversas: terra 71% e Jev 62% na categoria; na rota que importa, 92% contra 88%. Refiz o benchmark depois de achar que a amostra não era reprodutível. O Jev ficou como reserva."
8. **E o gpt-6?** "Testei: o gpt-6-astra fez 75%, um pouco acima do terra, mas dentro do erro da amostra, e eu teria de repetir todo o lote. Dá para trocar com uma variável."
9. **Por que o chamado na transportadora tem 29% de precisão?** "A política escrita (3 dias úteis parado) não descreve o que a equipe faz: os humanos abrem mais cedo e em outros casos. É o primeiro item do modo sombra."
10. **Isso substitui o atendente?** "Não. O que sai da alçada ou é suspeito vai para uma pessoa com o dossiê. O ganho é tirar o trabalho de formiga."
11. **E a LGPD?** "CPF, cartão e telefone são mascarados antes de ir ao modelo e na saída; o token não vai ao repositório; os dados do projeto são fictícios."
12. **Por que não um agente totalmente autônomo?** "Dinheiro e política não podem depender de um prompt. O código decide, o modelo propõe."
13. **A causa raiz é confiável?** "Ela mede reclamação, não causa, e por isso abre um incidente para o analista confirmar. Aplico Bonferroni e um mínimo de casos: dois falsos alarmes que achei nos testes. Nenhuma impressora ou lote passa no teste."
14. **Quanto custa rodar?** "O Jev custou US$ 0,0054 nas 210 triagens. Para os modelos de chat o proxy só informa tokens, então não consigo dar o preço em dólar sem inventar."
15. **O que você faria com mais uma semana?** "Financeiro, o relatório diário automático e a camada de canal completa; depois trocar a busca por embeddings."
