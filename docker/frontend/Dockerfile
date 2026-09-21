# syntax=docker/dockerfile:1
# Frontend: nginx (sem root) na frente do backend. Serve /static direto e repassa o resto.
# Contexto de build = raiz do projeto (docker compose build).
# "stable-alpine" acompanha a linha estável do nginx (a 1.27 usada antes estava parada e tinha ~95 falhas conhecidas
# nas bibliotecas do sistema). Rebuild com --pull renova a base.
FROM nginxinc/nginx-unprivileged:stable-alpine

# Correções de segurança do sistema (o apk precisa de root; volta para o usuário sem privilégios em seguida).
USER root
RUN apk upgrade --no-cache
USER 101

# A imagem processa /etc/nginx/templates/*.template com envsubst na partida.
COPY docker/frontend/nginx.conf.template /etc/nginx/templates/default.conf.template
COPY docker/frontend/proxy_backend.conf /etc/nginx/proxy_backend.conf

# Os mesmos arquivos estáticos do backend (css, ícones), servidos sem passar pelo Python.
COPY app/static /usr/share/nginx/html/static

# Uma única variável define a porta: a mesma dentro do contêiner e no host (ver docker-compose.yml).
ENV APP_PORT=8080 \
    BACKEND_HOST=backend \
    BACKEND_PORT=8000

EXPOSE 8080

HEALTHCHECK --interval=15s --timeout=4s --start-period=10s --retries=3 \
    CMD wget -q -O /dev/null "http://127.0.0.1:${APP_PORT}/healthz" || exit 1
