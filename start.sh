#!/bin/sh
# ============================================================================
# Losbeto — start.sh (v48.3.4 → v48.22.1-TIMEOUT)
# Por que existe: o Railway executa o startCommand do railway.toml SEM shell
# quando o builder é Dockerfile — então "$PORT" chegava literal ao gunicorn
# ("'$PORT' is not a valid port number") e o container morria em loop.
# Com este script, o comando de arranque é a string fixa "sh /app/start.sh"
# (sem variável nenhuma) e a expansão acontece AQUI DENTRO, com certeza.
# O "exec" faz o gunicorn herdar o PID: SIGTERM do Railway chega direto nele
# (graceful shutdown de 20s funciona de verdade).
# v48.3.4: "2>&1" funde o stderr no stdout — o gunicorn escreve logs de INFO
# no stderr por padrão e o Railway classificava tudo como [error] no painel
# ("Starting gunicorn", "Booting worker"...). Erros de verdade (tracebacks)
# continuam visíveis iguais — só muda a cor da etiqueta.
# v48.22.1-TIMEOUT: --timeout 45 → 120. Motivo: 2 WORKER TIMEOUT no dia
# 08/out (13:37 e 20:49, SIGKILL pid 184). Não é OOM — é request legítima
# cruzando 45s no pior caso: cadeia LLM com provider lento (gemini medido a
# 12-15s) + retry + fallback empilha; /agent-call com rerank ONNX no 1º uso
# após recycle do --max-requests também. Com 4 workers e ~1 req/s de média,
# um worker ocupado 120s não degrada o serviço; worker morto no meio de uma
# venda paga, sim. graceful-timeout e keep-alive inalterados.
# ============================================================================
# Ativa o venv se ele existir — no build Dockerfile o PATH já traz o venv
# (ativo redundante, inócuo); no rollback via nixpacks, é o que coloca o
# gunicorn no PATH. Cobre os dois mundos com o mesmo arquivo.
if [ -f /opt/venv/bin/activate ]; then . /opt/venv/bin/activate; fi
exec gunicorn --worker-class sync --workers 4 --preload --timeout 120 --graceful-timeout 20 --keep-alive 30 --max-requests 5000 --max-requests-jitter 500 --bind 0.0.0.0:${PORT:-8080} nexus_omega:app 2>&1
