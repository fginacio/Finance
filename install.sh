#!/usr/bin/env bash
# Instalador do Controle de Gastos: clona o repositório, prepara o .env e sobe o Docker.
# Uso:  curl -fsSL https://raw.githubusercontent.com/fginacio/Finance/main/install.sh | bash
set -euo pipefail

REPO_URL="https://github.com/fginacio/Finance.git"
DEST="${CONTROLE_GASTOS_DIR:-controle-de-gastos}"

echo "==> Controle de Gastos: instalador"

if ! command -v docker >/dev/null 2>&1; then
    echo "Docker não encontrado. Instale primeiro: https://docs.docker.com/get-docker/" >&2
    exit 1
fi
if ! docker compose version >/dev/null 2>&1; then
    echo "Docker Compose (plugin 'docker compose') não encontrado. Atualize o Docker Desktop/Engine." >&2
    exit 1
fi

if [ -d "$DEST" ]; then
    echo "==> Pasta '$DEST' já existe: atualizando (git pull)"
    git -C "$DEST" pull --ff-only
else
    echo "==> Clonando em '$DEST'"
    git clone "$REPO_URL" "$DEST"
fi
cd "$DEST"

if [ ! -f .env ]; then
    cp .env.example .env
    echo "==> Criado .env a partir de .env.example (ajuste porta, fuso horário etc. se quiser)"
fi

echo "==> Subindo os contêineres (build na primeira vez pode levar alguns minutos)"
docker compose up -d --build

echo
echo "==> Pronto! Crie o primeiro usuário (o app começa fechado, sem ninguém cadastrado):"
echo "    cd $DEST"
echo "    docker compose exec backend python -m app.usuarios criar SEU_USUARIO --nome \"Seu Nome\""
echo
echo "Depois abra http://localhost:8080 (ou http://<ip-desta-maquina>:8080 de outro aparelho na rede)."
