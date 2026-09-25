# Instalador do Controle de Gastos: clona o repositorio, prepara o .env e sobe o Docker.
# Uso:  iwr -useb https://raw.githubusercontent.com/fginacio/Finance/main/install.ps1 | iex
$ErrorActionPreference = "Stop"

$RepoUrl = "https://github.com/fginacio/Finance.git"
$Dest = if ($env:CONTROLE_GASTOS_DIR) { $env:CONTROLE_GASTOS_DIR } else { "controle-de-gastos" }

Write-Host "==> Controle de Gastos: instalador"

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Error "Docker nao encontrado. Instale primeiro: https://docs.docker.com/get-docker/"
    exit 1
}
try { docker compose version | Out-Null } catch {
    Write-Error "Docker Compose ('docker compose') nao encontrado. Atualize o Docker Desktop."
    exit 1
}

if (Test-Path $Dest) {
    Write-Host "==> Pasta '$Dest' ja existe: atualizando (git pull)"
    git -C $Dest pull --ff-only
} else {
    Write-Host "==> Clonando em '$Dest'"
    git clone $RepoUrl $Dest
}
Set-Location $Dest

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "==> Criado .env a partir de .env.example (ajuste porta, fuso horario etc. se quiser)"
}

Write-Host "==> Subindo os conteineres (build na primeira vez pode levar alguns minutos)"
docker compose up -d --build

Write-Host ""
Write-Host "==> Pronto! Crie o primeiro usuario (o app comeca fechado, sem ninguem cadastrado):"
Write-Host "    cd $Dest"
Write-Host '    docker compose exec backend python -m app.usuarios criar SEU_USUARIO --nome "Seu Nome"'
Write-Host ""
Write-Host "Depois abra http://localhost:8080 (ou http://<ip-desta-maquina>:8080 de outro aparelho na rede)."
