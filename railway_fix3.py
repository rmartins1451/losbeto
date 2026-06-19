# -*- coding: utf-8 -*-
"""
railway_fix3.py — Corrige o Root Directory do serviço (causa do ModuleNotFoundError)
Execute: python railway_fix3.py
"""

import urllib.request
import urllib.error
import json
import sys

# ══════════════════════════════════════════════════════
RAILWAY_TOKEN = "e394e190-cb98-462f-a8e4-72d6a62bba6a"
# ══════════════════════════════════════════════════════

PROJECT_ID     = "98d8b0ed-9224-460c-aea2-cedca35c835b"
ENVIRONMENT_ID = "a03f8938-5ff9-4b51-90d5-a2e5c5a6d924"
SERVICE_ID     = "931cb489-99bc-4084-b8d6-9f8947461abf"
RAILWAY_API    = "https://backboard.railway.app/graphql/v2"

# O app.py está em losbeto/app.py dentro do repo — então o root precisa apontar pra lá
ROOT_DIRECTORY = ""  # raiz do repo — é onde os arquivos realmente estão
START_COMMAND  = "gunicorn app:app --bind 0.0.0.0:$PORT --workers 2 --timeout 60"


def gql(query, variables=None):
    payload = json.dumps({"query": query, "variables": variables or {}}).encode("utf-8")
    req = urllib.request.Request(
        RAILWAY_API,
        data=payload,
        headers={
            "Content-Type":  "application/json; charset=utf-8",
            "Authorization": f"Bearer {RAILWAY_TOKEN}",
            "User-Agent":    "railway-deploy-script/1.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        print(f"  [HTTP {e.code}] {body[:500]}")
        return None
    except Exception as e:
        print(f"  [ERRO] {e}")
        return None


if RAILWAY_TOKEN == "COLE_SEU_TOKEN_AQUI":
    print("Preencha RAILWAY_TOKEN no topo do arquivo!")
    sys.exit(1)

print("\n" + "═"*60)
print("  railway_fix3.py — Corrigindo Root Directory")
print("═"*60)

# 1. Checar config atual primeiro
print("\n  Lendo configuração atual do serviço...")
r0 = gql("""
query($serviceId: String!, $environmentId: String!) {
  serviceInstance(serviceId: $serviceId, environmentId: $environmentId) {
    rootDirectory
    startCommand
  }
}
""", {"serviceId": SERVICE_ID, "environmentId": ENVIRONMENT_ID})

inst = ((r0 or {}).get("data") or {}).get("serviceInstance") or {}
print(f"  rootDirectory atual : {inst.get('rootDirectory') or '(vazio = raiz do repo)'}")
print(f"  startCommand atual  : {inst.get('startCommand') or '(não definido)'}")

# 2. Corrigir rootDirectory + startCommand juntos
print(f"\n  Definindo rootDirectory = '{ROOT_DIRECTORY}'")
print(f"  Definindo startCommand  = '{START_COMMAND}'")

r = gql("""
mutation($serviceId: String!, $environmentId: String!, $input: ServiceInstanceUpdateInput!) {
  serviceInstanceUpdate(
    serviceId: $serviceId
    environmentId: $environmentId
    input: $input
  )
}
""", {
    "serviceId":     SERVICE_ID,
    "environmentId": ENVIRONMENT_ID,
    "input": {
        "rootDirectory": ROOT_DIRECTORY,
        "startCommand":  START_COMMAND,
    },
})

ok = ((r or {}).get("data") or {}).get("serviceInstanceUpdate", False)
errs = (r or {}).get("errors")
if ok:
    print("  ✓ Configuração atualizada!")
elif errs:
    print(f"  ✗ Erro: {errs[0].get('message')}")
    sys.exit(1)
else:
    print(f"  ⚠ Resposta inesperada: {r}")

# 3. Redeploy
print("\n  Disparando redeploy...")
r2 = gql("""
mutation($serviceId: String!, $environmentId: String!) {
  serviceInstanceRedeploy(serviceId: $serviceId, environmentId: $environmentId)
}
""", {"serviceId": SERVICE_ID, "environmentId": ENVIRONMENT_ID})

ok2 = ((r2 or {}).get("data") or {}).get("serviceInstanceRedeploy", False)
if ok2:
    print("  ✓ Redeploy iniciado!")
else:
    print("  ⚠ Verifique manualmente no painel se precisar.")

print(f"""
{'═'*60}
  Aguarde 2-3 minutos para o build completar.

  Teste em seguida:
  https://losbeto-production-dd7c.up.railway.app/

  Painel:
  https://railway.com/project/{PROJECT_ID}
{'═'*60}
""")
