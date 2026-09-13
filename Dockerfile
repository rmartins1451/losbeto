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
COPY --from=nodebuild /usr/local/lib/node_modules /usr/local/lib/node_modules
COPY --from=pybuild /opt/venv /opt/venv

WORKDIR /app
COPY nexus_omega.py .
COPY start.sh .

# Ajustes finais:
# - symlink do acp recriado à mão, RELATIVO e exatamente como o npm -g faria.
#   NÃO usar COPY para o bin: o BuildKit dereferencia o symlink e copia o JS
#   como arquivo real em /usr/local/bin — o Node então resolve as deps a
#   partir de /usr/local/bin e morre com "Cannot find package 'dotenv'"
#   (bug visto em produção na v48.3.2; reproduzido e corrigido).
# - stub de xdg-open (o acp-cli tenta abrir browser no fluxo OAuth).
RUN ln -sf ../lib/node_modules/@virtuals-protocol/acp-cli/dist/bin/acp.js /usr/local/bin/acp \
 && ln -sf /usr/local/bin/acp /usr/bin/acp \
 && printf '#!/bin/sh\nexit 0\n' > /usr/local/bin/xdg-open \
 && chmod +x /usr/local/bin/xdg-open \
 && /usr/local/bin/acp --version

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

# Start via script commitado: o comando é a string fixa "sh /app/start.sh" —
# sem variável para o launcher expandir. Funciona COM ou SEM shell no runtime,
# e igualmente quando chamado pelo startCommand do railway.toml.
CMD ["sh", "/app/start.sh"]
