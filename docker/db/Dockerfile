# syntax=docker/dockerfile:1
# Camada de dados. O app usa SQLite (um arquivo, aberto pelo backend), então este serviço NÃO é um servidor de banco:
# ele é o guardião do volume persistente: backup diário consistente, verificação de integridade, retenção e restauração.
# Contexto de build = raiz do projeto (docker compose build).
FROM alpine:3.24

RUN apk upgrade --no-cache \
    && apk add --no-cache sqlite tzdata \
    && addgroup -S -g 10001 app && adduser -S -u 10001 -G app app \
    && mkdir -p /data /backups && chown app:app /data /backups

COPY --chmod=0755 docker/db/servico.sh docker/db/backup.sh docker/db/restaurar.sh docker/db/saude.sh /usr/local/bin/

USER app

ENV DB_FILE=/data/controle-gastos.db \
    BACKUP_DIR=/backups \
    BACKUP_HORAS=24 \
    BACKUP_RETENCAO_DIAS=30 \
    BACKUP_MINIMO=7

HEALTHCHECK --interval=60s --timeout=20s --start-period=30s --retries=3 CMD ["saude.sh"]

ENTRYPOINT ["servico.sh"]
