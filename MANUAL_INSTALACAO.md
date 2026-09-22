# Manual de instalação — MiScale Analytics Desktop

Guia passo a passo para instalar e rodar o programa neste computador
Windows, escrito para quem nunca usou terminal antes. Também existe uma
versão com visual mais amigável (checklist, botão de copiar comando) — peça
o link se preferir usar aquela.

No fim deste manual você vai ter duas telas:

- **Painel de administrador** (`/admin`) — onde você cadastra clientes,
  reseta PIN esquecido e vê o histórico de cada um. Usa mouse e teclado
  normal.
- **Quiosque** (`/`) — a tela que fica ao lado da balança. O cliente digita
  CPF ou telefone num teclado numérico, depois o PIN de 4 dígitos, e sobe
  na balança.

Tempo estimado: ~15 minutos, a maior parte só na primeira vez.

## Antes de começar

- Bluetooth do computador **ligado** (Central de Ações, ícone de Bluetooth).
- A balança por perto, com pilha.
- Você **não** precisa parear a balança nas configurações do Windows — o
  programa encontra ela sozinho.

## Passo 1 — Abrir o PowerShell dentro da pasta do programa

Abra o **Explorador de Arquivos** e navegue até:

```
C:\Users\ralan\programa\balanca
```

Clique na barra de endereço lá em cima, apague o que está escrito, digite
`powershell` e pressione **Enter**. Uma janela azul/preta abre já dentro
dessa pasta — é essa janela que você vai usar até o fim do manual.

## Passo 2 — Conferir se o Python está instalado

```powershell
python --version
```

Se aparecer algo como `Python 3.13.14`, pule para o Passo 3.

Se der erro ("não é reconhecido"):

1. Vá em [python.org/downloads](https://www.python.org/downloads/) e baixe
   a versão para Windows.
2. Abra o instalador e **marque a caixinha "Add python.exe to PATH"** antes
   de clicar em instalar — é o passo que a maioria esquece.
3. Feche o PowerShell e repita o Passo 1 para abrir uma janela nova.

## Passo 3 — Instalar as peças que o programa precisa (usa internet)

Dois comandos, um de cada vez, `Enter` depois de cada um:

```powershell
python -m venv .venv
```

```powershell
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

O segundo comando baixa da internet e pode levar um ou dois minutos, com
várias linhas passando na tela — é normal.

## Passo 4 — Criar seu login de administrador

Só se faz **uma vez**:

```powershell
.venv\Scripts\python.exe main.py --create-admin
```

O programa pergunta um e-mail e uma senha (a senha não aparece na tela
enquanto você digita — é assim mesmo). Guarde essas duas informações: são
o seu login do painel de administrador. Ainda não existe recuperação
automática de senha — se perder, é só rodar este comando de novo com outro
e-mail para criar um segundo login (os clientes cadastrados continuam
intactos).

## Passo 5 — Ligar o programa

Confira se o Bluetooth está **ativado** (Configurações → Bluetooth e
dispositivos — em muitos PCs vem desligado por padrão), e rode:

```powershell
.venv\Scripts\python.exe main.py
```

A tela mostra algumas linhas de log — é o programa avisando que subiu.
**Deixe essa janela aberta** enquanto usa o programa; é ela que está
"escutando" a balança. Se o Windows perguntar se o Python pode acessar a
rede, clique em **Permitir**.

> **Erro "O dispositivo não está pronto para uso" / `WinError -2147020577`?**
> É o Bluetooth do Windows desligado. Ative-o (ícone de rede na bandeja do
> sistema, ou Configurações → Bluetooth e dispositivos) e rode o comando de
> novo. Não significa falta de hardware.

## Passo 6 — Entrar no painel de administrador

Abra o navegador em:

```
http://127.0.0.1:8765/admin
```

Entre com o e-mail e a senha do Passo 4.

## Passo 7 — Cadastrar o primeiro cliente

Clique em **+ Novo cliente** e preencha: nome completo, CPF ou telefone
(só números — vai ser o "login" da pessoa), data de nascimento, sexo,
altura, algoritmo e um **PIN inicial de 4 dígitos**.

- **Xiaomi/Zepp Life** — os mesmos números que o aplicativo oficial da
  Xiaomi mostraria.
- **Científico** — fórmulas baseadas em literatura médica; os números
  podem sair um pouco diferentes do app oficial.

Marque a caixinha confirmando que a pessoa aceitou o uso dos dados de
saúde dela, e clique em **Salvar**. Repita para cada cliente novo — esta é
a única etapa que precisa de teclado com letras, por isso fica no painel
do administrador, não na balança.

## Passo 8 — Testar o quiosque e pesar

Abra outra aba (ou o monitor que vai ficar ao lado da balança) em:

```
http://127.0.0.1:8765
```

Com essa página em foco, digite o CPF ou telefone do cliente — pode ser
num teclado numérico USB ou nos números do topo de um teclado comum, tanto
faz. Ao completar os dígitos, a tela pede o PIN de 4 números.

Depois do PIN certo, a pessoa pisa na balança descalça e fica parada até o
visor travar o número. Em alguns segundos, o resultado aparece: peso,
gordura, água e um placar de 10 a 100 chamado **Body Score**. Sem nenhum
toque, a tela volta sozinha ao início depois de 30 segundos.

> **Atalho:** se o cliente já pesou antes, basta subir na balança antes de
> digitar qualquer coisa — o programa reconhece o peso e sugere o nome dela
> na tela; é só tocar no nome e digitar o PIN.

## Passo 9 — Parar e usar de novo depois

Para **parar**, clique na janela do PowerShell e pressione `Ctrl+C`, ou
feche a janela.

Da próxima vez, você **não** precisa repetir os Passos 2, 3 e 4. Só:

1. Abrir o PowerShell na pasta do programa (Passo 1).
2. Rodar `.venv\Scripts\python.exe main.py` (Passo 5).
3. Abrir `http://127.0.0.1:8765` (quiosque) ou `/admin` (cadastro).

Todos os cadastros e o histórico de pesagens ficam em `miscale.db`, dentro
da pasta do programa — apague esse arquivo só se quiser começar do zero
(perde todos os clientes cadastrados).

## Perguntas e problemas comuns

**"python não é reconhecido como comando" mesmo depois de instalar**
Você provavelmente instalou sem marcar "Add python.exe to PATH".
Desinstale o Python pelo Painel de Controle, instale de novo marcando essa
caixinha, feche toda janela do PowerShell aberta e abra uma nova.

**O comando de instalar (Passo 3) trava ou dá erro**
Confira a internet — é o único passo que baixa algo da rede. Se der erro
no meio, rode o mesmo comando de novo; ele continua de onde parou.

**A página não abre no navegador**
Confira se a janela do PowerShell do Passo 5 ainda está aberta, mostrando
log sem mensagem vermelha de erro. Se fechou sem querer, volte ao Passo 5.

**O peso não muda na tela quando alguém sobe na balança**
Confira: Bluetooth ligado; balança com pilha e "acordada" (visor aceso); e
o aplicativo oficial Mi Fit / Zepp Life fechado no celular (ele pode
interferir na conexão).

**O cliente esqueceu o PIN**
Entre em `/admin`, ache o cliente na lista e clique em **Resetar PIN**.
Não precisa do PIN antigo.

**Não tenho teclado numérico separado**
Sem problema — os números do topo de um teclado comum funcionam igual na
tela do quiosque. Um numérico USB só é mais prático por ficar fixo ao lado
da balança.

**Esqueci o e-mail/senha do administrador**
Ainda não existe recuperação automática. Rode
`.venv\Scripts\python.exe main.py --create-admin` de novo para criar um
segundo login — os clientes já cadastrados continuam intactos.

**Quero recomeçar do zero**
Feche o PowerShell, apague a pasta `.venv` (é recriada sozinha) e volte ao
Passo 1. Para apagar também os clientes cadastrados, apague `miscale.db`.

---

MiScale Analytics Desktop roda inteiramente neste computador — os dados da
balança nunca saem dele.
