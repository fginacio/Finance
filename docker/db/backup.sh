#!/bin/sh
# Backup consistente do SQLite (usa a API de backup do SQLite: seguro com o app em uso) + verificação + retenção.
# Uso: backup.sh            (também chamado pelo serviço na rotina diária)
set -eu
umask 077   # backups e banco só com acesso do dono

DB_FILE="${DB_FILE:-/data/controle-gastos.db}"
BACKUP_DIR="${BACKUP_DIR:-/backups}"
RETENCAO="${BACKUP_RETENCAO_DIAS:-30}"
MINIMO="${BACKUP_MINIMO:-7}"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }

[ -f "$DB_FILE" ] || { log "Banco ainda não existe em $DB_FILE; nada a copiar."; exit 0; }

destino="$BACKUP_DIR/controle-gastos-$(date +%Y%m%d-%H%M%S).db"
sqlite3 "$DB_FILE" ".timeout 15000" ".backup '$destino'"

resultado="$(sqlite3 "$destino" 'PRAGMA integrity_check;' | head -n 1)"
if [ "$resultado" != "ok" ]; then
    mv "$destino" "$destino.CORROMPIDO"
    log "ERRO: o backup não passou na verificação de integridade ($resultado). Guardado como $destino.CORROMPIDO"
    exit 1
fi
log "Backup criado: $destino ($(du -h "$destino" | cut -f1)), integridade ok."

# Retenção: apaga o que passou de RETENCAO dias, mas nunca deixa menos que MINIMO backups.
total="$(ls -1 "$BACKUP_DIR"/controle-gastos-*.db 2>/dev/null | wc -l)"
if [ "$total" -gt "$MINIMO" ]; then
    find "$BACKUP_DIR" -name 'controle-gastos-*.db' -mtime "+$RETENCAO" | sort | head -n "$((total - MINIMO))" | while read -r antigo; do
        rm -f "$antigo" && log "Backup antigo removido: $antigo"
    done
fi
