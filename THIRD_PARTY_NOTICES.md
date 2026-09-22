# Avisos de terceiros

O MiScale Analytics Desktop reutiliza lógica de três projetos open-source, mapeados
no PRD (seção 2). Postura de licenciamento adotada (PRD seção 3):

- **openScale (GPL-3.0) é usado apenas como referência de validação cruzada.**
  Nenhuma linha de `BodyMiScaleLib.kt` ou `MiScaleHandler.kt` foi copiada ou
  traduzida para este projeto — suas fórmulas foram usadas apenas para confirmar,
  de forma independente, as fórmulas e a correção de bits do parser BLE já
  presentes em `xiaomi_mi_scale` (MIT) e `bodymiscale` (Apache-2.0). O código
  vendorizado em `vendor/oliexdev_openScale/` permanece sob GPL-3.0 e não é
  importado por nenhum módulo de `app/`.

## lolouk44/xiaomi_mi_scale — MIT

Copyright (c) 2020 lolouk44
https://github.com/lolouk44/xiaomi_mi_scale
Commit de referência: `e9db989d21b23602a462338a285478658cbaa13`

`app/engine/xiaomi.py` é um port direto da classe `bodyMetrics` de
`src/Xiaomi_Scale_Body_Metrics.py`. Mudanças feitas em relação ao original:

- Convertido de classe com métodos `get*()` em CamelCase para funções puras
  em `snake_case`, operando sobre um `dataclass` de entrada/saída.
- `exit()` nas validações de limite (altura/peso/idade/impedância) substituído
  por uma exceção (`OutOfRangeReading`), capturada pela camada de scanner —
  ver RNF06 do PRD: uma leitura ruim não pode derrubar o processo.
- Demais fórmulas e constantes numéricas mantidas inalteradas.

`app/ble_scanner.py` usa a mesma leitura de byte de controle (`payload[1]`
para estabilizado/impedância-válida) confirmada em `src/Xiaomi_Scale.py`,
função `callback()` — ver PRD seção 11, item 5.

## dckiller51/bodymiscale — Apache-2.0

Copyright (c) dckiller51 e contribuidores
https://github.com/dckiller51/bodymiscale
Commit de referência: `684a5b99b621845e25e523f7e9261231d4ba725`

Vendorizado sem edição de fórmulas em `vendor/dckiller51_bodymiscale/`. Três
correções de sintaxe Python 2 → 3 foram aplicadas diretamente no fork
vendorizado (arquivo original tinha um bug que impedia a importação em
Python 3):

- `custom_components/bodymiscale/util.py`, linhas 27 e 119:
  `except ValueError, TypeError:` → `except (ValueError, TypeError):`
- `custom_components/bodymiscale/profile.py`, linha 121: idem.

`app/engine/science.py` (modo "Científico", RF06) e as funções
compartilhadas em `app/engine/common.py` são um port das fórmulas
mono-frequência de `custom_components/bodymiscale/metrics/impedance.py`,
`metrics/weight.py` e `util.py::get_bmr_schofield`. Mudanças feitas em
relação ao original:

- O componente Home Assistant inteiro (entidades, sensores, filtros de
  perfil) não foi portado — só as funções puras de cálculo.
- O modo dual-frequência S400 não foi portado (fica para a Fase 3).
- Assinaturas convertidas de `Mapping[Metric, ...]` (modelo de estado do
  HA) para o mesmo `dataclass` de entrada usado pelo modo Xiaomi.
- Mesma troca de `exit()`/validação por `OutOfRangeReading` do modo Xiaomi.
- Constantes numéricas e lógica de clamp mantidas inalteradas.

`app/matching.py` é uma reimplementação enxuta da ideia do
`NearestWeightFilter` de `custom_components/bodymiscale/profile.py` —
mesmo algoritmo (distância até o último peso conhecido, dentro de uma
tolerância), reescrito sem a dependência do Home Assistant. Adaptado para
o motor de sugestão do PRD de cadastro/autenticação (RF04): em vez de
autoatribuir a medição a um único perfil, retorna até 3 candidatos para o
cliente escolher e confirmar com PIN — a decisão de identidade nunca é
automática nesse fluxo.

`app/engine/body_score.py` (PRD seção 13, sugestão 1) é um port de
`metrics/body_score.py` e `metrics/scale.py` — as oito funções de penalidade
e as tabelas de referência de %gordura/massa muscular por idade/altura/sexo
foram transcritas sem alteração de fórmula, inclusive onde um ramo do `if`
original é inalcançável (ver comentário no topo do arquivo — fidelidade ao
publicado, não "correção" não solicitada). O ramo S400 (massa muscular
esquelética) não foi portado, já que este projeto não implementa o modo
dual-frequência.

## oliexdev/openScale — GPL-3.0 (referência apenas, não vendorizado no build)

Copyright (C) olie.xdev
https://github.com/oliexdev/openScale
Commit de referência: `e79e8005ed64826b7f31c2910f0fa01313e2051`

Mantido em `vendor/oliexdev_openScale/` só para consulta humana e para os
testes de referência cruzada do PRD. Nenhum código deste repositório é
importado, compilado ou empacotado com o MiScale Analytics Desktop.

### Itens da Fase 3 (PRD seção 13) deliberadamente não implementados

Dois itens sugeridos na seção 13 do PRD foram avaliados e **adiados**, não
por falta de tempo, mas porque implementá-los direito exigiria uma fonte
que este projeto não tem à disposição sem esbarrar na postura de
licenciamento acima:

- **Importação de histórico via GATT.** O protocolo (UUIDs de
  característica, sequência de handshake, formato dos frames de histórico
  de 10 bytes) só está vendorizado em `MiScaleHandler.kt`
  (`vendor/oliexdev_openScale/libs/`), GPL-3.0. As fórmulas de composição
  corporal puderam ser portadas porque são independentemente reproduzíveis
  a partir do `bodymiscale` (Apache-2.0); esse protocolo de conexão GATT
  específico, não. Portá-lo tornaria `app/ble_scanner.py` um trabalho
  derivado do openScale.
- **Exportação para o formato CSV do openScale.** Uma consulta ao código-fonte
  público (`ImportExportUseCases.kt`, mesmo repositório) mostrou que o
  importador usa um esquema de colunas baseado em "identidade" do tipo de
  medição, não uma lista fixa de cabeçalhos — mais elaborado do que a
  sugestão original do PRD supunha. Reproduzir isso com confiança exigiria
  ler esse arquivo linha a linha, o que teria o mesmo problema de licença
  do item acima.

Se algum desses for necessário no futuro, os caminhos razoáveis são: (a)
aceitar GPL-3.0 para um módulo opcional isolado que só cuida dessa
integração, ou (b) reverse-engineering independente direto do tráfego BLE
da balança / do formato de arquivo, sem consultar o código do openScale.

## Sistema de cadastro e autenticação — decisões de produto

O PRD de cadastro/login (CPF ou telefone + PIN, quiosque, painel
administrativo) substituiu o sistema de perfis das Fases 1–3. Três pontos
do PRD original foram implementados de forma diferente do especificado,
por decisão explícita do dono do produto (não por limitação técnica):

- **RF05 (recuperação de PIN por SMS/WhatsApp) → reset manual pelo admin.**
  Integrar um provedor de SMS/WhatsApp (Twilio, Zenvia, WhatsApp Business
  API) tem custo recorrente, exige credenciais de uma conta de terceiros e
  quebraria a operação 100% offline do resto do app. `POST
  /api/admin/clients/{id}/reset-pin` cobre o mesmo caso de uso (cliente
  esqueceu o PIN) sem nenhuma dessas dependências.
- **RNF02 (criptografia em repouso) → adiado, documentado como
  pendência.** `miscale.db` fica em SQLite comum, sem criptografia. Uma
  implementação futura provavelmente usaria SQLCipher (troca de driver,
  chave de criptografia gerenciada localmente) — não implementado ainda.
  Até lá, o controle de acesso é físico: restrinja quem chega perto do
  computador que roda o servidor.
- **RF01/RF03 (teclado numérico virtual na tela) → teclado físico USB.**
  O hardware real é um teclado numérico USB plugado no computador do
  servidor, não uma tela touch — então não existe teclado virtual
  desenhado na página; os campos de CPF/telefone e PIN recebem o evento de
  teclado físico normalmente. Como consequência, o cadastro de cliente
  (RF02) — que precisa de um campo de texto para o nome completo — não
  acontece no quiosque público, e sim no painel administrativo (`/admin`),
  a única tela pensada para mouse e teclado completo.
