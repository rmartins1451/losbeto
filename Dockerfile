FROM python:3.11-slim

WORKDIR /app

# Instala dependências de sistema mínimas
RUN apt-get update && apt-get install -y --no-install-recommends gcc libffi-dev && rm -rf /var/lib/apt/lists/*

# Copia e instala Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copia a aplicação
COPY nexus_omega.py .

# Porta padrão do Railway
ENV PORT=8000
EXPOSE 8000

# Comando de start
CMD gunicorn --worker-class gthread --workers 2 --threads 6 --timeout 120 --graceful-timeout 30 --keep-alive 30 --max-requests 1000 --max-requests-jitter 100 --bind 0.0.0.0:$PORT nexus_omega:app
