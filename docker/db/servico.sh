#!/bin/sh
# Processo principal do serviço db: espera o banco existir e faz backup a cada BACKUP_HORAS horas.
# Com argumentos, executa o comando pedido (é o que permite "docker compose run --rm db restaurar.sh ...").
set -eu
umask 077   # backups e banco só com acesso do dono

if [ "$#" -gt 0 ]; then
    exec "$@"
fi

BACKUP_HORAS="${BACKUP_HORAS:-24}"
DB_FILE="${DB_FILE:-/data/controle-gastos.db}"
BACKUP_DIR="${BACKUP_DIR:-/backups}"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }
trap 'log "Encerrando."; exit 0' TERM INT

log "Serviço de dados iniciado. Banco: $DB_FILE | backups: $BACKUP_DIR a cada ${BACKUP_HORAS}h (retenção ${BACKUP_RETENCAO_DIAS:-30} dias, mínimo ${BACKUP_MINIMO:-7})."

esperar() { sleep "$1" & wait $!; }   # permite receber o sinal de parada durante a espera

while [ ! -f "$DB_FILE" ]; do
    log "Aguardando o backend criar o banco..."
    esperar 20
done

while true; do
    # Não repete o backup se o contêiner só foi reiniciado (já existe um recente).
    if [ -z "$(find "$BACKUP_DIR" -name 'controle-gastos-*.db' -mmin "-$((BACKUP_HORAS * 60))" 2>/dev/null | head -n 1)" ]; then
        backup.sh || log "O backup falhou; tentarei de novo no próximo ciclo."
    else
        log "Já existe backup recente; próximo ciclo em ${BACKUP_HORAS}h."
    fi
    esperar "$((BACKUP_HORAS * 3600))"
done
