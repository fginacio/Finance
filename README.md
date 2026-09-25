<p align="center">
  <img src="app/static/favicon.svg" alt="Controle de Gastos" width="72">
</p>

<h1 align="center">Controle de Gastos</h1>

<p align="center">
  <strong>App de controle financeiro pessoal/familiar, self-hosted — lançamentos, orçamentos, importação de extrato e avisos no Telegram</strong>
</p>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-blue.svg" alt="License: MIT"></a>
  <img src="https://img.shields.io/badge/Python-3.13-blue.svg" alt="Python 3.13">
  <img src="https://img.shields.io/badge/Docker-Compose-2496ED.svg" alt="Docker Compose">
  <a href="https://github.com/fginacio/Finance/actions/workflows/tests.yml"><img src="https://github.com/fginacio/Finance/actions/workflows/tests.yml/badge.svg" alt="Tests"></a>
  <a href="https://github.com/fginacio/Finance/stargazers"><img src="https://img.shields.io/github/stars/fginacio/Finance?style=social" alt="GitHub stars"></a>
</p>

<p align="center">
  <a href="#funcionalidades">Funcionalidades</a> &bull;
  <a href="#capturas-de-tela">Capturas de tela</a> &bull;
  <a href="#instalacao-docker">Instalar</a> &bull;
  <a href="#configuracao">Configuração</a> &bull;
  <a href="#guia-de-uso">Guia de uso</a> &bull;
  <a href="#avisos-no-telegram">Telegram</a> &bull;
  <a href="#testes">Testes</a>
</p>

---

App de controle financeiro pessoal/familiar: lançamentos, contas recorrentes, orçamento por categoria e por
pessoa, importação de extrato bancário e fatura de cartão, relatórios com gráficos e avisos no Telegram. Tema
claro/escuro conforme o sistema, visual inspirado no Windows 11 e layout dedicado para celular.

O banco começa **vazio**: nenhum usuário, categoria, cartão ou lançamento vem pré-carregado. Depois de instalar,
você cria o primeiro usuário e configura tudo pelas telas (veja [Primeiro acesso](#primeiro-acesso) e
[Guia de uso](#guia-de-uso)).

## Funcionalidades

- **Painel** do mês: total gasto, gastos essenciais, pendências, gasto x orçamento por pessoa e por categoria,
  cartões de crédito, vale alimentação/refeição e tendência dos últimos meses.
- **Relatórios**: resumo mensal com gráficos (período configurável: 1/3/6/12 meses) e análise (categorias que
  mais pesam, concentração por cartão, categorias estouradas), com filtro por pessoa.
- **Lançamentos**: criar, editar, duplicar, excluir.
- **Recorrentes**: cadastro de contas fixas mensais e geração dos lançamentos pendentes do mês com um clique;
  palavras-chave permitem reconhecê-los automaticamente em extratos/faturas importados.
- **Importação** de extrato bancário (OFX, CSV, XLSX, PDF) e faturas em PDF (inclusive com senha).
- **A validar**: tudo que vem de uma importação chega aqui destacado, pronto para categorizar, confirmar,
  conciliar ou excluir; o sistema aprende com o que você confirma.
- **Duplicidades**: varre os lançamentos atrás de gastos contados duas vezes (por exemplo, uma fatura em PDF e o
  pagamento correspondente aparecendo também no extrato).
- **Cadastros**: categorias (com orçamento mensal e se contam ou não no total), cartões de crédito,
  pessoas/titulares (cada uma com seu próprio orçamento), vale alimentação/refeição, parâmetros gerais e usuários
  do sistema.
- **Leitura de QR de nota fiscal**: fotografe o QR de uma nota e o formulário de lançamento abre preenchido com
  valor, data e estabelecimento.
- **Leitura de boleto/conta de consumo**: linha digitável colada, por PDF (extrai o texto) ou por foto do código
  de barras — veja [Ler boleto/conta de consumo](#ler-boletoconta-de-consumo).
- **Avisos no Telegram** (opcional): atividade em tempo real, orçamento estourado, gasto alto, contas perto do
  vencimento e resumo do fechamento do mês — veja [Avisos no Telegram](#avisos-no-telegram).
- **Login por usuário e senha**, com sessões, bloqueio após tentativas erradas e troca de senha.

## Stack

Python + FastAPI + SQLite (sem ORM) + Jinja2 + HTMX + Bootstrap, tudo servido localmente (sem CDN). Sem build de
JavaScript. `database/schema.sql` define a estrutura do banco; bancos já existentes são migrados
automaticamente na inicialização (`migrar_db()` em `app/database.py`).

## Capturas de tela

Telas com um banco recém-instalado e vazio:

| Lançamentos | Relatórios |
|---|---|
| ![Lançamentos](screenshots/1-lancamentos.png) | ![Relatórios](screenshots/2-relatorios.png) |
| **Recorrentes** | **Cadastros** |
| ![Recorrentes](screenshots/4-recorrentes.png) | ![Cadastros](screenshots/5-cadastros-categorias.png) |

## Instalação (Docker)

Pré-requisito: [Docker](https://docs.docker.com/get-docker/) instalado e rodando.

```bash
git clone <url-deste-repositorio>
cd controle-de-gastos
cp .env.example .env          # opcional: ajustar porta, fuso horário, retenção de backup
docker compose up -d --build
```

Isso sobe três serviços:

```
celular / PC  ->  frontend (nginx)  ->  backend (FastAPI)  ->  db (dados + backups)
                  porta 8080:8080       porta 8000, interna     volume persistente
                  (a única publicada)   só na rede do Compose
```

| Serviço | O que é |
|---|---|
| `frontend` | nginx: serve CSS/ícones, limita tentativas de login, aceita uploads até 25 MB e repassa o resto para o backend |
| `backend` | a aplicação FastAPI; nenhuma porta publicada diretamente no host |
| `db` | camada de dados: dono do volume do banco, faz **backup diário consistente**, confere integridade e aplica a retenção |

O banco é **SQLite** (um único arquivo, não um servidor); por isso o serviço `db` não roda um servidor de banco —
ele só guarda o volume e os backups. Tudo roda **como usuário sem privilégios**, com o sistema de arquivos do
backend somente leitura, exceto o volume de dados.

### Primeiro acesso

O aplicativo começa **fechado**: sem nenhum usuário cadastrado, ninguém entra. Crie o primeiro pelo terminal (a
senha é digitada sem aparecer na tela):

```bash
docker compose exec backend python -m app.usuarios criar joao --nome "João Silva"
```

Abra `http://localhost:8080` (ou `http://<ip-da-maquina>:8080` de outro aparelho na mesma rede) e entre com o
usuário e a senha criados.

A partir daí, cadastre tudo pelas telas (menu **Cadastros**): pessoas/titulares, categorias, cartões de crédito
e, se quiser, contas recorrentes. Veja o [Guia de uso](#guia-de-uso) abaixo.

### Rodando sem Docker (desenvolvimento)

```bash
python -m venv .venv
.venv\Scripts\activate            # Linux/Mac: source .venv/bin/activate
pip install -r requirements.txt

python -m app.usuarios criar joao --nome "João Silva"
uvicorn app.main:app --reload
```

Abra `http://localhost:8000`. O banco é criado em `data/controle-gastos.db` na primeira execução.

## Configuração

Variáveis de ambiente (`.env`, veja `.env.example`):

| Variável | Padrão | O que faz |
|---|---|---|
| `APP_PORT` | `8080` | Porta do app, a mesma no host e dentro do contêiner do frontend |
| `TZ` | `America/Sao_Paulo` | Fuso horário (define "hoje" e "mês atual") |
| `COOKIE_SECURE` | `0` | `1` quando o HTTPS termina na frente (um proxy); o cookie de sessão passa a exigir HTTPS |
| `ORIGENS_PERMITIDAS` | (vazio) | Outros `host:porta` aceitos nos envios de formulário, se houver um proxy com outro nome |
| `BACKUP_HORAS` | `24` | Intervalo entre backups automáticos do banco |
| `BACKUP_RETENCAO_DIAS` | `30` | Retenção de backups em dias (nunca menos que `BACKUP_MINIMO`) |
| `BACKUP_MINIMO` | `7` | Número mínimo de backups mantidos, mesmo além da janela de retenção |
| `NOTIFICAR_DETALHES` | `1` | `0` = os avisos no Telegram trazem só a categoria, sem valor nem descrição |
| `GASTO_ALTO` | `500` | Valor acima do qual um lançamento novo dispara um aviso extra no Telegram; `0` desliga |

## Autenticação

- **Login por usuário e senha**; a sessão fica guardada no servidor (cookie `HttpOnly` + `SameSite=Lax`).
  "Manter conectado" vale 30 dias; sem marcar, a sessão dura 12 horas.
- **Todas as rotas exigem login**, exceto `/login` e `/static`.
- **Senhas** com hash scrypt, mínimo de 8 caracteres. 5 tentativas erradas seguidas bloqueiam o usuário por 15
  minutos.
- Cada pessoa troca a própria senha em **Minha conta** (menu ☰ → Minha conta); isso encerra qualquer outra
  sessão aberta daquele usuário.
- **Gerenciar usuários**: *Cadastros → Usuários* (criar, redefinir senha, desativar) ou pelo terminal:

```bash
docker compose exec backend python -m app.usuarios listar
docker compose exec backend python -m app.usuarios senha joao       # redefine e encerra as sessões abertas
docker compose exec backend python -m app.usuarios desativar joao   # / ativar
```

- **POSTs de outra origem são recusados** (pelo cabeçalho `Origin`). Atrás de um proxy com outro nome, liste-o
  em `ORIGENS_PERMITIDAS`.
- **HTTPS**: em HTTP puro, a senha trafega sem criptografia. Para expor o app além de uma rede local confiável,
  coloque-o atrás de um proxy HTTPS (Caddy, nginx, Traefik) e defina `COOKIE_SECURE=1`.

## Guia de uso

- **Painel** (`/`): visão geral do mês selecionado — total gasto, quanto é essencial, o que está pendente, gasto
  x orçamento por pessoa e categoria, cartões de crédito e vale alimentação/refeição.
- **Lançamentos**: lista de gastos do período, com filtros. "Duplicar" cria um novo lançamento com os mesmos
  dados, útil para compras repetidas (ex.: mercado).
- **Importar**: suba um extrato (OFX/CSV/XLSX/PDF) ou uma fatura em PDF. Só as saídas do mês de referência são
  importadas; o que casar com a palavra-chave de um recorrente é vinculado automaticamente.
- **Revisar → A validar**: lançamentos vindos de uma importação, destacados para revisão. Cada um pode ser
  confirmado (com a categoria certa), conciliado com um lançamento existente ou excluído.
- **Revisar → Duplicidades**: possíveis gastos contados duas vezes (ex.: uma fatura de cartão importada e o
  pagamento dela aparecendo também no extrato). Escolha qual manter, ou marque como "gastos diferentes" se não
  for de fato uma duplicidade.
- **Relatórios**: aba *Resumo mensal* (tabelas por categoria/grupo/pessoa/cartão/banco/forma de pagamento, no
  período escolhido) e aba *Análise* (categorias que mais pesam, concentração por cartão, orçamentos
  estourados).
- **Configurações → Recorrentes**: gastos fixos mensais (aluguel, assinaturas, parcelas...). O botão "Gerar
  lançamentos do mês" cria um lançamento pendente para cada recorrente ativo que ainda não tem um no mês.
- **Configurações → Cadastros**:
  - **Categorias**: nome, grupo, se é essencial, orçamento mensal e se conta no total (desmarque para
    categorias como poupança/aplicações, que não devem contar como gasto).
  - **Cartões de crédito**: identificador, a pessoa dona do cartão, banco emissor e palavras-chave (ex.: os
    últimos dígitos do cartão) para reconhecê-lo em faturas e extratos importados.
  - **Titulares**: as pessoas que registram gastos, cada uma com seu próprio orçamento mensal (`0` = sem
    orçamento), acompanhado no painel.
  - **Vale alimentação/refeição**: cartões de benefício (um por pessoa), cada um com valor mensal e dia de
    recarga; gastos pagos com essa forma não contam no total (é benefício, não dinheiro).
  - **Parâmetros**: meta de economia mensal e outras configurações gerais.
  - **Usuários**: quem pode entrar no sistema (diferente de "titular": usuário é quem faz login; titular é de
    quem é o gasto — podem ou não ser a mesma pessoa).
- **Sobre**: versão instalada e notas de cada versão.

### Cartão de crédito: a fatura é a fonte

O gasto no cartão entra pelo **total da fatura importada** (categoria "Cartões de crédito"). Lançamentos
feitos à mão com forma de pagamento "Cartão de crédito" (inclusive recorrentes e notas lidas por QR) **não
somam** no total, para não contar duas vezes; na lista aparecem com a etiqueta "não soma · na fatura". Vale
para o painel, os relatórios, o orçamento por categoria e o total da lista.

### Ler boleto/conta de consumo

Em **+ Novo gasto**, além do QR da nota fiscal, um segundo card lê boleto bancário ou conta de consumo (água,
luz, gás, telefone) pela **linha digitável**, de três jeitos:

- **Colar a linha digitável** direto (sempre funciona; 47 dígitos = boleto, 48 = conta de consumo/convênio).
- **Subir o PDF**: o servidor extrai o texto (`pypdf`) e procura a linha digitável nele — funciona quando o
  PDF não é uma imagem escaneada.
- **Foto do código de barras**: decodificada no navegador (código de barras linear, diferente do QR).

O app calcula o valor e, para boleto bancário, o vencimento; confere os dígitos verificadores e avisa (sem
travar) se algo não bater. Nada é gravado até você conferir e salvar no formulário.

Na tela **Revisar faturas** (importação de PDFs em lote), o texto lido também é checado por sinais de
"débito automático"; se encontrar, uma caixa vem pré-marcada e, mantida marcada, o lançamento sai com essa
forma de pagamento em vez de "Boleto".

### Listas fixas em Cadastros

**Grupo** (categorias) e **Banco/Emissor** (cartões) são listas fechadas, definidas em `app/listas.py`. Para
adicionar um item novo, edite esse arquivo (ou abra uma issue/PR); um valor já salvo num registro continua
válido mesmo se depois for removido da lista.

## Avisos no Telegram

Funcionalidade opcional: sem um bot configurado, tudo fica desligado e o app funciona normalmente.

### Configurando o bot

1. No Telegram, fale com o **@BotFather** e mande `/newbot`. Escolha um nome e um usuário para o bot (precisa
   terminar em `bot`, ex.: `meus_gastos_bot`). Ele devolve um **token** — guarde-o.
2. Envie qualquer mensagem para o bot recém-criado (ou adicione-o a um grupo).
3. Descubra o **chat id**: abra `https://api.telegram.org/bot<TOKEN>/getUpdates` no navegador (trocando
   `<TOKEN>` pelo token do passo 1), depois de enviar a mensagem do passo 2; o campo `"chat":{"id": ...}` na
   resposta é o chat id.
4. Fora da pasta do projeto (para não entrar num backup, nem sincronizar se o projeto estiver numa pasta na
   nuvem como OneDrive/Dropbox), crie estes arquivos:
   - `%USERPROFILE%\.controle-gastos\telegram.token` (Windows) ou `~/.controle-gastos/telegram.token`
     (Linux/Mac): só o token, sem quebra de linha extra.
   - `...\telegram.chat`: só o chat id.

O `docker-compose.yml` já lê esses arquivos como *Docker secrets*. Reinicie o backend depois de criar os
arquivos: `docker compose up -d`.

### O que cada aviso faz

1. **Atividade** (tempo real): toda vez que alguém cria, altera ou exclui um lançamento. Mudanças em lote
   (importação, "gerar recorrentes") viram um único resumo em vez de uma mensagem por item.
   `NOTIFICAR_DETALHES=0` envia só a categoria, sem valor nem descrição.
2. **Orçamento estourado** (tempo real, junto com o aviso de atividade): quando um lançamento novo ou editado
   faz uma categoria passar do orçamento mensal. Dispara só no momento em que cruza a linha, não em toda
   compra seguinte que já está acima.
3. **Gasto alto** (tempo real): um lançamento novo com valor ≥ `GASTO_ALTO` (padrão R$ 500; `0` desliga).
4. **Contas perto do vencimento** (uma vez por dia): avisa 3 dias antes, 1 dia antes, no dia do vencimento e
   todo dia enquanto a conta ficar em aberto e vencida.
5. **Resumo do fechamento do mês** (uma vez por dia, só age no dia 1º): total do mês anterior, variação em
   relação ao mês retrasado, % do orçamento usado, categorias que estouraram e os maiores gastos do mês.

Os avisos 4 e 5 não têm agendador embutido no contêiner; rode-os periodicamente (cron, Agendador de Tarefas do
Windows, ou similar):

```bash
docker compose exec -T backend python -m app.lembretes   # todo dia
docker compose exec -T backend python -m app.resumo      # todo dia (só age no dia 1º)
```

No Windows, `scripts\lembretes.ps1` e `scripts\resumo.ps1` fazem essa chamada; um exemplo de agendamento com
o Agendador de Tarefas está nos comentários desses scripts.

## Backup e restauração

O serviço `db` faz backup automático a cada `BACKUP_HORAS` horas, confere a integridade de cada backup e
mantém `BACKUP_RETENCAO_DIAS` dias de histórico (nunca menos que `BACKUP_MINIMO` cópias).

```bash
docker compose exec db backup.sh                                # backup agora
docker compose run --rm db restaurar.sh                          # lista os backups disponíveis
docker compose cp db:/backups ./backups-locais                   # copia para sua máquina
```

**Restaurar** (o banco atual é salvo antes de ser sobrescrito):

```bash
docker compose stop backend
docker compose run --rm db restaurar.sh controle-gastos-AAAAMMDD-HHMMSS.db
docker compose start backend
```

### Backup extra fora do Docker (opcional, cifrado)

Além do backup dentro do volume, `scripts/backup-onedrive.ps1` (Windows) copia uma versão **cifrada** para a
pasta `backups/` do projeto — útil se essa pasta for sincronizada por um serviço de nuvem (OneDrive, Dropbox
etc.) como cópia externa. Antes da primeira execução, gere a senha de criptografia (só uma vez; fica guardada
fora da pasta do projeto e nunca aparece na tela):

```bash
.venv\Scripts\python.exe scripts\gerar_senha_backup.py
```

Para restaurar um backup cifrado: `scripts\cifrar_backup.py decifrar backups\<arquivo>.db.enc` gera o `.db`
ao lado, que pode então ser copiado para o volume e restaurado como acima.

## Manutenção e segurança (scripts do Windows)

Os scripts em `scripts/` (PowerShell e Python) são opcionais e voltados para quem administra uma instalação
Windows; em outros sistemas, use os comandos `docker compose` equivalentes direto ou adapte a lógica para
bash/cron.

- `atualizar.ps1`: reconstrói as imagens com as bases atualizadas (Alpine/Python/nginx) e reinicia sem perder
  dados (faz backup antes). Com `-Bibliotecas`, também audita e regenera o `requirements.lock`.
- `auditar.ps1`: varre as imagens atrás de vulnerabilidades (Trivy) e as dependências Python (pip-audit); com
  `-Notificar`, reporta o resultado pelo Telegram.
- `backup-onedrive.ps1`, `lembretes.ps1`, `resumo.ps1`: veja as seções acima.

As imagens de produção instalam as dependências travadas em `requirements.lock` (versões exatas, auditadas) e
não trazem o `pip`.

## Testes

```bash
pip install -r requirements-dev.txt
python -m pytest tests/ -v
```

Cada teste roda num banco SQLite temporário, isolado do real. Veja `tests/README.md`.

## Estrutura do projeto

```
/
├── app/
│   ├── main.py                  rotas do painel, lançamentos, recorrentes, relatórios e cadastros
│   ├── rotas_importacao.py      importar extrato/faturas e tela "A validar"
│   ├── rotas_duplicidades.py    tela "Verificar duplicidades"
│   ├── beneficios.py            vale alimentação/refeição: tabelas e cálculo do saldo
│   ├── rotas_beneficios.py      cadastro dos cartões de benefício e exclusão de usos
│   ├── rotas_auth.py            login, logout, minha conta, usuários
│   ├── autenticacao.py          sessões, proteção global das rotas, cabeçalhos de segurança
│   ├── seguranca.py             hash de senha (scrypt) e regras de senha
│   ├── avisos.py                avisos no Telegram (atividade, orçamento, gasto alto)
│   ├── lembretes.py             aviso de contas perto do vencimento (agendado)
│   ├── resumo.py                resumo do fechamento do mês (agendado)
│   ├── nota_fiscal.py           QR de nota fiscal: chave, consulta na Sefaz, memória por CNPJ
│   ├── rotas_nota.py            "Ler QR da nota" (em Novo lançamento)
│   ├── boleto.py                linha digitável de boleto/conta de consumo: parser e extração de texto de PDF
│   ├── rotas_boleto.py          "Ler linha digitável" / upload de PDF (em Novo lançamento)
│   ├── rotas_sobre.py           tela Sobre (versão e notas de versão)
│   ├── versao.py                versão do app e notas de versão
│   ├── usuarios.py              comando de terminal para usuários
│   ├── importacao.py            leitura de OFX/CSV/XLSX/PDF, detecção de PIX etc. (funções puras)
│   ├── duplicidades.py          pontuação de pares suspeitos
│   ├── relatorios.py            consultas dos relatórios (período, filtro por titular, dados do gráfico)
│   ├── database.py              conexão SQLite, criação e migração do banco
│   ├── templating.py            templates Jinja compartilhados
│   ├── templates/               telas (Jinja2)
│   └── static/                  custom.css (estilo Windows 11), icons/, vendor/ (bibliotecas locais)
├── database/
│   ├── schema.sql                estrutura das tabelas
│   └── seed.sql                  o banco começa vazio (só comentários)
├── docker/
│   ├── frontend/                 Dockerfile + nginx.conf.template + proxy_backend.conf
│   ├── backend/Dockerfile
│   └── db/                       Dockerfile + servico.sh, backup.sh, restaurar.sh, saude.sh
├── docker-compose.yml            frontend, backend e db (constrói as imagens a partir do código)
├── scripts/                      scripts opcionais de manutenção para Windows (veja a seção acima)
├── tests/                        suíte pytest
├── .env.example                  variáveis de ambiente documentadas
├── requirements.txt              dependências (faixas de versão)
├── requirements-dev.txt          dependências extras para rodar os testes
└── requirements.lock             versões exatas e auditadas (as imagens de produção instalam deste)
```

## Contribuindo

Issues e pull requests são bem-vindos. Antes de abrir um PR, rode a suíte de testes
(`python -m pytest tests/ -v`) e, se possível, o equivalente a `scripts/auditar.ps1` (`pip-audit`,
`trivy image`) para checar vulnerabilidades.

Se este projeto foi útil para você, considere dar uma ⭐ — ajuda outras pessoas a encontrá-lo.

## Licença

MIT — veja [LICENSE](LICENSE).
