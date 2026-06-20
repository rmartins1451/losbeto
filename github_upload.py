# -*- coding: utf-8 -*-
"""
github_upload.py — Sobe o app.py direto para o GitHub via API (sem navegador)
Execute: python github_upload.py
"""

import urllib.request
import urllib.error
import json
import base64
import sys
import os

# ══════════════════════════════════════════════════════
#  PREENCHA AQUI
# ══════════════════════════════════════════════════════
GITHUB_TOKEN = "SvrOKt5R6Dlpj47fKaRnIO4NmE70Ej4aS8j4Hs1uaAU"
# Como gerar: https://github.com/settings/tokens/new
#   -> Note: "railway-upload"
#   -> Expiration: 7 days (ou o que preferir)
#   -> Marque o escopo: "repo" (Full control of private repositories)
#   -> Generate token -> copie e cole acima
# ══════════════════════════════════════════════════════

REPO   = "rmartins1451/losbeto"
BRANCH = "main"

# Arquivos locais que serão enviados (devem estar na mesma pasta deste script)
ARQUIVOS = ["app.py", "requirements.txt"]

# Arquivo antigo a remover do GitHub (causa conflito de import)
ARQUIVO_REMOVER = "x402_nexusai_binance_v3.py"


def gh_request(method, path, payload=None):
    url = f"https://api.github.com/repos/{REPO}/{path}"
    data = json.dumps(payload).encode("utf-8") if payload else None
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {GITHUB_TOKEN}",
            "Accept":        "application/vnd.github+json",
            "User-Agent":    "deploy-script/1.0",
            "Content-Type":  "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        return e.code, json.loads(body) if body else {}


if GITHUB_TOKEN == "COLE_SEU_GITHUB_TOKEN_AQUI":
    print("""
  Preencha GITHUB_TOKEN no topo do arquivo!

  Como gerar (30 segundos):
    1. Acesse: https://github.com/settings/tokens/new
    2. Note: railway-upload
    3. Expiration: 7 days
    4. Marque o escopo: "repo" (caixa principal, marca tudo dentro)
    5. Clique "Generate token" no final da página
    6. Copie o token (começa com ghp_...)
    7. Cole aqui no script e salve
    8. Rode novamente: python github_upload.py
""")
    sys.exit(1)

print("\n" + "═"*60)
print("  github_upload.py — Enviando arquivos via API")
print("═"*60)

# 1. Validar acesso ao repo
status, repo_info = gh_request("GET", "")
if status != 200:
    print(f"\n  ✗ Não consegui acessar o repositório: {repo_info}")
    sys.exit(1)
print(f"\n  ✓ Repositório OK: {repo_info.get('full_name')}")

# 2. Upload de cada arquivo
for nome_arquivo in ARQUIVOS:
    if not os.path.exists(nome_arquivo):
        print(f"\n  ✗ Arquivo '{nome_arquivo}' não encontrado nesta pasta!")
        print(f"    Coloque-o na mesma pasta deste script e rode de novo.")
        continue

    print(f"\n  Enviando '{nome_arquivo}'...")
    with open(nome_arquivo, "rb") as f:
        conteudo_b64 = base64.b64encode(f.read()).decode("utf-8")

    # Verifica se o arquivo já existe (precisa do SHA para atualizar)
    status, existing = gh_request("GET", f"contents/{nome_arquivo}?ref={BRANCH}")
    sha = existing.get("sha") if status == 200 else None

    payload = {
        "message": f"Atualiza {nome_arquivo} via script automático",
        "content": conteudo_b64,
        "branch":  BRANCH,
    }
    if sha:
        payload["sha"] = sha
        print(f"    (arquivo já existe — substituindo)")
    else:
        print(f"    (arquivo novo — criando)")

    status, result = gh_request("PUT", f"contents/{nome_arquivo}", payload)
    if status in (200, 201):
        print(f"  ✓ '{nome_arquivo}' enviado com sucesso!")
    else:
        print(f"  ✗ Erro ao enviar '{nome_arquivo}': {result}")

# 3. Remover arquivo antigo conflitante
print(f"\n  Verificando arquivo antigo '{ARQUIVO_REMOVER}'...")
status, existing = gh_request("GET", f"contents/{ARQUIVO_REMOVER}?ref={BRANCH}")
if status == 200:
    sha = existing["sha"]
    del_payload = {
        "message": f"Remove {ARQUIVO_REMOVER} (substituído por app.py)",
        "sha":     sha,
        "branch":  BRANCH,
    }
    status2, result2 = gh_request("DELETE", f"contents/{ARQUIVO_REMOVER}", del_payload)
    if status2 == 200:
        print(f"  ✓ '{ARQUIVO_REMOVER}' removido com sucesso!")
    else:
        print(f"  ⚠ Não consegui remover: {result2}")
else:
    print(f"  (arquivo antigo já não existe — nada a fazer)")

# 4. Confirmar árvore final
print("\n" + "─"*60)
print("  Árvore final do repositório:")
print("─"*60)
status, tree = gh_request("GET", f"contents?ref={BRANCH}")
if status == 200 and isinstance(tree, list):
    for item in tree:
        print(f"  📄 {item['name']}")

print(f"""
{'═'*60}
  ✅ CONCLUÍDO!

  O Railway deve detectar o push e fazer redeploy automático
  em alguns segundos (auto-deploy já está ativo).

  Aguarde ~2 minutos e rode: python railway_logs.py
  Ou teste direto: https://losbeto-production-dd7c.up.railway.app/version
{'═'*60}
""")
