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
    $tmp = Join-Path $env:TEMP "cg-venv"
    if (Test-Path $tmp) { Remove-Item $tmp -Recurse -Force }
    python -m venv $tmp
    & "$tmp\Scripts\python.exe" -m pip install -q -r requirements.txt pip-audit
    $cab = "# Versoes EXATAS auditadas ($(Get-Date -Format yyyy-MM-dd)). O Docker instala DESTE arquivo.`n# Para atualizar: scripts/atualizar.ps1 -Bibliotecas"
    $pac = & "$tmp\Scripts\python.exe" -m pip freeze --exclude pip-audit --exclude pip
    & "$tmp\Scripts\python.exe" -m pip_audit -r requirements.txt --progress-spinner off
    if ($LASTEXITCODE -ne 0) { throw "pip-audit encontrou vulnerabilidades: revise antes de subir." }
    Set-Content requirements.lock -Value ($cab + "`n" + ($pac -join "`n")) -Encoding utf8
}

Write-Host "2/4 Reconstruindo imagens com bases atualizadas..."
docker compose build --pull
Write-Host "3/4 Reiniciando (volumes preservados)..."
docker compose up -d
Write-Host "4/4 Estado:"
docker compose ps
Write-Host "Concluido. Rode .\scripts\auditar.ps1 para conferir vulnerabilidades."
