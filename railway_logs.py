# -*- coding: utf-8 -*-
"""
railway_logs.py — Mostra os logs do deployment mais recente
Execute: python railway_logs.py
"""

import urllib.request
import urllib.error
import json
import sys
import time

# ══════════════════════════════════════════════════════
RAILWAY_TOKEN = "e394e190-cb98-462f-a8e4-72d6a62bba6a"
# ══════════════════════════════════════════════════════

ENVIRONMENT_ID = "a03f8938-5ff9-4b51-90d5-a2e5c5a6d924"
SERVICE_ID     = "931cb489-99bc-4084-b8d6-9f8947461abf"
RAILWAY_API    = "https://backboard.railway.app/graphql/v2"


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
        print(f"  [HTTP {e.code}] {e.read().decode(errors='replace')[:400]}")
        return None
    except Exception as e:
        print(f"  [ERRO] {e}")
        return None


if RAILWAY_TOKEN == "COLE_SEU_TOKEN_AQUI":
    print("Preencha RAILWAY_TOKEN no topo do arquivo!")
    sys.exit(1)

print("\n" + "═"*56)
print("  railway_logs.py — Buscando deployment mais recente")
print("═"*56 + "\n")

# 1. Pegar o deployment mais recente
r = gql("""
query($serviceId: String!, $environmentId: String!) {
  deployments(
    first: 1
    input: { serviceId: $serviceId, environmentId: $environmentId }
  ) {
    edges { node { id status createdAt } }
  }
}
""", {"serviceId": SERVICE_ID, "environmentId": ENVIRONMENT_ID})

edges = ((r or {}).get("data") or {}).get("deployments", {}).get("edges", [])
if not edges:
    print("  Nenhum deployment encontrado.")
    sys.exit(1)

dep = edges[0]["node"]
dep_id = dep["id"]
status = dep["status"]
print(f"  Deployment: {dep_id}")
print(f"  Status atual: {status}\n")

# Se ainda estiver inicializando, espera um pouco
if status in ("INITIALIZING", "BUILDING", "DEPLOYING"):
    print("  Ainda em andamento — aguardando 20s antes de puxar logs...")
    time.sleep(20)

# 2. Puxar logs de build
print("─"*56)
print("  BUILD LOGS:")
print("─"*56)
rb = gql("""
query($deploymentId: String!) {
  buildLogs(deploymentId: $deploymentId, limit: 100) {
    message
    timestamp
  }
}
""", {"deploymentId": dep_id})

build_logs = ((rb or {}).get("data") or {}).get("buildLogs") or []
if build_logs:
    for log in build_logs[-40:]:
        print(f"  {log.get('message', '')}")
else:
    print("  (sem logs de build)")

# 3. Puxar logs de deploy/runtime
print("\n" + "─"*56)
print("  DEPLOY / RUNTIME LOGS:")
print("─"*56)
rd = gql("""
query($deploymentId: String!) {
  deploymentLogs(deploymentId: $deploymentId, limit: 100) {
    message
    timestamp
    severity
  }
}
""", {"deploymentId": dep_id})

deploy_logs = ((rd or {}).get("data") or {}).get("deploymentLogs") or []
if deploy_logs:
    for log in deploy_logs[-40:]:
        sev = log.get("severity", "")
        print(f"  [{sev}] {log.get('message', '')}")
else:
    print("  (sem logs de runtime ainda)")

print("\n" + "═"*56)
print(f"  Status final: {status}")
print("  Se status = SUCCESS e não há erro nos logs acima,")
print("  aguarde mais 1-2 min e teste a URL novamente.")
print("═"*56 + "\n")
