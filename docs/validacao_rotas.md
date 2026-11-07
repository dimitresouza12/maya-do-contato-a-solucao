# Validação das rotas contra as ações da equipe humana

Conversas do histórico no lote: **40**. Fonte humana: `acoes_executadas_sistemas.csv`.

| Ação | Agente e humano fizeram | Só o humano fez | Só o agente fez (risco) |
|---|---:|---:|---:|
| `reenviar_produto` | 1 | 6 | 1 |
| `reembolsar` | 0 | 1 | 0 |
| `trocar_produto` | 0 | 2 | 0 |
| `cancelar_pedido` | 2 | 0 | 0 |
| `abrir_chamado_transportadora` | 0 | 5 | 2 |
| `reimprimir_personalizacao` (o agente só pergunta/encaminha, por desenho) | 0 | 0 | 0 |
| `alterar_endereco` (o agente só pergunta/encaminha, por desenho) | 0 | 1 | 0 |

Leitura: **só o agente fez** é o número a explicar caso a caso (pode ser um caso que o humano negou ou encaminhou). **Só o humano fez** é resolução que o agente ainda deixa para uma pessoa ou para o cliente responder.

## Casos de `reenviar_produto` só do agente (1)
- AT111312 · categoria Produto faltando · desfecho autonomo

## Casos de `abrir_chamado_transportadora` só do agente (2)
- AT105900 · categoria Atraso · desfecho autonomo
- AT105601 · categoria Atraso · desfecho autonomo
