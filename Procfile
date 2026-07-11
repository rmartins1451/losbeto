web: gunicorn --worker-class gthread --workers 2 --threads 6 --timeout 120 --graceful-timeout 30 --keep-alive 30 --max-requests 1000 --max-requests-jitter 100 --bind 0.0.0.0:$PORT nexus_omega:app
