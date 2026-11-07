# Benchmark da triagem: Jev × gpt-5.6-luna × gpt-5.6-terra × regras

Pergunta: **quem classifica melhor a mensagem do cliente?** Feito em 07/11/2026 para decidir se o Jev continua na triagem do GoColega.

## Método
- **Amostra:** 100 conversas aleatórias (semente 42) entre as que têm `tag_agente`, de um total de 2.654 rotuladas.
- **Gabarito:** a `tag_agente`, escolhida **manualmente por um atendente** ao encerrar a conversa. Não é verdade absoluta (ver "Limites").
- **Entrada:** o mesmo texto que o GoColega recebe (mensagens do cliente concatenadas), com CPF, cartão e telefone mascarados.
- **Justiça:** os quatro receberam só os **nomes** das 13 categorias, sem definições. O texto do cliente entra delimitado como dado.
- **Reprodução:** `python codigo/benchmarks/comparar_triagem.py 100 42`. Resultados por conversa em `codigo/benchmarks/triagem_resultados.csv` (sem o texto do cliente).

## Resultado 1: acerto da categoria exata (13 categorias)

| Classificador | Acerto | Intervalo de 95% | Tempo médio | p95 |
|---|---|---|---|---|
| **Jev** | 52/100 | 42% a 62% | **0,53 s** | 0,57 s |
| gpt-5.6-luna | 54/100 | 44% a 63% | 2,13 s | 3,28 s |
| gpt-5.6-terra | 56/100 | 46% a 65% | 2,28 s | 3,48 s |
| Regras | 36/100 | 27% a 46% | instantâneo | instantâneo |

**Os três modelos empatam estatisticamente** (os intervalos se sobrepõem quase por inteiro). A diferença real é que as **regras ficam bem atrás** e que o **Jev é cerca de 4× mais rápido**.

## Resultado 2: acerto por rota (o que muda a ação do GoColega)
O GoColega só executa duas rotas: pós-venda (Avaria, Produto faltando, Reclamação produto) e rastreio (Rastreio, Atraso). Confundir Rastreio com Atraso, o erro mais comum do Jev, **não muda a ação**. Por rota:

| Classificador | Acerto por rota | Intervalo de 95% |
|---|---|---|
| Jev | 76/100 | 67% a 83% |
| luna | 79/100 | 70% a 86% |
| terra | 77/100 | 68% a 84% |
| Regras | 76/100 | 67% a 83% |

**Na rota, até as regras empatam.** A vantagem dos modelos está na granularidade das 13 categorias e, de forma anedótica, em casos como o sarcasmo (não medimos isso à parte).

## Resultado 3: a confiança é útil?

| Classificador | Acerto da categoria quando confiança ≥ 0,7 | quando < 0,7 |
|---|---|---|
| **Jev** | 46/77 (60%) | 6/23 (**26%**) |
| luna | 54/100 | nenhum caso |
| terra | 56/100 | nenhum caso |

- **A confiança do Jev informa:** abaixo de 0,7 o acerto da categoria cai para 26% (e o da rota para 14/23, 61%, contra 62/77, 81%, acima de 0,7).
- **A "confiança" do luna e do terra é inútil para decidir:** eles disseram ≥ 0,7 em **todas** as 100 respostas, errando 44% e 46%. Não dá para usá-la para chamar um humano.
- Faixas do Jev, por rota: confiança 0 a 0,5 acertou 3 de 6; 0,5 a 0,7, 11 de 17; 0,7 a 0,9, 13 de 17; 0,9 a 1,0, 49 de 60.

## Outras observações
- **Todos os modelos erram as mesmas categorias:** "Outros" (0 de 9 nos três modelos) e "Reclamação produto" (0 de 3). Nesses casos o gabarito humano é provavelmente ambíguo, e não um defeito do modelo.
- **Em 36 das 100 conversas nenhum dos quatro acertou.** Só em 47 os três modelos concordam e acertam. Isso sugere ruído no gabarito.
- **Custo:** o Jev gastou US$ 0,00256 nas 100 chamadas (≈ **US$ 0,0000256 por conversa**, estimativa do proxy). O proxy **não informa preço por chamada** para luna e terra, só tokens: 17.771 de entrada e ~2.300 de saída cada. Por isso **não dá para comparar custo em dólar** entre eles.
- **Cobertura do GoColega:** as duas rotas que ele executa somam 1.577 das 2.984 conversas do histórico (52,8%), pelas etiquetas humanas. As outras 47% ainda vão para uma pessoa.

## Decisão
**Manter o Jev na triagem.** Razões, em ordem de peso:
1. **Empata em acerto** com os modelos maiores (a diferença está dentro do erro da amostra).
2. **4× mais rápido** (0,53 s contra ~2,2 s) e com custo medido.
3. **Única confiança utilizável:** a dos outros dois não separa acerto de erro.

**Consequência (implementada):** o GoColega agia mesmo quando o Jev tinha confiança baixa (23% das conversas da amostra), e abaixo de 0,7 só 61% das rotas estavam certas. Agora há uma **cascata**: confiança < 0,7 chama o `terra` como segunda opinião, e a discordância na ação, ou a falta de resposta válida, vai para uma pessoa. Ver `DIARIO.md`, entrada 16. A taxa real de discordância **ainda não foi medida**.

## Limites (leia antes de citar estes números)
- **Amostra pequena:** 100 conversas, e os intervalos de 95% vão de ~±10 pontos. Diferenças de 2 a 4 pontos entre modelos **não significam nada**.
- **O gabarito é humano e ruidoso:** tags colocadas à mão, com conversas de mais de um assunto. O "acerto de 52%" **não é a acurácia do produto**: é a concordância com um atendente.
- **Prompt sem definições:** nenhum classificador recebeu a descrição de cada categoria. Com definições, todos provavelmente melhorariam. Não testado.
- **Só a categoria foi medida.** Os sinais de "caso sensível" e "injeção" **não têm rótulo** na base e **não foram avaliados**.
- **As regras já foram ajustadas por mim em cima de algumas conversas da base** (não necessariamente desta amostra), o que pode favorecê-las um pouco.
- **Uma só rodada** com uma semente. Não houve repetição para medir a variação.
