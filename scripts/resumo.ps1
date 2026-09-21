# Resumo do fechamento do mes anterior no Telegram (app/resumo.py). So age no dia 1; agendar diariamente
# e deixar o script decidir (mais simples que um gatilho mensal no Agendador de Tarefas).
# Uso: .\scripts\resumo.ps1
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)
docker compose exec -T backend python -m app.resumo
