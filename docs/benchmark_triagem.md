# Benchmark da triagem: Jev × gpt-5.6 × gpt-6 × regras

Pergunta: **quem classifica melhor a mensagem do cliente?** Feito em 07/11/2026 para decidir se o Jev continua na triagem da Maya.

> **Correção (mesmo dia):** a primeira versão deste documento dizia que Jev, luna e terra "empatam" (52%, 54%, 56%). Aqueles números vinham de uma amostra que **não era reprodutível** (o `group by` do DuckDB não tem ordem fixa e o sorteio com semente embaralhava uma lista diferente a cada execução; só 9 das 100 conversas coincidiam entre duas execuções). A amostra agora é ordenada antes do sorteio, e **todos os classificadores rodaram juntos, nas mesmas 100 conversas**. Os números abaixo substituem os antigos, e a conclusão mudou. Ver `DIARIO.md`, entrada 30.

## Método
- **Amostra:** 100 conversas (semente 42) entre as que têm `tag_agente`, de um total de 2.654 rotuladas. Agora reprodutível.
- **Gabarito:** a `tag_agente`, escolhida **manualmente por um atendente** ao encerrar a conversa. Não é verdade absoluta (ver "Limites").
- **Entrada:** o mesmo texto que A Maya recebe (mensagens do cliente concatenadas), com CPF, cartão e telefone mascarados.
- **Justiça:** todos receberam só os **nomes** das 13 categorias, sem definições. O texto do cliente entra delimitado como dado.
- **Modelos:** Jev; gpt-5.6-luna e gpt-5.6-terra (usados na Maya); gpt-6-luna e gpt-6-astra (testados agora); regras.
- **Reprodução:** `python codigo/benchmarks/comparar_triagem.py 100 42`. Resultados por conversa em `codigo/benchmarks/triagem_resultados.csv` (sem o texto do cliente).

## Resultado 1: acerto da categoria exata (13 categorias)

| Classificador | Acerto | Intervalo de 95% | Tempo médio | p95 |
|---|---|---|---|---|
| **Jev** | 62/100 | 52% a 71% | **0,55 s** | 0,59 s |
| gpt-5.6-luna | 70/100 | 60% a 78% | 2,08 s | 3,50 s |
| gpt-5.6-terra | 71/100 | 61% a 79% | 2,21 s | 2,95 s |
| gpt-6-luna | 72/100 | 63% a 80% | 5,78 s | 7,86 s |
| **gpt-6-astra** | **75/100** | 66% a 82% | 3,06 s | 6,13 s |
| Regras | 46/100 | 37% a 56% | instantâneo | instantâneo |

Os quatro modelos GPT ficam entre 70% e 75% e **empatam entre si**. O **Jev fica 8 a 13 pontos abaixo**: os intervalos ainda se tocam, mas a diferença é consistente nos quatro. As regras ficam bem atrás. O Jev é de 4× a 10× mais rápido.

## Resultado 2: acerto por rota (o que muda a ação da Maya)
A Maya só executa duas rotas: pós-venda (Avaria, Produto faltando, Reclamação produto) e rastreio (Rastreio, Atraso). Confundir Rastreio com Atraso **não muda a ação**.

| Classificador | Rota certa | Intervalo de 95% | Agiria em rota errada |
|---|---|---|---|
| Jev | 88/100 | 80% a 93% | 9 |
| gpt-5.6-luna | 90/100 | 83% a 94% | 7 |
| gpt-5.6-terra | 92/100 | 85% a 96% | 6 |
| gpt-6-luna | 92/100 | 85% a 96% | 6 |
| gpt-6-astra | 92/100 | 85% a 96% | 6 |
| Regras | 73/100 | 64% a 81% | 4 |

**Na rota, a diferença entre o Jev e os modelos GPT é pequena (88% contra 90% a 92%) e está dentro do erro da amostra.** Onde o Jev perde mais é na granularidade: confunde Rastreio com Atraso (13 vezes) e acerta só 11 das 25 conversas de Rastreio, contra 19 do gpt-6-astra.

## Resultado 3: a confiança é útil?

| Classificador | Acerto da categoria com confiança ≥ 0,7 | com confiança < 0,7 |
|---|---|---|
| **Jev** | 56/80 (70%) | 6/20 (**30%**) |
| gpt-5.6-luna | 70/99 | 0/1 |
| gpt-5.6-terra | 70/99 | 1/1 |
| gpt-6-luna | 72/100 | nenhum caso |
| gpt-6-astra | 75/100 | nenhum caso |

- **A confiança do Jev informa:** abaixo de 0,7 o acerto cai para 30%. É isso que dispara a segunda opinião da cascata.
- **A "confiança" dos modelos GPT é inútil para decidir:** eles disseram ≥ 0,7 em praticamente **todas** as respostas, errando entre 25% e 30%. Não dá para usá-la para chamar um humano.
- **Mas a confiança do Jev também deixa passar muito erro:** 24 das 80 respostas com confiança alta estavam erradas (30%).

## Outras observações
- **Todos erram as mesmas categorias:** "Reclamação produto" (0 de 3 em todos) e "Outros" (0 de 2, só as regras acertam 1). O gabarito humano é provavelmente ambíguo nesses casos.
- **Em 19 das 100 conversas nenhum classificador acertou.** Isso sugere ruído no gabarito.
- **Custo:** o Jev gastou US$ 0,00256 nas 100 chamadas (≈ **US$ 0,0000256 por conversa**, estimativa do proxy). O proxy **não informa preço por chamada** para os modelos GPT, só tokens (17.566 de entrada cada; saída de ~2.100 a ~2.300, e **4.783 no gpt-6-luna**). Por isso **não dá para comparar custo em dólar**.
- **Cobertura da Maya:** as duas rotas que ele executa somam 1.577 das 2.984 conversas do histórico (52,8%), pelas etiquetas humanas.

## Decisão
**Em aberto.** O que os dados sustentam:

| Opção | A favor | Contra |
|---|---|---|
| Manter **Jev + cascata** (terra desempata abaixo de 0,7) | 0,55 s, custo conhecido, sinal de confiança | 62% na categoria; 30% dos erros passam com confiança alta e a cascata não os vê |
| Trocar para **gpt-6-astra** | Maior acerto (75%), 92% na rota, 3 s é aceitável em atendimento | Sem confiança utilizável: não há como acionar a segunda opinião por incerteza; custo em dólar desconhecido |
| **gpt-6-astra com Jev como sinal de incerteza** (os dois rodam; humano se discordarem) | Usa o melhor de cada um | Duas chamadas por conversa; precisa ser medido |

Nenhuma troca foi feita no código: A Maya continua com Jev + cascata, e os números do lote de 210 conversas foram medidos assim.

## Limites (leia antes de citar estes números)
- **Amostra pequena:** 100 conversas, intervalos de 95% de cerca de ±10 pontos. Diferenças de 2 a 4 pontos entre modelos GPT **não significam nada**.
- **O gabarito é humano e ruidoso:** tags colocadas à mão, com conversas de mais de um assunto. O acerto **não é a acurácia do produto**: é a concordância com um atendente.
- **Prompt sem definições:** nenhum classificador recebeu a descrição de cada categoria. Com definições, todos provavelmente melhorariam. Não testado.
- **Só a categoria foi medida.** Os sinais de "caso sensível" e "injeção" **não têm rótulo** na base e **não foram avaliados**.
- **As regras já foram ajustadas por mim em cima de algumas conversas da base** (não necessariamente desta amostra), o que pode favorecê-las um pouco.
- **Uma só rodada** com uma semente. Não houve repetição para medir a variação.
