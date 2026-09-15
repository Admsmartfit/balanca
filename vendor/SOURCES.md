# Proveniência dos códigos vendorizados

Todos os arquivos abaixo são cópias INTEGRAS e NÃO MODIFICADAS, obtidas por
`git clone` diretamente dos repositórios oficiais na data indicada. Nenhum
trecho foi reescrito, resumido ou "corrigido" nesta pasta — correções
sugeridas ficam apenas no PRD, nunca nos arquivos vendorizados.

Baixado em: 2026-09-14

## 1. lolouk44/xiaomi_mi_scale — Licença MIT
Commit: e9db989d21b23602a462338a285478658cbaa13
URL: https://github.com/lolouk44/xiaomi_mi_scale
Permalink: https://github.com/lolouk44/xiaomi_mi_scale/tree/e9db989d21b23602a462338a285478658cbaa13

## 2. dckiller51/bodymiscale — Licença Apache-2.0
Commit: 684a5b99b621845e25e523f7e9261231d4ba725
URL: https://github.com/dckiller51/bodymiscale
Permalink: https://github.com/dckiller51/bodymiscale/tree/684a5b99b621845e25e523f7e9261231d4ba725

ATENÇÃO — bug confirmado no branch main nesta data: util.py (linha 27) e
profile.py (linha 121) usam a sintaxe Python 2 `except ValueError, TypeError:`,
que é SyntaxError em Python 3. Confirmado com `python3 -m py_compile`.
Corrija para `except (ValueError, TypeError):` antes de importar este código.

## 3. oliexdev/openScale — Licença GPL-3.0
Commit: e79e8005ed64826b7f31c2910f0fa01313e2051
URL: https://github.com/oliexdev/openScale
Permalink: https://github.com/oliexdev/openScale/tree/e79e8005ed64826b7f31c2910f0fa01313e2051

Apenas 3 arquivos Kotlin foram vendorizados (não o app inteiro), pois são os
únicos relevantes ao escopo deste PRD (parsing BLE do Mi Scale e a
port Kotlin das fórmulas do bodymiscale). ATENÇÃO: por ser GPL-3.0, qualquer
código derivado destes arquivos específicos herda a obrigação de
distribuição sob GPL-3.0 — ver seção "Licenciamento" do PRD.
