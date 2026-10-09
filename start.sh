#!/bin/sh
# ============================================================================
# Losbeto — start.sh (v48.3.4 → v48.23.0-FORKSAFE)
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
# v48.22.2-MAXREQ: --max-requests 5000 → 30000 (jitter 500 → 3000). Motivo:
# com ~62 mil probes/dia, cada worker batia 5000 requests em ~7h e fazia
# graceful restart ~3x/dia — e os logs de 09/out (07:18–07:31) mostram o
# worker TRAVANDO no encerramento do interpretador (SIGSEGV/SIGABRT de
# biblioteca nativa no teardown, típico de ONNX/gRPC com threads vivas) e o
# arbiter matando por timeout 120s: 4 dos 6 CRITICALs do dia vieram disso,
# não de venda. Restart ~6x mais raro (1x a cada ~2 dias por worker) corta
# ~85% desse ruído e continua limitando crescimento de memória.
# v48.23.0-FORKSAFE: hook post_fork via config GERADA AQUI (sem arquivo novo
# no repo — o Dockerfile só copia nexus_omega.py e start.sh). Por quê: com
# --preload, o import do nexus acontece no ARBITER; na v48.22 ~25 threads de
# background nasciam lá e o fork deixava locks herdados travados nos workers
# (2 de 4 congelavam ~30s após cada deploy → WORKER TIMEOUT 120s — padrão
# 00:03/00:18 de 09/out). O gunicorn recomenda iniciar threads no post_fork.
# Agora o nexus v48.23 não cria thread nenhuma no import e sobe tudo em
# post_fork_boot() — chamado por este hook em CADA worker após o fork (com
# fallback na 1ª request, caso o hook não exista). Se o hook falhar, o nó
# sobe igual: só os loops de fundo dependeriam do fallback — por isso o
# "|| true" nunca é usado aqui: config inválida deve derrubar o boot e
# aparecer no log, nunca passar em silêncio.
# ============================================================================
# Ativa o venv se ele existir — no build Dockerfile o PATH já traz o venv
# (ativo redundante, inócuo); no rollback via nixpacks, é o que coloca o
# gunicorn no PATH. Cobre os dois mundos com o mesmo arquivo.
if [ -f /opt/venv/bin/activate ]; then . /opt/venv/bin/activate; fi

# Config do gunicorn gerada em runtime (o repo não precisa de arquivo extra):
# hook post_fork → nexus_omega.post_fork_boot() em cada worker, pós-fork.
cat > /tmp/gunicorn_conf.py <<'PYEOF'
def post_fork(server, worker):
    import nexus_omega
    nexus_omega.post_fork_boot()
PYEOF

exec gunicorn --config /tmp/gunicorn_conf.py --worker-class sync --workers 4 --preload --timeout 120 --graceful-timeout 20 --keep-alive 30 --max-requests 30000 --max-requests-jitter 3000 --bind 0.0.0.0:${PORT:-8080} nexus_omega:app 2>&1
