# Lembrete no Telegram de contas pendentes perto do vencimento (app/lembretes.py). Agendar diariamente.
# Uso: .\scripts\lembretes.ps1
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)
docker compose exec -T backend python -m app.lembretes
