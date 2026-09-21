#!/bin/sh
# Healthcheck do serviço db: o banco (se já existir) está íntegro e a pasta de backups é gravável.
set -eu
DB_FILE="${DB_FILE:-/data/controle-gastos.db}"
BACKUP_DIR="${BACKUP_DIR:-/backups}"

[ -w "$BACKUP_DIR" ] || { echo "pasta de backups sem permissão de escrita"; exit 1; }
[ -f "$DB_FILE" ] || exit 0   # o backend ainda não criou o banco: saudável, só aguardando
[ "$(sqlite3 "$DB_FILE" '.timeout 8000' 'PRAGMA quick_check;' | head -n 1)" = "ok" ] || { echo "banco com problema de integridade"; exit 1; }
