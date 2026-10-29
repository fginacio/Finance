# Atualiza o sistema: baixa as bases novas, reconstrói as imagens e reinicia SEM apagar dados.
# Uso:  .\scripts\atualizar.ps1            (imagens: Alpine, Python, nginx e correções do sistema)
#       .\scripts\atualizar.ps1 -Bibliotecas   (também refaz requirements.lock e audita antes)
param([switch]$Bibliotecas)
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

Write-Host "1/4 Backup do banco..."
docker compose exec db backup.sh

if ($Bibliotecas) {
    Write-Host "Atualizando bibliotecas Python (requirements.lock)..."
    # Dois ambientes separados: um só com o app (o freeze vira o lock) e outro só com o pip-audit. No mesmo ambiente, o
    # freeze levaria para o lock as dependências do próprio pip-audit (requests, rich...), que o app não usa.
    $app = Join-Path $env:TEMP "cg-venv"
    $aud = Join-Path $env:TEMP "cg-venv-audit"
    foreach ($v in $app, $aud) { if (Test-Path $v) { Remove-Item $v -Recurse -Force }; python -m venv $v }
    & "$app\Scripts\python.exe" -m pip install -q -r requirements.txt
    & "$aud\Scripts\python.exe" -m pip install -q pip-audit
    # só ASCII nas mensagens: o PowerShell 5 lê este .ps1 (UTF-8 sem BOM) como ANSI e estragaria os acentos
    $cab = "# Versoes EXATAS auditadas (pip-audit sem vulnerabilidades em $(Get-Date -Format yyyy-MM-dd)). O Docker instala DESTE arquivo.`n" +
           "# Para atualizar: scripts/atualizar.ps1 -Bibliotecas  (refaz este arquivo a partir de requirements.txt e audita)."
    $pac = & "$app\Scripts\python.exe" -m pip freeze --all --exclude pip --exclude setuptools
    $novo = Join-Path $env:TEMP "cg-requirements.lock"
    # UTF-8 sem BOM (o Set-Content -Encoding utf8 do PowerShell 5 grava BOM)
    [IO.File]::WriteAllText($novo, $cab + "`n" + ($pac -join "`n") + "`n", (New-Object Text.UTF8Encoding $false))
    # audita as versões exatas que vão para a imagem (e não as faixas do requirements.txt); só então troca o lock
    & "$aud\Scripts\python.exe" -m pip_audit -r $novo --progress-spinner off
    if ($LASTEXITCODE -ne 0) { throw "pip-audit encontrou vulnerabilidades: revise antes de subir (requirements.lock nao foi alterado)." }
    Copy-Item $novo requirements.lock -Force
}

Write-Host "2/4 Reconstruindo imagens com bases atualizadas..."
docker compose build --pull
Write-Host "3/4 Reiniciando (volumes preservados)..."
docker compose up -d
Write-Host "4/4 Estado:"
docker compose ps
Write-Host "Concluido. Rode .\scripts\auditar.ps1 para conferir vulnerabilidades."
