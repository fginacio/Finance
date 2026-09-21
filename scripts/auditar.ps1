# Auditoria de seguranca: vulnerabilidades nas imagens (Trivy) e nas bibliotecas Python (pip-audit).
# Uso: .\scripts\auditar.ps1              (precisa do Docker rodando; roda a cada atualizacao ou mensalmente)
#      .\scripts\auditar.ps1 -Notificar   (tambem avisa no Telegram: tudo limpo ou o que encontrou)
param([switch]$Notificar)
$ErrorActionPreference = "Continue"
Set-Location (Split-Path $PSScriptRoot -Parent)
. (Join-Path $PSScriptRoot "notificar.ps1")
$achados = @()
foreach ($i in "backend", "frontend", "db") {
    Write-Host "== imagem $i (HIGH/CRITICAL)"
    docker run --rm -v /var/run/docker.sock:/var/run/docker.sock aquasec/trivy:latest image -q --severity HIGH,CRITICAL --ignore-unfixed --exit-code 1 "controle-gastos/${i}:latest"
    if ($LASTEXITCODE -ne 0) { $achados += "imagem $i" }
}
Write-Host "== bibliotecas Python"
docker run --rm -v "${PWD}:/src:ro" python:3.13-alpine sh -c "pip install -q pip-audit && pip-audit -r /src/requirements.lock --progress-spinner off"
if ($LASTEXITCODE -ne 0) { $achados += "bibliotecas Python" }
if ($Notificar) {
    if ($achados.Count -eq 0) { Enviar-Telegram "Controle de Gastos: auditoria mensal OK, nenhuma vulnerabilidade HIGH/CRITICAL." }
    else { Enviar-Telegram ("Controle de Gastos: auditoria encontrou vulnerabilidades em: " + ($achados -join ", ") + ". Rode scripts\atualizar.ps1.") }
}
