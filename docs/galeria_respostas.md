# Galeria de respostas do GoColega

Conversas **reais da base** (dados fictícios do evento), sorteadas por semente, sem escolha a dedo. Cada caso mostra a mensagem do cliente, o que o agente fez e a resposta que enviou (simulada: vai para o log, não para um WhatsApp real). Os casos que vão para uma pessoa também estão aqui.

Gerado por `python codigo/ferramentas_dev/galeria_respostas.py 3 11` com os modelos reais.

## Rastreio (etiqueta do atendente)

### AT112042 · Resolvido pelo agente

> **Cliente:** Boa tarde / Meu pedido está parado no centro de distribuição da Expressa Já em Caruaru desde 24/09. Tô ansioso kkk / e se não chegar até sábado?

**GoColega** (triagem: *Atraso*; ações: abrir_chamado_transportadora):

> O pedido GCH546167 está em transferência no centro de distribuição da transportadora Expressa Já desde 26/09/2026. A previsão de entrega permanece para 30/09/2026, e abrimos um chamado com a transportadora devido à falta de atualização no rastreio há 3 dias.

### AT106983 · Resolvido pelo agente

> **Cliente:** oii / já é a 2ª vez que entro em contato / Queria saber o status do pedido GCH533474. Tô ansiosa kkk

**GoColega** (triagem: *Rastreio*; ações: nenhuma):

> O pedido GCH533474 está em transferência no centro de distribuição da transportadora Expressa Já, conforme atualização de 20/08/2026. A previsão de entrega permanece para 25/08/2026, dentro do prazo.

### AT113339 · Resolvido pelo agente

> **Cliente:** Olá! Já foi enviado a máscara de cílios que comprei dia 05/10? Pedido GBH450350. Atenciosamente, Jéssica Batista

**GoColega** (triagem: *Rastreio*; ações: nenhuma):

> O pedido GBH450350, enviado pela transportadora Correio Ágil, consta como entregue. A previsão original era 13/10/2026; caso não tenha recebido, avise-nos.

## Atraso (etiqueta do atendente)

### AT106209 · Resolvido pelo agente

> **Cliente:** Já é a 2ª vez que entro em contato. Que serviço maravilhoso, comprei dia 07/08 e tô esperando até agora. Nota 10 🙄 / o número é GBH379756

**GoColega** (triagem: *Atraso*; ações: nenhuma):

> O pedido GBH379756 está em transferência no centro de distribuição da transportadora Expressa Já, conforme última atualização de 12/08/2026. A previsão de entrega permanece para 14/08/2026, dentro do prazo.

### AT107837 · Perguntou ao cliente

> **Cliente:** Bom dia! / Já é a 2ª vez que entro em contato. Tô esperando a gaarrafa Urban desde 30/07, o prazo era 10/08. O rastreio da Expressa Já parou em Lauro de Freitas faz 21 dias e não sai de lá. Já perdi a data que eu precisava. Até quando vou ter que esperar? / GCH527518

**GoColega** (triagem: *Atraso*; ações: nenhuma):

> Lamentamos o atraso do pedido GCH527518, que está há 14 dias úteis além da previsão original. Podemos providenciar o reenvio ou o reembolso, conforme sua preferência; qual opção você escolhe?

### AT114514 · Rascunho público (Reclame Aqui)

> **Cliente:** [Pedido sem atualização] Comprei dia 14/10 e ainda não chegou, consegue ver onde está? Tô ansioso kkk. Pedido GBH460552. Compra feita em 14/10, produto: Sérum Ácido Hialurônico 30ml + Brinde Necessaire GoBeauté.

**GoColega** (triagem: *Rastreio*; ações: rascunho_resposta_publica, acionar_pessoa):

> O pedido GBH460552 está em transferência no centro de distribuição da transportadora Expressa Já, conforme atualização de 16/10/2026. A previsão atual de entrega é 21/10/2026, e o pedido está dentro do prazo.

## Avaria (etiqueta do atendente)

### AT113988 · Resolvido pelo agente

> **Cliente:** O pote do whey vegano chegou rachado e o pó espalhado na caixa. Nem consegui usar. Pedido GBH448549. Att, Maria Eduarda Ferreira / segue a foto [imagem]

**GoColega** (triagem: *Avaria*; ações: reenviar_produto):

> Seu reenvio sem custo foi aprovado e executado. O código de rastreio será informado assim que o pedido sair.

### AT105523 · Perguntou ao cliente

> **Cliente:** O lacre de segurança do multivitamínico estava violado, fiquei com medo de tomar / Tenho as fotos. Quero outro / o número é GBH370837 / mandei as fotos aí / Tá bom, aguardo retorno

**GoColega** (triagem: *Avaria*; ações: solicitar_foto):

> Para seguirmos com a solução, por favor, envie uma foto do produto e da embalagem recebida. Assim poderemos analisar o problema relatado e dar continuidade ao atendimento.

### AT116254 · Resolvido pelo agente

> **Cliente:** Bom dia! A foto da capinha do Galaxy S24 FE saiu toda pixelada. Conferi o pedido e eu escrevi certo. Quero que refaçam / GCH555786 / [imagem] [imagem] / obrigada

**GoColega** (triagem: *Reclamacao produto*; ações: reenviar_produto):

> Seu reenvio sem custo foi aprovado e executado. O código de rastreio será informado assim que o pedido sair.

## Produto faltando (etiqueta do atendente)

### AT114758 · Perguntou ao cliente

> **Cliente:** Olá, equipe Kokeshi, tudo bem? Pedi 3 e veio só 1 na caixa, cadê o resto? Já é a segunda vez que acontece comigo. Pedido GBH456507. Sabrina

**GoColega** (triagem: *Produto faltando*; ações: solicitar_foto):

> Para seguirmos com a solução, por favor, envie uma foto do produto e outra da embalagem. Assim poderemos analisar o problema relatado no pedido.

### AT110339 · Perguntou ao cliente

> **Cliente:** [Pedido incompleto] Já entrei em contato 2 vezes sem solução. Pedi 2 e veio só 1 na caixa, cadê o resto? Já é a segunda vez que acontece comigo. Pedido GBH409705. / mandei as fotos aí

**GoColega** (triagem: *Produto faltando*; ações: solicitar_foto, rascunho_resposta_publica, acionar_pessoa):

> Para seguirmos com a solução, por favor, envie uma foto do produto e outra da embalagem recebida. Assim que recebermos as imagens, daremos continuidade ao atendimento.

### AT115820 · Resolvido pelo agente

> **Cliente:** Faltou a necessaire de brinde no meu pedido GBH465777, a compra foi de R$ 169,80 / [imagem] [imagem] / perfeito, obrigada!

**GoColega** (triagem: *Produto faltando*; ações: reenviar_produto):

> O reenvio sem custo foi aprovado e executado. O código de rastreio será informado assim que o pedido sair.

## Troca (etiqueta do atendente)

### AT105004 · Rascunho público (Reclame Aqui)

> **Cliente:** [Devolução] Me arrependi, ainda dá pra cancelar antes de enviarem? Pedido GBH378688.

**GoColega** (triagem: *Cancelamento*; ações: cancelar_pedido, rascunho_resposta_publica, acionar_pessoa):

> O pedido GBH378688 foi cancelado antes de ser separado. O estorno foi realizado integralmente.

### AT112700 · Negou pela política, com a regra

> **Cliente:** o cheiro do perfume Âmbar é muito diferente do que eu esperava. Posso trocar?

**GoColega** (triagem: *Troca*; ações: negar_por_politica):

> A troca do pedido GBH390947 não foi autorizada porque ele foi recebido há 45 dias, ultrapassando o prazo de 30 dias previsto na política de trocas.

### AT108707 · Resolvido pelo agente

> **Cliente:** Olá! De novo aqui. A tampa da base veio quebrada. Nem consegui usar. Pedido GBH384182. Flávia / [imagem] [imagem]

**GoColega** (triagem: *Avaria*; ações: reenviar_produto):

> Seu reenvio sem custo foi aprovado e já foi realizado. O código de rastreio será informado assim que o pedido sair.

## Cancelamento (etiqueta do atendente)

### AT105044 · Resolvido pelo agente

> **Cliente:** Voltando aqui porque não resolveram. O prazo de entrega do meu pedido venceu dia 06/08 e não recebi. Preciso pra um presente! Aguardo retorno urgente.

**GoColega** (triagem: *Atraso*; ações: nenhuma):

> O pedido GBH370680 está em transferência no centro de distribuição da transportadora Expressa Já desde 01/08/2026. A previsão atual de entrega permanece em 06/08/2026, com atraso de 1 dia, e já existe um chamado aberto desde essa data.

### AT111783 · Rascunho público (Reclame Aqui)

> **Cliente:** [Produto não entregue] Comprei dia 13/09 com prazo até 18/09 e o pedido ainda não chegou. Aguardo retorno urgente. Pedido GBH422659. Compra feita em 13/09, produto: Pomada Modeladora Efeito Seco 80g.

**GoColega** (triagem: *Atraso*; ações: abrir_chamado_transportadora, rascunho_resposta_publica, acionar_pessoa):

> O pedido GBH422659 está com a transportadora Correio Ágil e teve o último evento registrado em 25/09/2026, com chegada à unidade de destino em SP. A entrega está atrasada em 6 dias úteis, e já abrimos um chamado com a transportadora para acompanhar a situação.

### AT107156 · Perguntou ao cliente

> **Cliente:** Oi, tudo bem? Meu marido não curtiu o cheiro, dá pra trocaar por outro? Posso trocar? Obrigado, Yuri / é o GBH380388

**GoColega** (triagem: *Troca*; ações: nenhuma):

> Para prosseguirmos com a troca de fragrância, informe quanto do produto foi utilizado. A troca é válida para produtos com no máximo 20% de uso; também nos diga por qual fragrância deseja trocar.

## Endereço (etiqueta do atendente)

### AT106201 · Negou pela política, com a regra

> **Cliente:** Preciso mudar o número da casa no pedido GBH388253

**GoColega** (triagem: *Endereco*; ações: negar_por_politica):

> O pedido GBH388253 já foi separado, por isso não é mais possível alterar o endereço. A alteração de endereço só pode ser feita antes da separação do pedido.

### AT113834 · Perguntou ao cliente

> **Cliente:** Oi, bom dia! Preciso mudar o número da casa no pedido GBH458313 / perfeito, obrigada!

**GoColega** (triagem: *Endereco*; ações: nenhuma):

> Para prosseguirmos com a alteração, informe o endereço completo correto, com rua, número, complemento, bairro, cidade e CEP.

### AT106518 · Negou pela política, com a regra

> **Cliente:** Olá, equipe Gocase! Coloquei o CEP errado, dá pra corrigir? Pedido GCH532041. Att, Matheus Lopes / ok

**GoColega** (triagem: *Endereco*; ações: negar_por_politica):

> O pedido GCH532041 já foi separado, por isso não é mais possível alterar o endereço. A alteração de endereço só pode ser feita antes da separação do pedido.

## Financeiro (etiqueta do atendente)

### AT109969 · Resolvido pelo agente

> **Cliente:** Bom dia! Paguei o boleto e cobraram no cartão também / é o GBH424596 / Tá bom, aguardo retorno

**GoColega** (triagem: *Financeiro*; ações: nenhuma):

> O pagamento do pedido GBH424596 foi confirmado no gateway, no valor de R$ 67,92.

### AT113616 · Resolvido pelo agente

> **Cliente:** Paguei o pix e o pedido continua 'aguardando pagamento' / O que eu faço? / pedido GBH456670

**GoColega** (triagem: *Financeiro*; ações: nenhuma):

> O pagamento do pedido GBH456670 foi confirmado no gateway, no valor de R$ 138,81.

### AT112858 · Perguntou ao cliente

> **Cliente:** Olá, equipe Gocase! O pix saiu duas vezes da minha conta, R$ 98,80 cada. Isso é golpe? Pedido GCH551694. Att, Manuela Andrade

**GoColega** (triagem: *Financeiro*; ações: nenhuma):

> Conferi o gateway do pedido GCH551694 e consta uma única cobrança confirmada de R$ 98,80, sem duplicidade. Se o extrato apresentar outra cobrança, por favor, envie o comprovante para verificarmos.

## Promoção (etiqueta do atendente)

### AT109918 · Resolvido pelo agente

> **Cliente:** o cupom GOCASE20 nao está funcionando / 👍

**GoColega** (triagem: *Promocao*; ações: nenhuma):

> O cupom GOCASE20 não foi aplicado porque estava fora do período de vigência, válido de 20/04 a 30/04/2026.

### AT112167 · Resolvido pelo agente

> **Cliente:** O frete grátis não apareceu mesmo acima do valor mínimo / obrigada

**GoColega** (triagem: *Promocao*; ações: nenhuma):

> Para usar o frete grátis, aplique o cupom FRETEGRATIS no carrinho e confira se ele foi digitado corretamente. A condição é válida de 01/01 a 31/12/2026, sem valor mínimo e limitada a 5 usos por cliente.

### AT110360 · Resolvido pelo agente

> **Cliente:** Olá, boa noite. / O cupom do influenciador não funciona, é FRETEGRATIS / certo, obrigada pela atenção

**GoColega** (triagem: *Promocao*; ações: nenhuma):

> O cupom FRETEGRATIS não foi aplicado porque não é cumulativo com outra promoção já aplicada ao pedido.

## Dúvida (etiqueta do atendente)

### AT106312 · Perguntou ao cliente

> **Cliente:** [Alteração de endereço] Vou viajar, consegue entregar no endereço do meu trabalho? Pedido GBH391933. / Considero resolvido, obrigada.

**GoColega** (triagem: *Endereco*; ações: rascunho_resposta_publica, acionar_pessoa):

> Por favor, informe o endereço completo correto, com rua, número, complemento, bairro, cidade e CEP, para realizarmos a alteração.

### AT108548 · Resolvido pelo agente

> **Cliente:** Olá, equipe Lescent, tudo bem? Meu pedido está 'em trânsito' faz 1 dias, isso é normal? Tô ansiosa kkk. Me avisem pfv. Obrigada, Luiza

**GoColega** (triagem: *Rastreio*; ações: nenhuma):

> O pedido GBH407148 está em transferência no centro de distribuição da transportadora Expressa Já, conforme última atualização de 02/09/2026. A previsão de entrega permanece em 08/09/2026 e o pedido está dentro do prazo.

### AT106657 · Resolvido pelo agente

> **Cliente:** O frete grátis não apareceu mesmo acima do valor mínimo

**GoColega** (triagem: *Promocao*; ações: nenhuma):

> Para usar o frete grátis, aplique o cupom FRETEGRATIS no carrinho antes de finalizar a compra. A promoção é válida de 01/01 a 31/12/2026, sem valor mínimo e limitada a 5 usos por cliente. Confira se o cupom foi digitado corretamente no carrinho.

## Elogio (etiqueta do atendente)

### AT113924 · Resolvido pelo agente

> **Cliente:** Olá, boa noite. / Só passando pra dizer que o whey vegano é maravilhoso, já virou favorito / é o GBH446854

**GoColega** (triagem: *Elogio*; ações: agradecer):

> Agradecemos muito pelo elogio! Ficamos felizes em saber que você gostou do produto e do atendimento.

### AT114286 · Resolvido pelo agente

> **Cliente:** Olá, boa tarde. Amei o magnésio, chegou rapidinho e super bem embalado! / pedido GBH453841 / certo, obrigado pela atenção

**GoColega** (triagem: *Elogio*; ações: agradecer):

> Agradecemos muito pelo elogio! Ficamos felizes em saber que você gostou do produto e do atendimento.

### AT110021 · Resolvido pelo agente

> **Cliente:** oie / amei o perfume Neroli, chegou rapidinho e super bem embalado! 😡

**GoColega** (triagem: *Elogio*; ações: agradecer):

> Agradecemos muito pelo seu elogio! Ficamos felizes em saber que você gostou do produto e do atendimento.

## Reclamação produto (etiqueta do atendente)

### AT115386 · Resolvido pelo agente

> **Cliente:** recebbi o pedido GBH465631 mas não veio o brinde da promoção (Necessaire GoBeauté). Quero q enviem o q faltou. CPF: [CPF omitido] / segue a foto [imagem] / ok, obrigada

**GoColega** (triagem: *Produto faltando*; ações: reenviar_produto):

> Seu reenvio sem custo foi aprovado e executado. O código de rastreio será informado assim que o pedido sair.

### AT114013 · Perguntou ao cliente

> **Cliente:** Boa tarde / O hidratante do kit veio com a embalagem estourada / Ah, e e não veio o brinde / CPF: [CPF omitido]

**GoColega** (triagem: *Avaria*; ações: solicitar_foto):

> Para seguirmos com a solução, por favor, envie uma foto do produto e outra da embalagem recebida. Assim poderemos analisar o problema relatado.

### AT111400 · Perguntou ao cliente

> **Cliente:** O zíper da mini tote veio quebrado. A caixa também veio toda amassada. Quero outro. Meu cpf é [CPF omitido] / mandei as fotos aí

**GoColega** (triagem: *Troca*; ações: nenhuma):

> Olá! Sobre a troca da Gocase, você deseja devolver o produto e receber o reembolso?

---

**Resumo desta galeria (36 conversas):** Resolvido pelo agente 20, Perguntou ao cliente 10, Rascunho público (Reclame Aqui) 3, Negou pela política, com a regra 3

Esta amostra é pequena e serve para ver o comportamento; os números medidos estão no README.
