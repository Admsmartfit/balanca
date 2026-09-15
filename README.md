# MiScale Analytics Desktop

Aplicação local, cross-platform (Linux/Windows), que escuta os anúncios BLE da
Xiaomi Mi Body Composition Scale 2, calcula métricas de composição corporal e
exibe tudo em um painel web servido localmente — sem conta Mi, sem nuvem, sem
telemetria. Ver o PRD completo para o produto inteiro (requisitos, riscos,
roadmap); este README cobre o que já está implementado.

## Status — Fases 0, 1, 2 e parte da 3

- **Fase 0 — Correção de base:** repositórios vendorizados em `vendor/`,
  patch Python 2→3 aplicado ao `bodymiscale`, parser BLE com a leitura de
  bits corrigida, postura de licenciamento definida (ver abaixo).
- **Fase 1 — MVP:** varredura passiva BLE, WebSocket com atualizações
  parciais/finais, painel web básico.
- **Fase 2:** motor de bioimpedância nos dois modos (Xiaomi/Zepp Life e
  Científico, por perfil — RF06), histórico persistido em SQLite com
  exportação CSV/JSON (RF07), múltiplos perfis com identificação automática
  por peso mais próximo e confirmação manual em caso de ambiguidade (RF08),
  gráfico de tendência no painel (RF09), modo convidado quando não há
  perfil correspondente (RF10).
- **Fase 3 (parcial):** Body Score agregado 10–100 no cartão principal,
  notificação desktop "de quem é essa pesagem?" quando o RF08 fica ambíguo,
  e leitura sem impedância agora grava o peso mesmo assim em vez de
  descartar a medição inteira (PRD seção 13, sugestão "modo apenas peso").

**Adiado, não implementado** — os dois itens restantes da seção 13 do PRD
exigiriam replicar comportamento específico do `openScale` (GPL-3.0) sem uma
fonte independente para verificar contra o código real, o que conflita com a
postura de licenciamento da seção 3 e com o princípio de reprodutibilidade
do próprio PRD (seção 17: nada é portado sem conferir contra o código-fonte
real). Ver `THIRD_PARTY_NOTICES.md` para o detalhe de cada um:

- **Importação de histórico via GATT** — o protocolo de handshake
  (características BLE, sequência de comandos) só existe vendorizado no
  `MiScaleHandler.kt` do openScale; portá-lo tornaria o módulo
  efetivamente derivado de código GPL-3.0.
- **Exportação para openScale** — o formato de CSV do importador do
  openScale usa um esquema de colunas mais elaborado do que parecia à
  primeira vista (identidades de tipo de medição, não só nomes fixos de
  coluna); sem ler o arquivo fonte linha a linha (mesmo problema de
  licença acima) não dá pra garantir compatibilidade real.

## Licenciamento

Este projeto é **MIT** (ver `LICENSE`). Trata o `openScale` (GPL-3.0) como
referência de validação cruzada apenas — nenhum código dele é importado ou
distribuído. Atribuições completas e o que foi adaptado de cada repositório
de origem estão em `THIRD_PARTY_NOTICES.md`.

## Como rodar

Pré-requisitos: Python 3.11+, Bluetooth ligado, balança pareada/próxima.

```bash
python -m venv .venv
source .venv/Scripts/activate   # Windows (git-bash); no Linux: .venv/bin/activate
pip install -r requirements.txt
cp config.example.json config.json   # opcional — ajuste o MAC da balança se tiver mais de uma por perto
python main.py
```

Abra `http://127.0.0.1:8765`, cadastre pelo menos um perfil (altura, idade,
sexo, algoritmo) e suba na balança. O histórico e os perfis ficam salvos em
`miscale.db` (SQLite, na raiz do projeto — ignorado pelo git).

No Linux, se o scanner falhar por falta de permissão, dê a capability ao
interpretador em vez de rodar como root (RNF03):

```bash
sudo setcap 'cap_net_raw,cap_net_admin+eip' $(readlink -f $(which python3))
```

## Testes

```bash
pip install -r requirements-dev.txt
pytest
```

- `tests/test_xiaomi_engine.py` — motor Xiaomi por paridade numérica contra
  a classe `bodyMetrics` vendorizada (execução real, não comparação de
  memória).
- `tests/test_science_engine.py` — motor científico conferido contra uma
  segunda transcrição independente das fórmulas de `bodymiscale`.
- `tests/test_ble_scanner.py` — correção de bits do parser BLE (PRD seção 11).
- `tests/test_matching.py` — identificação de perfil por peso mais próximo
  (RF08), incluindo empate/ambiguidade.
- `tests/test_db.py` — persistência de perfis e medições (RF07).
- `tests/test_body_score.py` — Body Score, incluindo um caso conferido
  manualmente ponto a ponto contra a fórmula original.
- `tests/test_notifications.py` — notificação desktop nunca propaga exceção
  (a leitura da balança não pode travar por causa disso).
- `tests/test_server_integration.py` — fluxo completo BLE → WebSocket →
  confirmação de perfil → persistência, via `TestClient` e um hook de teste
  que injeta leituras sem precisar de balança física.

## Estrutura

```
app/
  ble_scanner.py       # RF01/RF02 — varredura passiva + decodificação do payload
  engine/
    common.py          # fórmulas compartilhadas entre os modos
    xiaomi.py           # RF03/RF06 — modo Xiaomi/Zepp Life
    science.py          # RF06 — modo Científico
    body_score.py       # PRD seção 13 — pontuação agregada 10–100
  db.py                 # RF07 — perfis e histórico (SQLite) + exportação CSV/JSON
  matching.py           # RF08 — identificação de perfil por peso mais próximo
  notifications.py      # PRD seção 13 — notificação desktop de ambiguidade
  server.py             # RF04/RF05/RF08/RF10 — FastAPI + WebSocket, serve o painel
web/                    # painel HTML/JS/CSS servido pelo próprio FastAPI
vendor/                 # código de terceiros, referência — ver THIRD_PARTY_NOTICES.md
```
