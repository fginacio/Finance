# Testes automatizados

Suíte pytest. Cada teste roda num banco SQLite novo, em arquivo temporário — nunca no banco
real (`data/controle-gastos.db` local ou o volume do Docker).

## Rodar

```
pip install -r requirements-dev.txt
python -m pytest tests/ -v
```

## O que tem hoje

- `test_autenticacao.py` — login, cookie de sessão, bloqueio após 5 tentativas, proteção contra
  POST de outra origem, e a checagem de que **toda rota nova continua exigindo login** (varre
  `app.routes` e testa cada uma sem sessão).
- `test_relatorios.py` — período configurável (1/3/6/12 meses), linhas zeradas somem das tabelas,
  a coluna "Real/orç." usa o orçamento do mês (não do período), e os cards do topo comparam
  sempre com o mês anterior de verdade, mesmo com período de 1 mês.
- `test_avisos.py` — alerta de orçamento estourado (só dispara ao cruzar a linha, não a cada compra
  seguinte já estourada), alerta de gasto alto (só para lançamento novo, respeita o limiar 0 = desligado),
  e o lembrete de conta pendente (só nos dias certos: 3/1/0 antes do vencimento e todo dia se vencida).
- `test_boleto.py` — parser da linha digitável (boleto bancário de 47 dígitos e conta de consumo/convênio
  de 48), incluindo os dígitos verificadores e a extração do valor/vencimento.
- `test_rotas_boleto.py` — upload de PDF em `/lancamentos/boleto/arquivo` (extração da linha digitável do
  texto do PDF) e leitura da linha colada em `/lancamentos/boleto`.
- `test_rotas_importacao_debito.py` — reconhecimento de "débito automático" no texto de uma fatura
  importada e o efeito na forma de pagamento gravada.

## Ao adicionar uma rota ou tela nova

Rode a suíte antes de publicar (`docker compose up -d --build`). `test_todas_as_rotas_exigem_login`
falha sozinho se uma rota nova ficar sem proteção — não precisa lembrar de testar isso à mão.

## Cobertura ainda pendente

Autenticação, relatórios e os avisos do Telegram têm testes automatizados. Importação de
extrato/fatura, duplicidades, cadastros, dashboard e cartões ainda não têm — ao mexer numa
dessas áreas, é um bom momento para escrever o teste correspondente.
