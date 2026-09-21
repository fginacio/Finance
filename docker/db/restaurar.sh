#!/bin/sh
# Restaura um backup sobre o banco atual (o banco atual é guardado antes). PARE o backend antes:
#   docker compose stop backend
#   docker compose run --rm db restaurar.sh controle-gastos-20260918-120000.db
#   docker compose start backend
# Sem argumento, lista os backups disponíveis.
set -eu
umask 077   # backups e banco só com acesso do dono
DB_FILE="${DB_FILE:-/data/controle-gastos.db}"
BACKUP_DIR="${BACKUP_DIR:-/backups}"

if [ $# -eq 0 ]; then
    echo "Backups disponíveis em $BACKUP_DIR:"
    ls -1t "$BACKUP_DIR" | grep '^controle-gastos-.*\.db$' || echo "(nenhum)"
    exit 0
fi

origem="$BACKUP_DIR/$(basename "$1")"
[ -f "$origem" ] || { echo "Backup não encontrado: $origem"; exit 1; }
[ "$(sqlite3 "$origem" 'PRAGMA integrity_check;' | head -n 1)" = "ok" ] || { echo "O backup escolhido não passou na verificação de integridade. Nada foi alterado."; exit 1; }

if [ -f "$DB_FILE" ]; then
    seguranca="$BACKUP_DIR/antes-da-restauracao-$(date +%Y%m%d-%H%M%S).db"
    sqlite3 "$DB_FILE" ".backup '$seguranca'"
    echo "Banco atual guardado em $seguranca"
fi
rm -f "$DB_FILE-journal" "$DB_FILE-wal" "$DB_FILE-shm"
cp "$origem" "$DB_FILE"
echo "Restaurado: $origem -> $DB_FILE. Agora inicie o backend: docker compose start backend"
