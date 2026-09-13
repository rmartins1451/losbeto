# syntax=docker/dockerfile:1
# ============================================================================
# Losbeto — Dockerfile próprio (substitui o build automático do nixpacks)
#
# Por que existe: o builder automático injeta TODAS as variáveis do serviço
# como ARG/ENV no Dockerfile gerado (24 alertas SecretsUsedInArgOrEnv) e os
# segredos ficam GRAVADOS na imagem final. Com Dockerfile próprio, o Railway
# só expõe ao build o que for declarado com ARG — aqui, nada. Em runtime,
# todas as variáveis do serviço continuam sendo injetadas normalmente:
# o app não muda absolutamente nada.
#
# Rollback: apagar/renomear este arquivo — o Railway volta ao nixpacks.toml.
# ============================================================================

# --- Estágio 1: dependências Python (gcc fica só neste estágio)
FROM python:3.11-slim-bookworm AS pybuild
RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential \
 && rm -rf /var/lib/apt/lists/*
COPY requirements.txt /tmp/requirements.txt
RUN python -m venv --copies /opt/venv \
 && /opt/venv/bin/pip install --no-cache-dir -r /tmp/requirements.txt

# --- Estágio 2: ACP CLI (agente Virtuals) sobre Node 22
FROM node:22-bookworm-slim AS nodebuild
RUN npm i -g @virtuals-protocol/acp-cli && which acp

# --- Imagem final: Python 3.11 + runtime Node (o ACP roda como subprocesso)
FROM python:3.11-slim-bookworm
COPY --from=nodebuild /usr/local/bin/node /usr/local/bin/node
COPY --from=nodebuild /usr/local/bin/acp /usr/local/bin/acp
COPY --from=nodebuild /usr/local/lib/node_modules /usr/local/lib/node_modules
COPY --from=pybuild /opt/venv /opt/venv

WORKDIR /app
COPY nexus_omega.py .

# Mesmos ajustes do nixpacks.toml: acp também em /usr/bin e stub de xdg-open
# (o acp-cli tenta abrir browser no fluxo OAuth; sem o stub ele quebra)
RUN ln -sf /usr/local/bin/acp /usr/bin/acp \
 && printf '#!/bin/sh\nexit 0\n' > /usr/local/bin/xdg-open \
 && chmod +x /usr/local/bin/xdg-open

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

# Start idêntico ao do nixpacks.toml, mas à prova de runtime:
# - exec form (JSON): o Railway NÃO envolve shell-form com /bin/sh -c como o
#   Docker faz — foi isso que derrubou o deploy ("'$PORT' is not a valid
#   port number": o gunicorn recebeu o texto literal '$PORT').
# - sh -c explícito: garante a expansão da porta em qualquer runtime.
# - ${PORT:-8080}: porta padrão se a variável não existir.
# - exec: o gunicorn vira o PID 1 e recebe o SIGTERM direto do Railway —
#   o graceful-timeout de 20s passa a funcionar de verdade.
CMD ["sh", "-c", "exec gunicorn --worker-class sync --workers 4 --preload --timeout 45 --graceful-timeout 20 --keep-alive 30 --max-requests 5000 --max-requests-jitter 500 --bind 0.0.0.0:${PORT:-8080} nexus_omega:app"]
