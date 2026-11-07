# Dados

Bases CSV **fictícias** do Desafio 1 (Atendimento ao Cliente), fornecidas pelo GoHacks Talent 2026. O código só **lê** estes arquivos: as ações do agente vão para um log, nunca alteram os CSVs.

| Pasta | O que é | No repositório? |
|---|---|---|
| `amostra/` | Recorte mínimo (~100 KB, 13 tabelas, incluindo as fichas de produto, as políticas e o rastreio) das 6 conversas da demo e dos testes, mais as fotos que elas compartilham com outros pedidos. Gerada por `codigo/ferramentas_dev/gerar_amostra.py` | **Sim** |
| `atendimento/` | Base completa (24 CSVs, ~11 MB) | **Não** (ver `.gitignore`) |

**O código escolhe sozinho:** `GOCOLEGA_DATA_DIR` (se definido) → `dados/atendimento/` (se tiver `pedidos.csv`) → `dados/amostra/`. A demo mostra qual está em uso.

- **Só com a amostra:** `python codigo/demo.py` roda as 5 cenas, e `python -m pytest` roda os testes que não dependem da base inteira (os demais são pulados, com o motivo).
- **Com a base completa:** baixe `GoHacks_Talent_2026_bases_csv.zip` do Drive do evento, extraia a subpasta `atendimento/` em `dados/atendimento/` e todos os testes e o benchmark rodam.

A base completa não foi versionada por precaução: são dados do evento e ocupam 11 MB. Posição dos dados: 02/11/2026 às 08h. O significado de cada coluna está em `atendimento/dicionario_de_dados.md` (dentro da base completa).
