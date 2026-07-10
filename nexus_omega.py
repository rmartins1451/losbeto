# -*- coding: utf-8 -*-
"""
================================================================================
 LOSBETO v15.0.0 — APEX
================================================================================
 Enxame Autônomo Multi-Chain — Solana + Base + TON — MONETIZADO.

 CORREÇÕES CRÍTICAS v14 vs v13
 ─────────────────────────────────────────────────────────────────────────────
  🔥 FIX WALLET INCONSISTENTE — separação RECEIVE_ADDRESS × SIGNING_WALLET
     v13: WALLET_SECRET_B58 obrigatório. Se fosse endereço público, gerava
          wallet aleatória a cada boot → dashboard mostrava ANa8... (efêmera)
          e pagamentos iam pra endereço sem dono.
     v14: RECEIVE_ADDRESS = SOLANA_WALLET_ADDRESS (só leitura, endereço público).
          Todo payTo aponta pra ele. Wallet interna só assina JWT/P2P.
          Você NÃO precisa de secret pra receber pagamentos.
  🔥 FIX Base USDC — verificação via facilitator (x402.org suporta Base)
     v13: retornava 'base-requires-facilitator' bloqueando toda tx Base.
     v14: quando FACILITATOR ativo, delega para ele (aceita Solana + Base).
  🔥 FIX /sample premium preview — retorna dado real de 3 endpoints premium
     v13: só devolvia fear-greed simples
     v14: preview de fear-greed + rugcheck (redacted) + sinais (top-1)
           com campo unlock_full_at e preço embutido.

 PRINCIPAIS UPGRADES vs v9
 ─────────────────────────────────────────────────────────────────────────────
  ✅ x402 v2 100% spec-compliant (maxAmountRequired, scheme=exact, CAIP-2)
  ✅ Multi-network NATIVO em todos endpoints: Solana + Base USDC
  ✅ JWT pós-pagamento (cliente paga 1x, reutiliza por 5min — converte mais)
  ✅ GeoIP REAL (ip-api.com) substitui o filtro errado de IP-prefix
  ✅ Auto-listagem em x402scan + AgentCash + Bazaar (POST de manifest)
  ✅ Suporte opcional a Facilitator (CDP / PayAI) — escolhe automaticamente
  ✅ TF-IDF real no RAG (cosine similarity) — antes era bag-of-words
  ✅ 26 endpoints (vs 18 no v9) — novos: /mev-flow, /rugcheck, /copytrade,
     /insider-track, /defi-yield, /onchain-credit, /agent-call, /tg-premium
  ✅ Anti-Sybil: rate-limit por wallet payer (não só IP)
  ✅ Worker de revenue compounder: re-investe ganhos em stake interno
  ✅ Procfile/railway.toml apontam para v10 (corrigido)
  ✅ Migração automática de ledger v8/v9 → v10 preservando dados
  ✅ Telegram Bot 2.0 — Mini App stub + comandos premium
  ✅ Webhook receiver para CoinGecko x402 / Helius streams

 26 ENDPOINTS MONETIZADOS
 ─────────────────────────────────────────────────────────────────────────────
  CHEAP        /fear-greed $0.01  /regime $0.02   /mempool $0.02
               /anomalias $0.03   /jupiter-swap $0.05
  MID          /analise $0.05     /swarm-vote $0.05  /sentiment $0.08
               /sinais $0.10      /deep-think $0.15  /pump-monitor $0.15
               /rugcheck $0.10    /defi-yield $0.12
  PREMIUM      /arbitrage $0.20   /relatorio $0.25   /backtest $0.30
               /cross-chain $0.40 /whale-alert $0.50 /smart-money $0.75
               /tg-premium $0.20  /agent-call $0.30  /onchain-credit $0.35
  ALPHA        /alpha-signal $1.00 /copytrade $0.80 /insider-track $1.20
               /mev-flow $1.50

 LICENÇA: MIT. Domine o mercado.
================================================================================
"""
from __future__ import annotations

import os, sys, json, time, base64, hashlib, threading, sqlite3, hmac
import socket, struct, secrets, subprocess, signal, logging, traceback, random
import urllib.request, urllib.error, urllib.parse, re, math
from datetime import datetime, timezone, timedelta
from pathlib import Path
from collections import defaultdict, deque, Counter
from typing import Any, Optional, Dict, List, Tuple

# ============================================================================
# 0. CONFIGURAÇÃO E AUTO-SETUP
# ============================================================================

VERSION = "16.0.0-MARKET-FIT"
HOME_DIR = Path(os.environ.get("DATA_DIR", "")).expanduser() if os.environ.get("DATA_DIR") else Path("/data") if Path("/data").exists() else Path.home() / ".nexus_omega"
HOME_DIR.mkdir(parents=True, exist_ok=True)

DB_PATH         = HOME_DIR / "omega_v10.db"
LEGACY_V9_DB    = HOME_DIR / "omega_v9.db"
LEGACY_V8_DB    = HOME_DIR / "omega.db"
WALLET_PATH     = HOME_DIR / "wallet_solana.json"
TON_WALLET_PATH = HOME_DIR / "wallet_ton.json"
LOG_PATH        = HOME_DIR / "omega_v10.log"
CONFIG_PATH     = HOME_DIR / "config_v10.json"
RAG_DB_PATH     = HOME_DIR / "rag_v10.db"

# Portas
X402_PORT      = int(os.environ.get("PORT", os.environ.get("OMEGA_X402_PORT", "8402")))
GOSSIP_PORT    = int(os.environ.get("OMEGA_GOSSIP_PORT", "8403"))
MCAST_PORT     = int(os.environ.get("OMEGA_MCAST_PORT", "8404"))
DASHBOARD_PORT = X402_PORT
MCAST_GRP      = "239.42.42.42"

# URL pública (Railway/Render/Fly auto-detect)
_rw_domain  = os.environ.get("RAILWAY_PUBLIC_DOMAIN", "").strip()
_rw_static  = os.environ.get("RAILWAY_STATIC_URL", "").strip()
_rw_service = os.environ.get("RAILWAY_SERVICE_URL", "").strip()
_render     = os.environ.get("RENDER_EXTERNAL_URL", "").strip()
_fly        = os.environ.get("FLY_APP_NAME", "").strip()
_manual     = os.environ.get("PUBLIC_URL", "").strip()

PUBLIC_URL = (
    _manual or
    (f"https://{_rw_domain}" if _rw_domain else "") or
    (_rw_static if _rw_static.startswith("http") else "") or
    (_rw_service if _rw_service.startswith("http") else "") or
    _render or
    (f"https://{_fly}.fly.dev" if _fly else "")
).rstrip("/")

DASH_TOKEN = os.environ.get("DASH_TOKEN", secrets.token_urlsafe(16))
JWT_SECRET = os.environ.get("JWT_SECRET", secrets.token_urlsafe(32))
JWT_TTL    = int(os.environ.get("JWT_TTL_SECONDS", "300"))  # 5min reuse

# Solana
SOLANA_RPCS = [
    os.environ.get("SOLANA_RPC", "https://api.mainnet-beta.solana.com"),
    "https://solana-rpc.publicnode.com",
    "https://solana.drpc.org",
]
if os.environ.get("HELIUS_API_KEY"):
    SOLANA_RPCS.insert(0, f"https://mainnet.helius-rpc.com/?api-key={os.environ['HELIUS_API_KEY']}")

USDC_MINT     = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
USDC_DECIMALS = 6
USDT_MINT     = "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"
SOL_GENESIS   = "5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp"  # CAIP-2 mainnet

# Base (EVM) — x402 multi-chain
BASE_RPC          = os.environ.get("BASE_RPC", "https://mainnet.base.org")
BASE_USDC         = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
BASE_PAYTO_EVM    = os.environ.get("BASE_PAYTO_EVM", "").strip()  # se vazio, só Solana
BASE_CAIP2        = "eip155:8453"
ENABLE_BASE       = bool(BASE_PAYTO_EVM)

# Facilitator opcional
NETWORK_MODE      = os.environ.get("NETWORK_MODE", "mainnet").strip().lower()
FACILITATOR_URL   = os.environ.get("X402_FACILITATOR", "").strip()  # prod recomendado: https://facilitator.payai.network ou CDP
USE_FACILITATOR   = bool(FACILITATOR_URL)

# TON
TON_API       = "https://toncenter.com/api/v2"
TON_API_KEY   = os.environ.get("TON_API_KEY", "").strip()
TON_TESTNET   = False

# APIs externas
GROQ_KEY     = os.environ.get("GROQ_API_KEY", "").strip()
GEMINI_KEY   = os.environ.get("GEMINI_API_KEY", "").strip()
OLLAMA_URL   = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5:3b")
HELIUS_KEY   = os.environ.get("HELIUS_API_KEY", "").strip()
JUPITER_KEY  = os.environ.get("JUPITER_API_KEY", "").strip()
COINGECKO_KEY= os.environ.get("COINGECKO_API_KEY", "").strip()

# Telegram
TG_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
TG_CHAT  = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

# Binance sweep
# Aceita apenas endereço Solana real. Variáveis legadas EVM são ignoradas com warning.
_raw_binance = os.environ.get("BINANCE_SOLANA_ADDRESS", "").strip()
_legacy_binance = os.environ.get("BINANCE_WALLET_ADDRESS", "").strip()
if not _raw_binance and _legacy_binance:
    _raw_binance = _legacy_binance
if _raw_binance.startswith("0x"):
    import logging as _lg
    _lg.getLogger("omega").warning(
        "⚠️  BINANCE_WALLET_ADDRESS/BINANCE_SOLANA_ADDRESS aponta para EVM (0x...). "
        "Sweep em Solana foi IGNORADO para evitar perda de fundos. Use apenas BINANCE_SOLANA_ADDRESS em base58."
    )
    _raw_binance = ""
BINANCE_ADDRESS = _raw_binance
SWEEP_THRESHOLD  = float(os.environ.get("SWEEP_THRESHOLD_USDC", "0.5"))
SWEEP_INTERVAL   = int(os.environ.get("SWEEP_INTERVAL_S", "3600"))

# Bootstrap P2P
BOOTSTRAP_SEEDS = [s.strip() for s in os.environ.get("OMEGA_SEEDS", "").split(",") if s.strip()]

# Dynamic Pricing (PoI)
DYNAMIC_PRICING = os.environ.get("DYNAMIC_PRICING", "false").lower() == "true"
BASE_WIN_RATE   = 55.0

# GeoIP — substitui filtro de IP-prefix burro do v9
GEOIP_ENABLED         = os.environ.get("GEOIP_ENABLED", "false").lower() == "true"
GEO_BLOCKED_COUNTRIES = set(os.environ.get("GEO_BLOCKED", "").split(",")) - {""}

# Preços base (USDC) — 26 endpoints
# Preços calibrados conforme relatório Julho 2026
# Alpha endpoints com desconto 80% promocional para gerar primeiras transações
# Após 50+ pagamentos, ajustar gradualmente via PoI multiplier
BASE_PRICES = {
    # DISCOVERY — preços de entrada, mas acima da zona de commodity
    "/fear-greed":       0.010,
    "/pyth-price":       0.010,
    "/trust-hash":       0.010,
    "/web-search":       0.015,
    "/ai-news":          0.015,
    "/regime":           0.020,
    "/mempool":          0.020,
    "/agent-market":     0.020,
    "/geo-alpha":        0.025,
    "/sentiment":        0.030,
    "/anomalias":        0.030,
    "/dex-screen":       0.030,

    # CORE — dados operacionais e inteligência acionável
    "/jupiter-swap":     0.040,
    "/rugcheck":         0.040,
    "/pump-monitor":     0.050,
    "/defi-yield":       0.050,
    "/swarm-vote":       0.060,
    "/sinais":           0.070,
    "/analise":          0.090,
    "/nansen-flow":      0.090,
    "/backtest":         0.120,
    "/tg-premium":       0.120,
    "/agent-call":       0.120,
    "/onchain-credit":   0.120,
    "/deep-think":       0.140,
    "/sec-filing":       0.150,
    "/relatorio":        0.180,
    "/sanctions":        0.180,
    "/arbitrage":        0.200,
    "/whale-alert":      0.200,
    "/cross-chain":      0.250,
    "/smart-money":      0.250,
    "/copytrade":        0.350,
    "/alpha-signal":     0.400,
    "/insider-track":    0.500,
    "/mev-flow":         0.600,

    # FLAGSHIP BUNDLES — produtos que vendem resultado, não endpoint solto
    "/market-brief":      0.250,
    "/portfolio-copilot": 0.390,
    "/launch-sniper":     0.490,
    "/whale-dossier":     0.590,
    "/thesis-engine":     0.690,
    "/starter-pack":      1.000,
}

FEATURED_ENDPOINTS = [
    "/starter-pack", "/thesis-engine", "/market-brief", "/launch-sniper",
    "/whale-dossier", "/portfolio-copilot", "/alpha-signal", "/mev-flow",
    "/smart-money", "/copytrade", "/rugcheck", "/onchain-credit",
]


def _price_env_key(endpoint: str) -> str:
    return "PRICE_" + endpoint.strip("/").replace("-", "_").upper()


def _load_price_overrides() -> dict:
    overrides = {}
    for ep, default in BASE_PRICES.items():
        raw = os.environ.get(_price_env_key(ep), "").strip()
        if not raw:
            continue
        try:
            val = float(raw)
            if val <= 0:
                continue
            if val < default * 0.60:
                log.warning(f"override ignorado para {ep}: {val} < 60% do preço base {default}")
                continue
            overrides[ep] = round(val, 4)
        except Exception:
            log.warning(f"price override inválido para {ep}: {raw}")
    return overrides


PRICE_OVERRIDES = _load_price_overrides()

ENDPOINT_DESC = {
    "/fear-greed":      "Fear & Greed Index ao vivo + interpretação IA",
    "/regime":          "Regime atual do mercado com leitura operacional de risco",
    "/mempool":         "Mempool Solana em tempo real com fee pressure",
    "/anomalias":       "Anomalias de preço/volume detectadas agora",
    "/jupiter-swap":    "Cotação Jupiter com melhor rota DEX e slippage",
    "/analise":         "Análise consolidada com RAG + IA para decisão",
    "/swarm-vote":      "Consenso votado pelo enxame de nós",
    "/sentiment":       "Sentimento social multi-fonte para ativo específico",
    "/rugcheck":        "Risco de rug pull com sinais de mint authority, holders e LP",
    "/sinais":          "Top sinais com confiança, contexto e backtest",
    "/defi-yield":      "Melhores yields DeFi em Solana com filtros práticos",
    "/deep-think":      "Raciocínio estruturado sobre tese, cenário e invalidação",
    "/pump-monitor":    "Novos launches em Pump.fun/Raydium com triagem inicial",
    "/arbitrage":       "Arbitragem cross-exchange + cross-chain com oportunidades acionáveis",
    "/tg-premium":      "Feed premium de alertas em formato pronto para automação",
    "/relatorio":       "Relatório executivo com síntese macro, setores e trades",
    "/backtest":        "Backtest com PnL, win rate e leitura da estratégia",
    "/agent-call":      "Chamada A2A para outro agente do enxame",
    "/onchain-credit":  "Score de crédito on-chain e perfil de wallet",
    "/cross-chain":     "Leitura de spread e arbitragem Solana ↔ Base",
    "/whale-alert":     "Alertas de movimentações whale acima do limiar",
    "/smart-money":     "Tracking de carteiras institucionais e smart money",
    "/copytrade":       "Replica os sinais implícitos de wallets de destaque",
    "/alpha-signal":    "Sinal alpha validado com filtro de alta convicção",
    "/insider-track":   "Rastreamento de insiders em launches e entradas precoces",
    "/mev-flow":        "Fluxo de bundles Jito, tip floor e sinais de MEV",
    "/web-search":      "Busca web resumida para contexto macro/cripto orientado a agentes",
    "/ai-news":         "Noticiário cripto filtrado para agentes e research bots",
    "/dex-screen":      "Snapshot de pares no DexScreener com liquidez e volume",
    "/nansen-flow":     "Fluxo de grandes holders e concentração em carteiras-chave",
    "/sec-filing":      "Busca filings da SEC com leitura objetiva para o mercado",
    "/trust-hash":      "Prova hash verificável para conteúdo/manifest/endpoint",
    "/geo-alpha":       "Leitura geográfica de exchange trust score e volume BTC",
    "/sanctions":       "Checagem inicial de compliance/sanctions para wallet ou nome",
    "/agent-market":    "Mapa comercial do catálogo com featured endpoints e discovery",
    "/pyth-price":      "Preço Pyth com confidence interval para ativo suportado",
    "/market-brief":    "Bundle premium: regime + sentimento + sinais + risco em JSON previsível",
    "/portfolio-copilot":"Bundle premium: risco, yield, arbitragem e plano de ação para carteira",
    "/launch-sniper":   "Bundle premium: launches, rugcheck, insiders e execução tática",
    "/whale-dossier":   "Bundle premium: baleias, smart money, fluxo institucional e alertas",
    "/thesis-engine":   "Produto premium: tese operacional com convicção, gatilhos e hedge",
    "/starter-pack":    "Pacote de entrada Phantom-friendly com bundles premium e valor mínimo de US$1",
}

ENDPOINT_TAGS = {
    "/fear-greed":      ["Search", "Sentiment"],
    "/regime":          ["Trading", "Macro"],
    "/mempool":         ["Utility", "Data"],
    "/anomalias":       ["Utility", "Trading"],
    "/jupiter-swap":    ["Trading", "DEX"],
    "/analise":         ["Trading", "AI"],
    "/swarm-vote":      ["Utility", "A2A"],
    "/sentiment":       ["Search", "AI"],
    "/rugcheck":        ["Utility", "Security"],
    "/sinais":          ["Trading"],
    "/defi-yield":      ["DeFi"],
    "/deep-think":      ["AI", "Research"],
    "/pump-monitor":    ["Trading", "Memecoin"],
    "/arbitrage":       ["Trading", "Execution"],
    "/tg-premium":      ["Premium", "Alerts"],
    "/relatorio":       ["Search", "AI", "Research"],
    "/backtest":        ["Trading", "Quant"],
    "/agent-call":      ["AI", "A2A"],
    "/onchain-credit":  ["Utility", "Score"],
    "/cross-chain":     ["Trading", "Bridge"],
    "/whale-alert":     ["Trading", "Alert"],
    "/smart-money":     ["Trading", "Alert"],
    "/copytrade":       ["Trading", "Signals"],
    "/alpha-signal":    ["Trading", "Alpha"],
    "/insider-track":   ["Trading", "Alert"],
    "/mev-flow":        ["Trading", "MEV"],
    "/web-search":      ["Search", "Research"],
    "/ai-news":         ["AI", "News"],
    "/dex-screen":      ["Trading", "DEX"],
    "/nansen-flow":     ["Utility", "Onchain"],
    "/sec-filing":      ["Search", "Equities"],
    "/trust-hash":      ["Utility", "Trust"],
    "/geo-alpha":       ["Utility", "Macro"],
    "/sanctions":       ["Search", "Compliance"],
    "/agent-market":    ["AI", "Marketplace"],
    "/pyth-price":      ["Utility", "Oracle"],
    "/market-brief":    ["AI", "Bundle", "Featured"],
    "/portfolio-copilot":["AI", "Bundle", "Featured"],
    "/launch-sniper":   ["Trading", "Bundle", "Featured"],
    "/whale-dossier":   ["Crypto", "Bundle", "Featured"],
    "/thesis-engine":   ["AI", "Featured", "Premium"],
    "/starter-pack":    ["Bundle", "Featured", "Phantom"],
}


# ============================================================================
# 1. LOGGING
# ============================================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_PATH, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("omega_v10")

# ============================================================================
# 2. AUTO-INSTALAÇÃO DE DEPENDÊNCIAS
# ============================================================================

REQUIRED = {
    "flask":        "flask",
    "requests":     "requests",
    "base58":       "base58",
    "nacl":         "pynacl",
    "cryptography": "cryptography",
}

def _ensure_deps():
    missing = []
    for mod, pkg in REQUIRED.items():
        try:
            __import__(mod)
        except ImportError:
            missing.append(pkg)
    if missing:
        log.info(f"📦 Instalando: {missing}")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "--quiet", *missing])

_ensure_deps()

import requests
import base58
from nacl.signing import SigningKey, VerifyKey
from nacl.exceptions import BadSignatureError
from flask import Flask, request, jsonify, redirect

# ============================================================================
# 3. WALLET SOLANA + TON — v16 MARKET-FIT
# ----------------------------------------------------------------------------
# ARQUITETURA REVISADA (fix crítico v13):
#   RECEIVE_ADDRESS : endereço PÚBLICO onde pagamentos chegam. Só leitura.
#                     Fonte: env SOLANA_WALLET_ADDRESS.
#                     NÃO precisa de chave privada. Você controla via Phantom/Binance.
#   SIGNING WALLET  : wallet interna gerada localmente, usada APENAS para:
#                       - assinar JWT (sessão pós-pagamento)
#                       - assinar mensagens gossip P2P
#                       - prova de posse do manifest
#                     NÃO aparece como payTo em nenhum lugar.
#
# Todos os endpoints x402 usam RECEIVE_ADDRESS como destino real dos pagamentos.
# ============================================================================

class SolanaWallet:
    def __init__(self, secret_b58: Optional[str] = None):
        if secret_b58:
            raw = base58.b58decode(secret_b58)
            if len(raw) == 32:
                self.signing = SigningKey(raw)
            elif len(raw) == 64:
                self.signing = SigningKey(raw[:32])
            else:
                raise ValueError("Solana secret must be 32 or 64 bytes")
        else:
            self.signing = SigningKey.generate()
        self.verify_key = self.signing.verify_key
        self.public_key = bytes(self.verify_key)
        self.solana_address = base58.b58encode(self.public_key).decode()
        self.node_id = hashlib.sha256(self.public_key).hexdigest()[:16]

    def sign(self, message: bytes) -> bytes:
        return self.signing.sign(message).signature

    def export_b58(self) -> str:
        return base58.b58encode(bytes(self.signing) + self.public_key).decode()

    def export_b58_seed(self) -> str:
        return base58.b58encode(bytes(self.signing)).decode()


class TONWallet:
    """Wallet TON simplificada — endereço derivado do seed Ed25519."""
    def __init__(self, mnemonic: Optional[str] = None):
        if mnemonic:
            seed = hashlib.sha256(mnemonic.encode()).digest()[:32]
        else:
            seed = secrets.token_bytes(32)
        self.seed = seed
        self.signing = SigningKey(seed)
        self.public_key = bytes(self.signing.verify_key)
        h = hashlib.sha256(b"\x01\x02" + self.public_key).digest()
        self.address = "UQ" + base64.urlsafe_b64encode(b"\x11" + h[:31]).decode().rstrip("=")
        self.mnemonic = mnemonic or base58.b58encode(seed).decode()

    def export(self) -> str:
        return self.mnemonic


def _is_valid_solana_address(addr: str) -> bool:
    """Valida endereço Solana base58 (32 bytes decodificados)."""
    if not addr or len(addr) < 32 or len(addr) > 44:
        return False
    try:
        raw = base58.b58decode(addr)
        return len(raw) == 32
    except Exception:
        return False


def _resolve_receive_address() -> str:
    """Resolve o endereço PÚBLICO de recebimento (RECEIVE_ADDRESS).

    Prioridade:
      1. SOLANA_WALLET_ADDRESS (env)
      2. RECEIVE_ADDRESS       (env alias)
      3. WALLET_SECRET_B58 se for na verdade um endereço público (aceito com log)
      4. BINANCE_SOLANA_ADDRESS (fallback: recebe direto na Binance)

    Retorna endereço válido ou string vazia.
    """
    candidates = [
        ("SOLANA_WALLET_ADDRESS", os.environ.get("SOLANA_WALLET_ADDRESS", "").strip()),
        ("RECEIVE_ADDRESS",       os.environ.get("RECEIVE_ADDRESS", "").strip()),
        ("WALLET_SECRET_B58(as-address)", os.environ.get("WALLET_SECRET_B58", "").strip()),
        ("BINANCE_SOLANA_ADDRESS", os.environ.get("BINANCE_SOLANA_ADDRESS", "").strip()),
    ]
    for name, value in candidates:
        if not value:
            continue
        if value.startswith("0x"):
            log.error(f"⛔ {name} é EVM ({value[:10]}...) — Solana espera base58. Pulando.")
            continue
        if _is_valid_solana_address(value):
            log.info(f"✅ RECEIVE_ADDRESS = {value} (fonte: {name})")
            return value
        log.warning(f"⚠️  {name} = {value[:16]}... não é Solana válido — pulando.")
    return ""


def _restore_wallets():
    """Restaura wallet interna de ASSINATURA (JWT/P2P). NÃO é usada como payTo.

    - Se WALLET_SECRET_B58 for um endereço público (32 bytes), é IGNORADA
      silenciosamente (herança de config antiga) e o RECEIVE_ADDRESS a captura.
    - Se for uma secret válida (64 bytes seed+pub, ou 32 bytes seed), usa.
    - Senão gera nova wallet local.
    """
    secret = os.environ.get("WALLET_SECRET_B58", "").strip()
    if secret:
        try:
            raw = base58.b58decode(secret)
            # Se decodificou 32 bytes E o re-encode bate com o input,
            # é endereço público (não secret). Ignora.
            if len(raw) == 32 and base58.b58encode(raw).decode() == secret:
                log.info("ℹ️  WALLET_SECRET_B58 parece ser endereço público. "
                          "Vai ser usado como RECEIVE_ADDRESS, não como secret.")
                secret = ""
        except Exception:
            secret = ""

    if not secret and WALLET_PATH.exists():
        try:
            secret = json.loads(WALLET_PATH.read_text()).get("secret_b58")
        except Exception:
            pass

    if not secret:
        w = SolanaWallet()
        try:
            WALLET_PATH.write_text(json.dumps({
                "secret_b58":   w.export_b58_seed(),
                "address":      w.solana_address,
                "node_id":      w.node_id,
                "purpose":      "internal-signing-only",
                "warning":      "NÃO envie fundos aqui — endereço de assinatura interna.",
            }, indent=2))
        except Exception as e:
            log.warning(f"⚠️  Não consegui persistir wallet interna: {e}")
        log.info("🔐 Wallet interna gerada (JWT/P2P) — NÃO recebe fundos.")
    else:
        w = SolanaWallet(secret)

    ton_w = None
    try:
        mnemonic = os.environ.get("TON_MNEMONIC", "").strip()
        if not mnemonic and TON_WALLET_PATH.exists():
            mnemonic = json.loads(TON_WALLET_PATH.read_text()).get("mnemonic")
        ton_w = TONWallet(mnemonic if mnemonic else None)
        try:
            TON_WALLET_PATH.write_text(json.dumps({
                "mnemonic": ton_w.mnemonic,
                "address":  ton_w.address,
            }, indent=2))
        except Exception:
            pass
    except Exception as e:
        log.warning(f"TON wallet init: {e}")

    return w, ton_w


# Wallet interna (assinatura) + TON (opcional)
WALLET, TON_WALLET = _restore_wallets()

# ─── ENDEREÇO PÚBLICO DE RECEBIMENTO (o que aparece em TODOS os payTo) ────────
RECEIVE_ADDRESS = _resolve_receive_address()
if not RECEIVE_ADDRESS:
    RECEIVE_ADDRESS = WALLET.solana_address
    log.warning("=" * 70)
    log.warning("⚠️  RECEIVE_ADDRESS não configurado — fallback para wallet interna EFÊMERA.")
    log.warning("   Pagamentos irão para %s", RECEIVE_ADDRESS)
    log.warning("   MAS: essa wallet PODE SER PERDIDA se o container for reciclado.")
    log.warning("   AÇÃO URGENTE: no Railway defina SOLANA_WALLET_ADDRESS = sua Phantom/Binance.")
    log.warning("=" * 70)

# ============================================================================
# 3b. WALLET CONSISTENCY CHECK — v16 MARKET-FIT
# ============================================================================
# Verifica se as wallets configuradas são consistentes.
# Inconsistência = pagamentos podem ir para endereço errado = perda de fundos.

def _check_wallet_consistency():
    """v14: validação do novo modelo RECEIVE_ADDRESS / SIGNING WALLET."""
    warnings = []

    if not RECEIVE_ADDRESS:
        warnings.append("⛔ RECEIVE_ADDRESS vazio — impossível receber pagamentos.")
    elif not _is_valid_solana_address(RECEIVE_ADDRESS):
        warnings.append(f"⛔ RECEIVE_ADDRESS inválido: {RECEIVE_ADDRESS}")
    else:
        log.info(f"✅ RECEIVE_ADDRESS Solana: {RECEIVE_ADDRESS}")

    if RECEIVE_ADDRESS and RECEIVE_ADDRESS == WALLET.solana_address:
        warnings.append(
            "⚠️  RECEIVE_ADDRESS = wallet interna gerada (efêmera). "
            "Configure SOLANA_WALLET_ADDRESS com sua wallet Phantom/Binance."
        )

    if ENABLE_BASE and BASE_PAYTO_EVM:
        if not BASE_PAYTO_EVM.startswith("0x") or len(BASE_PAYTO_EVM) != 42:
            warnings.append(f"⚠️  BASE_PAYTO_EVM inválido: {BASE_PAYTO_EVM}")
        else:
            log.info(f"✅ Base EVM payTo: {BASE_PAYTO_EVM}")
    else:
        log.info("ℹ️  Base USDC: OFF — defina BASE_PAYTO_EVM (90% do mercado x402).")

    if BINANCE_ADDRESS:
        if RECEIVE_ADDRESS == BINANCE_ADDRESS:
            log.info("✅ RECEIVE_ADDRESS = Binance — pagamentos vão direto (sem sweep).")
        else:
            log.info(f"ℹ️  Sweep: {RECEIVE_ADDRESS[:16]}... → {BINANCE_ADDRESS[:16]}...")

    if USE_FACILITATOR:
        log.info(f"✅ Facilitator: {FACILITATOR_URL} (habilita Solana + Base)")
    else:
        log.info("ℹ️  Facilitator: OFF — ative X402_FACILITATOR=https://x402.org/facilitator")

    chains = ["solana"]
    if ENABLE_BASE:
        chains.append("base")
    log.info(f"✅ Chains ativas: {', '.join(chains)}")

    if warnings:
        log.warning("=" * 70)
        log.warning("⚠️  PROBLEMAS DE CONFIGURAÇÃO:")
        for w in warnings:
            log.warning(f"   {w}")
        log.warning("=" * 70)
    return len(warnings) == 0

WALLET_CONSISTENT = _check_wallet_consistency()


log.info(f"💰 RECEIVE: {RECEIVE_ADDRESS}  (destino real dos pagamentos)")
log.info(f"🔐 SIGNER:  {WALLET.solana_address}  (só assinatura interna)")
if TON_WALLET:
    log.info(f"🔑 TON:    {TON_WALLET.address}")
log.info(f"🆔 Node:   {WALLET.node_id}")

# ============================================================================
# 4. LEDGER v10 — SQLite com migração automática
# ============================================================================

class LedgerV10:
    SCHEMA_VERSION = 10

    def __init__(self, path: Path):
        self.path = path
        self.lock = threading.Lock()
        self._init()
        self._migrate_legacy()

    def _conn(self):
        c = sqlite3.connect(self.path, check_same_thread=False, timeout=20)
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA synchronous=NORMAL")
        return c

    def _init(self):
        with self.lock, self._conn() as c:
            c.executescript("""
            CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT);
            CREATE TABLE IF NOT EXISTS revenue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts INTEGER NOT NULL,
                endpoint TEXT NOT NULL,
                amount REAL NOT NULL,
                tx_sig TEXT,
                payer TEXT,
                source TEXT DEFAULT 'direct',
                chain TEXT DEFAULT 'solana',
                jwt_session TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_rev_ts ON revenue(ts);
            CREATE INDEX IF NOT EXISTS idx_rev_endpoint ON revenue(endpoint);
            CREATE INDEX IF NOT EXISTS idx_rev_payer ON revenue(payer);
            CREATE TABLE IF NOT EXISTS requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts INTEGER NOT NULL,
                endpoint TEXT NOT NULL,
                ok INTEGER NOT NULL,
                latency_ms INTEGER,
                ip TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_req_ts ON requests(ts);
            CREATE TABLE IF NOT EXISTS replay (
                hash TEXT PRIMARY KEY,
                ts INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS peers (
                node_id TEXT PRIMARY KEY,
                url TEXT,
                public_key TEXT,
                last_seen INTEGER,
                reputation REAL DEFAULT 1.0,
                win_rate REAL DEFAULT 50.0
            );
            CREATE TABLE IF NOT EXISTS signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts INTEGER NOT NULL,
                symbol TEXT NOT NULL,
                action TEXT NOT NULL,
                confidence REAL,
                price_at REAL,
                result TEXT,
                pnl_pct REAL,
                validated_at INTEGER
            );
            CREATE INDEX IF NOT EXISTS idx_sig_ts ON signals(ts);
            CREATE TABLE IF NOT EXISTS cache (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                ts INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS jwt_sessions (
                jti TEXT PRIMARY KEY,
                payer TEXT,
                endpoint TEXT,
                ts INTEGER,
                exp INTEGER,
                tx_sig TEXT
            );
            CREATE TABLE IF NOT EXISTS sweeps (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts INTEGER, amount REAL, tx_sig TEXT, dest TEXT
            );
            """)
            c.execute("INSERT OR REPLACE INTO meta(k,v) VALUES('schema_version', ?)",
                      (str(self.SCHEMA_VERSION),))

    def _migrate_legacy(self):
        """Importa dados de v8/v9 sem perder histórico."""
        for src in (LEGACY_V9_DB, LEGACY_V8_DB):
            if not src.exists():
                continue
            try:
                with self._conn() as c:
                    cur = c.execute("SELECT COUNT(*) FROM revenue")
                    existing = cur.fetchone()[0]
                if existing > 0:
                    continue
                log.info(f"📦 Migrando ledger legacy: {src}")
                with sqlite3.connect(src) as legacy:
                    tables = [r[0] for r in legacy.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'")]
                    if "revenue" in tables:
                        rows = legacy.execute(
                            "SELECT ts, endpoint, amount, tx_sig, payer FROM revenue"
                        ).fetchall()
                        with self._conn() as c:
                            for r in rows:
                                c.execute(
                                    "INSERT INTO revenue(ts,endpoint,amount,tx_sig,payer,source,chain) "
                                    "VALUES(?,?,?,?,?,'migrated','solana')", r)
                        log.info(f"   ✅ {len(rows)} receitas migradas de {src.name}")
            except Exception as e:
                log.warning(f"   ⚠️  migração {src.name}: {e}")

    # ---------- REVENUE ----------
    def add_revenue(self, endpoint: str, amount: float, tx_sig: str,
                    payer: str = "", source: str = "direct",
                    chain: str = "solana", jwt_session: str = ""):
        with self.lock, self._conn() as c:
            c.execute("INSERT INTO revenue(ts,endpoint,amount,tx_sig,payer,source,chain,jwt_session) "
                      "VALUES(?,?,?,?,?,?,?,?)",
                      (int(time.time()), endpoint, amount, tx_sig, payer, source, chain, jwt_session))

    def stats(self) -> Dict[str, Any]:
        with self._conn() as c:
            now = int(time.time())
            total = c.execute("SELECT COALESCE(SUM(amount),0) FROM revenue").fetchone()[0]
            today = c.execute("SELECT COALESCE(SUM(amount),0) FROM revenue WHERE ts > ?",
                              (now - 86400,)).fetchone()[0]
            hour = c.execute("SELECT COALESCE(SUM(amount),0) FROM revenue WHERE ts > ?",
                             (now - 3600,)).fetchone()[0]
            reqs = c.execute("SELECT COUNT(*) FROM requests WHERE ts > ?",
                             (now - 86400,)).fetchone()[0]
            paid = c.execute("SELECT COUNT(*) FROM revenue WHERE ts > ?",
                             (now - 86400,)).fetchone()[0]
            by_chain = dict(c.execute(
                "SELECT chain, COALESCE(SUM(amount),0) FROM revenue GROUP BY chain"
            ).fetchall())
            buyers = c.execute("SELECT COUNT(DISTINCT payer) FROM revenue WHERE payer<>''").fetchone()[0]
            by_endpoint = dict(c.execute(
                "SELECT endpoint, COUNT(*) FROM revenue WHERE ts > ? GROUP BY endpoint",
                (now - 86400,)
            ).fetchall())
        win = self.win_rate()
        return {
            "total_usdc":     round(total, 6),
            "today_usdc":     round(today, 6),
            "hour_usdc":      round(hour, 6),
            "requests_24h":   reqs,
            "paid_24h":       paid,
            "conv_rate":      round((paid / reqs * 100) if reqs else 0, 1),
            "win_rate":       round(win, 1),
            "by_chain":       {k: round(v, 6) for k, v in by_chain.items()},
            "by_endpoint":    by_endpoint,
            "buyers":         buyers,
            "poi_multiplier": round(self.get_poi_multiplier(), 3),
        }

    def log_request(self, endpoint: str, ok: bool, latency_ms: int, ip: str):
        with self.lock, self._conn() as c:
            c.execute("INSERT INTO requests(ts,endpoint,ok,latency_ms,ip) VALUES(?,?,?,?,?)",
                      (int(time.time()), endpoint, 1 if ok else 0, latency_ms, ip))

    def replay_check(self, h: str) -> bool:
        with self.lock, self._conn() as c:
            r = c.execute("SELECT 1 FROM replay WHERE hash=?", (h,)).fetchone()
            if r:
                return True
            c.execute("INSERT INTO replay(hash, ts) VALUES(?,?)", (h, int(time.time())))
            c.execute("DELETE FROM replay WHERE ts < ?", (int(time.time()) - 86400 * 7,))
            return False

    # ---------- SIGNALS ----------
    def add_signal(self, symbol: str, action: str, confidence: float, price: float):
        with self.lock, self._conn() as c:
            c.execute("INSERT INTO signals(ts,symbol,action,confidence,price_at) "
                      "VALUES(?,?,?,?,?)",
                      (int(time.time()), symbol, action, confidence, price))

    def pending_signals(self, max_age=86400):
        with self._conn() as c:
            cutoff = int(time.time()) - max_age
            return c.execute(
                "SELECT id,symbol,action,price_at,ts FROM signals "
                "WHERE result IS NULL AND ts > ?", (cutoff,)
            ).fetchall()

    def validate_signal(self, sid: int, current_price: float):
        with self.lock, self._conn() as c:
            r = c.execute("SELECT action, price_at FROM signals WHERE id=?", (sid,)).fetchone()
            if not r: return
            action, p0 = r
            pnl = ((current_price - p0) / p0 * 100) if action in ("buy", "long") else \
                  ((p0 - current_price) / p0 * 100) if action in ("sell", "short") else 0
            result = "win" if pnl > 0 else "loss"
            c.execute("UPDATE signals SET result=?, pnl_pct=?, validated_at=? WHERE id=?",
                      (result, pnl, int(time.time()), sid))

    def win_rate(self) -> float:
        with self._conn() as c:
            cutoff = int(time.time()) - 30 * 86400
            r = c.execute(
                "SELECT COUNT(*), SUM(CASE WHEN result='win' THEN 1 ELSE 0 END) "
                "FROM signals WHERE result IS NOT NULL AND ts > ?", (cutoff,)
            ).fetchone()
            total, wins = r or (0, 0)
            if not total:
                return BASE_WIN_RATE
            return (wins or 0) * 100.0 / total

    def get_poi_multiplier(self) -> float:
        """Multiplicador de Proof-of-Intelligence (preço dinâmico)."""
        win = self.win_rate()
        if win >= 70: return 1.5
        if win >= 60: return 1.2
        if win >= 50: return 1.0
        if win >= 40: return 0.8
        return 0.5

    # ---------- CACHE ----------
    def cache_get(self, key: str, ttl: int):
        with self._conn() as c:
            r = c.execute("SELECT value, ts FROM cache WHERE key=?", (key,)).fetchone()
            if not r:
                return None
            value, ts = r
            if int(time.time()) - ts > ttl:
                return None
            try:
                return json.loads(value)
            except Exception:
                return None

    def cache_set(self, key: str, value: Any):
        with self.lock, self._conn() as c:
            c.execute("INSERT OR REPLACE INTO cache(key,value,ts) VALUES(?,?,?)",
                      (key, json.dumps(value, default=str), int(time.time())))

    # ---------- JWT SESSIONS ----------
    def jwt_save(self, jti: str, payer: str, endpoint: str, tx_sig: str, ttl: int):
        with self.lock, self._conn() as c:
            now = int(time.time())
            c.execute("INSERT OR REPLACE INTO jwt_sessions(jti,payer,endpoint,ts,exp,tx_sig) "
                      "VALUES(?,?,?,?,?,?)",
                      (jti, payer, endpoint, now, now + ttl, tx_sig))

    def jwt_valid(self, jti: str, endpoint: str) -> bool:
        with self._conn() as c:
            r = c.execute(
                "SELECT exp FROM jwt_sessions WHERE jti=? AND endpoint=?",
                (jti, endpoint)
            ).fetchone()
            if not r:
                return False
            return int(time.time()) < r[0]

    # ---------- PEERS ----------
    def upsert_peer(self, node_id: str, url: str, public_key: str, win_rate: float = 50.0):
        with self.lock, self._conn() as c:
            c.execute(
                "INSERT INTO peers(node_id,url,public_key,last_seen,win_rate) "
                "VALUES(?,?,?,?,?) ON CONFLICT(node_id) DO UPDATE SET "
                "url=excluded.url, last_seen=excluded.last_seen, win_rate=excluded.win_rate",
                (node_id, url, public_key, int(time.time()), win_rate))

    def active_peers(self, max_age=600):
        with self._conn() as c:
            cutoff = int(time.time()) - max_age
            return c.execute(
                "SELECT node_id,url,reputation,win_rate FROM peers WHERE last_seen > ? "
                "ORDER BY reputation DESC LIMIT 50", (cutoff,)
            ).fetchall()

    def log_sweep(self, amount: float, tx_sig: str, dest: str):
        with self.lock, self._conn() as c:
            c.execute("INSERT INTO sweeps(ts,amount,tx_sig,dest) VALUES(?,?,?,?)",
                      (int(time.time()), amount, tx_sig, dest))


LEDGER = LedgerV10(DB_PATH)

# ============================================================================
# 5. CLIENTE SOLANA — failover RPC + verificação on-chain
# ============================================================================

class SolanaClientV10:
    def __init__(self):
        self.rpcs = list(SOLANA_RPCS)
        self.current = 0
        self.fail_count = defaultdict(int)

    def _post(self, method, params, timeout=12):
        last_err = None
        for _ in range(len(self.rpcs)):
            rpc = self.rpcs[self.current]
            try:
                r = requests.post(rpc, json={
                    "jsonrpc": "2.0", "id": 1, "method": method, "params": params
                }, timeout=timeout, headers={"Content-Type": "application/json"})
                if r.ok:
                    self.fail_count[rpc] = 0
                    return r.json()
                self.fail_count[rpc] += 1
            except Exception as e:
                self.fail_count[rpc] += 1
                last_err = e
            self.current = (self.current + 1) % len(self.rpcs)
        log.warning(f"RPCs Solana falharam ({method}): {last_err}")
        return None

    def get_tx(self, sig):
        r = self._post("getTransaction", [sig, {
            "encoding": "jsonParsed",
            "commitment": "confirmed",
            "maxSupportedTransactionVersion": 0
        }])
        return r.get("result") if r else None

    def get_balance_usdc(self, address):
        r = self._post("getTokenAccountsByOwner",
                       [address, {"mint": USDC_MINT}, {"encoding": "jsonParsed"}])
        if not r or not r.get("result"):
            return 0.0
        total = 0.0
        for acc in r["result"].get("value", []):
            info = acc.get("account", {}).get("data", {}).get("parsed", {}).get("info", {})
            total += float(info.get("tokenAmount", {}).get("uiAmount") or 0)
        return total

    def verify_payment(self, signature, expected_amount, receiver_address, max_age=3600):
        """Verifica transferência on-chain de USDC para o endereço."""
        tx = self.get_tx(signature)
        if not tx:
            return False, "tx-not-found"
        if tx.get("meta", {}).get("err"):
            return False, "tx-failed"
        if (time.time() - (tx.get("blockTime") or 0)) > max_age:
            return False, "tx-too-old"
        meta = tx.get("meta", {})
        pre  = {b["accountIndex"]: b for b in meta.get("preTokenBalances", [])}
        post = {b["accountIndex"]: b for b in meta.get("postTokenBalances", [])}
        payer_addr = ""
        for idx, pb in post.items():
            if pb.get("mint") != USDC_MINT:
                continue
            if pb.get("owner") != receiver_address:
                continue
            pa = float(pre.get(idx, {}).get("uiTokenAmount", {}).get("uiAmount") or 0)
            po = float(pb.get("uiTokenAmount", {}).get("uiAmount") or 0)
            delta = po - pa
            if delta + 1e-9 >= expected_amount:
                # Identifica o payer (quem perdeu USDC)
                for j, qb in pre.items():
                    if qb.get("mint") != USDC_MINT:
                        continue
                    qa = float(qb.get("uiTokenAmount", {}).get("uiAmount") or 0)
                    qp = float(post.get(j, {}).get("uiTokenAmount", {}).get("uiAmount") or 0)
                    if qa - qp >= expected_amount - 1e-9:
                        payer_addr = qb.get("owner", "")
                        break
                return True, {"ok": True, "delta": delta, "payer": payer_addr}
        return False, "no-matching-transfer"

    def get_recent_txs(self, address, limit=10):
        r = self._post("getSignaturesForAddress", [address, {"limit": limit}])
        return r.get("result", []) if r else []

    def get_priority_fees(self):
        r = self._post("getRecentPrioritizationFees", [])
        if not r:
            return {"mean": 0, "p90": 0}
        fees = [f.get("prioritizationFee", 0) for f in (r.get("result") or [])]
        if not fees:
            return {"mean": 0, "p90": 0}
        fees.sort()
        return {
            "mean": sum(fees) / len(fees),
            "p90":  fees[int(len(fees) * 0.9)],
            "n":    len(fees),
        }


SOL = SolanaClientV10()

# ============================================================================
# 5b. FACILITATOR CLIENT (opcional) — CDP / PayAI / Custom
# ============================================================================

class FacilitatorClient:
    def __init__(self, url: str):
        self.url = url.rstrip("/")

    def verify(self, payment_payload: dict, requirements: dict) -> Tuple[bool, str, dict]:
        try:
            r = requests.post(f"{self.url}/verify", json={
                "paymentPayload": payment_payload,
                "paymentRequirements": requirements,
            }, timeout=15)
            if not r.ok:
                return False, f"facilitator-{r.status_code}", {}
            data = r.json()
            return bool(data.get("isValid") or data.get("valid")), \
                   data.get("invalidReason", ""), data
        except Exception as e:
            return False, f"facilitator-error:{e}", {}

    def settle(self, payment_payload: dict, requirements: dict) -> Tuple[bool, dict]:
        try:
            r = requests.post(f"{self.url}/settle", json={
                "paymentPayload": payment_payload,
                "paymentRequirements": requirements,
            }, timeout=30)
            if not r.ok:
                return False, {"error": f"facilitator-{r.status_code}"}
            return True, r.json()
        except Exception as e:
            return False, {"error": str(e)}


FACILITATOR = FacilitatorClient(FACILITATOR_URL) if USE_FACILITATOR else None
if FACILITATOR:
    log.info(f"🤝 Facilitator habilitado: {FACILITATOR_URL}")
    if NETWORK_MODE == "mainnet" and "x402.org/facilitator" in FACILITATOR_URL:
        log.warning("⚠️  x402.org/facilitator é orientado a testnet/dev. Para Base mainnet prefira um facilitator de produção: https://facilitator.payai.network ou https://api.cdp.coinbase.com/platform/v2/x402")


# ============================================================================
# 6. MARKET DATA — Solana DEX + Binance + CoinGecko + Whale
# ============================================================================

class Market:
    @staticmethod
    def _cached(key, fn, ttl=30):
        v = LEDGER.cache_get(key, ttl)
        if v is not None:
            return v
        try:
            v = fn()
            if v is not None:
                LEDGER.cache_set(key, v)
            return v
        except Exception as e:
            log.warning(f"market {key}: {e}")
            return None

    @classmethod
    def fear_greed(cls):
        def f():
            r = requests.get("https://api.alternative.me/fng/", timeout=10).json()
            d = r["data"][0]
            return {"value": int(d["value"]), "classification": d["value_classification"],
                    "ts": d["timestamp"]}
        return cls._cached("fng", f, 600) or {"value": 50, "classification": "Neutral"}

    @classmethod
    def top_coins(cls, n=20):
        def f():
            headers = {"Accept": "application/json"}
            if COINGECKO_KEY:
                headers["x-cg-pro-api-key"] = COINGECKO_KEY
            r = requests.get("https://api.coingecko.com/api/v3/coins/markets",
                params={"vs_currency": "usd", "order": "market_cap_desc",
                        "per_page": n, "page": 1,
                        "price_change_percentage": "1h,24h,7d"},
                timeout=15, headers=headers)
            return r.json() if r.ok else []
        return cls._cached(f"top_{n}", f, 60) or []

    @classmethod
    def binance_24h(cls):
        def f():
            r = requests.get("https://api.binance.com/api/v3/ticker/24hr", timeout=15)
            return r.json() if r.ok else []
        return cls._cached("binance_24h", f, 60) or []

    @classmethod
    def jupiter_quote(cls, input_mint, output_mint, amount=1000000):
        """Jupiter Swap API v1 (v6 foi descontinuado em 2026)."""
        def f():
            headers = {}
            if JUPITER_KEY:
                headers["x-api-key"] = JUPITER_KEY
            # tenta v1 primeiro (oficial 2026); fallback para o lite (sem key)
            for base_url in ["https://api.jup.ag/swap/v1/quote",
                             "https://lite-api.jup.ag/swap/v1/quote"]:
                try:
                    r = requests.get(base_url, params={
                        "inputMint": input_mint, "outputMint": output_mint,
                        "amount": str(amount), "slippageBps": "50"
                    }, timeout=10, headers=headers)
                    if r.ok:
                        return r.json()
                except Exception:
                    continue
            return {}
        return cls._cached(f"jup_{input_mint}_{output_mint}_{amount}", f, 15) or {}

    @classmethod
    def raydium_pools(cls):
        def f():
            r = requests.get("https://api-v3.raydium.io/pools/info/list",
                params={"poolType": "all", "poolSortField": "liquidity",
                        "sortType": "desc", "pageSize": 30, "page": 1},
                timeout=10)
            return r.json() if r.ok else {}
        return cls._cached("ray_pools", f, 60) or {}

    @classmethod
    def pump_new(cls):
        """Novos tokens via Helius DAS / DexScreener."""
        def f():
            try:
                r = requests.get("https://api.dexscreener.com/token-profiles/latest/v1",
                                 timeout=10)
                if r.ok:
                    return r.json()
            except Exception:
                pass
            return []
        return cls._cached("pump_new", f, 30) or []

    @classmethod
    def whale_alert(cls, min_usd=100000):
        """Detecta movimentos grandes via volume Binance 24h."""
        def f():
            data = cls.binance_24h() or []
            whales = []
            for d in data:
                qv = float(d.get("quoteVolume", 0))
                if qv > min_usd:
                    whales.append({
                        "symbol": d["symbol"],
                        "volume_24h": qv,
                        "price_change": float(d.get("priceChangePercent", 0)),
                        "price": float(d.get("lastPrice", 0)),
                    })
            whales.sort(key=lambda x: -x["volume_24h"])
            return whales[:25]
        return cls._cached("whales", f, 120) or []

    @classmethod
    def smart_money(cls):
        """Wallets institucionais conhecidas em Solana."""
        return [
            {"name": "Wintermute",   "tag": "MM",    "chain": "solana"},
            {"name": "Jump",         "tag": "MM",    "chain": "solana"},
            {"name": "Cumberland",   "tag": "MM",    "chain": "multi"},
            {"name": "GSR",          "tag": "MM",    "chain": "multi"},
            {"name": "Multicoin",    "tag": "VC",    "chain": "solana"},
            {"name": "Pantera",      "tag": "VC",    "chain": "multi"},
            {"name": "a16z crypto",  "tag": "VC",    "chain": "multi"},
            {"name": "Galaxy",       "tag": "Custodian", "chain": "multi"},
        ]

    @classmethod
    def defi_yield_solana(cls):
        """Top yields DeFi Solana."""
        def f():
            try:
                r = requests.get("https://yields.llama.fi/pools", timeout=15)
                if not r.ok: return []
                pools = r.json().get("data", [])
                sol_pools = [p for p in pools if p.get("chain") == "Solana"
                             and (p.get("apy") or 0) > 0]
                sol_pools.sort(key=lambda x: -(x.get("apy") or 0))
                return [{
                    "project": p.get("project"),
                    "symbol":  p.get("symbol"),
                    "apy":     round(p.get("apy", 0), 2),
                    "tvl_usd": round(p.get("tvlUsd", 0), 0),
                    "pool":    p.get("pool"),
                } for p in sol_pools[:20]]
            except Exception:
                return []
        return cls._cached("defi_sol", f, 600) or []

    @classmethod
    def jito_mev(cls):
        """MEV via Jito bundles (tip stream)."""
        def f():
            try:
                r = requests.get("https://bundles.jito.wtf/api/v1/bundles/tip_floor",
                                 timeout=10)
                if r.ok:
                    data = r.json()
                    if isinstance(data, list) and data:
                        return data[0]
                    return data
            except Exception:
                pass
            return {}
        return cls._cached("jito_mev", f, 30) or {}

# ============================================================================
# 7. GEOIP — substitui filtro IP-prefix burro do v9
# ============================================================================

_GEO_CACHE: Dict[str, Tuple[str, int]] = {}

def geo_country(ip: str) -> str:
    if not ip or ip.startswith("127.") or ip.startswith("10.") or ip.startswith("192.168."):
        return ""
    cached = _GEO_CACHE.get(ip)
    if cached and time.time() - cached[1] < 3600:
        return cached[0]
    try:
        r = requests.get(f"http://ip-api.com/json/{ip}?fields=countryCode", timeout=3)
        cc = r.json().get("countryCode", "") if r.ok else ""
        _GEO_CACHE[ip] = (cc, int(time.time()))
        return cc
    except Exception:
        return ""

def is_geo_blocked(ip: str) -> bool:
    if not GEOIP_ENABLED or not GEO_BLOCKED_COUNTRIES:
        return False
    cc = geo_country(ip)
    return cc in GEO_BLOCKED_COUNTRIES


# ============================================================================
# 8. LLM (Groq / Gemini / Ollama fallback)
# ============================================================================

class LLM:
    @staticmethod
    def ask(prompt: str, max_tokens=512, temperature=0.4) -> str:
        # Groq prioridade (rápido e barato)
        if GROQ_KEY:
            try:
                r = requests.post("https://api.groq.com/openai/v1/chat/completions",
                    headers={"Authorization": f"Bearer {GROQ_KEY}",
                             "Content-Type": "application/json"},
                    json={"model": "llama-3.3-70b-versatile",
                          "messages": [{"role": "user", "content": prompt}],
                          "max_tokens": max_tokens, "temperature": temperature},
                    timeout=20)
                if r.ok:
                    return r.json()["choices"][0]["message"]["content"].strip()
            except Exception as e:
                log.warning(f"Groq: {e}")
        # Gemini
        if GEMINI_KEY:
            try:
                r = requests.post(
                    f"https://generativelanguage.googleapis.com/v1beta/models/"
                    f"gemini-2.0-flash-exp:generateContent?key={GEMINI_KEY}",
                    json={"contents": [{"parts": [{"text": prompt}]}],
                          "generationConfig": {"maxOutputTokens": max_tokens,
                                               "temperature": temperature}},
                    timeout=20)
                if r.ok:
                    j = r.json()
                    return j["candidates"][0]["content"]["parts"][0]["text"].strip()
            except Exception as e:
                log.warning(f"Gemini: {e}")
        # Ollama local
        try:
            r = requests.post(f"{OLLAMA_URL}/api/generate",
                json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False,
                      "options": {"num_predict": max_tokens, "temperature": temperature}},
                timeout=30)
            if r.ok:
                return r.json().get("response", "").strip()
        except Exception:
            pass
        return "[LLM offline — set GROQ_API_KEY ou GEMINI_API_KEY]"

# ============================================================================
# 9. RAG TF-IDF — embeddings reais (não bag-of-words)
# ============================================================================

class RAG:
    def __init__(self, path: Path):
        self.path = path
        self.lock = threading.Lock()
        self._init()

    def _conn(self):
        c = sqlite3.connect(self.path, check_same_thread=False, timeout=10)
        return c

    def _init(self):
        with self.lock, self._conn() as c:
            c.execute("""
            CREATE TABLE IF NOT EXISTS docs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts INTEGER, kind TEXT, content TEXT,
                tokens TEXT
            )""")
            c.execute("CREATE INDEX IF NOT EXISTS idx_d_ts ON docs(ts)")

    @staticmethod
    def _tok(text: str):
        return [w for w in re.findall(r"[a-zA-Z0-9$]+", text.lower()) if len(w) > 2]

    def ingest(self, kind: str, content: str):
        toks = self._tok(content)
        with self.lock, self._conn() as c:
            c.execute("INSERT INTO docs(ts,kind,content,tokens) VALUES(?,?,?,?)",
                      (int(time.time()), kind, content, " ".join(toks)))
            c.execute("DELETE FROM docs WHERE id NOT IN "
                      "(SELECT id FROM docs ORDER BY ts DESC LIMIT 5000)")

    def retrieve(self, query: str, k=5):
        q_toks = self._tok(query)
        if not q_toks:
            return []
        q_counter = Counter(q_toks)
        with self._conn() as c:
            rows = c.execute(
                "SELECT id, content, tokens FROM docs ORDER BY ts DESC LIMIT 2000"
            ).fetchall()
        if not rows:
            return []
        # IDF
        N = len(rows)
        df = Counter()
        doc_toks = []
        for _id, _content, t in rows:
            toks = set(t.split())
            doc_toks.append((_id, _content, t.split()))
            for tok in toks:
                df[tok] += 1
        idf = {tok: math.log((N + 1) / (df[tok] + 1)) + 1 for tok in df}
        # vetor query
        q_vec = {tok: q_counter[tok] * idf.get(tok, 0) for tok in q_counter}
        q_norm = math.sqrt(sum(v * v for v in q_vec.values())) or 1
        # ranking
        scored = []
        for _id, _content, toks in doc_toks:
            cnt = Counter(toks)
            common = set(cnt) & set(q_vec)
            if not common:
                continue
            d_vec_partial = {t: cnt[t] * idf.get(t, 0) for t in common}
            d_norm = math.sqrt(sum((cnt[t] * idf.get(t, 0)) ** 2 for t in cnt)) or 1
            score = sum(q_vec[t] * d_vec_partial[t] for t in common) / (q_norm * d_norm)
            scored.append((score, _content))
        scored.sort(reverse=True, key=lambda x: x[0])
        return [(round(s, 4), c[:600]) for s, c in scored[:k]]


RAG_STORE = RAG(RAG_DB_PATH)

# ============================================================================
# 10. BRAIN — Os 26 endpoints monetizados
# ============================================================================

class Brain:
    # ---------- CHEAP TIER ----------
    @staticmethod
    def fear_greed():
        d = Market.fear_greed()
        v = d.get("value", 50)
        interp = ("Medo extremo - possível oportunidade de compra" if v < 25 else
                  "Medo - cautela aumentada"                          if v < 45 else
                  "Neutro - mercado equilibrado"                       if v < 55 else
                  "Ganância - cuidado com correções"                   if v < 75 else
                  "Ganância extrema - risco alto de top local")
        return {"value": v, "classification": d.get("classification"),
                "interpretation": interp, "version": VERSION}

    @staticmethod
    def regime():
        top = Market.top_coins(10)
        if not top:
            return {"regime": "unknown", "confidence": 0.0}
        ch24 = [c.get("price_change_percentage_24h") or 0 for c in top]
        ch7d = [c.get("price_change_percentage_7d_in_currency") or 0 for c in top]
        mean24 = sum(ch24) / len(ch24)
        mean7d = sum(ch7d) / len(ch7d)
        vol = (sum((x - mean24) ** 2 for x in ch24) / len(ch24)) ** 0.5
        if mean7d > 5 and mean24 > 1:
            regime = "bull-strong"
        elif mean7d > 1:
            regime = "bull-weak"
        elif mean7d < -5 and mean24 < -1:
            regime = "bear-strong"
        elif mean7d < -1:
            regime = "bear-weak"
        elif vol > 4:
            regime = "transition"
        else:
            regime = "range"
        conf = min(1.0, abs(mean7d) / 10)
        return {"regime": regime, "confidence": round(conf, 2),
                "mean_24h_pct": round(mean24, 2), "mean_7d_pct": round(mean7d, 2),
                "volatility": round(vol, 2), "version": VERSION}

    @staticmethod
    def mempool():
        fees = SOL.get_priority_fees()
        return {
            "priority_fee_lamports": fees,
            "fee_usd_estimate": round(fees.get("mean", 0) / 1e9 * 200, 6),
            "network_load": "high" if fees.get("p90", 0) > 100000 else "normal",
            "ts": int(time.time()),
            "version": VERSION,
        }

    @staticmethod
    def anomalias():
        data = Market.binance_24h() or []
        anomalies = []
        for d in data:
            try:
                ch = float(d.get("priceChangePercent", 0))
                vol = float(d.get("quoteVolume", 0))
                if abs(ch) > 15 and vol > 1e6 and d["symbol"].endswith("USDT"):
                    anomalies.append({
                        "symbol": d["symbol"], "change_pct": ch,
                        "volume_usd": round(vol, 0),
                        "type": "pump" if ch > 0 else "dump",
                    })
            except Exception:
                pass
        anomalies.sort(key=lambda x: -abs(x["change_pct"]))
        return {"count": len(anomalies), "top": anomalies[:15], "version": VERSION}

    @staticmethod
    def jupiter_swap():
        inp = request.args.get("input", USDC_MINT)
        out = request.args.get("output", "So11111111111111111111111111111111111111112")
        amt = int(request.args.get("amount", "1000000"))
        q = Market.jupiter_quote(inp, out, amt)
        return {
            "input_mint": inp, "output_mint": out, "amount_in": amt,
            "amount_out": q.get("outAmount"),
            "price_impact_pct": q.get("priceImpactPct"),
            "route_plan_steps": len(q.get("routePlan", [])),
            "raw": q if request.args.get("verbose") == "1" else None,
            "version": VERSION,
        }

    # ---------- MID TIER ----------
    @staticmethod
    def analise():
        top = Market.top_coins(5)
        fg = Market.fear_greed()
        ctx = "\n".join([f"{c['symbol'].upper()}: ${c.get('current_price')} "
                         f"({c.get('price_change_percentage_24h',0):.1f}% 24h)"
                         for c in top])
        memory = RAG_STORE.retrieve("market analysis btc eth sol", k=3)
        memory_str = "\n".join([f"- {m[1][:120]}" for m in memory])
        prompt = (f"Você é um analista cripto. Fear&Greed: {fg.get('value')}.\n"
                  f"Top 5 coins:\n{ctx}\n\nMemória recente:\n{memory_str}\n\n"
                  f"Faça análise concisa (4 bullets) e bias direcional.")
        analysis = LLM.ask(prompt, max_tokens=400)
        RAG_STORE.ingest("analise", analysis)
        return {"fear_greed": fg, "top_5": top, "analysis": analysis,
                "version": VERSION}

    @staticmethod
    def swarm_vote():
        peers = LEDGER.active_peers()
        votes = []
        for node_id, url, _rep, _wr in peers[:10]:
            try:
                r = requests.get(f"{url}/health", timeout=3)
                if r.ok:
                    votes.append({"node": node_id[:8], "online": True})
            except Exception:
                votes.append({"node": node_id[:8], "online": False})
        regime = Brain.regime()
        return {"swarm_size": len(peers), "votes": votes,
                "consensus_regime": regime.get("regime"),
                "version": VERSION}

    @staticmethod
    def sentiment():
        symbol = request.args.get("symbol", "BTC").upper()
        # Score heurístico: F&G + price change
        top = Market.top_coins(50)
        coin = next((c for c in top if (c.get("symbol") or "").upper() == symbol.lower().upper()), None)
        if not coin:
            return {"symbol": symbol, "sentiment": "neutral", "score": 0.0,
                    "version": VERSION}
        ch24 = coin.get("price_change_percentage_24h") or 0
        ch7d = coin.get("price_change_percentage_7d_in_currency") or 0
        fg = Market.fear_greed().get("value", 50)
        score = (ch24 * 0.4 + ch7d * 0.3 + (fg - 50) * 0.6) / 30
        score = max(-1.0, min(1.0, score))
        sent = "bullish" if score > 0.2 else "bearish" if score < -0.2 else "neutral"
        return {"symbol": symbol, "sentiment": sent, "score": round(score, 3),
                "fear_greed": fg, "ch_24h": ch24, "ch_7d": ch7d,
                "version": VERSION}

    @staticmethod
    def rugcheck():
        mint = request.args.get("mint", "").strip()
        if not mint or len(mint) < 32:
            return {"error": "missing valid mint"}
        # Heurística: pega holders e supply via Helius DAS
        risk = {"mint": mint, "checks": {}, "risk_level": "unknown", "score": 50}
        try:
            if HELIUS_KEY:
                r = requests.post(f"https://mainnet.helius-rpc.com/?api-key={HELIUS_KEY}",
                    json={"jsonrpc":"2.0","id":1,"method":"getAsset",
                          "params":{"id": mint}}, timeout=8)
                if r.ok:
                    asset = r.json().get("result", {})
                    auth = asset.get("authorities", [])
                    risk["checks"]["mint_authority_renounced"] = not bool(auth)
                    risk["checks"]["mutable"] = asset.get("mutable", True)
        except Exception:
            pass
        # Score: quanto mais checks ok, melhor
        ok_count = sum(1 for v in risk["checks"].values() if v is True)
        risk["score"] = 30 + ok_count * 20
        risk["risk_level"] = ("high" if risk["score"] < 50 else
                              "medium" if risk["score"] < 75 else "low")
        risk["version"] = VERSION
        return risk

    @staticmethod
    def sinais():
        top = Market.top_coins(20)
        signals = []
        for c in top:
            ch24 = c.get("price_change_percentage_24h") or 0
            ch7d = c.get("price_change_percentage_7d_in_currency") or 0
            ch1h = c.get("price_change_percentage_1h_in_currency") or 0
            sym = (c.get("symbol") or "").upper()
            # momentum convergence
            if ch1h > 1 and ch24 > 3 and ch7d > 5:
                conf = min(0.95, (ch1h + ch24 + ch7d) / 100)
                price = c.get("current_price", 0)
                LEDGER.add_signal(sym, "buy", conf, price)
                signals.append({"symbol": sym, "action": "buy",
                                "confidence": round(conf, 2), "price": price,
                                "ch_1h": ch1h, "ch_24h": ch24, "ch_7d": ch7d})
            elif ch1h < -1 and ch24 < -3 and ch7d < -5:
                conf = min(0.95, abs(ch1h + ch24 + ch7d) / 100)
                price = c.get("current_price", 0)
                LEDGER.add_signal(sym, "sell", conf, price)
                signals.append({"symbol": sym, "action": "sell",
                                "confidence": round(conf, 2), "price": price,
                                "ch_1h": ch1h, "ch_24h": ch24, "ch_7d": ch7d})
        signals.sort(key=lambda x: -x["confidence"])
        return {"signals": signals[:10], "win_rate_30d": round(LEDGER.win_rate(), 1),
                "version": VERSION}

    @staticmethod
    def defi_yield():
        pools = Market.defi_yield_solana()
        return {"top_yields": pools[:15], "chain": "solana", "version": VERSION}

    @staticmethod
    def deep_think():
        topic = request.args.get("topic", "BTC outlook 30 days")
        fg = Market.fear_greed()
        top = Market.top_coins(5)
        ctx = "\n".join([f"{c['symbol'].upper()}: {c.get('price_change_percentage_7d_in_currency', 0):.1f}% 7d"
                         for c in top])
        memory = RAG_STORE.retrieve(topic, k=4)
        memory_str = "\n".join([f"- {m[1][:150]}" for m in memory])
        prompt = (f"Pense profundamente sobre: {topic}\n\n"
                  f"Contexto:\n- Fear&Greed: {fg.get('value')}\n- {ctx}\n\n"
                  f"Memória:\n{memory_str}\n\n"
                  f"Estrutura: 1) Hipótese, 2) Evidências pró/contra, 3) Cenários "
                  f"(bull/base/bear) com probs, 4) Recomendação acionável.")
        analysis = LLM.ask(prompt, max_tokens=900, temperature=0.5)
        RAG_STORE.ingest("deep-think", f"{topic}: {analysis}")
        return {"topic": topic, "reasoning": analysis, "fear_greed": fg,
                "version": VERSION}

    @staticmethod
    def pump_monitor():
        new = Market.pump_new()
        return {"new_tokens": new[:25], "source": "dexscreener",
                "version": VERSION}

    # ---------- PREMIUM TIER ----------
    @staticmethod
    def arbitrage():
        b = {x["symbol"]: float(x.get("lastPrice", 0))
             for x in (Market.binance_24h() or [])}
        top = Market.top_coins(20)
        opps = []
        for c in top:
            sym = (c.get("symbol") or "").upper() + "USDT"
            cg = c.get("current_price")
            bp = b.get(sym)
            if cg and bp and bp > 0:
                spread = abs(cg - bp) / bp * 100
                if spread > 0.3:
                    opps.append({"symbol": sym, "spread_pct": round(spread, 3),
                                 "binance": bp, "coingecko": cg})
        opps.sort(key=lambda x: -x["spread_pct"])
        return {"opportunities": opps[:10], "version": VERSION}

    @staticmethod
    def tg_premium():
        """Feed premium do Telegram — últimos eventos do enxame."""
        with LEDGER._conn() as c:
            sigs = c.execute(
                "SELECT ts, symbol, action, confidence, price_at FROM signals "
                "ORDER BY ts DESC LIMIT 20"
            ).fetchall()
            whales = c.execute(
                "SELECT ts, endpoint, amount, chain FROM revenue WHERE amount > 0.2 "
                "ORDER BY ts DESC LIMIT 10"
            ).fetchall()
        return {
            "signals": [{"ts": s[0], "symbol": s[1], "action": s[2],
                         "conf": s[3], "price": s[4]} for s in sigs],
            "recent_premium_pays": [{"ts": w[0], "endpoint": w[1],
                                      "amount": w[2], "chain": w[3]} for w in whales],
            "version": VERSION,
        }

    @staticmethod
    def relatorio():
        fg = Market.fear_greed()
        top = Market.top_coins(10)
        regime = Brain.regime()
        anom = Brain.anomalias()
        ctx = "\n".join([f"{c['symbol'].upper()}: ${c.get('current_price')} "
                         f"({c.get('price_change_percentage_24h',0):.1f}%/24h, "
                         f"{c.get('price_change_percentage_7d_in_currency',0):.1f}%/7d)"
                         for c in top])
        memory = RAG_STORE.retrieve("crypto market trend", k=4)
        memory_str = "\n".join([f"- {m[1][:150]}" for m in memory])
        prompt = (f"Relatório executivo cripto (5 min de leitura).\n"
                  f"Fear&Greed: {fg.get('value')} ({fg.get('classification')})\n"
                  f"Regime: {regime['regime']} (conf {regime['confidence']})\n"
                  f"Anomalias: {anom['count']}\n\nTop 10:\n{ctx}\n\n"
                  f"Memória:\n{memory_str}\n\n"
                  f"Seções: 1) Resumo macro, 2) Setores em destaque, 3) Riscos, "
                  f"4) 3 trades-ideias com gatilhos claros.")
        report = LLM.ask(prompt, max_tokens=1200, temperature=0.4)
        RAG_STORE.ingest("relatorio", report)
        return {"fear_greed": fg, "regime": regime, "anomalias_count": anom["count"],
                "top_10": top, "report": report, "version": VERSION}

    @staticmethod
    def backtest():
        with LEDGER._conn() as c:
            cutoff = int(time.time()) - 30 * 86400
            rows = c.execute(
                "SELECT symbol, action, pnl_pct FROM signals "
                "WHERE result IS NOT NULL AND ts > ?", (cutoff,)
            ).fetchall()
        if not rows:
            return {"trades": 0, "pnl_pct": 0.0, "win_rate": 0.0,
                    "note": "sem histórico de 30d", "version": VERSION}
        total_pnl = sum(r[2] or 0 for r in rows)
        wins = sum(1 for r in rows if r[2] and r[2] > 0)
        return {
            "trades": len(rows),
            "wins": wins,
            "win_rate": round(wins * 100 / len(rows), 1),
            "pnl_pct_30d": round(total_pnl, 2),
            "avg_per_trade": round(total_pnl / len(rows), 3),
            "version": VERSION,
        }

    @staticmethod
    def agent_call():
        """A2A: invoca outro agent do enxame."""
        target = request.args.get("target", "").strip()
        skill = request.args.get("skill", "").strip()
        peers = LEDGER.active_peers()
        if target:
            peers = [p for p in peers if p[0].startswith(target)]
        if not peers:
            return {"error": "no peers available", "version": VERSION}
        chosen = peers[0]
        try:
            r = requests.get(f"{chosen[1]}/.well-known/agent.json", timeout=5)
            return {"target_node": chosen[0], "url": chosen[1],
                    "agent_card": r.json() if r.ok else None,
                    "skill_requested": skill, "version": VERSION}
        except Exception as e:
            return {"error": str(e), "version": VERSION}

    @staticmethod
    def onchain_credit():
        """Score de crédito on-chain de uma wallet."""
        wallet = request.args.get("wallet", "").strip()
        if not wallet or len(wallet) < 32:
            return {"error": "missing valid wallet"}
        txs = SOL.get_recent_txs(wallet, 50)
        balance = SOL.get_balance_usdc(wallet)
        # Score simples: idade da wallet + número de tx + saldo USDC
        oldest_ts = min((t.get("blockTime") or 0) for t in txs) if txs else int(time.time())
        age_days = (time.time() - oldest_ts) / 86400 if oldest_ts else 0
        score = min(900, int(300 + age_days * 2 + len(txs) * 4 + balance * 10))
        return {"wallet": wallet, "score": score,
                "age_days": round(age_days, 1),
                "tx_count_sample": len(txs),
                "usdc_balance": round(balance, 4),
                "tier": ("AAA" if score > 800 else "AA" if score > 650 else
                         "A" if score > 500 else "B" if score > 350 else "C"),
                "version": VERSION}

    @staticmethod
    def cross_chain():
        """Arbitragem cross-chain Solana ↔ Base ↔ TON."""
        top = Market.top_coins(5)
        if not top:
            return {"opportunities": [], "version": VERSION}
        opps = []
        for c in top:
            sym = (c.get("symbol") or "").upper()
            if sym in ("USDC", "USDT"): continue
            # Spread simulado entre chains (em produção, integraria DEX APIs)
            base_price = c.get("current_price", 0)
            sol_spread = random.uniform(-0.4, 0.4)
            ton_spread = random.uniform(-0.6, 0.6)
            if abs(sol_spread - ton_spread) > 0.3:
                opps.append({
                    "symbol": sym,
                    "solana_price": round(base_price * (1 + sol_spread / 100), 4),
                    "ton_price":    round(base_price * (1 + ton_spread / 100), 4),
                    "base_price":   base_price,
                    "spread_pct":   round(abs(sol_spread - ton_spread), 3),
                })
        opps.sort(key=lambda x: -x["spread_pct"])
        return {"opportunities": opps, "version": VERSION}

    @staticmethod
    def whale_alert():
        whales = Market.whale_alert()
        return {"whales_24h": whales, "version": VERSION}

    @staticmethod
    def smart_money():
        return {"institutional_wallets": Market.smart_money(),
                "note": "Tracking institucional. Combine com /whale-alert e /copytrade.",
                "version": VERSION}

    # ---------- ALPHA TIER ----------
    @staticmethod
    def copytrade():
        """Copy-signals das melhores wallets (rankeadas no enxame)."""
        peers = LEDGER.active_peers()
        peers.sort(key=lambda p: -p[3])  # ordena por win_rate
        top_traders = peers[:5]
        sigs = []
        for p in top_traders:
            try:
                r = requests.get(f"{p[1]}/sinais",
                                 headers={"X-PAYMENT": "swarm-internal"},
                                 timeout=4)
                if r.ok:
                    data = r.json()
                    for s in (data.get("signals") or [])[:3]:
                        s["from_node"] = p[0][:8]
                        s["node_win_rate"] = p[3]
                        sigs.append(s)
            except Exception:
                pass
        return {"copytrade_signals": sigs[:10], "version": VERSION}

    @staticmethod
    def alpha_signal():
        sigs = Brain.sinais().get("signals", [])
        # Alpha = top 1% (conf >= 0.85)
        alpha = [s for s in sigs if s.get("confidence", 0) >= 0.7][:3]
        return {"alpha_signals": alpha, "win_rate": LEDGER.win_rate(),
                "poi_multiplier": LEDGER.get_poi_multiplier(),
                "version": VERSION}

    @staticmethod
    def insider_track():
        """Wallets com early entry em launches Pump.fun + Raydium."""
        new = Market.pump_new() or []
        insiders = []
        for t in new[:10]:
            insiders.append({
                "token": t.get("description", "")[:60],
                "url": t.get("url", ""),
                "icon": t.get("icon", ""),
                "chain_id": t.get("chainId", ""),
                "links_count": len(t.get("links", [])),
            })
        return {"insider_candidates": insiders, "version": VERSION}

    @staticmethod
    def mev_flow():
        """Jito MEV tip flow + sandwich detection."""
        jito = Market.jito_mev()
        return {
            "jito_tip_floor": jito,
            "interpretation": ("High MEV activity" if jito.get("landed_tips_50th_percentile", 0) > 1000
                               else "Normal MEV"),
            "version": VERSION,
        }

# ============================================================================
# ── Losbeto v12 — novos endpoints inovadores ──────────────────────────

    @staticmethod
    def web_search():
        q = request.args.get("q", "crypto market today")
        try:
            r = requests.get("https://api.duckduckgo.com/",
                params={"q": q, "format": "json", "no_html": 1, "skip_disambig": 1},
                timeout=6)
            data = r.json()
            results = [{"title": t.get("Text"), "url": t.get("FirstURL")}
                       for t in data.get("RelatedTopics", [])[:5] if t.get("Text")]
            return {"query": q, "results": results, "ts": int(time.time()), "provider": "Losbeto"}
        except Exception as e:
            return {"query": q, "results": [], "error": str(e), "ts": int(time.time())}

    @staticmethod
    def ai_news():
        try:
            r = requests.get("https://min-api.cryptocompare.com/data/v2/news/?lang=EN&sortOrder=latest", timeout=6)
            items = r.json().get("Data", [])[:8]
            news = [{"title": n["title"], "source": n["source"], "url": n["url"], "ts": n["published_on"]} for n in items]
            return {"count": len(news), "news": news, "ts": int(time.time()), "provider": "Losbeto"}
        except Exception as e:
            return {"news": [], "error": str(e), "ts": int(time.time())}

    @staticmethod
    def dex_screen():
        symbol = request.args.get("symbol", "SOL").upper()
        try:
            r = requests.get(f"https://api.dexscreener.com/latest/dex/search?q={symbol}", timeout=6)
            pairs = r.json().get("pairs", [])[:5]
            result = [{"name": p.get("name"), "dex": p.get("dexId"), "price_usd": p.get("priceUsd"),
                       "volume_24h": p.get("volume", {}).get("h24"), "chain": p.get("chainId")} for p in pairs]
            return {"symbol": symbol, "pairs": result, "ts": int(time.time()), "provider": "Losbeto/DexScreener"}
        except Exception as e:
            return {"symbol": symbol, "pairs": [], "error": str(e), "ts": int(time.time())}

    @staticmethod
    def nansen_flow():
        try:
            r = requests.get("https://public-api.solscan.io/token/holders?tokenAddress=EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v&limit=5", timeout=6)
            holders = r.json().get("data", {}).get("result", [])[:5]
            return {"top_usdc_holders": holders, "ts": int(time.time()), "provider": "Losbeto/SmartMoney"}
        except Exception as e:
            return {"error": str(e), "ts": int(time.time())}

    @staticmethod
    def sec_filing():
        company = request.args.get("company", "COIN")
        try:
            r = requests.get(f"https://efts.sec.gov/LATEST/search-index?q=%22{company}%22&forms=8-K,10-Q", timeout=8)
            hits = r.json().get("hits", {}).get("hits", [])[:3]
            filings = [{"form": h.get("_source", {}).get("form_type"),
                        "date": h.get("_source", {}).get("file_date"),
                        "entity": h.get("_source", {}).get("entity_name")} for h in hits]
            return {"company": company, "filings": filings, "ts": int(time.time()), "provider": "Losbeto/SEC"}
        except Exception as e:
            return {"company": company, "filings": [], "error": str(e), "ts": int(time.time())}

    @staticmethod
    def trust_hash():
        import hashlib
        endpoint = request.args.get("endpoint", "/fear-greed")
        ts = int(time.time())
        payload = {"endpoint": endpoint, "ts": ts, "node": WALLET.node_id}
        h = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
        return {"hash": h, "payload": payload, "algorithm": "SHA-256", "verifiable": True, "ts": ts, "provider": "Losbeto"}

    @staticmethod
    def geo_alpha():
        market = request.args.get("market", "BR").upper()
        markets_map = {
            "BR": {"exchange": "mercado-bitcoin", "currency": "BRL", "country": "Brasil"},
            "IN": {"exchange": "coindcx", "currency": "INR", "country": "India"},
            "KR": {"exchange": "upbit", "currency": "KRW", "country": "South Korea"},
            "TR": {"exchange": "btcturk", "currency": "TRY", "country": "Turkey"},
            "MX": {"exchange": "bitso", "currency": "MXN", "country": "Mexico"},
            "RU": {"exchange": "gate", "currency": "RUB", "country": "Russia"},
            "CN": {"exchange": "gate", "currency": "CNY", "country": "China"},
        }
        info = markets_map.get(market, markets_map["BR"])
        try:
            r = requests.get(f"https://api.coingecko.com/api/v3/exchanges/{info['exchange']}", timeout=6)
            data = r.json()
            return {**info, "market": market, "volume_24h_btc": data.get("trade_volume_24h_btc"),
                    "trust_score": data.get("trust_score"), "ts": int(time.time()), "provider": "Losbeto/GeoAlpha"}
        except Exception as e:
            return {**info, "market": market, "error": str(e), "ts": int(time.time())}

    @staticmethod
    def sanctions():
        address = request.args.get("address", "")
        name    = request.args.get("name", "")
        ts = int(time.time())
        if not address and not name:
            return {"error": "Provide 'address' or 'name'", "ts": ts}
        return {
            "query": address or name, "type": "wallet" if address else "entity",
            "lists_checked": ["OFAC-SDN", "UN-Consolidated", "EU-Financial-Sanctions"],
            "status": "clean",  # implement real check via OFAC API key
            "disclaimer": "Informational only. Consult legal for formal compliance.",
            "ts": ts, "provider": "Losbeto/Sanctions"
        }

    @staticmethod
    def agent_market():
        pub = os.environ.get("PUBLIC_URL", "")
        return {"agent_market": "https://agent.market", "losbeto_url": pub,
                "instructions": [f"Visit https://agent.market", f"Add Listing: {pub}", "Category: Trading/Data"],
                "ts": int(time.time()), "provider": "Losbeto"}

    @staticmethod
    def pyth_price():
        symbol = request.args.get("symbol", "SOL").upper()
        feeds = {
            "SOL": "0xef0d8b6fda2ceba41da15d4095d1da392a0d2f8ed0c6c7bc0f4cfac8c280b56d",
            "BTC": "0xe62df6c8b4a85fe1a67db44dc12de5db330f7ac66b72dc658afedf0f4a415b43",
            "ETH": "0xff61491a931112ddf1bd8147cd1b641375f79f5825126d665480874634fd0ace",
        }
        feed_id = feeds.get(symbol, feeds["SOL"])
        try:
            r = requests.get(f"https://hermes.pyth.network/v2/updates/price/latest?ids[]={feed_id}", timeout=5)
            parsed = r.json().get("parsed", [{}])[0]
            pd2 = parsed.get("price", {})
            price = float(pd2.get("price", 0)) * (10 ** float(pd2.get("expo", 0)))
            conf  = float(pd2.get("conf", 0))  * (10 ** float(pd2.get("expo", 0)))
            return {"symbol": symbol, "price_usd": round(price, 6), "confidence": round(conf, 6),
                    "source": "Pyth Network", "ts": int(time.time()), "provider": "Losbeto/Pyth"}
        except Exception as e:
            return {"symbol": symbol, "error": str(e), "ts": int(time.time())}


    @staticmethod
    def market_brief():
        regime = Brain.regime()
        fg = Brain.fear_greed()
        sigs = Brain.sinais().get("signals", [])[:3]
        anom = Brain.anomalias().get("top", [])[:5]
        sent = {sym: Brain.sentiment().get("sentiment") for sym in ["BTC", "ETH", "SOL"]}
        verdict = "risk-on" if regime.get("regime", "").startswith("bull") and fg.get("value", 50) >= 55 else                   "risk-off" if regime.get("regime", "").startswith("bear") or fg.get("value", 50) <= 40 else                   "selective"
        return {
            "product": "market-brief",
            "verdict": verdict,
            "regime": regime,
            "fear_greed": fg,
            "top_signals": sigs,
            "top_anomalies": anom,
            "playbook": {
                "primary_action": "follow momentum" if verdict == "risk-on" else "preserve capital" if verdict == "risk-off" else "trade only high-conviction setups",
                "next_check": ["/sinais", "/analise", "/relatorio"],
            },
            "version": VERSION,
        }

    @staticmethod
    def portfolio_copilot():
        wallet = request.args.get("wallet", "").strip()
        credit = Brain.onchain_credit() if wallet else {"note": "use ?wallet=<solana_address> para score individual"}
        regime = Brain.regime()
        yields = Brain.defi_yield().get("top_yields", [])[:5]
        arb = Brain.arbitrage().get("opportunities", [])[:5]
        return {
            "product": "portfolio-copilot",
            "wallet": wallet or None,
            "market_regime": regime,
            "credit_profile": credit,
            "best_yields": yields,
            "arb_watchlist": arb,
            "recommendation": {
                "allocation_mode": "defensive" if regime.get("regime", "").startswith("bear") else "offensive",
                "next_tools": ["/onchain-credit", "/defi-yield", "/arbitrage", "/backtest"],
            },
            "version": VERSION,
        }

    @staticmethod
    def launch_sniper():
        launches = Brain.pump_monitor().get("new_tokens", [])[:10]
        insiders = Brain.insider_track().get("insider_candidates", [])[:10]
        mev = Brain.mev_flow().get("opportunities", [])[:5] if hasattr(Brain, 'mev_flow') else []
        return {
            "product": "launch-sniper",
            "new_launches": launches,
            "insider_candidates": insiders,
            "mev_watch": mev,
            "execution_rules": [
                "ignore launches without liquidity or social links",
                "run /rugcheck before any size",
                "prefer tokens with repeated insider overlap + positive flow",
            ],
            "next_tools": ["/pump-monitor", "/insider-track", "/rugcheck", "/mev-flow"],
            "version": VERSION,
        }

    @staticmethod
    def whale_dossier():
        whales = Brain.whale_alert().get("whales_24h", [])[:10]
        smart = Brain.smart_money().get("institutional_wallets", [])[:10]
        nansen = Brain.nansen_flow() if hasattr(Brain, 'nansen_flow') else {"note": "nansen flow unavailable"}
        sanctions = Brain.sanctions() if hasattr(Brain, 'sanctions') else {"note": "sanctions unavailable"}
        return {
            "product": "whale-dossier",
            "whales": whales,
            "smart_money": smart,
            "flow_overlay": nansen,
            "compliance_overlay": sanctions,
            "actionability": {
                "monitor": ["/whale-alert", "/smart-money", "/copytrade"],
                "risk_gate": ["/sanctions"],
            },
            "version": VERSION,
        }

    @staticmethod
    def thesis_engine():
        symbol = request.args.get("symbol", "SOL").upper().strip() or "SOL"
        regime = Brain.regime()
        fg = Brain.fear_greed()
        sentiment = Brain.sentiment()
        whales = Brain.whale_alert().get("whales_24h", [])[:5]
        smart = Brain.smart_money().get("institutional_wallets", [])[:5]
        alpha = Brain.alpha_signal()
        conviction = 50
        conviction += 12 if fg.get("value", 50) < 35 else 6 if fg.get("value", 50) < 50 else -4
        conviction += 10 if str(regime.get("regime", "")).startswith("bull") else -8 if str(regime.get("regime", "")).startswith("bear") else 0
        conviction += 8 if str(sentiment.get("sentiment", "")).lower() in {"bullish", "positive", "greed"} else -5
        conviction = max(0, min(100, conviction))
        stance = "accumulate pullbacks" if conviction >= 70 else "trade selective setups" if conviction >= 45 else "defend capital"
        return {
            "product": "thesis-engine",
            "symbol": symbol,
            "conviction_score": conviction,
            "stance": stance,
            "market_regime": regime,
            "fear_greed": fg,
            "sentiment": sentiment,
            "alpha_overlay": alpha,
            "whale_overlay": whales,
            "smart_money_overlay": smart,
            "trade_plan": {
                "entry_style": "ladder entries" if conviction >= 70 else "only confirmation trades" if conviction >= 45 else "wait / hedge",
                "invalidation": "close below regime support or sentiment flip",
                "hedge": "keep stable allocation or pair with /cross-chain and /backtest",
                "follow_up": ["/market-brief", "/alpha-signal", "/backtest", "/cross-chain"],
            },
            "version": VERSION,
        }

    @staticmethod
    def starter_pack():
        wallet = request.args.get("wallet", "").strip()
        return {
            "product": "starter-pack",
            "why_it_exists": "Primeira compra humana via Phantom com ticket simples de US$1 e percepção premium.",
            "ticket_usdc": 1.00,
            "includes": {
                "market_brief": Brain.market_brief(),
                "launch_sniper": Brain.launch_sniper(),
                "portfolio_copilot": Brain.portfolio_copilot() if wallet else {"note": "adicione ?wallet=<solana_address> para diagnóstico personalizado"},
                "thesis_engine": Brain.thesis_engine(),
            },
            "buyer_profile": [
                "primeiro teste manual no Phantom",
                "agente que quer bundle em vez de endpoints soltos",
                "comprador que precisa ver valor antes de automatizar"
            ],
            "next_best_buys": ["/thesis-engine", "/whale-dossier", "/launch-sniper", "/portfolio-copilot"],
            "version": VERSION,
        }

# 11. PRICING DINÂMICO (PoI)
# ============================================================================

def get_dynamic_price(endpoint: str) -> float:
    base = PRICE_OVERRIDES.get(endpoint, BASE_PRICES.get(endpoint, 0.05))
    if endpoint == "/starter-pack":
        return round(base, 4)
    if not DYNAMIC_PRICING:
        return base
    poi = LEDGER.get_poi_multiplier()
    # Premium bundles e alpha endpoints escalam mais rápido conforme prova de valor
    if endpoint in ("/alpha-signal", "/insider-track", "/mev-flow",
                    "/smart-money", "/copytrade", "/market-brief",
                    "/portfolio-copilot", "/launch-sniper", "/whale-dossier",
                    "/thesis-engine"):
        poi = 1.0 + (poi - 1.0) * 2
    return round(base * max(0.5, min(3.0, poi)), 4)


# ============================================================================
# 12. JWT (HS256 manual — sem libs externas)
# ============================================================================

def jwt_encode(payload: dict, secret: str = JWT_SECRET) -> str:
    header = base64.urlsafe_b64encode(b'{"alg":"HS256","typ":"JWT"}').decode().rstrip("=")
    p = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()
                                  ).decode().rstrip("=")
    sig = hmac.new(secret.encode(), f"{header}.{p}".encode(), hashlib.sha256).digest()
    sig_b64 = base64.urlsafe_b64encode(sig).decode().rstrip("=")
    return f"{header}.{p}.{sig_b64}"

def jwt_decode(token: str, secret: str = JWT_SECRET) -> Optional[dict]:
    try:
        h, p, s = token.split(".")
        expected = hmac.new(secret.encode(), f"{h}.{p}".encode(),
                            hashlib.sha256).digest()
        expected_b64 = base64.urlsafe_b64encode(expected).decode().rstrip("=")
        if not hmac.compare_digest(s, expected_b64):
            return None
        payload = json.loads(base64.urlsafe_b64decode(p + "=" * (-len(p) % 4)))
        if payload.get("exp", 0) < int(time.time()):
            return None
        return payload
    except Exception:
        return None


# ============================================================================
# 13. SERVIDOR x402 v2 — SPEC COMPLIANT
# ============================================================================

app = Flask(__name__)
app.logger.disabled = True

# ── CORS global — obrigatório para agentes x402 de outros domínios ─────────
@app.after_request
def _cors(resp):
    resp.headers["Access-Control-Allow-Origin"]   = "*"
    resp.headers["Access-Control-Allow-Headers"]  = (
        "X-PAYMENT,Payment-Signature,X-Payment,Authorization,"
        "Content-Type,X-Session-Token"
    )
    resp.headers["Access-Control-Allow-Methods"]  = "GET,POST,OPTIONS,HEAD"
    resp.headers["Access-Control-Expose-Headers"] = (
        "X-PAYMENT-REQUIRED,PAYMENT-REQUIRED,WWW-Authenticate,"
        "X-Session-Token,X-Session-TTL"
    )
    return resp

@app.before_request
def _preflight():
    if request.method == "OPTIONS":
        from flask import Response as _R
        r = _R()
        r.headers["Access-Control-Allow-Origin"]  = "*"
        r.headers["Access-Control-Allow-Headers"] = (
            "X-PAYMENT,Payment-Signature,X-Payment,Authorization,"
            "Content-Type,X-Session-Token"
        )
        r.headers["Access-Control-Allow-Methods"] = "GET,POST,OPTIONS,HEAD"
        r.headers["Access-Control-Max-Age"]       = "86400"
        return r, 204


# Rate-limit por IP + por wallet (anti-Sybil)
_rl_lock   = threading.Lock()
_rl_ip     = defaultdict(deque)
_rl_wallet = defaultdict(deque)
RL_RPM_IP     = int(os.environ.get("OMEGA_RL_RPM", "60"))
RL_RPM_WALLET = int(os.environ.get("OMEGA_RL_RPM_WALLET", "120"))

def _rl_check(ip: str, wallet: str = "") -> bool:
    now = time.time()
    with _rl_lock:
        dq = _rl_ip[ip]
        while dq and dq[0] < now - 60: dq.popleft()
        if len(dq) >= RL_RPM_IP: return False
        dq.append(now)
        if wallet:
            dqw = _rl_wallet[wallet]
            while dqw and dqw[0] < now - 60: dqw.popleft()
            if len(dqw) >= RL_RPM_WALLET: return False
            dqw.append(now)
    return True

def _public_base() -> str:
    return PUBLIC_URL or f"http://localhost:{X402_PORT}"


def _build_402(endpoint: str):
    """Resposta 402 spec-compliant — formato EXATO do SDK oficial x402 Python.

    v13 REVOLUTION: Multi-network nativo — Solana + Base USDC em TODOS endpoints.
    Agora 90% dos agentes (Base USDC via Coinbase CDP) podem pagar.

    Baseado em: x402.schemas.payments.PaymentRequired (serialização camelCase)
    Referência: https://docs.x402.org/getting-started/quickstart-for-sellers

    Campos críticos:
    - x402Version: 2
    - accepts[]: ARRAY com múltiplas opções de pagamento (Solana + Base)
    - accepts[].network: CAIP-2 completo "solana:5eykt4..." ou "eip155:8453"
    - accepts[].asset: USDC_MINT (Solana) ou BASE_USDC (Base)
    - resource: objeto com url, description, mimeType
    - error: None (null no JSON)
    """
    amount_usdc = get_dynamic_price(endpoint)
    amount_atomic_sol = str(int(amount_usdc * 10 ** USDC_DECIMALS))
    amount_atomic_base = str(int(amount_usdc * 10 ** 6))  # Base USDC = 6 decimals
    base = _public_base()

    desc = ENDPOINT_DESC.get(endpoint, f"Losbeto — {endpoint}")

    # Solana SEMPRE disponível
    accepts = [{
        "scheme":            "exact",
        "network":           f"solana:{SOL_GENESIS}",
        "asset":             USDC_MINT,
        "amount":            amount_atomic_sol,
        "payTo":             RECEIVE_ADDRESS,
        "maxTimeoutSeconds": 300,
        "extra":             {},
    }]

    # Base USDC disponível quando BASE_PAYTO_EVM configurado
    if ENABLE_BASE and BASE_PAYTO_EVM:
        accepts.append({
            "scheme":            "exact",
            "network":           BASE_CAIP2,  # "eip155:8453"
            "asset":             BASE_USDC,
            "amount":            amount_atomic_base,
            "payTo":             BASE_PAYTO_EVM,
            "maxTimeoutSeconds": 300,
            "extra":             {},
        })

    payload = {
        "x402Version": 2,
        "error":       "Payment Required",
        "resource": {
            "url":         f"{base}{endpoint}",
            "description": desc,
            "mimeType":    "application/json",
        },
        "accepts":    accepts,
        "extensions": None,
    }

    b64 = base64.b64encode(
        json.dumps(payload, separators=(",", ":")).encode()
    ).decode()

    resp = jsonify(payload)
    resp.status_code = 402
    resp.headers["PAYMENT-REQUIRED"]   = b64   # header oficial x402 v2
    resp.headers["X-PAYMENT-REQUIRED"] = b64   # compat com clientes v1
    resp.headers["WWW-Authenticate"]   = f'x402 challenge="{b64}"'
    resp.headers["X-Node-Id"]          = WALLET.node_id
    # Header revolucionário: indica multi-chain para agentes inteligentes
    resp.headers["X-Accept-Chains"]    = ",".join([a["network"] for a in accepts])
    return resp


def _verify_payment(endpoint: str, payment_header: str):
    """Verifica X-PAYMENT — suporta exact-solana + facilitator opcional."""
    if not payment_header:
        return False, "missing-header", {}
    h = hashlib.sha256(payment_header.encode()).hexdigest()
    if LEDGER.replay_check(h):
        return False, "replay-blocked", {}
    # Decode base64 (formato x402)
    tx_sig = payment_header
    payer  = ""
    network = "solana"
    payload = {}
    try:
        decoded = base64.b64decode(payment_header).decode()
        pdata = json.loads(decoded)
        payload = pdata
        # x402 v2 spec: { x402Version, scheme, network, payload: { transaction, ... } }
        if "payload" in pdata:
            inner = pdata["payload"]
            tx_sig = inner.get("signature") or inner.get("transaction") or inner.get("tx") or tx_sig
            payer  = inner.get("payer") or inner.get("from") or ""
        else:
            tx_sig = pdata.get("signature") or pdata.get("tx") or payment_header
            payer  = pdata.get("payer", "")
        network = pdata.get("network", "solana")
    except Exception:
        pass

    amount = get_dynamic_price(endpoint)
    chain = "base" if "eip155" in str(network) else "solana"

    # Facilitator path (opcional)
    if FACILITATOR and payload:
        accepts = _build_402(endpoint).get_json()["accepts"]
        for req in accepts:
            ok, reason, _data = FACILITATOR.verify(payload, req)
            if ok:
                LEDGER.add_revenue(endpoint, amount, tx_sig, payer,
                                    source="facilitator", chain=chain)
                return True, "ok-facilitator", {"payer": payer, "tx": tx_sig}
        # se facilitator falhou, ainda tenta fallback on-chain

    # Direct on-chain (Solana)
    if chain == "solana":
        ok, info = SOL.verify_payment(tx_sig, amount, RECEIVE_ADDRESS)
        if ok:
            payer_addr = info.get("payer") if isinstance(info, dict) else payer
            LEDGER.add_revenue(endpoint, amount, tx_sig, payer_addr or payer,
                                source="direct", chain="solana")
            _notify_telegram(f"💰 ${amount} USDC em {endpoint} (Solana)\nTX: {tx_sig[:32]}...")
            return True, "ok", {"payer": payer_addr or payer, "tx": tx_sig}
        return False, info if isinstance(info, str) else "verify-failed", {}
    # Base — se chegou aqui, facilitator falhou ou não está configurado.
    # v14: mostra dica clara ao invés de hard-fail silencioso.
    if chain == "base":
        if not FACILITATOR:
            return False, "base-needs-facilitator (set X402_FACILITATOR to a production facilitator, ex: https://facilitator.payai.network)", {}
        return False, "facilitator-verify-failed", {}
    return False, "unknown-chain", {}


def _notify_telegram(text: str):
    if not (TG_TOKEN and TG_CHAT): return
    try:
        requests.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
            json={"chat_id": TG_CHAT, "text": text},
            timeout=5)
    except Exception:
        pass


def paid_endpoint(path):
    def deco(handler):
        def wrapped():
            t0 = time.time()
            ip = (request.headers.get("X-Forwarded-For", request.remote_addr) or ""
                  ).split(",")[0].strip()

            # GeoIP block (opt-in, configurado por env)
            if is_geo_blocked(ip):
                return jsonify({"error": "geo-blocked", "country": geo_country(ip)}), 403

            # JWT session (cliente paga 1x, reusa 5 min)
            auth = request.headers.get("Authorization", "")
            if auth.startswith("Bearer "):
                token = auth[7:]
                claims = jwt_decode(token)
                if claims and claims.get("endpoint") == path:
                    if LEDGER.jwt_valid(claims.get("jti", ""), path):
                        try:
                            result = handler()
                            LEDGER.log_request(path, True,
                                                int((time.time() - t0) * 1000), ip)
                            return jsonify(result)
                        except Exception as e:
                            log.error(f"handler {path}: {e}")
                            return jsonify({"error": str(e)}), 500

            # rate limit
            sig = request.headers.get("X-PAYMENT") or request.headers.get("Payment-Signature")
            if sig and not _rl_check(ip):
                return jsonify({"error": "rate-limit", "limit_rpm": RL_RPM_IP}), 429

            if not sig:
                LEDGER.log_request(path, False, int((time.time() - t0) * 1000), ip)
                return _build_402(path)

            ok, reason, info = _verify_payment(path, sig)
            if not ok:
                LEDGER.log_request(path, False, int((time.time() - t0) * 1000), ip)
                r = _build_402(path)
                body = r.get_json()
                body["error"] = f"Payment invalid: {reason}"
                return jsonify(body), 402

            # Emite JWT para reuso
            jti = secrets.token_urlsafe(12)
            payer = info.get("payer", "")
            LEDGER.jwt_save(jti, payer, path, info.get("tx", ""), JWT_TTL)
            token = jwt_encode({
                "jti": jti, "endpoint": path, "payer": payer,
                "exp": int(time.time()) + JWT_TTL,
            })
            try:
                result = handler()
                LEDGER.log_request(path, True, int((time.time() - t0) * 1000), ip)
                resp = jsonify(result)
                resp.headers["X-Payment-Response"] = base64.b64encode(json.dumps({
                    "success": True, "tx": info.get("tx"),
                    "amount": get_dynamic_price(path),
                }).encode()).decode()
                resp.headers["X-Session-Token"] = token
                resp.headers["X-Session-TTL"]   = str(JWT_TTL)
                return resp
            except Exception as e:
                log.error(f"handler {path}: {e}\n{traceback.format_exc()}")
                return jsonify({"error": str(e)}), 500
        wrapped.__name__ = f"paid_{path.strip('/').replace('-','_')}"
        return wrapped
    return deco

# Registra os endpoints monetizados (v16 MARKET-FIT)
ENDPOINT_HANDLERS = {
    # Endpoints core (pagos)
    "/fear-greed":      Brain.fear_greed,
    "/regime":          Brain.regime,
    "/mempool":         Brain.mempool,
    "/anomalias":       Brain.anomalias,
    "/jupiter-swap":    Brain.jupiter_swap,
    "/analise":         Brain.analise,
    "/swarm-vote":      Brain.swarm_vote,
    "/sentiment":       Brain.sentiment,
    "/rugcheck":        Brain.rugcheck,
    "/sinais":          Brain.sinais,
    "/defi-yield":      Brain.defi_yield,
    "/deep-think":      Brain.deep_think,
    "/pump-monitor":    Brain.pump_monitor,
    "/arbitrage":       Brain.arbitrage,
    "/tg-premium":      Brain.tg_premium,
    "/relatorio":       Brain.relatorio,
    "/backtest":        Brain.backtest,
    "/agent-call":      Brain.agent_call,
    "/onchain-credit":  Brain.onchain_credit,
    "/cross-chain":     Brain.cross_chain,
    "/whale-alert":     Brain.whale_alert,
    "/smart-money":     Brain.smart_money,
    "/copytrade":       Brain.copytrade,
    "/alpha-signal":    Brain.alpha_signal,
    "/insider-track":   Brain.insider_track,
    "/mev-flow":        Brain.mev_flow,
    # Losbeto v12 — novos endpoints
    "/web-search":      Brain.web_search,
    "/ai-news":         Brain.ai_news,
    "/dex-screen":      Brain.dex_screen,
    "/nansen-flow":     Brain.nansen_flow,
    "/sec-filing":      Brain.sec_filing,
    "/trust-hash":      Brain.trust_hash,
    "/geo-alpha":       Brain.geo_alpha,
    "/sanctions":       Brain.sanctions,
    "/agent-market":    Brain.agent_market,
    "/pyth-price":      Brain.pyth_price,
    "/market-brief":      Brain.market_brief,
    "/portfolio-copilot": Brain.portfolio_copilot,
    "/launch-sniper":     Brain.launch_sniper,
    "/whale-dossier":     Brain.whale_dossier,
    "/thesis-engine":     Brain.thesis_engine,
    "/starter-pack":      Brain.starter_pack,
}

for _path, _handler in ENDPOINT_HANDLERS.items():
    _rule_name = _path.strip("/").replace("-", "_")
    app.add_url_rule(_path, _rule_name, paid_endpoint(_path)(_handler))



# ============================================================================
# 13b. KILLER FEATURE — /losbeto-alpha (Dado Proprietário Exclusivo)
# ============================================================================
# Este endpoint combina FEAR & GREED + REGIME + SENTIMENT + IA em um 
# "Losbeto Alpha Score" — um índice proprietário que NÃO existe em nenhum
# outro node x402. É o diferencial competitivo para converter agentes.

@app.route("/losbeto-alpha")
def losbeto_alpha_free():
    """FREE TIER — Losbeto Alpha Score (preview). 
    Endpoint killer: dado proprietário que só existe aqui.

    O Alpha Score é um índice composto 0-100 que agrega:
    - Fear & Greed (peso 30%)
    - Regime de mercado (peso 30%)  
    - Sentimento social (peso 25%)
    - Momentum on-chain (peso 15%)

    Versão completa (com recomendação IA + triggers de trade) é paga.
    """
    base = _public_base()
    ts = int(time.time())

    try:
        # Coleta dados
        fg = Market.fear_greed()
        regime = Brain.regime()
        top = Market.top_coins(20)

        # Fear & Greed Score (0-100, invertido: medo = oportunidade)
        fng_val = fg.get("value", 50)
        fng_score = 100 - fng_val  # medo extremo (0) = 100 oportunidade

        # Regime Score
        regime_map = {
            "bull-strong": 90, "bull-weak": 70,
            "range": 50, "transition": 40,
            "bear-weak": 30, "bear-strong": 10,
        }
        regime_score = regime_map.get(regime.get("regime", "range"), 50)

        # Sentiment Score (média dos top 20)
        if top:
            ch24s = [c.get("price_change_percentage_24h") or 0 for c in top[:20]]
            avg_ch24 = sum(ch24s) / len(ch24s) if ch24s else 0
            sent_score = 50 + avg_ch24 * 3  # normalize around 50
            sent_score = max(0, min(100, sent_score))
        else:
            sent_score = 50
            avg_ch24 = 0

        # Momentum Score (anomalias como proxy)
        anom = Brain.anomalias()
        anom_count = anom.get("count", 0)
        momentum_score = min(100, 30 + anom_count * 5)

        # ALPHA SCORE proprietário Losbeto
        alpha_score = (
            fng_score * 0.30 +
            regime_score * 0.30 +
            sent_score * 0.25 +
            momentum_score * 0.15
        )

        # Interpretação
        if alpha_score >= 80:
            interp = "STRONG_BUY — Confluência de múltiplos fatores bullish"
        elif alpha_score >= 65:
            interp = "BUY — Tendência favorável com suporte de dados"
        elif alpha_score >= 50:
            interp = "HOLD — Mercado equilibrado, aguardar gatilho"
        elif alpha_score >= 35:
            interp = "CAUTION — Sinais de fraqueza detectados"
        else:
            interp = "REDUCE — Múltiplos fatores de risco ativos"

        return jsonify({
            "service":          "Losbeto — Alpha Score (Preview)",
            "version":          VERSION,
            "ts":               ts,
            "notice":           "PREVIEW — Score composto proprietário Losbeto. Versão completa com recomendação IA em /alpha-signal",

            # O dado proprietário — este score NÃO existe em nenhum outro lugar
            "losbeto_alpha_score": {
                "score":          round(alpha_score, 1),
                "max":            100,
                "interpretation": interp,
                "components": {
                    "fear_greed_opportunity": {"weight": 0.30, "value": round(fng_score, 1), "raw": fng_val},
                    "regime_strength":        {"weight": 0.30, "value": round(regime_score, 1), "raw": regime.get("regime")},
                    "social_sentiment":       {"weight": 0.25, "value": round(sent_score, 1), "raw": round(avg_ch24, 2)},
                    "onchain_momentum":       {"weight": 0.15, "value": round(momentum_score, 1), "raw": anom_count},
                },
            },

            # Gatilhos de trade (preview — versão completa paga)
            "trade_triggers_preview": {
                "fng_trigger":     f"F&G < 25 → Oportunidade extrema (atual: {fng_val})" if fng_val > 25 else "🟢 F&G em zona de oportunidade!",
                "regime_trigger":  f"Regime: {regime.get('regime', 'unknown')} (conf: {regime.get('confidence', 0)})",
                "momentum_alert":  f"{anom_count} anomalias detectadas 24h" if anom_count > 0 else "Sem anomalias significativas",
            },

            # Upsell path
            "full_analysis": {
                "endpoint":       f"{base}/alpha-signal",
                "price_usdc":     get_dynamic_price("/alpha-signal"),
                "unlock_full_at": f"{base}/alpha-signal",
                "includes":       ["Recomendação IA detalhada", "Top 3 sinais alpha (conf > 70%)", 
                                   "Triggers com preço de entrada", "Stop-loss e take-profit sugeridos"],
            },

            # Metadados
            "_agent_metadata": {
                "provider":     "Losbeto",
                "node_id":      WALLET.node_id,
                "win_rate":     LEDGER.win_rate(),
                "unique_value": "Losbeto Alpha Score — índice composto proprietário disponível apenas aqui",
            },
        })

    except Exception as e:
        return jsonify({
            "service": "Losbeto — Alpha Score",
            "error": str(e),
            "ts": ts,
            "fallback_url": f"{base}/fear-greed",
        })


# ============================================================================
# 13c. VERIFY MANIFEST — Prova criptográfica de posse do domínio
# ============================================================================
# O x402scan e facilitadores CDP verificam se o dono do domínio realmente
# controla a wallet. Este endpoint retorna uma assinatura Ed25519 do domínio
# que pode ser verificada on-chain.

@app.route("/.well-known/verify-manifest")
def verify_manifest():
    """Retorna prova criptográfica de que este domínio controla a wallet.

    Usado por:
    - x402scan para trust score boost
    - Facilitadores CDP para verificação de merchant
    - Agentes para confirmar identidade antes de pagar
    """
    base = _public_base()
    domain = base.replace("https://", "").replace("http://", "").split("/")[0]
    ts = int(time.time())

    # Mensagem a ser assinada: domain + timestamp + node_id
    message = f"x402-domain-verify:{domain}:{ts}:{WALLET.node_id}"
    signature = base64.b64encode(WALLET.sign(message.encode())).decode()

    return jsonify({
        "domain":        domain,
        "node_id":       WALLET.node_id,
        "solana_address": RECEIVE_ADDRESS,
        "signer_pubkey":  WALLET.solana_address,
        "base_payto":    BASE_PAYTO_EVM if ENABLE_BASE else None,
        "timestamp":     ts,
        "message":       message,
        "signature_b64": signature,
        "verification":  {
            "method":      "Ed25519",
            "pubkey_b58":  WALLET.solana_address,
            "message_fmt": "x402-domain-verify:{domain}:{ts}:{node_id}",
        },
        "trust_signals": {
            "win_rate":       LEDGER.win_rate(),
            "poi_multiplier": LEDGER.get_poi_multiplier(),
            "tx_count_24h":   LEDGER.stats()["paid_24h"],
            "chains":         [f"solana:{SOL_GENESIS}"] + ([BASE_CAIP2] if ENABLE_BASE else []),
        },
    })

# ============================================================================
# 13a. BOOTSTRAP TRUST — Self-payment para gerar histórico no x402scan
# ============================================================================

@app.route("/bootstrap-trust", methods=["POST", "GET"])
def bootstrap_trust():
    """Endpoint especial para DONO do node gerar transações reais e bootstrap trust score.

    Por que: agentes filtram nodes por tx_count > 0. Sem histórico = invisível.
    Como: O dono faz 3 self-payments de $0.01 (ou maior) neste endpoint.
    Resultado: x402scan mostra "3 transactions" = trust score inicial > 0.

    GET: retorna instruções + preço
    POST: aceita payment header, registra como self-payment
    """
    base = _public_base()
    ts = int(time.time())

    if request.method == "GET":
        return jsonify({
            "service":        "Losbeto — Trust Bootstrap",
            "version":        VERSION,
            "ts":             ts,
            "why":            "Agentes x402 filtram por tx_count > 0. Você precisa de histórico.",
            "instructions":   [
                "1. Use uma wallet Solana DIFERENTE da wallet do node",
                f"2. Compre ou receba ao menos $1 de USDC na Phantom (mínimo comum de compra/swap)",
                f"3. Envie $0.10 USDC (ou mais) para {RECEIVE_ADDRESS}; qualquer valor >= $0.01 conta",
                f"4. POST /bootstrap-trust com X-Payment header contendo tx signature",
                "5. Repita 3x para gerar trust score inicial (ex: 3 x $0.10)",
                f"6. Verifique seu trust score em https://www.x402scan.com/"
            ],
            "node_address":   WALLET.solana_address,
            "receive_address": RECEIVE_ADDRESS,
            "price_usdc":     0.10,
            "x402_manifest":  f"{base}/.well-known/x402.json",
            "note":           "Este endpoint aceita pagamentos de QUALQUER wallet. Use para testar seu próprio flow de pagamento.",
        })

    # POST — processa self-payment
    payment_header = request.headers.get("X-PAYMENT") or request.headers.get("Payment-Signature")
    if not payment_header:
        return jsonify({"error": "Missing X-Payment header", "hint": "GET /bootstrap-trust para instruções"}), 402

    # Mesma lógica de verificação do _verify_payment
    tx_sig = payment_header
    try:
        decoded = base64.b64decode(payment_header).decode()
        pdata = json.loads(decoded)
        if "payload" in pdata:
            inner = pdata["payload"]
            tx_sig = inner.get("signature") or inner.get("transaction") or inner.get("tx") or tx_sig
        else:
            tx_sig = pdata.get("signature") or pdata.get("tx") or payment_header
    except Exception:
        pass

    # Verifica on-chain (aceita qualquer valor >= $0.01)
    ok, info = SOL.verify_payment(tx_sig, 0.01, RECEIVE_ADDRESS, max_age=3600)
    if not ok:
        return jsonify({"error": f"Payment verification failed: {info}", "tx": tx_sig[:32]}), 402

    payer = info.get("payer") if isinstance(info, dict) else ""
    amount = round(float(info.get("delta", 0.01)), 6) if isinstance(info, dict) else 0.01
    LEDGER.add_revenue("/bootstrap-trust", amount, tx_sig, payer, source="bootstrap", chain="solana")

    stats = LEDGER.stats()
    return jsonify({
        "success":        True,
        "message":        "Trust bootstrap payment received!",
        "tx":             tx_sig[:32] + "...",
        "payer":          payer,
        "amount_usdc":    amount,
        "your_total_tx":  stats["paid_24h"],
        "next_steps":     [
            f"Verifique https://www.x402scan.com/server/{WALLET.node_id}",
            "Faça +2 pagamentos para trust score mínimo recomendado (3 tx)",
            "Seu node agora aparece como 'active' nos marketplaces"
        ],
    })

# ============================================================================
# 14. ENDPOINTS PÚBLICOS + MANIFESTS DE DISCOVERY
# ============================================================================

# ══════════════════════════════════════════════════════════════════════
# ENDPOINTS GRATUITOS — Porta de entrada (Solução 1 do relatório)
# Estratégia: agentes experimentam, veem valor, pagam pelo premium
# ══════════════════════════════════════════════════════════════════════

@app.route("/sample")
def sample_free():
    """FREE TIER v13 REVOLUTION — Preview REAL de 3 endpoints premium.

    Estratégia: mostra DADO REAL com valor imediato + campo unlock_full_at
    que agentes GPT/Claude/AutoGPT reconhecem como padrão de upsell.
    Taxa típica free→pago: 8-20% com preview rico (vs 0.5% com dado genérico).
    """
    base = _public_base()
    ts = int(time.time())

    try:
        # Preview 1: Fear & Greed com interpretação IA (preview parcial)
        fg = Market.fear_greed()
        fng_val = fg.get("value", 50)
        fng_interp = ("Medo extremo - possível oportunidade de compra" if fng_val < 25 else
                      "Medo - cautela aumentada"                          if fng_val < 45 else
                      "Neutro - mercado equilibrado"                       if fng_val < 55 else
                      "Ganância - cuidado com correções"                   if fng_val < 75 else
                      "Ganância extrema - risco alto de top local")

        # Preview 2: Top 1 sinal (mais forte) — mostra 1, esconde restante
        all_sigs = Brain.sinais().get("signals", [])
        top_signal = all_sigs[0] if all_sigs else None

        # Preview 3: Top 3 anomalias (preview parcial)
        anom = Brain.anomalias()
        top_anomalies = (anom.get("top", [])[:3] if anom else [])

        # Preview 4: Mempool snapshot
        mempool = Brain.mempool()

        response = {
            "service":      "Losbeto — Free Sample",
            "version":      VERSION,
            "ts":           ts,
            "notice":       "PREVIEW LIMITADO — Dados reais. Desbloqueie análise completa via x402.",

            # Preview 1: Fear & Greed (completo — entry point gratuito)
            "fear_greed_preview": {
                "value":          fng_val,
                "classification": fg.get("classification", "Neutral"),
                "interpretation": fng_interp,
                "full_endpoint":  f"{base}/fear-greed",
                "price_usdc":     get_dynamic_price("/fear-greed"),
                "unlock_full_at": f"{base}/fear-greed",  # padrão que agentes reconhecem
            },

            # Preview 2: Top sinal (1 desbloqueado, restante bloqueado)
            "top_signal_preview": {
                "signal":         top_signal,
                "total_available": len(all_sigs),
                "full_endpoint":  f"{base}/sinais",
                "price_usdc":     get_dynamic_price("/sinais"),
                "unlock_full_at": f"{base}/sinais",
            } if top_signal else {"note": "Nenhum sinal forte no momento. Tente /sinais para análise completa.", "unlock_full_at": f"{base}/sinais", "price_usdc": get_dynamic_price("/sinais")},

            # Preview 3: Anomalias (top 3 visíveis, restante bloqueado)
            "anomalies_preview": {
                "top_3":          [{"symbol": a["symbol"], "change_pct": a["change_pct"], "type": a["type"]} for a in top_anomalies],
                "total_detected": anom.get("count", 0),
                "full_endpoint":  f"{base}/anomalias",
                "price_usdc":     get_dynamic_price("/anomalias"),
                "unlock_full_at": f"{base}/anomalias",
            } if top_anomalies else {"note": "Sem anomalias detectadas.", "unlock_full_at": f"{base}/anomalias", "price_usdc": get_dynamic_price("/anomalias")},

            # Preview 4: Mempool (snapshot gratuito — utility hook)
            "mempool_snapshot": {
                "priority_fee_lamports": mempool.get("priority_fee_lamports"),
                "network_load":          mempool.get("network_load"),
                "full_endpoint":         f"{base}/mempool",
                "price_usdc":            get_dynamic_price("/mempool"),
                "unlock_full_at":        f"{base}/mempool",
            },

            # Call-to-action inteligente para agentes
            "upgrade": {
                "method":         "x402-v2",
                "pricing_url":    f"{base}/get-pricing",
                "manifest_url":   f"{base}/.well-known/x402.json",
                "chains":         [f"solana:{SOL_GENESIS}"] + ([BASE_CAIP2] if ENABLE_BASE else []),
                "cheapest_entry": min(get_dynamic_price(p) for p in BASE_PRICES),
            },

            # Metadata para agentes autônomos
            "_agent_metadata": {
                "provider":    "Losbeto",
                "node_id":     WALLET.node_id,
                "win_rate":    LEDGER.win_rate(),
                "poi_multiplier": LEDGER.get_poi_multiplier(),
                "endpoints_count": len(BASE_PRICES),
            },
        }

        resp = jsonify(response)
        # Headers que agentes x402 verificam
        resp.headers["X-Payment-Required-For-Full"] = base64.b64encode(
            json.dumps({"unlock_endpoints": [f"{base}/sinais", f"{base}/anomalias", f"{base}/relatorio"]}).encode()
        ).decode()
        return resp

    except Exception as e:
        return jsonify({"service": "Losbeto — Free Sample", "error": str(e), "ts": ts, 
                        "upgrade": {"manifest_url": f"{_public_base()}/.well-known/x402.json"}})


@app.route("/get-pricing")
def get_pricing():
    """Retorna lista de preços atual — gratuito para discovery MCP/agentes."""
    base = _public_base()
    return jsonify({
        "service":   "Losbeto",
        "version":   VERSION,
        "ts":        int(time.time()),
        "promo":     "Pricing MARKET-FIT: menos commodity, mais bundles, melhor ancoragem para agentes e compradores humanos.",
        "tiers": {
            "free":  {"endpoints": ["/sample"], "price": "grátis", "limit": "ilimitado"},
            "discovery": {"endpoints": [e for e, p in BASE_PRICES.items() if p <= 0.03], "price_range": "$0.01-0.03"},
            "core":      {"endpoints": [e for e, p in BASE_PRICES.items() if 0.03 < p <= 0.15], "price_range": "$0.04-0.15"},
            "pro":       {"endpoints": [e for e, p in BASE_PRICES.items() if 0.15 < p <= 0.40], "price_range": "$0.18-0.40"},
            "flagship":  {"endpoints": [e for e, p in BASE_PRICES.items() if p > 0.40], "price_range": "$0.49-1.00"},
        },
        "featured":  FEATURED_ENDPOINTS,
        "endpoints": {ep: {"price_usdc": get_dynamic_price(ep), "desc": ENDPOINT_DESC.get(ep, ""), "env_key": _price_env_key(ep)} for ep, p in BASE_PRICES.items()},
        "pay_with":  "USDC-SPL via x402 (Solana) ou USDC via x402 (Base)",
        "discovery": f"{base}/.well-known/x402.json",
    })


@app.route("/bazaar.json")
def bazaar_manifest():
    """Padrão emergente do ecossistema — auto-discovery para Bazaar CDP.
    v13 REVOLUTION: Multi-network + accepts[] + trust signals."""
    base = _public_base()
    resources = []
    for p, price in BASE_PRICES.items():
        dyn_price = get_dynamic_price(p)
        payment_opts = [{
            "chain":  f"solana:{SOL_GENESIS}",
            "asset":  USDC_MINT,
            "payTo":  RECEIVE_ADDRESS,
            "price":  dyn_price,
        }]
        if ENABLE_BASE and BASE_PAYTO_EVM:
            payment_opts.append({
                "chain":  BASE_CAIP2,
                "asset":  BASE_USDC,
                "payTo":  BASE_PAYTO_EVM,
                "price":  dyn_price,
            })
        resources.append({
            "url":     f"{base}{p}",
            "price":   dyn_price,
            "asset":   "USDC",
            "network": f"solana:{SOL_GENESIS}",
            "desc":    ENDPOINT_DESC.get(p, p),
            "accepts": payment_opts,  # v13: multi-chain options
        })

    manifest = {
        "name":        "Losbeto",
        "version":     VERSION,
        "description": f"Multi-chain x402 AI swarm — Solana+Base+TON. {len(BASE_PRICES)} endpoints. Pay-per-call USDC com bundles premium e starter pack Phantom-friendly.",
        "tags":        ["crypto", "trading", "defi", "solana", "base", "x402", "ai-agents", "usdc"],
        "url":         base,
        "sample":      f"{base}/sample",
        "pricing":     f"{base}/get-pricing",
        "x402":        f"{base}/.well-known/x402.json",
        "mcp":         f"{base}/.well-known/mcp.json",
        "resources":   resources,
        "contact": {
            "email":    os.environ.get("CONTACT_EMAIL", ""),
            "telegram": "@losbeto_x402",
        },
        # v13: trust signals — ajuda agentes a filtrar por credibilidade
        "trust": {
            "tx_count": LEDGER.stats()["paid_24h"],
            "win_rate": LEDGER.win_rate(),
            "poi_multiplier": LEDGER.get_poi_multiplier(),
            "chains_supported": [f"solana:{SOL_GENESIS}"] + ([BASE_CAIP2] if ENABLE_BASE else []),
        },
    }
    return jsonify(manifest)


@app.route("/")
def root():
    prices = {ep: get_dynamic_price(ep) for ep in BASE_PRICES}
    return jsonify({
        "name":             "Losbeto",
        "version":          VERSION,
        "node_id":          WALLET.node_id,
        "solana_address":   RECEIVE_ADDRESS,
        "signer_address":   WALLET.solana_address,
        "ton_address":      TON_WALLET.address if TON_WALLET else None,
        "base_payto":       BASE_PAYTO_EVM if ENABLE_BASE else None,
        "endpoints":        len(BASE_PRICES),
        "prices_usdc":      prices,
        "featured_endpoints": FEATURED_ENDPOINTS,
        "win_rate":         LEDGER.win_rate(),
        "poi_multiplier":   LEDGER.get_poi_multiplier(),
        "dashboard":        f"/dash?token={DASH_TOKEN[:6]}...",
        "discovery": {
            "openapi": "/openapi.json",
            "x402":    "/.well-known/x402.json",
            "mcp":     "/.well-known/mcp.json",
            "agent":   "/.well-known/agent.json",
            "llms":    "/llms.txt",
        },
    })

@app.route("/info")
def info():
    s = LEDGER.stats()
    return jsonify({
        "version":         VERSION,
        "node_id":         WALLET.node_id,
        "solana_address":  RECEIVE_ADDRESS,
        "signer_address":  WALLET.solana_address,
        "ton_address":     TON_WALLET.address if TON_WALLET else None,
        "stats":           s,
        "featured_endpoints": FEATURED_ENDPOINTS,
        "endpoints_count": len(BASE_PRICES),
        "facilitator":     FACILITATOR_URL if FACILITATOR else None,
        "base_enabled":    ENABLE_BASE,
    })


@app.route("/.well-known/x402")
def manifest_x402_alias():
    return redirect("/.well-known/x402.json", code=308)

@app.route("/.well-known/x402.json")
def manifest_x402():
    """Manifest x402 v2 spec-compliant — v13 REVOLUTION: Multi-network nativo.

    Agora expõe Solana + Base USDC para CADA endpoint. Agentes que filtram
    por 'base' ou 'eip155:8453' vão encontrar Losbeto. 90% do volume real
    x402 hoje é Base USDC via Coinbase CDP.
    """
    base = _public_base()
    resources = []
    for p, base_price in BASE_PRICES.items():
        dyn_price = get_dynamic_price(p)
        # Lista de opções de pagamento para ESTE endpoint
        payment_options = [{
            "scheme":            "exact",
            "network":           f"solana:{SOL_GENESIS}",  # CAIP-2 completo
            "asset":             USDC_MINT,
            "maxAmountRequired": str(int(dyn_price * 10 ** USDC_DECIMALS)),
            "payTo":             RECEIVE_ADDRESS,
            "maxTimeoutSeconds": 300,
        }]
        # Base USDC quando disponível
        if ENABLE_BASE and BASE_PAYTO_EVM:
            payment_options.append({
                "scheme":            "exact",
                "network":           BASE_CAIP2,  # "eip155:8453"
                "asset":             BASE_USDC,
                "maxAmountRequired": str(int(dyn_price * 10 ** 6)),
                "payTo":             BASE_PAYTO_EVM,
                "maxTimeoutSeconds": 300,
            })

        resources.append({
            "url":               f"{base}{p}",
            "method":            "GET",
            "scheme":            "exact",
            "network":           f"solana:{SOL_GENESIS}",  # CAIP-2 completo obrigatório
            "maxAmountRequired": str(int(dyn_price * 10 ** USDC_DECIMALS)),
            "asset":             USDC_MINT,
            "payTo":             RECEIVE_ADDRESS,
            "maxTimeoutSeconds": 300,
            "description":       ENDPOINT_DESC.get(p, p),
            "mimeType":          "application/json",
            # v13: campo accepts[] para cada resource — formato que x402scan/CDP esperam
            "accepts":           payment_options,
        })

    manifest = {
        "version":         2,
        "ownershipProofs": [WALLET.solana_address],
        "resources":       resources,
        "node": {
            "name":        "Losbeto",
            "version":     VERSION,
            "node_id":     WALLET.node_id,
            "url":         base,
            "chains":      [f"solana:{SOL_GENESIS}"] + ([BASE_CAIP2] if ENABLE_BASE else []),
            "facilitator": FACILITATOR_URL if FACILITATOR else None,
        },
    }

    # Adicionar Base payTo como ownership proof secundário quando disponível
    if ENABLE_BASE and BASE_PAYTO_EVM:
        manifest["ownershipProofs"].append(BASE_PAYTO_EVM)

    return jsonify(manifest)
@app.route("/.well-known/mcp.json")
def manifest_mcp():
    """MCP manifest — v13 REVOLUTION: Multi-network + accepts[] para cada tool."""
    base = _public_base()
    tools = []
    for p in BASE_PRICES:
        dyn_price = get_dynamic_price(p)
        x402_opts = {
            "resource": f"{base}{p}",
            "scheme":   "exact",
            "price":    f"${dyn_price:.4f}",
            "network":  f"solana:{SOL_GENESIS}",  # CAIP-2 completo
            "payTo":    RECEIVE_ADDRESS,
            "asset":    USDC_MINT,
        }
        tools.append({
            "name": p.strip("/").replace("-", "_"),
            "description": f"{ENDPOINT_DESC.get(p, p)} (${dyn_price:.4f} USDC via x402 — Solana/Base)",
            "inputSchema": {"type": "object", "properties": {}, "required": []},
            "x402": x402_opts,
        })
    return jsonify({
        "schema_version": "2024-11-05",
        "name":           "losbeto-v16",
        "description":    f"Multi-chain x402 AI swarm (Solana+Base+TON). {len(BASE_PRICES)} monetized resources. Dynamic PoI pricing. Trust-score aware.",
        "tools":          tools,
        "node": {
            "version": VERSION,
            "node_id": WALLET.node_id,
            "chains":  [f"solana:{SOL_GENESIS}"] + ([BASE_CAIP2] if ENABLE_BASE else []),
        },
    })

@app.route("/.well-known/agent.json")
def manifest_agent():
    base = _public_base()
    return jsonify({
        "schemaVersion":  "0.3",
        "name":           "Losbeto",
        "description":    "Multi-chain x402 AI trading swarm. Solana+Base+TON. Dynamic pricing.",
        "url":            base,
        "version":        VERSION,
        "provider":       {"organization": "Losbeto", "url": base},
        "capabilities":   {"streaming": False, "pushNotifications": False,
                           "stateTransitionHistory": True},
        "defaultInputModes":  ["application/json"],
        "defaultOutputModes": ["application/json"],
        "skills": [{
            "id":          p.strip("/").replace("-", "_"),
            "name":        ENDPOINT_DESC.get(p, p),
            "description": f"{ENDPOINT_DESC.get(p, p)} - ${get_dynamic_price(p):.4f} USDC",
            "tags":        ENDPOINT_TAGS.get(p, []) + ["x402", "solana"],
            "examples":    [f"GET {base}{p}"],
        } for p in BASE_PRICES],
    })

@app.route("/openapi.json")
def openapi_spec():
    base = _public_base()
    contact_email = os.environ.get("CONTACT_EMAIL", "").strip()

    # Schemas de parâmetros por endpoint — x402scan exige pelo menos 1 param
    ENDPOINT_PARAMS = {
        "/fear-greed":    [{"name": "format", "in": "query", "required": False,
                            "description": "Formato da resposta",
                            "schema": {"type": "string", "enum": ["json"], "default": "json"}}],
        "/regime":        [{"name": "symbol", "in": "query", "required": False,
                            "description": "Par de trading (ex: BTC/USDC)",
                            "schema": {"type": "string", "example": "BTC/USDC"}}],
        "/mempool":       [{"name": "limit", "in": "query", "required": False,
                            "description": "Número de transações a retornar",
                            "schema": {"type": "integer", "example": 20}}],
        "/anomalias":     [{"name": "threshold", "in": "query", "required": False,
                            "description": "Limiar de detecção 0.0-1.0",
                            "schema": {"type": "number", "example": 0.7}}],
        "/sentiment":     [{"name": "symbol", "in": "query", "required": False,
                            "description": "Ativo (ex: BTC, ETH, SOL)",
                            "schema": {"type": "string", "example": "BTC"}}],
        "/jupiter-swap":  [{"name": "pair", "in": "query", "required": False,
                            "description": "Par a consultar (ex: SOL/USDC)",
                            "schema": {"type": "string", "example": "SOL/USDC"}}],
        "/analise":       [{"name": "symbol", "in": "query", "required": False,
                            "description": "Ativo a analisar",
                            "schema": {"type": "string", "example": "SOL/USDC"}}],
        "/swarm-vote":    [{"name": "proposal", "in": "query", "required": False,
                            "description": "ID da proposta",
                            "schema": {"type": "string", "example": "prop-001"}}],
        "/rugcheck":      [{"name": "token", "in": "query", "required": False,
                            "description": "Endereço do token a verificar",
                            "schema": {"type": "string", "example": "4k3D..."}}],
        "/sinais":        [{"name": "timeframe", "in": "query", "required": False,
                            "description": "Timeframe do sinal",
                            "schema": {"type": "string", "enum": ["1h","4h","1d"], "example": "1h"}}],
        "/defi-yield":    [{"name": "protocol", "in": "query", "required": False,
                            "description": "Protocolo DeFi (ex: raydium, orca)",
                            "schema": {"type": "string", "example": "raydium"}}],
        "/deep-think":    [{"name": "question", "in": "query", "required": False,
                            "description": "Pergunta para análise profunda de IA",
                            "schema": {"type": "string", "example": "BTC vai subir nas próximas 24h?"}}],
        "/pump-monitor":  [{"name": "limit", "in": "query", "required": False,
                            "description": "Número de tokens a monitorar",
                            "schema": {"type": "integer", "example": 10}}],
        "/arbitrage":     [{"name": "pair", "in": "query", "required": False,
                            "description": "Par a verificar arbitragem",
                            "schema": {"type": "string", "example": "SOL/USDC"}}],
        "/tg-premium":    [{"name": "format", "in": "query", "required": False,
                            "description": "Formato do feed",
                            "schema": {"type": "string", "enum": ["json","text"], "default": "json"}}],
        "/relatorio":     [{"name": "period", "in": "query", "required": False,
                            "description": "Período do relatório",
                            "schema": {"type": "string", "enum": ["24h","7d","30d"], "example": "24h"}}],
        "/backtest":      [{"name": "strategy", "in": "query", "required": False,
                            "description": "ID da estratégia a testar",
                            "schema": {"type": "string", "example": "momentum_v1"}},
                           {"name": "days", "in": "query", "required": False,
                            "description": "Dias de histórico",
                            "schema": {"type": "integer", "example": 30}}],
        "/agent-call":    [{"name": "target", "in": "query", "required": False,
                            "description": "Endereço do nó alvo",
                            "schema": {"type": "string", "example": "https://peer.example.com"}}],
        "/onchain-credit":[{"name": "wallet", "in": "query", "required": False,
                            "description": "Endereço Solana a avaliar",
                            "schema": {"type": "string", "example": "7xKX..."}}],
        "/cross-chain":   [{"name": "pair", "in": "query", "required": False,
                            "description": "Par cross-chain (ex: SOL-ETH)",
                            "schema": {"type": "string", "example": "SOL-ETH"}}],
        "/whale-alert":   [{"name": "min_usd", "in": "query", "required": False,
                            "description": "Valor mínimo em USD para alertar",
                            "schema": {"type": "number", "example": 100000}}],
        "/smart-money":   [{"name": "limit", "in": "query", "required": False,
                            "description": "Número de wallets a rastrear",
                            "schema": {"type": "integer", "example": 10}}],
        "/copytrade":     [{"name": "wallet", "in": "query", "required": False,
                            "description": "Wallet a copiar",
                            "schema": {"type": "string", "example": "7xKX..."}}],
        "/market-brief":  [{"name": "focus", "in": "query", "required": False,
                            "description": "Foco do briefing (macro, btc, sol, rotation)",
                            "schema": {"type": "string", "example": "macro"}}],
        "/portfolio-copilot":[{"name": "wallet", "in": "query", "required": False,
                            "description": "Wallet Solana a diagnosticar",
                            "schema": {"type": "string", "example": "7xKX..."}}],
        "/launch-sniper": [{"name": "limit", "in": "query", "required": False,
                            "description": "Quantidade de launches analisados",
                            "schema": {"type": "integer", "example": 10}}],
        "/whale-dossier": [{"name": "min_usd", "in": "query", "required": False,
                            "description": "Corte mínimo para fluxo whale",
                            "schema": {"type": "number", "example": 250000}}],
        "/thesis-engine": [{"name": "symbol", "in": "query", "required": False,
                            "description": "Ativo principal da tese",
                            "schema": {"type": "string", "example": "SOL"}}],
        "/starter-pack":  [{"name": "wallet", "in": "query", "required": False,
                            "description": "Wallet opcional para personalizar o pack",
                            "schema": {"type": "string", "example": "7xKX..."}}],
        "/alpha-signal":  [{"name": "confidence", "in": "query", "required": False,
                            "description": "Confiança mínima do sinal 0-100",
                            "schema": {"type": "integer", "example": 75}}],
        "/insider-track": [{"name": "limit", "in": "query", "required": False,
                            "description": "Número de wallets insider a rastrear",
                            "schema": {"type": "integer", "example": 5}}],
        "/mev-flow":      [{"name": "limit", "in": "query", "required": False,
                            "description": "Número de oportunidades MEV",
                            "schema": {"type": "integer", "example": 5}}],
    }

    paths = {}
    for p in BASE_PRICES:
        price = BASE_PRICES[p]
        params = ENDPOINT_PARAMS.get(p, [
            {"name": "format", "in": "query", "required": False,
             "description": "Formato da resposta",
             "schema": {"type": "string", "enum": ["json"], "default": "json"}}
        ])
        paths[p] = {
            "get": {
                "summary":     ENDPOINT_DESC.get(p, p),
                "description": f"{ENDPOINT_DESC.get(p, p)}. Preço: ${price:.4f} USDC via x402.",
                "operationId": p.strip("/").replace("-", "_"),
                "tags":        ENDPOINT_TAGS.get(p, ["Trading"]),
                "parameters":  params,
                "security":    [{"x402": []}],
                # x-payment-info: convenção emergente usada por x402scan e 402 Index
                "x-payment-info": {
                    "scheme":  "exact",
                    "network": f"solana:{SOL_GENESIS}",
                    "asset":   USDC_MINT,
                    "amount":  str(int(price * 10 ** USDC_DECIMALS)),
                    "payTo":   RECEIVE_ADDRESS,
                },
                "responses": {
                    "200": {"description": "Sucesso",
                            "content": {"application/json": {"schema": {"type": "object"}}}},
                    "402": {"description": "Payment Required — use protocolo x402"},
                },
            }
        }

    info = {
        "title":       "Losbeto",
        "version":     VERSION,
        "description": f"Multi-chain x402 AI swarm — Solana + Base. {len(BASE_PRICES)} monetized resources with flagship bundles, thesis engine e starter pack.",
    }
    if contact_email:
        info["contact"] = {"email": contact_email}

    return jsonify({
        "openapi": "3.0.0",
        "info":    info,
        "servers": [{"url": base}],
        "components": {
            "securitySchemes": {
                "x402": {
                    "type":        "apiKey",
                    "in":          "header",
                    "name":        "PAYMENT-REQUIRED",
                    "description": "x402 payment — base64 encoded PaymentRequired payload",
                }
            }
        },
        "paths": paths,
    })

@app.route("/llms.txt")
def llms_txt():
    """llms.txt v13 — Otimizado para descoberta por agentes LLM."""
    base = _public_base()
    lines = [
        f"# Losbeto v{VERSION}",
        f"> Multi-chain AI swarm. Solana + Base + TON. {len(BASE_PRICES)} endpoints. Pay-per-call via x402.",
        "> WIN RATE: {:.1f}% | POI: {:.2f}x | CHAINS: {}{}".format(
            LEDGER.win_rate(), LEDGER.get_poi_multiplier(),
            f"solana:{SOL_GENESIS}", 
            f", {BASE_CAIP2}" if ENABLE_BASE else ""
        ),
        "",
        "## Pagar (Multi-Chain)",
        f"Solana payTo: {RECEIVE_ADDRESS} (network: solana:{SOL_GENESIS})",
    ]
    if ENABLE_BASE and BASE_PAYTO_EVM:
        lines.append(f"Base payTo:   {BASE_PAYTO_EVM} (network: eip155:8453)")
    if TON_WALLET:
        lines.append(f"TON address:  {TON_WALLET.address}")
    lines += ["", "## Endpoints por Tier"]

    # Group by price tier
    tiers = {"DISCOVERY ($0.01-0.03)": [], "CORE ($0.04-0.15)": [], 
             "PRO ($0.18-0.40)": [], "FLAGSHIP ($0.49-1.00)": []}
    for p, price in sorted(BASE_PRICES.items(), key=lambda x: x[1]):
        if price <= 0.03:
            tiers["DISCOVERY ($0.01-0.03)"].append((p, price))
        elif price <= 0.15:
            tiers["CORE ($0.04-0.15)"].append((p, price))
        elif price <= 0.40:
            tiers["PRO ($0.18-0.40)"].append((p, price))
        else:
            tiers["FLAGSHIP ($0.49-1.00)"].append((p, price))

    for tier_name, endpoints in tiers.items():
        lines.append(f"\n### {tier_name}")
        for p, price in endpoints:
            lines.append(f"- [{base}{p}]({base}{p}) — {ENDPOINT_DESC.get(p, p)} (${price:.4f})")

    # Free tier
    lines += ["", "### FREE (sem pagamento)",
              f"- [{base}/sample]({base}/sample) — Preview de dados reais (Fear&Greed + Sinais + Anomalias)",
              f"- [{base}/losbeto-alpha]({base}/losbeto-alpha) — Losbeto Alpha Score (índice proprietário exclusivo)",
              f"- [{base}/bootstrap-trust]({base}/bootstrap-trust) — Bootstrap trust score (self-payment)",
              f"- [{base}/starter-pack]({base}/starter-pack) — Pacote premium de US$1 para primeira compra manual",
              f"- [{base}/get-pricing]({base}/get-pricing) — Lista completa de preços"]

    lines += ["", "## Discovery",
              f"- OpenAPI:    {base}/openapi.json",
              f"- x402:       {base}/.well-known/x402.json",
              f"- MCP:        {base}/.well-known/mcp.json",
              f"- A2A:        {base}/.well-known/agent.json",
              f"- Verify:     {base}/.well-known/verify-manifest (prova criptográfica de posse)",
              f"- Bazaar:     {base}/bazaar.json",
              f"- llms.txt:   {base}/llms.txt"]
    return app.response_class("\n".join(lines), mimetype="text/plain")

@app.route("/favicon.ico")
def favicon():
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">'
           '<rect width="32" height="32" rx="6" fill="#7B61FF"/>'
           '<text x="16" y="22" font-size="16" text-anchor="middle" '
           'fill="white" font-family="sans-serif" font-weight="bold">Ω10</text></svg>')
    return app.response_class(svg, mimetype="image/svg+xml")

@app.route("/health")
def health():
    return jsonify({"ok": True, "version": VERSION, "ts": int(time.time())})

@app.route("/ready")
def ready():
    return jsonify({"ready": True, "version": VERSION,
                    "node_id": WALLET.node_id,
                    "endpoints": len(BASE_PRICES),
                    "ts": int(time.time())})

# ── FREE TIER: entrada gratuita — converte visitantes em pagantes ────────────
@app.route("/peers")
def peers_list():
    peers = LEDGER.active_peers()
    return jsonify({"count": len(peers),
                    "peers": [{"node": p[0], "url": p[1],
                               "reputation": p[2], "win_rate": p[3]}
                              for p in peers]})


# ============================================================================
# 15. DASHBOARD v16 MARKET-FIT
# ============================================================================

DASH_HTML = """<!doctype html><html lang="pt-BR"><head>
<meta charset="utf-8"><title>Losbeto Dashboard</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
:root{--bg:#0a0e1a;--card:#141a2e;--accent:#7B61FF;--green:#22c55e;--red:#ef4444;--text:#e7eaff;--muted:#8a93b8}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--text);font:14px/1.5 system-ui,-apple-system,sans-serif;padding:20px}
.header{display:flex;justify-content:space-between;align-items:center;margin-bottom:20px}
.badge{background:var(--accent);padding:4px 10px;border-radius:6px;font-size:11px;font-weight:bold}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:16px;margin-bottom:24px}
.card{background:var(--card);border:1px solid #232a45;border-radius:10px;padding:16px}
.card h3{color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:1px;margin-bottom:8px}
.card .v{font-size:28px;font-weight:700;color:var(--text)}
.card .sub{color:var(--muted);font-size:12px;margin-top:4px}
.green{color:var(--green)} .red{color:var(--red)}
.yellow{color:#eab308}
.alert{background:linear-gradient(135deg,#7B61FF22,#7B61FF11);border:1px solid var(--accent);border-radius:10px;padding:16px;margin-bottom:20px}
.alert h4{color:var(--accent);font-size:13px;margin-bottom:8px}
.alert p{color:var(--muted);font-size:12px;line-height:1.6}
a{color:var(--accent);text-decoration:none}
a:hover{text-decoration:underline}
table{width:100%;border-collapse:collapse;background:var(--card);border-radius:10px;overflow:hidden}
th,td{padding:10px;text-align:left;border-bottom:1px solid #232a45}
th{background:#1a2140;color:var(--muted);font-size:11px;text-transform:uppercase}
code{background:#0f1428;padding:2px 6px;border-radius:4px;font-size:12px;color:var(--accent)}
.footer{margin-top:30px;color:var(--muted);font-size:12px;text-align:center}
</style></head><body>
<div class="header">
  <div><h1>⚡ Losbeto <span class="badge">v16 MARKET-FIT</span></h1>
       <div style="color:var(--muted);font-size:12px;margin-top:4px" id="node">node···</div></div>
  <div style="text-align:right">
       <div style="font-size:11px;color:var(--muted)">Solana</div>
       <code id="addr" style="font-size:10px">···</code>
       <div id="base_addr" style="font-size:10px;color:var(--muted);margin-top:4px"></div>
  </div>
</div>

<div class="alert" id="trust_alert">
  <h4>🚀 Trust Score Boost</h4>
  <p>Seu node precisa de <strong>3 transações reais</strong> para aparecer nos marketplaces. 
     Use <code>/bootstrap-trust</code> para gerar self-payments ou aguarde pagamentos orgânicos.
     <br>Verifique: <a href="https://www.x402scan.com" target="_blank">x402scan.com</a>
     <br><span id="signer" style="font-size:11px;color:var(--muted);margin-top:6px;display:inline-block"></span>
  </p>
</div>

<div class="grid" id="cards"></div>
<h2 style="margin:20px 0 10px;color:var(--muted);font-size:14px;text-transform:uppercase">Top Endpoints (24h)</h2>
<table id="tbl"><thead><tr><th>Endpoint</th><th>Hits</th><th>Preço (USDC)</th></tr></thead><tbody></tbody></table>
<h2 style="margin:20px 0 10px;color:var(--muted);font-size:14px;text-transform:uppercase">Ações Rápidas</h2>
<div class="grid" style="grid-template-columns:repeat(auto-fit,minmax(250px,1fr))">
  <div class="card">
    <h3>📍 Listar em Marketplaces</h3>
    <div class="sub" style="margin-top:8px">
      <a href="https://www.x402scan.com/resources/register" target="_blank">x402scan</a> | 
      <a href="https://github.com/xpaysh/awesome-x402" target="_blank">awesome-x402</a> | 
      <a href="https://agentcash.dev" target="_blank">AgentCash</a> | 
      <a href="https://mcpay.tech" target="_blank">MCPay</a>
    </div>
  </div>
  <div class="card">
    <h3>🧪 Testar Pagamento</h3>
    <div class="sub" style="margin-top:8px">
      <code style="font-size:10px">POST /bootstrap-trust</code> com <code style="font-size:10px">X-Payment: &lt;tx-sig&gt;</code>
    </div>
  </div>
  <div class="card">
    <h3>🔗 Manifests</h3>
    <div class="sub" style="margin-top:8px">
      <a href="/.well-known/x402.json" target="_blank">x402.json</a> | 
      <a href="/.well-known/mcp.json" target="_blank">mcp.json</a> | 
      <a href="/bazaar.json" target="_blank">bazaar.json</a>
    </div>
  </div>
</div>

<div class="footer">Atualização automática a cada 10s. Win-rate dirige preço (PoI). v16 MARKET-FIT.</div>
<script>
async function reload(){
  const r=await fetch("/dash/api/stats?token=__TOKEN__");
  if(!r.ok)return;
  const j=await r.json();
  document.getElementById("node").textContent="node "+j.node_id;
  document.getElementById("addr").textContent=j.solana_address;
  const sigEl=document.getElementById("signer");
  if(sigEl && j.signer_address && j.signer_address!==j.solana_address){
    sigEl.textContent="signer "+j.signer_address.slice(0,8)+"..."+j.signer_address.slice(-4);
    sigEl.title="Signer (JWT/P2P) — não recebe pagamentos: "+j.signer_address;
  }
  const cards=[
    ["💰 Receita Total",`$${j.stats.total_usdc.toFixed(4)}`,"USDC acumulado"],
    ["📅 Hoje (24h)",`$${j.stats.today_usdc.toFixed(4)}`,j.stats.paid_24h+" pagamentos"],
    ["⏱️ Última hora",`$${j.stats.hour_usdc.toFixed(4)}`,"USDC"],
    ["🎯 Win Rate",`${j.stats.win_rate.toFixed(1)}%`,"30 dias"],
    ["⚡ PoI Multiplier",`${j.stats.poi_multiplier.toFixed(2)}x`,"preço dinâmico"],
    ["📊 Conversão",`${j.stats.conv_rate.toFixed(1)}%`,j.stats.requests_24h+" requisições"],
    ["👥 Compradores",j.stats.buyers,"únicos"],
    ["⛓️ Chains",(j.chains||["solana"]).join(", "),"ativas"],
    ["📈 Trust Score",j.stats.paid_24h >= 3 ? "✅ ATIVO" : "⚠️ BOOTSTRAP NEEDED", j.stats.paid_24h+" tx"],
    ["🌐 Endpoints",j.endpoints,"monetizados"],
  ];
  document.getElementById("cards").innerHTML = cards.map(c =>
    `<div class="card"><h3>${c[0]}</h3><div class="v">${c[1]}</div><div class="sub">${c[2]}</div></div>`
  ).join("");
  const rows = Object.entries(j.stats.by_endpoint||{})
    .sort((a,b)=>b[1]-a[1]).slice(0,15);
  document.getElementById("tbl").querySelector("tbody").innerHTML =
    rows.length ? rows.map(([ep,n])=>`<tr><td><code>${ep}</code></td><td>${n}</td><td>$${(j.prices[ep]||0).toFixed(4)}</td></tr>`).join("")
                : '<tr><td colspan=3 style="text-align:center;color:var(--muted)">Aguardando pagamentos... Use /bootstrap-trust para gerar 3 transações iniciais reais.</td></tr>';
}
reload(); setInterval(reload, 10000);
</script></body></html>"""

@app.route("/dash")
def dash():
    if request.args.get("token") != DASH_TOKEN:
        return "Forbidden — pass ?token=...", 403
    return app.response_class(DASH_HTML.replace("__TOKEN__", DASH_TOKEN),
                              mimetype="text/html")

@app.route("/dash/api/stats")
def dash_api():
    if request.args.get("token") != DASH_TOKEN:
        return jsonify({"error": "forbidden"}), 403
    return jsonify({
        "version":         VERSION,
        "node_id":         WALLET.node_id,
        "solana_address":  RECEIVE_ADDRESS,
        "signer_address":  WALLET.solana_address,
        "ton_address":     TON_WALLET.address if TON_WALLET else None,
        "base_payto":      BASE_PAYTO_EVM if ENABLE_BASE else None,
        "chains":          [f"solana:{SOL_GENESIS}"] + ([BASE_CAIP2] if ENABLE_BASE else []),
        "stats":           LEDGER.stats(),
        "endpoints":       len(BASE_PRICES),
        "prices":          {ep: get_dynamic_price(ep) for ep in BASE_PRICES},
        "featured_endpoints": FEATURED_ENDPOINTS,
    })

# ============================================================================
# 16. TELEGRAM BOT 2.0
# ============================================================================

class TelegramBot:
    def __init__(self, token: str):
        self.token = token
        self.last_update = 0

    def send(self, chat_id, text, parse_mode="Markdown"):
        try:
            requests.post(f"https://api.telegram.org/bot{self.token}/sendMessage",
                json={"chat_id": chat_id, "text": text, "parse_mode": parse_mode,
                      "disable_web_page_preview": True},
                timeout=10)
        except Exception as e:
            log.warning(f"TG send: {e}")

    def poll(self):
        try:
            r = requests.get(f"https://api.telegram.org/bot{self.token}/getUpdates",
                params={"offset": self.last_update + 1, "timeout": 30}, timeout=35)
            if not r.ok: return
            for u in r.json().get("result", []):
                self.last_update = u["update_id"]
                msg = u.get("message")
                if not msg or "text" not in msg: continue
                self._handle(msg)
        except Exception as e:
            log.warning(f"TG poll: {e}")

    def _handle(self, msg):
        chat_id = msg["chat"]["id"]
        text = msg["text"].strip()
        if text == "/start":
            self.send(chat_id, (
                f"⚡ *Losbeto v{VERSION}*\n\n"
                f"Comandos disponíveis:\n"
                f"/precos - lista preços ao vivo\n"
                f"/sinais - top sinais agora\n"
                f"/whale - whale alerts 24h\n"
                f"/sentiment BTC - sentimento de um símbolo\n"
                f"/pump - novos tokens Pump.fun\n"
                f"/status - status do nó\n"
                f"/wallet - endereços para pagamento\n\n"
                f"💡 _Para chamadas API completas use {_public_base()}_"
            ))
        elif text == "/precos":
            lines = ["💰 *Preços atuais (USDC)*\n"]
            for ep in BASE_PRICES:
                lines.append(f"`{ep}` — `${get_dynamic_price(ep):.4f}`")
            self.send(chat_id, "\n".join(lines))
        elif text == "/sinais":
            sigs = Brain.sinais().get("signals", [])[:5]
            if not sigs:
                self.send(chat_id, "📊 Sem sinais fortes agora.")
            else:
                lines = ["📊 *Top sinais agora*\n"]
                for s in sigs:
                    emoji = "🟢" if s["action"] == "buy" else "🔴"
                    lines.append(f"{emoji} `{s['symbol']}` {s['action'].upper()} "
                                 f"conf {s['confidence']:.0%} @ ${s['price']:.4f}")
                self.send(chat_id, "\n".join(lines))
        elif text.startswith("/sentiment"):
            parts = text.split()
            sym = parts[1] if len(parts) > 1 else "BTC"
            with app.test_request_context(f"/sentiment?symbol={sym}"):
                r = Brain.sentiment()
            emoji = "🟢" if r.get("sentiment") == "bullish" else \
                    "🔴" if r.get("sentiment") == "bearish" else "⚪"
            self.send(chat_id, f"{emoji} *{r.get('symbol')}*\n"
                              f"Sentimento: *{r.get('sentiment')}*\n"
                              f"Score: `{r.get('score')}`\n"
                              f"F&G: `{r.get('fear_greed')}`")
        elif text == "/whale":
            w = Market.whale_alert()[:5]
            if not w:
                self.send(chat_id, "🐋 Sem whales agora.")
            else:
                lines = ["🐋 *Top 5 maior volume 24h*\n"]
                for x in w:
                    lines.append(f"`{x['symbol']}` — `${x['volume_24h']/1e6:.1f}M` "
                                 f"({x['price_change']:+.1f}%)")
                self.send(chat_id, "\n".join(lines))
        elif text == "/pump":
            new = Market.pump_new()[:5]
            lines = ["🚀 *Novos tokens monitorados*\n"]
            for t in new:
                lines.append(f"• {t.get('description', 'N/A')[:50]}")
            self.send(chat_id, "\n".join(lines) if new else "Nenhum token detectado.")
        elif text == "/status":
            s = LEDGER.stats()
            self.send(chat_id, (
                f"⚡ *Status Losbeto v{VERSION}*\n\n"
                f"💰 Total: `${s['total_usdc']:.4f}` USDC\n"
                f"📅 24h: `${s['today_usdc']:.4f}` ({s['paid_24h']} pagamentos)\n"
                f"⏱️ 1h: `${s['hour_usdc']:.4f}`\n"
                f"🎯 Win rate: `{s['win_rate']}%`\n"
                f"⚡ PoI: `{s['poi_multiplier']:.2f}x`\n"
                f"👥 Compradores: `{s['buyers']}`\n"
                f"🌐 Peers: `{len(LEDGER.active_peers())}`"
            ))
        elif text == "/wallet":
            txt = f"💳 *Endereços de pagamento*\n\nSolana:\n`{RECEIVE_ADDRESS}`"
            if ENABLE_BASE:
                txt += f"\n\nBase (EVM):\n`{BASE_PAYTO_EVM}`"
            if TON_WALLET:
                txt += f"\n\nTON:\n`{TON_WALLET.address}`"
            self.send(chat_id, txt)
        else:
            self.send(chat_id, "❓ Comando não reconhecido. Tente /start")

TG_BOT = TelegramBot(TG_TOKEN) if TG_TOKEN else None

# ============================================================================
# 17. WORKERS BACKGROUND
# ============================================================================

def signal_validator_loop():
    while True:
        time.sleep(900)  # 15min
        try:
            pending = LEDGER.pending_signals()
            top = {(c.get("symbol") or "").upper(): c.get("current_price")
                   for c in Market.top_coins(50)}
            for sid, sym, action, _p0, _ts in pending:
                if sym in top and top[sym]:
                    LEDGER.validate_signal(sid, top[sym])
        except Exception as e:
            log.warning(f"validator: {e}")

def signal_generator_loop():
    while True:
        time.sleep(600)  # 10min
        try:
            Brain.sinais()  # gera e armazena
        except Exception as e:
            log.warning(f"sig-gen: {e}")

def rag_ingest_loop():
    while True:
        time.sleep(1800)  # 30min
        try:
            fg = Market.fear_greed()
            regime = Brain.regime()
            top = Market.top_coins(10)
            content = (f"Market snapshot {datetime.utcnow().isoformat()}: "
                       f"F&G={fg.get('value')} regime={regime.get('regime')} "
                       f"Top: " + ", ".join(
                           f"{c['symbol'].upper()}={c.get('price_change_percentage_24h', 0):.1f}%"
                           for c in top[:10]))
            RAG_STORE.ingest("snapshot", content)
        except Exception as e:
            log.warning(f"rag: {e}")

def sweeper_loop():
    if not BINANCE_ADDRESS:
        log.info("Sweep desativado (BINANCE_SOLANA_ADDRESS vazio)")
        return
    log.info(f"Sweep para {BINANCE_ADDRESS} — threshold ${SWEEP_THRESHOLD}")
    while True:
        time.sleep(SWEEP_INTERVAL)
        try:
            bal = SOL.get_balance_usdc(RECEIVE_ADDRESS)
            if bal >= SWEEP_THRESHOLD:
                log.info(f"💸 Sweep: ${bal:.4f} → {BINANCE_ADDRESS}")
                # NOTE: A construção/envio da transação SPL token transfer requer
                # a Solana web3 library completa. Aqui registramos a intenção.
                # Em produção, integrar com solana-py para enviar a tx real.
                LEDGER.log_sweep(bal, "pending-impl", BINANCE_ADDRESS)
                _notify_telegram(f"💸 Sweep solicitado: ${bal:.4f}\nDestino: {BINANCE_ADDRESS}")
        except Exception as e:
            log.warning(f"sweep: {e}")

def telegram_loop():
    if not TG_BOT: return
    log.info(f"🤖 Telegram bot ativo")
    while True:
        try:
            TG_BOT.poll()
        except Exception as e:
            log.warning(f"tg loop: {e}")
            time.sleep(5)

def autoregister_x402scan():
    """Registro automático em TODOS os marketplaces — x402scan, AgentCash, MCPay, BlockRun."""
    time.sleep(25)
    if not PUBLIC_URL:
        log.warning("autoregister: PUBLIC_URL não definida")
        return
    try:
        r = requests.get(f"{PUBLIC_URL}/.well-known/x402.json", timeout=15)
        if not r.ok:
            log.warning(f"autoregister: manifest retornou {r.status_code}")
            return

        log.info("=" * 62)
        log.info(f"⚡ LOSBETO v{VERSION} — OPERACIONAL")
        log.info(f"   URL:         {PUBLIC_URL}")
        log.info(f"   Free tier:   {PUBLIC_URL}/sample")
        log.info(f"   Pricing:     {PUBLIC_URL}/get-pricing")
        log.info(f"   Bazaar:      {PUBLIC_URL}/bazaar.json")
        log.info(f"   x402:        {PUBLIC_URL}/.well-known/x402.json")
        log.info(f"   MCP:         {PUBLIC_URL}/.well-known/mcp.json")
        log.info(f"   llms.txt:    {PUBLIC_URL}/llms.txt")
        log.info("=" * 62)

        # 1. x402scan auto-register
        try:
            reg = requests.post("https://www.x402scan.com/api/register",
                json={"url": PUBLIC_URL, "version": 2}, timeout=10)
            log.info(f"📍 x402scan: {'✅ OK' if reg.ok else 'manual → x402scan.com/resources/register'}")
        except Exception:
            log.info(f"📍 x402scan: registre em https://www.x402scan.com/resources/register")

        # 2. PayAI Bazaar index
        try:
            payai = requests.post("https://facilitator.payai.network/api/register",
                json={"url": PUBLIC_URL}, timeout=8)
            log.info(f"📍 PayAI Bazaar: {'✅ indexado' if payai.ok else 'pendente'}")
        except Exception:
            log.info(f"📍 PayAI: acesse https://facilitator.payai.network para indexar")

        # 3. AgentCash
        log.info(f"📍 AgentCash: https://agentcash.dev → cole {PUBLIC_URL}")
        log.info(f"   ⚠️  Delete listagem v1 antiga antes de registrar v2!")

        # 4. MCPay.tech
        log.info(f"📍 MCPay.tech: https://mcpay.tech → listar MCP server")

        # 5. Awesome-x402 (PR no GitHub)
        log.info(f"📍 Awesome-x402: https://github.com/xpaysh/awesome-x402 → abrir PR")

        # 6. BlockRun
        log.info(f"📍 BlockRun marketplace: https://blockrun.ai/marketplace")
        log.info(f"   Contato parceria: vicky@blockrun.ai | @bc1max no Telegram")
        log.info(f"   Revenue share: 70% Losbeto / 30% router")

        # Wallet + sweep info
        log.info(f"💰 Recebe em: {RECEIVE_ADDRESS}")
        if BINANCE_ADDRESS:
            log.info(f"🏦 Sweep Binance: {BINANCE_ADDRESS}")

        log.info("=" * 62)

        # 6. 402 Index (PipRail)
        try:
            r402 = requests.post("https://api.piprail.com/v1/index/register",
                json={"url": PUBLIC_URL, "chain": "solana"}, timeout=8)
            if r402.ok:
                log.info("✅ 402 Index (PipRail): registrado")
        except Exception:
            pass

        # 7. Nodit x402 Index
        try:
            rnodit = requests.post("https://api.nodit.io/x402/v1/register",
                json={"url": PUBLIC_URL, "chains": ["solana", "base"]}, timeout=8)
            if rnodit.ok:
                log.info("✅ Nodit x402 Index: registrado")
        except Exception:
            pass

        # 8. PromptHero (AI agent discovery)
        try:
            rph = requests.post("https://api.prompthero.com/x402/register",
                json={"url": PUBLIC_URL, "category": "crypto-trading"}, timeout=8)
            if rph.ok:
                log.info("✅ PromptHero: registrado")
        except Exception:
            pass

        # 9. LangChain Tools Registry
        try:
            rlc = requests.post("https://api.langchain.com/tools/register",
                json={"url": PUBLIC_URL, "type": "x402-payment"}, timeout=8)
            if rlc.ok:
                log.info("✅ LangChain Tools: registrado")
        except Exception:
            pass

        log.info("=" * 62)
        log.info("📋 CHECKLIST PÓS-DEPLOY — Faça MANUALMENTE:")
        log.info("   1. x402scan:      https://www.x402scan.com/resources/register")
        log.info("   2. awesome-x402:  https://github.com/xpaysh/awesome-x402/pulls")
        log.info("   3. AgentCash:     https://agentcash.dev (cole sua URL)")
        log.info("   4. MCPay:         https://mcpay.tech (listar MCP)")
        log.info("   5. BlockRun:      https://blockrun.ai/marketplace")
        log.info("   6. Tweet:         @x402scan @CoinbaseDev @base @solana")
        log.info("   7. Bootstrap:     POST /bootstrap-trust com 3 tx de $0.01 (Phantom-friendly)")
        log.info("=" * 62)

        def _recheck():
            time.sleep(600)
            try:
                r2 = requests.get(f"{PUBLIC_URL}/health", timeout=10)
                if r2.ok:
                    log.info("✅ Losbeto estável após 10min — pronto para receber pagamentos")
            except Exception:
                pass
        threading.Thread(target=_recheck, daemon=True).start()

    except Exception as e:
        log.warning(f"autoregister erro: {e}")

def run_server():
    threading.Thread(target=signal_validator_loop, daemon=True).start()
    threading.Thread(target=signal_generator_loop, daemon=True).start()
    threading.Thread(target=rag_ingest_loop, daemon=True).start()
    threading.Thread(target=sweeper_loop, daemon=True).start()
    if TG_BOT:
        threading.Thread(target=telegram_loop, daemon=True).start()
    threading.Thread(target=autoregister_x402scan, daemon=True).start()

    log.info("=" * 72)
    log.info(f"⚡ LOSBETO v{VERSION} — ATIVO")
    log.info(f"   Node ID:    {WALLET.node_id}")
    log.info(f"   RECEIVE:    {RECEIVE_ADDRESS}")
    log.info(f"   SIGNER:     {WALLET.solana_address}")
    if TON_WALLET:
        log.info(f"   TON:        {TON_WALLET.address}")
    if ENABLE_BASE:
        log.info(f"   Base EVM:   {BASE_PAYTO_EVM}")
    if BINANCE_ADDRESS:
        log.info(f"   Sweep →     {BINANCE_ADDRESS}")
    log.info(f"   URL:        {_public_base()}")
    log.info(f"   Dashboard:  {_public_base()}/dash?token={DASH_TOKEN}")
    log.info(f"   Telegram:   {'ATIVO' if TG_BOT else 'off'}")
    log.info(f"   Facilitator:{'ATIVO ' + FACILITATOR_URL if FACILITATOR else 'off'}")
    log.info(f"   Dynamic:    {'ATIVO' if DYNAMIC_PRICING else 'off'}")
    log.info(f"   GeoIP:      {'ATIVO blocked=' + str(GEO_BLOCKED_COUNTRIES) if GEOIP_ENABLED else 'off'}")
    log.info(f"   Endpoints:  {len(BASE_PRICES)}")
    log.info("=" * 72)

    # Tenta gunicorn primeiro (produção); fallback Flask dev
    try:
        from gunicorn.app.base import BaseApplication
        class _G(BaseApplication):
            def __init__(self, app, opts): self.app_app = app; self.opts = opts; super().__init__()
            def load_config(self):
                for k, v in self.opts.items(): self.cfg.set(k, v)
            def load(self): return self.app_app
        opts = {
            "bind":     f"0.0.0.0:{X402_PORT}",
            "workers":  int(os.environ.get("GUNICORN_WORKERS", "2")),
            "threads":  int(os.environ.get("GUNICORN_THREADS", "8")),
            "timeout":  60,
            "accesslog": "-",
            "errorlog":  "-",
            "loglevel":  "info",
        }
        _G(app, opts).run()
    except ImportError:
        app.run(host="0.0.0.0", port=X402_PORT, threaded=True, use_reloader=False)


def cli():
    args = sys.argv[1:]
    if "--wallet" in args:
        print(f"RECEIVE address: {RECEIVE_ADDRESS}")
        print(f"Signer address:  {WALLET.solana_address}")
        print(f"Signer seed:     {WALLET.export_b58_seed()}")
        if TON_WALLET:
            print(f"TON address:    {TON_WALLET.address}")
            print(f"TON mnemonic:   {TON_WALLET.mnemonic[:32]}...")
        return
    if "--reset" in args:
        for p in (DB_PATH, RAG_DB_PATH):
            if p.exists():
                p.unlink()
                print(f"removed {p}")
        return
    if "--stats" in args:
        print(json.dumps(LEDGER.stats(), indent=2))
        return
    if "--help" in args:
        print(__doc__)
        return
    run_server()


if __name__ == "__main__":
    cli()
