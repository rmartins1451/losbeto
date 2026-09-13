#!/bin/sh
# ============================================================================
# Losbeto — start.sh (v48.3.4)
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
# ============================================================================
# Ativa o venv se ele existir — no build Dockerfile o PATH já traz o venv
# (ativo redundante, inócuo); no rollback via nixpacks, é o que coloca o
# gunicorn no PATH. Cobre os dois mundos com o mesmo arquivo.
if [ -f /opt/venv/bin/activate ]; then . /opt/venv/bin/activate; fi
exec gunicorn --worker-class sync --workers 4 --preload --timeout 45 --graceful-timeout 20 --keep-alive 30 --max-requests 5000 --max-requests-jitter 500 --bind 0.0.0.0:${PORT:-8080} nexus_omega:app 2>&1
