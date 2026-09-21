# syntax=docker/dockerfile:1
# Backend: FastAPI + SQLite (arquivo no volume /app/data). Alpine: imagem pequena.
# Contexto de build = raiz do projeto (docker compose build).
# Para receber correções de segurança do sistema e do Python: docker compose build --pull  (scripts/atualizar.ps1).
FROM python:3.13-alpine

ENV PYTHONDONTWRITEBYTECODE=1     PYTHONUNBUFFERED=1     PIP_NO_CACHE_DIR=1     PIP_DISABLE_PIP_VERSION_CHECK=1     DATABASE_PATH=/app/data/controle-gastos.db

WORKDIR /app

# Sistema atualizado + usuário sem privilégios (uid fixo: o volume de dados e o serviço db usam o mesmo).
RUN apk upgrade --no-cache     && apk add --no-cache tzdata     && addgroup -S -g 10001 app && adduser -S -u 10001 -G app -h /app app

# Versões exatas e auditadas (requirements.lock). Depois da instalação o pip é REMOVIDO da imagem: o app não
# precisa dele em execução, e ele traz cópias embutidas (msgpack, setuptools) que aparecem em varreduras.
COPY requirements.lock .
RUN pip install -r requirements.lock     ; pip uninstall -y pip setuptools wheel >/dev/null 2>&1     ; rm -rf /usr/local/lib/python3.13/ensurepip /usr/local/lib/python3.13/site-packages/pip              /usr/local/lib/python3.13/site-packages/pip-*.dist-info /usr/local/bin/pip /usr/local/bin/pip3 /usr/local/bin/pip3.13     ; python -c "import fastapi, uvicorn, pypdf, openpyxl, cryptography"

COPY app ./app
COPY database ./database

# /app/data pertence ao usuário app: o volume nomeado herda esse dono na primeira montagem.
RUN mkdir -p /app/data && chown -R app:app /app/data
USER app

EXPOSE 8000

# /login é público e não depende de nada além do app e do banco.
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=3     CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/login', timeout=4)" || exit 1

# --proxy-headers: confia no nginx (rede interna) para enviar o IP e o protocolo reais (http/https).
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
