# MiScale Analytics Desktop

Aplicação local (Windows/Linux) que escuta os anúncios BLE da Xiaomi Mi Body
Composition Scale 2, identifica quem subiu na balança e calcula métricas de
composição corporal — sem nuvem, sem telemetria, tudo salvo neste computador.

Duas telas:

- **Quiosque** (`/`) — pensado para um monitor + teclado numérico USB ao
  lado da balança. Cliente digita CPF/telefone (ou toca num nome sugerido
  pelo peso), digita o PIN de 4 dígitos, sobe na balança e vê o resultado:
  peso e Body Score em destaque, um cartão por métrica com tendência frente
  à medição anterior, medidor abaixo/normal/acima (IMC, gordura, massa
  muscular, gordura visceral) e um mini-gráfico do histórico recente.
- **Administração** (`/admin`) — para o operador, num computador com mouse
  e teclado. Cadastra clientes, reseta PIN esquecido, vê histórico,
  exporta CSV/JSON, baixa o PDF de cada medição e gerencia fotos de
  evolução por cliente.

Cada medição gera automaticamente um PDF do resultado (`data/reports/`),
pronto para ser enviado depois — o canal de envio (e-mail, WhatsApp etc.)
ainda não está implementado, é a próxima etapa planejada.

## Como rodar

Pré-requisitos: Python 3.11+, Bluetooth ligado, balança por perto.

**Windows (PowerShell)** — não precisa "ativar" o venv; chame o Python de
dentro dele direto, assim nenhum passo depende de `source` (que não existe
no PowerShell) nem de política de execução de scripts:

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
copy config.example.json config.json   # opcional — ajuste o MAC da balança se tiver mais de uma por perto
```

Crie o primeiro administrador (só precisa fazer isso uma vez):

```powershell
.venv\Scripts\python.exe main.py --create-admin
```

Depois, suba o servidor normalmente:

```powershell
.venv\Scripts\python.exe main.py
```

**Linux/macOS (bash/zsh)** — aqui sim vale o padrão de ativar o venv:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp config.example.json config.json
python main.py --create-admin   # uma vez só
python main.py
```

Abra `http://127.0.0.1:8765/admin`, entre com o e-mail/senha que você criou
e cadastre o primeiro cliente (nome, CPF ou telefone, data de nascimento,
sexo, altura, algoritmo e um PIN inicial de 4 dígitos). Depois abra
`http://127.0.0.1:8765/` no monitor do quiosque — é lá que o cliente
digita o documento e o PIN no teclado numérico USB para se identificar e
subir na balança.

Todos os dados (clientes, PINs com hash, administradores, histórico de
medições) ficam em `miscale.db` (SQLite, na raiz do projeto — ignorado pelo
git). Os PDFs gerados e as fotos de evolução ficam em `data/` (também
ignorado pelo git).

No Linux, se o scanner BLE falhar por falta de permissão, dê a capability
ao interpretador em vez de rodar como root:

```bash
sudo setcap 'cap_net_raw,cap_net_admin+eip' $(readlink -f $(which python3))
```

## Segurança e privacidade — decisões tomadas

O sistema de cadastro/login segue o PRD de autenticação, com três desvios
deliberados em relação ao documento original (decisões do produto, não
limitações técnicas — ver `THIRD_PARTY_NOTICES.md` para o raciocínio
completo de cada uma):

- **PINs e senhas** são hasheados com bcrypt (nunca texto plano).
- **Recuperação de PIN** é feita pelo administrador no painel (`/admin` →
  Resetar PIN), não por SMS/WhatsApp — evita depender de um provedor
  externo pago e mantém o app 100% offline.
- **Criptografia em repouso do banco** (LGPD) foi avaliada e **adiada**:
  `miscale.db` fica em texto plano no disco. Restrinja o acesso físico e de
  rede ao computador do servidor até isso ser endereçado.
- **Foto de evolução** só existe no `/admin` (upload manual de arquivo,
  com suporte à câmera do dispositivo via `capture="environment"` quando o
  painel é aberto de um celular). O quiosque não tem câmera nem mouse para
  operar um upload — a tela de resultado só mostra um aviso "em breve".

## Testes

```powershell
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.venv\Scripts\python.exe -m pytest
```

(Linux/macOS com o venv ativado: `pip install -r requirements-dev.txt && pytest`.)

A suíte usa bcrypt de verdade (sem mock) nos testes de PIN/senha, então
rodar tudo leva cerca de um minuto — é o custo do hash, não um teste lento.

- `tests/test_xiaomi_engine.py`, `tests/test_science_engine.py` — os dois
  motores de bioimpedância, por paridade numérica contra as fórmulas de
  origem (não reimplementadas de memória).
- `tests/test_ble_scanner.py` — decodificação do payload BLE.
- `tests/test_body_score.py` — pontuação agregada 10–100.
- `tests/test_security.py` — hash de PIN/senha, validação de documento,
  expiração de sessão de admin.
- `tests/test_db.py` — persistência de clientes, admins, medições e fotos.
- `tests/test_matching.py` — motor de sugestão por peso.
- `tests/test_reference_ranges.py` — faixas abaixo/normal/acima do medidor.
- `tests/test_report.py` — geração do PDF (bytes válidos, com e sem impedância).
- `tests/test_server_integration.py` — fluxo completo via `TestClient`:
  login por documento ou sugestão, medição vinculada à sessão, timeout de
  inatividade, CRUD administrativo, RBAC, histórico do quiosque, PDF
  automático, upload/consulta/exclusão de fotos.

## Estrutura

```
app/
  ble_scanner.py         # varredura passiva BLE + decodificação do payload
  engine/
    common.py            # fórmulas compartilhadas entre os modos
    xiaomi.py             # modo Xiaomi/Zepp Life
    science.py             # modo Científico
    body_score.py          # pontuação agregada 10–100
    reference_ranges.py    # faixas abaixo/normal/acima do medidor visual e do PDF
  security.py             # hash de PIN/senha, validação de documento, sessão de admin
  db.py                   # clientes, admins, medições e fotos (SQLite) + exportação
  matching.py              # sugestão de cliente por peso mais próximo
  report.py                # geração automática do PDF de cada medição
  server.py                # FastAPI + WebSocket — quiosque e admin
web/
  index.html, app.js, style.css   # quiosque (resultado com medidor + tendência + histórico)
  admin.html, admin.js, admin.css # painel administrativo (CRUD, PDF, fotos)
vendor/                    # código de terceiros, referência — ver THIRD_PARTY_NOTICES.md
data/                      # gerado em runtime: PDFs (reports/) e fotos (photos/) — ignorado pelo git
```

## Histórico do projeto

O app nasceu de um primeiro PRD (varredura BLE + cálculo de composição
corporal + painel simples de perfis, sem autenticação) implementado em
quatro fases; um segundo PRD substituiu o sistema de perfis por este fluxo
de cadastro com CPF/telefone + PIN e painel administrativo. `THIRD_PARTY_NOTICES.md`
mantém a atribuição completa de cada fórmula/ideia portada dos repositórios
de origem (`lolouk44/xiaomi_mi_scale`, `dckiller51/bodymiscale`,
`oliexdev/openScale`), que continua valendo integralmente para o motor de
bioimpedância — só a camada de identidade/autenticação é nova.

## Licenciamento

Este projeto é **MIT** (ver `LICENSE`). Trata o `openScale` (GPL-3.0) como
referência de validação cruzada apenas — nenhum código dele é importado ou
distribuído. Atribuições completas em `THIRD_PARTY_NOTICES.md`.
