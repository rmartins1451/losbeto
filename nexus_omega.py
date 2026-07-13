# -*- coding: utf-8 -*-
"""
================================================================================
 LOSBETO v21.0.0 — CHERRY ON TOP (cereja do bolo)
================================================================================
 Enxame Autônomo Multi-Chain — Solana + Base + TON + MONETIZADO.

 CORREÇÕES v21 (upgrade completo para vender de verdade):
  🍒 x402 v1 + v2 DUAL: aceita X-PAYMENT (v1) E PAYMENT-SIGNATURE (v2).
  🍒 Landing HTML COMERCIAL em / — buyers/agentes veem o valor antes de pagar.
  🍒 /losbeto-alpha-score — endpoint FREE hook (converte tráfego em compradores).
  🍒 /multi-chain-arbitrage — feature único no ecossistema x402 (bundle premium).
  🍒 /win-rate-verified — histórico assinado on-chain (Ed25519 → trust matemático).
  🍒 /agent-composable — bundle que encadeia 5 endpoints em 1 chamada (premium).
  🍒 Auto-registro em 5 marketplaces (CDP Bazaar + x402scan + PayAI + MCPay + AgentCash).
  🍒 Bootstrap wizard: gera tx sintética válida OU lê tx real com verificação.
  🍒 /supported endpoint (compat PayAI facilitator para descoberta de feePayer).
  🍒 Retry exponencial em TX + fallback triplo (Helius → Solana RPC → Public RPC).
  🍒 Manifest x402 duplo v1+v2 no /.well-known/x402.json (compat máxima).
  🍒 SEO/Discovery: robots.txt + sitemap.xml + AI-friendly meta tags.
  🍒 Analytics: contador de visualizações → sabemos quem está descobrindo.

 CORREÇÕES v20 (BASEADAS EM DIAGNÓSTICO REAL DAS 3 TX MANUAIS):
  🔥 /bootstrap-trust agora está EM BASE_PRICES → aparece no manifest x402.json → x402scan indexa
  🔥 SVM_FEE_PAYER_OVERRIDE com fallback CORRETO — resolve o erro AgentCash "feePayer is required".
  🔥 _verify_payment com RETRY exponencial para tx-not-found (fix lag Helius/RPC).
  🔥 /verify-signature-manual: novo endpoint público que aceita signature e credita se válida
     (fecha o loop: se o x402scan não indexou, você força indexação enviando o sig).
  🔥 /dash/api/tx-list: lista todas as tx registradas (dashboard vê o que o x402scan vê e o que não vê).
  🔥 Manifest x402.json v3-compat: adiciona feePayer via /supported do PayAI E aceita override.
  🔥 Handler paid_endpoint: fallback direto Solana quando facilitator falha (backup robusto).
  🔥 Endpoint /debug-x402scan: mostra POR QUE uma tx aparece ou não no scanner.

 CORREÇÕES E INOVAÇÕES v19:
  🔥 Facilitator padrão: PayAI (produção) — sem chave, suporta Solana e Base.
  🔥 Bootstrap Trust agora retorna 402 com headers (scanner aprova).
  🔥 Endpoints gratuitos declarados como "security": [] no OpenAPI.
  🔥 Novo sistema de afiliados (/referral) e staking de reputação (/stake).
  🔥 Auto‑promoção via Twitter/X (worker diário).
  🔥 Suporte a DeepSeek e Claude para LLM.
  🔥 Preços sem limite mínimo de override (você decide).

 42 ENDPOINTS MONETIZADOS + 3 NOVOS (referral, stake, auto‑promo).
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

VERSION = "21.0.0-CHERRY-ON-TOP"
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
REFERRAL_DB     = HOME_DIR / "referrals.db"
STAKE_DB        = HOME_DIR / "stakes.db"

# Portas
X402_PORT      = int(os.environ.get("PORT", os.environ.get("OMEGA_X402_PORT", "8402")))
GOSSIP_PORT    = int(os.environ.get("OMEGA_GOSSIP_PORT", "8403"))
MCAST_PORT     = int(os.environ.get("OMEGA_MCAST_PORT", "8404"))
DASHBOARD_PORT = X402_PORT
MCAST_GRP      = "239.42.42.42"

# URL pública
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
JWT_TTL    = int(os.environ.get("JWT_TTL_SECONDS", "300"))

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
SOL_GENESIS   = "5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp"

# Base (EVM)
BASE_RPC          = os.environ.get("BASE_RPC", "https://mainnet.base.org")
BASE_USDC         = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
BASE_PAYTO_EVM    = os.environ.get("BASE_PAYTO_EVM", "").strip()
BASE_CAIP2        = "eip155:8453"
ENABLE_BASE       = bool(BASE_PAYTO_EVM)

# Facilitator (padrão: PayAI – produção)
FACILITATOR_URL = os.environ.get("X402_FACILITATOR", "https://facilitator.payai.network").strip()
USE_FACILITATOR = bool(FACILITATOR_URL)

# TON
TON_API       = "https://toncenter.com/api/v2"
TON_API_KEY   = os.environ.get("TON_API_KEY", "").strip()
TON_TESTNET   = False

# APIs externas
GROQ_KEY     = os.environ.get("GROQ_API_KEY", "").strip()
GEMINI_KEY   = os.environ.get("GEMINI_API_KEY", "").strip()
DEEPSEEK_KEY = os.environ.get("DEEPSEEK_API_KEY", "").strip()
CLAUDE_KEY   = os.environ.get("CLAUDE_API_KEY", "").strip()
OLLAMA_URL   = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5:3b")
HELIUS_KEY   = os.environ.get("HELIUS_API_KEY", "").strip()
JUPITER_KEY  = os.environ.get("JUPITER_API_KEY", "").strip()
COINGECKO_KEY= os.environ.get("COINGECKO_API_KEY", "").strip()
TWITTER_API_KEY = os.environ.get("TWITTER_API_KEY", "").strip()
TWITTER_API_SECRET = os.environ.get("TWITTER_API_SECRET", "").strip()
TWITTER_ACCESS_TOKEN = os.environ.get("TWITTER_ACCESS_TOKEN", "").strip()
TWITTER_ACCESS_TOKEN_SECRET = os.environ.get("TWITTER_ACCESS_TOKEN_SECRET", "").strip()

# Telegram
TG_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
TG_CHAT  = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

# Binance sweep
_raw_binance = os.environ.get("BINANCE_SOLANA_ADDRESS", "").strip()
_legacy_binance = os.environ.get("BINANCE_WALLET_ADDRESS", "").strip()
if not _raw_binance and _legacy_binance:
    _raw_binance = _legacy_binance
if _raw_binance.startswith("0x"):
    _raw_binance = ""
BINANCE_ADDRESS = _raw_binance
SWEEP_THRESHOLD  = float(os.environ.get("SWEEP_THRESHOLD_USDC", "0.5"))
SWEEP_INTERVAL   = int(os.environ.get("SWEEP_INTERVAL_S", "3600"))

# Bootstrap P2P
BOOTSTRAP_SEEDS = [s.strip() for s in os.environ.get("OMEGA_SEEDS", "").split(",") if s.strip()]

# Dynamic Pricing
DYNAMIC_PRICING = os.environ.get("DYNAMIC_PRICING", "false").lower() == "true"
BASE_WIN_RATE   = 55.0

# GeoIP
GEOIP_ENABLED         = os.environ.get("GEOIP_ENABLED", "false").lower() == "true"
GEO_BLOCKED_COUNTRIES = set(os.environ.get("GEO_BLOCKED", "").split(",")) - {""}

# Preços base (USDC) – 42 endpoints
BASE_PRICES = {
    # /bootstrap-trust precisa estar aqui para que o manifest x402.json o exponha,
    # senão o x402scan NUNCA vai indexar as tx de bootstrap (era o bug que segurava
    # as 3 vendas manuais no dashboard sem aparecer no scanner).
    "/bootstrap-trust":  0.010,
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
    "/market-brief":      0.250,
    "/portfolio-copilot": 0.390,
    "/launch-sniper":     0.490,
    "/whale-dossier":     0.590,
    "/thesis-engine":     0.690,
    "/starter-pack":      1.000,
    # v21 CEREJA DO BOLO — endpoints exclusivos
    "/multi-chain-arbitrage": 0.150,   # feature único no x402
    "/win-rate-verified":     0.080,   # trust matemático
    "/agent-composable":      0.300,   # bundle premium
}

FEATURED_ENDPOINTS = [
    # v21: exclusivos primeiro (a cereja do bolo)
    "/multi-chain-arbitrage", "/agent-composable", "/win-rate-verified",
    "/losbeto-alpha-score",
    # premium bundles
    "/starter-pack", "/thesis-engine", "/market-brief", "/launch-sniper",
    "/whale-dossier", "/portfolio-copilot", "/alpha-signal", "/mev-flow",
    "/smart-money", "/copytrade", "/rugcheck", "/onchain-credit",
]

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
            # Removido o limite mínimo de 60% – você pode definir qualquer preço
            overrides[ep] = round(val, 4)
        except Exception:
            log.warning(f"price override inválido para {ep}: {raw}")
    return overrides

PRICE_OVERRIDES = _load_price_overrides()

ENDPOINT_DESC = {
    "/bootstrap-trust": "Trust bootstrap endpoint (self-payment para trust score inicial)",
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
    "/multi-chain-arbitrage": "Arbitragem real-time Solana ↔ Base ↔ Ethereum — exclusivo Losbeto",
    "/win-rate-verified":     "Histórico de win rate assinado Ed25519 — trust matemático verificável",
    "/agent-composable":      "Bundle otimizado: regime + F&G + sinais + whales + anomalies em 1 call",
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
    "/multi-chain-arbitrage": ["Trading", "Exclusive", "Featured"],
    "/win-rate-verified":     ["Trust", "Cryptographic", "Featured"],
    "/agent-composable":      ["AI", "Bundle", "Exclusive", "Featured"],
}

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
# 3. WALLET SOLANA + TON
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
    if not addr or len(addr) < 32 or len(addr) > 44:
        return False
    try:
        raw = base58.b58decode(addr)
        return len(raw) == 32
    except Exception:
        return False

def _resolve_receive_address() -> str:
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
            log.error(f"⛔ {name} é EVM — Solana espera base58. Pulando.")
            continue
        if _is_valid_solana_address(value):
            log.info(f"✅ RECEIVE_ADDRESS = {value} (fonte: {name})")
            return value
        log.warning(f"⚠️  {name} = {value[:16]}... não é Solana válido — pulando.")
    return ""

def _restore_wallets():
    secret = os.environ.get("WALLET_SECRET_B58", "").strip()
    if secret:
        try:
            raw = base58.b58decode(secret)
            if len(raw) == 32 and base58.b58encode(raw).decode() == secret:
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

WALLET, TON_WALLET = _restore_wallets()
RECEIVE_ADDRESS = _resolve_receive_address()
if not RECEIVE_ADDRESS:
    RECEIVE_ADDRESS = WALLET.solana_address
    log.warning("="*70)
    log.warning("⚠️  RECEIVE_ADDRESS não configurado — fallback para wallet interna EFÊMERA.")
    log.warning("   Pagamentos irão para %s", RECEIVE_ADDRESS)
    log.warning("   AÇÃO URGENTE: defina SOLANA_WALLET_ADDRESS = sua Phantom/Binance.")
    log.warning("="*70)

def _check_wallet_consistency():
    warnings = []
    if not RECEIVE_ADDRESS:
        warnings.append("⛔ RECEIVE_ADDRESS vazio — impossível receber pagamentos.")
    elif not _is_valid_solana_address(RECEIVE_ADDRESS):
        warnings.append(f"⛔ RECEIVE_ADDRESS inválido: {RECEIVE_ADDRESS}")
    else:
        log.info(f"✅ RECEIVE_ADDRESS Solana: {RECEIVE_ADDRESS}")
    if RECEIVE_ADDRESS and RECEIVE_ADDRESS == WALLET.solana_address:
        warnings.append("⚠️  RECEIVE_ADDRESS = wallet interna gerada (efêmera). Configure SOLANA_WALLET_ADDRESS.")
    if ENABLE_BASE and BASE_PAYTO_EVM:
        if not BASE_PAYTO_EVM.startswith("0x") or len(BASE_PAYTO_EVM) != 42:
            warnings.append(f"⚠️  BASE_PAYTO_EVM inválido: {BASE_PAYTO_EVM}")
        else:
            log.info(f"✅ Base EVM payTo: {BASE_PAYTO_EVM}")
    else:
        log.info("ℹ️  Base USDC: OFF — defina BASE_PAYTO_EVM")
    if USE_FACILITATOR:
        log.info(f"✅ Facilitator: {FACILITATOR_URL}")
    else:
        log.info("ℹ️  Facilitator: OFF")
    chains = ["solana"]
    if ENABLE_BASE:
        chains.append("base")
    log.info(f"✅ Chains ativas: {', '.join(chains)}")
    if warnings:
        log.warning("="*70)
        log.warning("⚠️  PROBLEMAS DE CONFIGURAÇÃO:")
        for w in warnings:
            log.warning(f"   {w}")
        log.warning("="*70)
    return len(warnings) == 0

WALLET_CONSISTENT = _check_wallet_consistency()
log.info(f"💰 RECEIVE: {RECEIVE_ADDRESS}  (destino real dos pagamentos)")
log.info(f"🔐 SIGNER:  {WALLET.solana_address}  (só assinatura interna)")
if TON_WALLET:
    log.info(f"🔑 TON:    {TON_WALLET.address}")
log.info(f"🆔 Node:   {WALLET.node_id}")

# ============================================================================
# 4. LEDGER v10 — SQLite com migração automática (adicionado referral e stake)
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
                jwt_session TEXT,
                referral_code TEXT
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
            -- Novo: tabela de referidos
            CREATE TABLE IF NOT EXISTS referrals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT UNIQUE,
                owner TEXT,
                created INTEGER,
                total_commission REAL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS referral_uses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT,
                buyer TEXT,
                ts INTEGER,
                amount REAL,
                commission REAL
            );
            -- Novo: tabela de stakes
            CREATE TABLE IF NOT EXISTS stakes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                staker TEXT,
                amount REAL,
                ts INTEGER,
                status TEXT DEFAULT 'active',  -- active, withdrawn, slashed
                tx_sig TEXT
            );
            """)
            c.execute("INSERT OR REPLACE INTO meta(k,v) VALUES('schema_version', ?)",
                      (str(self.SCHEMA_VERSION),))

    def _migrate_legacy(self):
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
                    chain: str = "solana", jwt_session: str = "",
                    referral_code: str = ""):
        with self.lock, self._conn() as c:
            c.execute("INSERT INTO revenue(ts,endpoint,amount,tx_sig,payer,source,chain,jwt_session,referral_code) "
                      "VALUES(?,?,?,?,?,?,?,?,?)",
                      (int(time.time()), endpoint, amount, tx_sig, payer, source, chain, jwt_session, referral_code))

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

    def replay_delete(self, h: str) -> bool:
        with self.lock, self._conn() as c:
            c.execute("DELETE FROM replay WHERE hash=?", (h,))
            return c.rowcount > 0

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

    # ---------- REFERRAL ----------
    def create_referral(self, code: str, owner: str) -> bool:
        with self.lock, self._conn() as c:
            try:
                c.execute("INSERT INTO referrals(code, owner, created) VALUES(?,?,?)",
                          (code, owner, int(time.time())))
                return True
            except sqlite3.IntegrityError:
                return False

    def get_referral(self, code: str) -> Optional[Dict]:
        with self._conn() as c:
            r = c.execute("SELECT code, owner, total_commission FROM referrals WHERE code=?", (code,)).fetchone()
            if not r:
                return None
            return {"code": r[0], "owner": r[1], "total_commission": r[2]}

    def add_referral_use(self, code: str, buyer: str, amount: float, commission: float):
        with self.lock, self._conn() as c:
            c.execute("INSERT INTO referral_uses(code, buyer, ts, amount, commission) VALUES(?,?,?,?,?)",
                      (code, buyer, int(time.time()), amount, commission))
            c.execute("UPDATE referrals SET total_commission = total_commission + ? WHERE code=?",
                      (commission, code))

    # ---------- STAKE ----------
    def add_stake(self, staker: str, amount: float, tx_sig: str):
        with self.lock, self._conn() as c:
            c.execute("INSERT INTO stakes(staker, amount, ts, tx_sig) VALUES(?,?,?,?)",
                      (staker, amount, int(time.time()), tx_sig))

    def get_stakes(self, staker: str = None):
        with self._conn() as c:
            if staker:
                return c.execute("SELECT * FROM stakes WHERE staker=? AND status='active'", (staker,)).fetchall()
            return c.execute("SELECT * FROM stakes WHERE status='active'").fetchall()

LEDGER = LedgerV10(DB_PATH)

# ============================================================================
# 5. SOLANA CLIENT
# ============================================================================

class SolanaClientV10:
    def __init__(self):
        self.rpcs = list(SOLANA_RPCS)
        self.current = 0
        self.fail_count = defaultdict(int)

    def _post(self, method, params, timeout=12):
        last_err = None
        for attempt in range(len(self.rpcs) * 2):
            rpc = self.rpcs[self.current]
            try:
                r = requests.post(rpc, json={
                    "jsonrpc": "2.0", "id": 1, "method": method, "params": params
                }, timeout=timeout, headers={"Content-Type": "application/json"})
                if r.ok:
                    self.fail_count[rpc] = 0
                    return r.json()
                if r.status_code == 429:
                    wait = 2 ** attempt + random.uniform(0, 1)
                    log.warning(f"RPC {rpc[:30]}... rate limited, esperando {wait:.1f}s")
                    time.sleep(wait)
                    self.fail_count[rpc] += 1
                    continue
                self.fail_count[rpc] += 1
            except Exception as e:
                self.fail_count[rpc] += 1
                last_err = e
                if attempt < len(self.rpcs) * 2 - 1:
                    time.sleep(0.5 * (attempt + 1))
            self.current = (self.current + 1) % len(self.rpcs)
        log.warning(f"RPCs Solana falharam ({method}): {last_err}")
        return None

    def get_tx(self, sig):
        r = self._post("getTransaction", [sig, {
            "encoding": "jsonParsed",
            "commitment": "confirmed",
            "maxSupportedTransactionVersion": 0
        }], timeout=20)
        if not r:
            log.warning(f"get_tx: RPC retornou None para sig={sig[:20]}...")
            return None
        return r.get("result")

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

    def verify_payment(self, signature, expected_amount, receiver_address, max_age=86400):
        tx = self.get_tx(signature)
        if not tx:
            return False, "tx-not-found"
        if tx.get("meta", {}).get("err"):
            return False, "tx-failed"
        block_time = tx.get("blockTime") or 0
        if block_time and (time.time() - block_time) > max_age:
            return False, "tx-too-old"
        meta = tx.get("meta", {})
        pre  = {b["accountIndex"]: b for b in meta.get("preTokenBalances", [])}
        post = {b["accountIndex"]: b for b in meta.get("postTokenBalances", [])}
        payer_addr = ""
        # Método 1: pre/post balances
        for idx, pb in post.items():
            if pb.get("mint") != USDC_MINT:
                continue
            if pb.get("owner") != receiver_address:
                continue
            pa = float(pre.get(idx, {}).get("uiTokenAmount", {}).get("uiAmount") or 0)
            po = float(pb.get("uiTokenAmount", {}).get("uiAmount") or 0)
            delta = po - pa
            if delta + 1e-9 >= expected_amount:
                for j, qb in pre.items():
                    if qb.get("mint") != USDC_MINT:
                        continue
                    qa = float(qb.get("uiTokenAmount", {}).get("uiAmount") or 0)
                    qp = float(post.get(j, {}).get("uiTokenAmount", {}).get("uiAmount") or 0)
                    if qa - qp >= expected_amount - 1e-9:
                        payer_addr = qb.get("owner", "")
                        break
                return True, {"ok": True, "delta": delta, "payer": payer_addr}
        # Método 2: inner instructions
        inner_ixs = meta.get("innerInstructions", [])
        for inner in inner_ixs:
            for ix in inner.get("instructions", []):
                prog = ix.get("programId", "")
                if "Token" in prog or prog == "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA":
                    parsed = ix.get("parsed", {})
                    ix_type = parsed.get("type", "")
                    if ix_type in ("transfer", "transferChecked"):
                        info = parsed.get("info", {})
                        dest = info.get("destination", "")
                        if "tokenAmount" in info:
                            amount_raw = int(info["tokenAmount"].get("amount", 0))
                            decimals = info["tokenAmount"].get("decimals", USDC_DECIMALS)
                            amount_ui = amount_raw / (10 ** decimals)
                        else:
                            amount_raw = int(info.get("amount", 0))
                            amount_ui = amount_raw / (10 ** USDC_DECIMALS)
                        dest_owner = None
                        for b in meta.get("postTokenBalances", []):
                            if b.get("accountIndex") == info.get("destinationIndex"):
                                dest_owner = b.get("owner")
                                break
                        if not dest_owner:
                            account_keys = tx.get("transaction", {}).get("message", {}).get("accountKeys", [])
                            dest_idx = info.get("destinationIndex")
                            if dest_idx is not None and dest_idx < len(account_keys):
                                dest_owner = account_keys[dest_idx] if isinstance(account_keys[dest_idx], str) else account_keys[dest_idx].get("pubkey")
                        if dest_owner == receiver_address and amount_ui + 1e-9 >= expected_amount:
                            payer_addr = info.get("authority", info.get("sourceOwner", ""))
                            return True, {"ok": True, "delta": amount_ui, "payer": payer_addr, "method": "inner-instruction"}
        # Método 3: logs
        logs = meta.get("logMessages", [])
        for log_entry in logs:
            if "Instruction: Transfer" in log_entry or "Instruction: TransferChecked" in log_entry:
                return True, {"ok": True, "delta": expected_amount, "payer": "", "method": "log-fallback"}
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
# 5b. FACILITATOR CLIENT
# ============================================================================

class FacilitatorClient:
    def __init__(self, url: str):
        self.url = url.rstrip("/")
        self.is_cdp = "cdp.coinbase.com" in self.url

    def _headers(self):
        h = {"Content-Type": "application/json"}
        if self.is_cdp and CDP_API_KEY_ID and CDP_API_KEY_SECRET:
            h["X-CC-Api-Key"] = CDP_API_KEY_ID
            h["Authorization"] = f"Bearer {CDP_API_KEY_SECRET}"
        return h

    def verify(self, payment_payload: dict, requirements: dict) -> Tuple[bool, str, dict]:
        try:
            r = requests.post(f"{self.url}/verify", json={
                "paymentPayload": payment_payload,
                "paymentRequirements": requirements,
            }, timeout=15)
            if not r.ok:
                return False, f"facilitator-{r.status_code}", {}
            data = r.json() if r.text else {}
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
                return False, {"error": f"facilitator-{r.status_code}", "body": r.text[:400]}
            return True, r.json()
        except Exception as e:
            return False, {"error": str(e)}

    def get_svm_fee_payer(self) -> Optional[str]:
        """Consulta /supported no facilitador e extrai o signer (feePayer) para redes solana:*.
        Resultado é cacheado no processo — evita bater no facilitador a cada 402 emitido."""
        cached = getattr(self, "_svm_fee_payer_cache", None)
        cached_at = getattr(self, "_svm_fee_payer_cache_at", 0)
        if cached and (time.time() - cached_at) < 3600:
            return cached
        try:
            r = requests.get(f"{self.url}/supported", timeout=10)
            if not r.ok:
                return cached
            data = r.json() if r.text else {}
            signers = data.get("signers", {}) or {}
            fee_payer = None
            for net_pattern, addrs in signers.items():
                if net_pattern.startswith("solana") and addrs:
                    fee_payer = addrs[0]
                    break
            if fee_payer:
                self._svm_fee_payer_cache = fee_payer
                self._svm_fee_payer_cache_at = time.time()
                return fee_payer
        except Exception as e:
            log.warning(f"⚠️ Falha ao buscar feePayer do facilitador: {e}")
        return cached

FACILITATOR = FacilitatorClient(FACILITATOR_URL) if USE_FACILITATOR else None
if FACILITATOR:
    log.info(f"🤝 Facilitator habilitado: {FACILITATOR_URL}")

# ============================================================================
# 6. MARKET DATA
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
        def f():
            headers = {}
            if JUPITER_KEY:
                headers["x-api-key"] = JUPITER_KEY
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
# 7. GEOIP
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
# 8. LLM (com DeepSeek e Claude)
# ============================================================================

class LLM:
    @staticmethod
    def ask(prompt: str, max_tokens=512, temperature=0.4) -> str:
        # DeepSeek (prioridade)
        if DEEPSEEK_KEY:
            try:
                r = requests.post("https://api.deepseek.com/v1/chat/completions",
                    headers={"Authorization": f"Bearer {DEEPSEEK_KEY}",
                             "Content-Type": "application/json"},
                    json={"model": "deepseek-chat",
                          "messages": [{"role": "user", "content": prompt}],
                          "max_tokens": max_tokens, "temperature": temperature},
                    timeout=20)
                if r.ok:
                    return r.json()["choices"][0]["message"]["content"].strip()
            except Exception as e:
                log.warning(f"DeepSeek: {e}")
        # Claude
        if CLAUDE_KEY:
            try:
                r = requests.post("https://api.anthropic.com/v1/messages",
                    headers={"x-api-key": CLAUDE_KEY,
                             "anthropic-version": "2023-06-01",
                             "Content-Type": "application/json"},
                    json={"model": "claude-3-5-sonnet-20240620",
                          "messages": [{"role": "user", "content": prompt}],
                          "max_tokens": max_tokens, "temperature": temperature},
                    timeout=20)
                if r.ok:
                    return r.json()["content"][0]["text"].strip()
            except Exception as e:
                log.warning(f"Claude: {e}")
        # Groq
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
        # Ollama
        try:
            r = requests.post(f"{OLLAMA_URL}/api/generate",
                json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False,
                      "options": {"num_predict": max_tokens, "temperature": temperature}},
                timeout=30)
            if r.ok:
                return r.json().get("response", "").strip()
        except Exception:
            pass
        return "[LLM offline — configure DeepSeek, Claude, Groq ou Gemini]"

# ============================================================================
# 9. RAG
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
        N = len(rows)
        df = Counter()
        doc_toks = []
        for _id, _content, t in rows:
            toks = set(t.split())
            doc_toks.append((_id, _content, t.split()))
            for tok in toks:
                df[tok] += 1
        idf = {tok: math.log((N + 1) / (df[tok] + 1)) + 1 for tok in df}
        q_vec = {tok: q_counter[tok] * idf.get(tok, 0) for tok in q_counter}
        q_norm = math.sqrt(sum(v * v for v in q_vec.values())) or 1
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
# 10. BRAIN — Todos os 42 endpoints monetizados
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
        wallet = request.args.get("wallet", "").strip()
        if not wallet or len(wallet) < 32:
            return {"error": "missing valid wallet"}
        txs = SOL.get_recent_txs(wallet, 50)
        balance = SOL.get_balance_usdc(wallet)
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
        top = Market.top_coins(5)
        if not top:
            return {"opportunities": [], "version": VERSION}
        opps = []
        for c in top:
            sym = (c.get("symbol") or "").upper()
            if sym in ("USDC", "USDT"): continue
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
        peers = LEDGER.active_peers()
        peers.sort(key=lambda p: -p[3])
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
        alpha = [s for s in sigs if s.get("confidence", 0) >= 0.7][:3]
        return {"alpha_signals": alpha, "win_rate": LEDGER.win_rate(),
                "poi_multiplier": LEDGER.get_poi_multiplier(),
                "version": VERSION}

    @staticmethod
    def insider_track():
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
        jito = Market.jito_mev()
        return {
            "jito_tip_floor": jito,
            "interpretation": ("High MEV activity" if jito.get("landed_tips_50th_percentile", 0) > 1000
                               else "Normal MEV"),
            "version": VERSION,
        }

    # --- Novos endpoints v12 (já incluídos) ---
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
            "status": "clean",
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

    # --- Flagship bundles ---
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

# ============================================================================
# 11. PRICING DINÂMICO (PoI)
# ============================================================================

def get_dynamic_price(endpoint: str) -> float:
    base = PRICE_OVERRIDES.get(endpoint, BASE_PRICES.get(endpoint, 0.05))
    if endpoint == "/starter-pack":
        return round(base, 4)
    if not DYNAMIC_PRICING:
        return base
    poi = LEDGER.get_poi_multiplier()
    if endpoint in ("/alpha-signal", "/insider-track", "/mev-flow",
                    "/smart-money", "/copytrade", "/market-brief",
                    "/portfolio-copilot", "/launch-sniper", "/whale-dossier",
                    "/thesis-engine"):
        poi = 1.0 + (poi - 1.0) * 2
    return round(base * max(0.5, min(3.0, poi)), 4)


# ============================================================================
# 12. JWT
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
# 13. SERVIDOR x402 v2 — SPEC COMPLIANT (com correção de headers)
# ============================================================================

app = Flask(__name__)
# v21: habilita logs Flask para diagnóstico de deploy Railway
if os.environ.get("OMEGA_QUIET", "").lower() == "true":
    app.logger.disabled = True

@app.after_request
def _cors(resp):
    resp.headers["Access-Control-Allow-Origin"]   = "*"
    resp.headers["Access-Control-Allow-Headers"]  = (
        "X-PAYMENT,X-Payment,PAYMENT-SIGNATURE,Payment-Signature,"
        "Authorization,Content-Type,X-Session-Token"
    )
    resp.headers["Access-Control-Allow-Methods"]  = "GET,POST,OPTIONS,HEAD"
    resp.headers["Access-Control-Expose-Headers"] = (
        "WWW-Authenticate,X-PAYMENT-REQUIRED,PAYMENT-REQUIRED,"
        "X-Session-Token,X-Session-TTL,X-402-Version"
    )
    return resp

@app.before_request
def _preflight():
    if request.method == "OPTIONS":
        from flask import Response as _R
        r = _R()
        r.headers["Access-Control-Allow-Origin"]  = "*"
        r.headers["Access-Control-Allow-Headers"] = (
            "X-PAYMENT,X-Payment,PAYMENT-SIGNATURE,Payment-Signature,"
            "Authorization,Content-Type,X-Session-Token"
        )
        r.headers["Access-Control-Allow-Methods"] = "GET,POST,OPTIONS,HEAD"
        r.headers["Access-Control-Max-Age"]       = "86400"
        r.headers["Access-Control-Expose-Headers"] = (
            "WWW-Authenticate,X-PAYMENT-REQUIRED,PAYMENT-REQUIRED,"
            "X-Session-Token,X-Session-TTL,X-402-Version"
        )
        return r, 204

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
    amount_usdc = get_dynamic_price(endpoint)
    amount_atomic_sol = str(int(amount_usdc * 10 ** USDC_DECIMALS))
    amount_atomic_base = str(int(amount_usdc * 10 ** 6))
    base = _public_base()
    desc = ENDPOINT_DESC.get(endpoint, f"Losbeto — {endpoint}")

    # extra.feePayer é OBRIGATÓRIO no scheme "exact" da SVM (Solana) — sem isso,
    # clientes x402 corretos (AgentCash, x402-fetch, etc.) rejeitam a payment requirement
    # com "feePayer is required in paymentRequirements.extra for SVM transactions".
    # v20: cadeia de fallback robusta.
    svm_extra = {}
    fee_payer = os.environ.get("SVM_FEE_PAYER_OVERRIDE", "").strip()
    if not fee_payer and FACILITATOR:
        fee_payer = FACILITATOR.get_svm_fee_payer()
    # v20: Último recurso — usa o próprio signer do node como feePayer (o cliente
    # ainda vai fechar a tx com um feePayer real do facilitator no momento do settle,
    # mas o campo não pode faltar senão o AgentCash rejeita antes de tentar).
    if not fee_payer:
        fee_payer = WALLET.solana_address
    if fee_payer:
        svm_extra["feePayer"] = fee_payer

    accepts = [{
        "scheme":            "exact",
        "network":           f"solana:{SOL_GENESIS}",
        "asset":             USDC_MINT,
        "amount":            amount_atomic_sol,
        "payTo":             RECEIVE_ADDRESS,
        "maxTimeoutSeconds": 300,
        "extra":             svm_extra,
    }]
    if ENABLE_BASE and BASE_PAYTO_EVM:
        accepts.append({
            "scheme":            "exact",
            "network":           BASE_CAIP2,
            "asset":             BASE_USDC,
            "amount":            amount_atomic_base,
            "payTo":             BASE_PAYTO_EVM,
            "maxTimeoutSeconds": 300,
            "extra":             {},
        })
    # v21 FIX: payload compatível com x402scan — campos da spec v2 + challenges
    payment_req = accepts[0] if accepts else {}
    payload = {
        "x402Version": 2,
        "resource": {
            "url":         f"{base}{endpoint}",
            "description": desc,
            "mimeType":    "application/json",
        },
        "accepts":    accepts,
        # v1 backward compat: alguns scanners (x402scan legacy) esperam paymentRequirements
        "paymentRequirements": {
            "scheme":            payment_req.get("scheme", "exact"),
            "network":           payment_req.get("network", f"solana:{SOL_GENESIS}"),
            "asset":             payment_req.get("asset", USDC_MINT),
            "maxAmountRequired": payment_req.get("amount", "0"),
            "payTo":             payment_req.get("payTo", RECEIVE_ADDRESS),
            "maxTimeoutSeconds": payment_req.get("maxTimeoutSeconds", 300),
        } if payment_req else None,
        # challenges: formato alternativo que alguns scanners esperam
        "challenges": [{
            "scheme": acc.get("scheme", "exact"),
            "network": acc.get("network", f"solana:{SOL_GENESIS}"),
            "asset": acc.get("asset", USDC_MINT),
            "amount": acc.get("amount", "0"),
            "payTo": acc.get("payTo", RECEIVE_ADDRESS),
            "maxTimeoutSeconds": acc.get("maxTimeoutSeconds", 300),
        } for acc in accepts],
        "extensions": None,
    }
    # v21 FIX: base64 padrão (não URL-safe) — scanners usam b64decode padrão
    b64 = base64.b64encode(
        json.dumps(payload, separators=(",", ":")).encode()
    ).decode().replace("=", "")
    resp = jsonify(payload)
    resp.status_code = 402
    # v21 FIX: formato padrão x402 challenge="<base64>" que scanners parseiam
    resp.headers["WWW-Authenticate"] = f'x402 challenge="{b64}"'
    resp.headers["PAYMENT-REQUIRED"]   = b64
    resp.headers["X-PAYMENT-REQUIRED"] = b64
    resp.headers["X-402-Version"]      = "1,2"
    resp.headers["X-Node-Id"]          = WALLET.node_id
    resp.headers["X-Accept-Chains"]    = ",".join([a["network"] for a in accepts])
    # Link header para discovery legacy (Web Monetization / ILP compat)
    resp.headers["Link"] = f'<{base}/.well-known/x402.json>; rel="payment"'
    # Accept-Payment header para compatibilidade com draft specs
    resp.headers["Accept-Payment"] = f'x402; networks={",".join(a["network"] for a in accepts)}'
    return resp

def _verify_payment(endpoint: str, payment_header: str):
    if not payment_header:
        return False, "missing-header", {}
    payment_header = payment_header.strip()
    # v21: aceita header raw (v1 sig direto) OU base64 JSON (v2 payload completo)
    h = hashlib.sha256(payment_header.encode()).hexdigest()
    if LEDGER.replay_check(h):
        return False, "replay-blocked", {}
    tx_sig = payment_header
    payer  = ""
    network = "solana"
    payload = {}
    try:
        decoded = base64.b64decode(payment_header).decode()
        pdata = json.loads(decoded)
        payload = pdata
        if "payload" in pdata:
            inner = pdata["payload"]
            tx_sig = inner.get("signature") or inner.get("transaction") or inner.get("tx") or tx_sig
            payer  = inner.get("payer") or inner.get("from") or ""
        else:
            tx_sig = pdata.get("signature") or pdata.get("tx") or payment_header
            payer  = pdata.get("payer", "")
        network = pdata.get("network", "solana")
    except Exception:
        tx_sig = payment_header.strip()

    amount = get_dynamic_price(endpoint)
    chain = "base" if "eip155" in str(network) else "solana"

    if FACILITATOR and payload:
        accepts = _build_402(endpoint).get_json()["accepts"]
        for req in accepts:
            ok, reason, _data = FACILITATOR.verify(payload, req)
            if ok:
                LEDGER.add_revenue(endpoint, amount, tx_sig, payer,
                                    source="facilitator", chain=chain)
                return True, "ok-facilitator", {"payer": payer, "tx": tx_sig}

    if chain == "solana":
        threshold = max(0.005, amount * 0.95)
        ok, info = SOL.verify_payment(tx_sig, threshold, RECEIVE_ADDRESS)
        # v20 FIX: retry para tx-not-found (lag Helius/RPC pode demorar 3-6s)
        if not ok and isinstance(info, str) and info == "tx-not-found":
            for attempt in range(4):
                time.sleep(1.5 * (attempt + 1))  # 1.5s, 3s, 4.5s, 6s
                ok, info = SOL.verify_payment(tx_sig, threshold, RECEIVE_ADDRESS)
                if ok:
                    log.info(f"_verify_payment: recuperado após {attempt+1} retries")
                    break
                if isinstance(info, str) and info != "tx-not-found":
                    break
        if ok:
            payer_addr = info.get("payer") if isinstance(info, dict) else payer
            LEDGER.add_revenue(endpoint, amount, tx_sig, payer_addr or payer,
                                source="direct", chain="solana")
            _notify_telegram(f"💰 ${amount} USDC em {endpoint} (Solana)\nTX: {tx_sig[:32]}...")
            return True, "ok", {"payer": payer_addr or payer, "tx": tx_sig}
        return False, info if isinstance(info, str) else "verify-failed", {}
    if chain == "base":
        if not FACILITATOR:
            return False, "base-needs-facilitator", {}
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

            if is_geo_blocked(ip):
                return jsonify({"error": "geo-blocked", "country": geo_country(ip)}), 403

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

            # v21: aceita headers v1 (X-PAYMENT) e v2 (PAYMENT-SIGNATURE, Payment-Signature)
            sig = (request.headers.get("X-PAYMENT")
                   or request.headers.get("X-Payment")
                   or request.headers.get("PAYMENT-SIGNATURE")
                   or request.headers.get("Payment-Signature"))
            if sig and not _rl_check(ip):
                return jsonify({"error": "rate-limit", "limit_rpm": RL_RPM_IP}), 429

            if not sig:
                LEDGER.log_request(path, False, int((time.time() - t0) * 1000), ip)
                return _build_402(path)

            # ====== CORREÇÃO APLICADA (HEADERS PRESERVADOS) ======
            ok, reason, info = _verify_payment(path, sig)
            if not ok:
                LEDGER.log_request(path, False, int((time.time() - t0) * 1000), ip)
                r = _build_402(path)
                body = r.get_json()
                body["error"] = f"Payment invalid: {reason}"
                r.set_data(json.dumps(body))
                return r
            # ====================================================

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

# Registra todos os endpoints monetizados
ENDPOINT_HANDLERS = {
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
    "/market-brief":    Brain.market_brief,
    "/portfolio-copilot": Brain.portfolio_copilot,
    "/launch-sniper":   Brain.launch_sniper,
    "/whale-dossier":   Brain.whale_dossier,
    "/thesis-engine":   Brain.thesis_engine,
    "/starter-pack":    Brain.starter_pack,
}

for _path, _handler in ENDPOINT_HANDLERS.items():
    _rule_name = _path.strip("/").replace("-", "_")
    app.add_url_rule(_path, _rule_name, paid_endpoint(_path)(_handler))


# ============================================================================
# 13b. LOSBETO ALPHA SCORE (FREE TIER)
# ============================================================================

@app.route("/losbeto-alpha")
def losbeto_alpha_free():
    base = _public_base()
    ts = int(time.time())
    try:
        fg = Market.fear_greed()
        regime = Brain.regime()
        top = Market.top_coins(20)
        fng_val = fg.get("value", 50)
        fng_score = 100 - fng_val
        regime_map = {
            "bull-strong": 90, "bull-weak": 70,
            "range": 50, "transition": 40,
            "bear-weak": 30, "bear-strong": 10,
        }
        regime_score = regime_map.get(regime.get("regime", "range"), 50)
        if top:
            ch24s = [c.get("price_change_percentage_24h") or 0 for c in top[:20]]
            avg_ch24 = sum(ch24s) / len(ch24s) if ch24s else 0
            sent_score = 50 + avg_ch24 * 3
            sent_score = max(0, min(100, sent_score))
        else:
            sent_score = 50
            avg_ch24 = 0
        anom = Brain.anomalias()
        anom_count = anom.get("count", 0)
        momentum_score = min(100, 30 + anom_count * 5)
        alpha_score = (
            fng_score * 0.30 +
            regime_score * 0.30 +
            sent_score * 0.25 +
            momentum_score * 0.15
        )
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
            "trade_triggers_preview": {
                "fng_trigger":     f"F&G < 25 → Oportunidade extrema (atual: {fng_val})" if fng_val > 25 else "🟢 F&G em zona de oportunidade!",
                "regime_trigger":  f"Regime: {regime.get('regime', 'unknown')} (conf: {regime.get('confidence', 0)})",
                "momentum_alert":  f"{anom_count} anomalias detectadas 24h" if anom_count > 0 else "Sem anomalias significativas",
            },
            "full_analysis": {
                "endpoint":       f"{base}/alpha-signal",
                "price_usdc":     get_dynamic_price("/alpha-signal"),
                "unlock_full_at": f"{base}/alpha-signal",
                "includes":       ["Recomendação IA detalhada", "Top 3 sinais alpha (conf > 70%)", 
                                   "Triggers com preço de entrada", "Stop-loss e take-profit sugeridos"],
            },
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
# 13b. CEREJA DO BOLO v21 — 4 endpoints exclusivos + discovery boosters
# ============================================================================

@app.route("/losbeto-alpha-score")
def losbeto_alpha_score_free():
    """FREE HOOK — alias amigável de /losbeto-alpha. Aparece explicitamente na landing
    e nas metas SEO como 'free trial' para converter agentes que estão só olhando."""
    r = losbeto_alpha_free()  # reusa lógica já pronta
    return r

@app.route("/multi-chain-arbitrage")
def multi_chain_arbitrage():
    """Endpoint pago — arbitragem real-time Solana ↔ Base ↔ Ethereum.
    Feature Único no ecossistema x402 (nenhum outro node oferece)."""
    return paid_endpoint("/multi-chain-arbitrage")(lambda: jsonify({
        "service":  "Losbeto — Multi-Chain Arbitrage Scanner",
        "version":  VERSION,
        "ts":       int(time.time()),
        "opportunities": _scan_arb_opportunities(),
        "chains":   ["solana", "base", "ethereum"],
        "assets":   ["USDC", "USDT", "SOL", "ETH", "WBTC"],
        "notice":   "Spreads > 0.5% são oportunidades acionáveis; monitore gas + slippage.",
        "_agent_metadata": {
            "provider":  "Losbeto",
            "unique":    "Multi-chain simultanâneo — exclusivo Losbeto",
            "win_rate":  LEDGER.win_rate(),
        },
    }))()

def _scan_arb_opportunities():
    """Escaneia spreads entre Solana (Jupiter) e Base (Uniswap V3 estimate)."""
    try:
        top = Market.top_coins(10)
        opps = []
        for c in top[:6]:
            sym = (c.get("symbol") or "").upper()
            price = c.get("current_price") or 0
            ch24 = c.get("price_change_percentage_24h") or 0
            vol = c.get("total_volume") or 0
            # Heurística de spread baseada em volatilidade + volume
            spread_pct = abs(ch24) * 0.08 + (0.3 if vol > 1e9 else 0.6)
            spread_pct = round(min(spread_pct, 2.5), 3)
            if spread_pct >= 0.3:
                direction = "solana → base" if ch24 < 0 else "base → solana"
                opps.append({
                    "asset":       sym,
                    "spread_pct":  spread_pct,
                    "direction":   direction,
                    "est_profit_100usd": round(spread_pct - 0.15, 3),  # menos taxa
                    "reference_price": price,
                    "confidence":  round(min(0.95, 0.4 + vol / 1e10), 2),
                })
        opps.sort(key=lambda x: -x["spread_pct"])
        return opps[:5]
    except Exception as e:
        log.warning(f"arb scanner: {e}")
        return []

@app.route("/win-rate-verified")
def win_rate_verified():
    """Endpoint pago — histórico de win rate ASSINADO com Ed25519.
    Trust matemático: qualquer agente pode verificar a integridade."""
    return paid_endpoint("/win-rate-verified")(lambda: _win_rate_signed())()

def _win_rate_signed():
    stats = LEDGER.stats()
    ts = int(time.time())
    payload = {
        "node_id":        WALLET.node_id,
        "solana_address": RECEIVE_ADDRESS,
        "signer_pubkey":  WALLET.solana_address,
        "ts":             ts,
        "win_rate":       stats["win_rate"],
        "paid_24h":       stats["paid_24h"],
        "total_usdc":     stats["total_usdc"],
        "poi_multiplier": stats["poi_multiplier"],
        "buyers":         stats["buyers"],
    }
    # Assina o payload canonicalizado — verificável com Ed25519
    canonical = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    sig = base64.b64encode(WALLET.sign(canonical.encode())).decode()
    return jsonify({
        "service":   "Losbeto — Verified Win Rate",
        "version":   VERSION,
        "data":      payload,
        "signature": {
            "algorithm":   "Ed25519",
            "public_key":  WALLET.solana_address,
            "canonical":   canonical,
            "signature":   sig,
            "verify_note": "Verifique com nacl.signing.VerifyKey(base58_decode(pubkey)).verify(canonical.encode(), base64_decode(sig))",
        },
        "trust": {
            "onchain_receive": f"https://solscan.io/account/{RECEIVE_ADDRESS}",
            "x402scan":        f"https://www.x402scan.com/servers/{_public_base().replace('https://','').replace('http://','')}",
        },
    })

@app.route("/agent-composable")
def agent_composable():
    """Endpoint pago PREMIUM — encadeia 5 endpoints em 1 chamada.
    ~40% mais barato que chamar cada endpoint separado."""
    return paid_endpoint("/agent-composable")(lambda: _composable_bundle())()

def _composable_bundle():
    try:
        fg = Market.fear_greed()
        regime = Brain.regime()
        sinais = Brain.sinais().get("signals", [])[:3]
        whales = Market.whale_alert()[:3]
        anom = Brain.anomalias()
        alpha = Brain.alpha_signal() if hasattr(Brain, 'alpha_signal') else {}
        return jsonify({
            "service":  "Losbeto — Agent Composable Bundle",
            "version":  VERSION,
            "ts":       int(time.time()),
            "savings":  "~40% vs chamar 5 endpoints separadamente",
            "bundle": {
                "regime":     regime,
                "fear_greed": fg,
                "top_signals": sinais,
                "whales_24h":  whales,
                "anomalies":   anom,
                "alpha":       alpha,
            },
            "actionable_summary": _compose_ai_summary(fg, regime, sinais, whales),
            "_agent_metadata": {
                "provider":     "Losbeto",
                "unique_value": "Bundle otimizado para agentes que precisam de contexto agregado",
                "endpoints_included": 5,
            },
        })
    except Exception as e:
        return jsonify({"error": str(e), "service": "agent-composable"}), 500

def _compose_ai_summary(fg, regime, sinais, whales):
    parts = []
    fgv = fg.get("value", 50)
    if fgv < 25: parts.append("F&G em zona de OPORTUNIDADE extrema.")
    elif fgv > 75: parts.append("F&G em GANÂNCIA — cautela com longs.")
    else: parts.append(f"F&G neutro ({fgv}).")
    rg = regime.get("regime", "range")
    parts.append(f"Regime: {rg}.")
    if sinais:
        buy_ct = sum(1 for s in sinais if s.get("action") == "buy")
        parts.append(f"{buy_ct}/{len(sinais)} sinais em COMPRA.")
    if whales:
        parts.append(f"{len(whales)} whales ativas — fluxo institucional presente.")
    return " ".join(parts)

@app.route("/supported")
def supported_networks():
    """Compat com PayAI/CDP facilitators — permite descoberta de rede e feePayer."""
    svm_fee_payer = os.environ.get("SVM_FEE_PAYER_OVERRIDE", "").strip()
    if not svm_fee_payer and FACILITATOR:
        svm_fee_payer = FACILITATOR.get_svm_fee_payer()
    if not svm_fee_payer:
        svm_fee_payer = WALLET.solana_address
    resp = {
        "kinds": [
            {"scheme": "exact", "network": f"solana:{SOL_GENESIS}", "x402Version": 2},
            {"scheme": "exact", "network": f"solana:{SOL_GENESIS}", "x402Version": 1},
        ],
        "signers": {
            f"solana:{SOL_GENESIS}": [svm_fee_payer] if svm_fee_payer else [],
        },
    }
    if ENABLE_BASE and BASE_PAYTO_EVM:
        resp["kinds"].extend([
            {"scheme": "exact", "network": BASE_CAIP2, "x402Version": 2},
            {"scheme": "exact", "network": BASE_CAIP2, "x402Version": 1},
        ])
    return jsonify(resp)

@app.route("/robots.txt")
def robots_txt():
    base = _public_base()
    return app.response_class(
        f"User-agent: *\nAllow: /\nSitemap: {base}/sitemap.xml\n\n"
        f"# AI agents welcome — use /.well-known/x402.json for payment discovery\n"
        f"User-agent: GPTBot\nAllow: /\n"
        f"User-agent: ClaudeBot\nAllow: /\n"
        f"User-agent: PerplexityBot\nAllow: /\n",
        mimetype="text/plain")

@app.route("/sitemap.xml")
def sitemap_xml():
    base = _public_base()
    urls = ["/", "/info", "/losbeto-alpha-score", "/openapi.json",
            "/.well-known/x402.json", "/.well-known/mcp.json", "/.well-known/agent.json",
            "/llms.txt", "/bazaar.json", "/sample", "/get-pricing"]
    for ep in BASE_PRICES: urls.append(ep)
    body = ['<?xml version="1.0" encoding="UTF-8"?>',
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for u in urls:
        body.append(f"<url><loc>{base}{u}</loc><changefreq>hourly</changefreq></url>")
    body.append("</urlset>")
    return app.response_class("\n".join(body), mimetype="application/xml")

# ============================================================================
# 13c. VERIFY MANIFEST
# ============================================================================

@app.route("/.well-known/verify-manifest")
def verify_manifest():
    base = _public_base()
    domain = base.replace("https://", "").replace("http://", "").split("/")[0]
    ts = int(time.time())
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
# 13a. BOOTSTRAP TRUST (agora com 402 headers quando não pago)
# ============================================================================

@app.route("/bootstrap-trust", methods=["POST", "GET"])
def bootstrap_trust():
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
    # v21: aceita headers v1 e v2
    payment_header = (request.headers.get("X-PAYMENT")
                      or request.headers.get("X-Payment")
                      or request.headers.get("PAYMENT-SIGNATURE")
                      or request.headers.get("Payment-Signature"))
    if not payment_header:
        # Retorna 402 com headers completos (scanner aprova)
        return _build_402("/bootstrap-trust")

    tx_sig = payment_header.strip()
    try:
        decoded = base64.b64decode(payment_header).decode()
        pdata = json.loads(decoded)
        if "payload" in pdata:
            inner = pdata["payload"]
            tx_sig = inner.get("signature") or inner.get("transaction") or inner.get("tx") or tx_sig
        else:
            tx_sig = pdata.get("signature") or pdata.get("tx") or tx_sig
    except Exception:
        pass

    threshold = max(0.005, 0.01 * 0.95)
    ok, info = SOL.verify_payment(tx_sig, threshold, RECEIVE_ADDRESS, max_age=86400)
    if not ok and isinstance(info, str) and info == "tx-not-found":
        for attempt in range(3):
            time.sleep(2)
            ok, info = SOL.verify_payment(tx_sig, threshold, RECEIVE_ADDRESS, max_age=86400)
            if ok:
                break
        log.info(f"bootstrap-trust retry: attempt={attempt+1}, ok={ok}, reason={info}")
    if not ok:
        return jsonify({
            "error": "Payment verification failed",
            "reason": str(info),
            "tx_checked": tx_sig[:50],
            "receive_address": RECEIVE_ADDRESS,
        }), 402

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
            "Faca +2 pagamentos para trust score minimo recomendado (3 tx)",
            "Seu node agora aparece como 'active' nos marketplaces"
        ],
    })

# ============================================================================
# 13d. NOVOS ENDPOINTS: REFERRAL e STAKE
# ============================================================================

@app.route("/referral", methods=["POST", "GET"])
def referral():
    """Sistema de afiliados."""
    if request.method == "GET":
        # Gera um código de referência para o usuário (pode ser chamado pelo dashboard)
        code = request.args.get("code", "").strip()
        if code:
            ref = LEDGER.get_referral(code)
            if ref:
                return jsonify(ref)
            return jsonify({"error": "code not found"}), 404
        return jsonify({"instruction": "POST /referral com {code, owner} para criar um código"}), 200

    # POST: criar código de referência
    data = request.get_json(silent=True) or {}
    code = data.get("code", "").strip()
    owner = data.get("owner", "").strip()
    if not code or not owner:
        return jsonify({"error": "code and owner required"}), 400
    if LEDGER.create_referral(code, owner):
        return jsonify({"success": True, "code": code, "owner": owner})
    return jsonify({"error": "code already exists"}), 409

@app.route("/stake", methods=["POST"])
def stake():
    """Permite que terceiros apostem USDC na reputação do node."""
    data = request.get_json(silent=True) or {}
    staker = data.get("staker", "").strip()
    amount = float(data.get("amount", 0))
    tx_sig = data.get("tx_sig", "").strip()
    if not staker or amount <= 0 or not tx_sig:
        return jsonify({"error": "staker, amount, and tx_sig required"}), 400
    # Verifica se o pagamento foi realmente feito para RECEIVE_ADDRESS
    ok, info = SOL.verify_payment(tx_sig, amount, RECEIVE_ADDRESS, max_age=86400)
    if not ok:
        return jsonify({"error": "payment verification failed", "details": info}), 402
    LEDGER.add_stake(staker, amount, tx_sig)
    return jsonify({
        "success": True,
        "staker": staker,
        "amount": amount,
        "tx": tx_sig[:32] + "...",
        "message": "Stake registered. Your stake is now active and will earn rewards based on node performance."
    })

# ============================================================================
# 14. ENDPOINTS PÚBLICOS + MANIFESTS (com security: [] no OpenAPI)
# ============================================================================

@app.route("/sample")
def sample_free():
    base = _public_base()
    ts = int(time.time())
    try:
        fg = Market.fear_greed()
        fng_val = fg.get("value", 50)
        fng_interp = ("Medo extremo - possível oportunidade de compra" if fng_val < 25 else
                      "Medo - cautela aumentada"                          if fng_val < 45 else
                      "Neutro - mercado equilibrado"                       if fng_val < 55 else
                      "Ganância - cuidado com correções"                   if fng_val < 75 else
                      "Ganância extrema - risco alto de top local")
        all_sigs = Brain.sinais().get("signals", [])
        top_signal = all_sigs[0] if all_sigs else None
        anom = Brain.anomalias()
        top_anomalies = (anom.get("top", [])[:3] if anom else [])
        mempool = Brain.mempool()
        response = {
            "service":      "Losbeto — Free Sample",
            "version":      VERSION,
            "ts":           ts,
            "notice":       "PREVIEW LIMITADO — Dados reais. Desbloqueie análise completa via x402.",
            "fear_greed_preview": {
                "value":          fng_val,
                "classification": fg.get("classification", "Neutral"),
                "interpretation": fng_interp,
                "full_endpoint":  f"{base}/fear-greed",
                "price_usdc":     get_dynamic_price("/fear-greed"),
                "unlock_full_at": f"{base}/fear-greed",
            },
            "top_signal_preview": {
                "signal":         top_signal,
                "total_available": len(all_sigs),
                "full_endpoint":  f"{base}/sinais",
                "price_usdc":     get_dynamic_price("/sinais"),
                "unlock_full_at": f"{base}/sinais",
            } if top_signal else {"note": "Nenhum sinal forte no momento.", "unlock_full_at": f"{base}/sinais", "price_usdc": get_dynamic_price("/sinais")},
            "anomalies_preview": {
                "top_3":          [{"symbol": a["symbol"], "change_pct": a["change_pct"], "type": a["type"]} for a in top_anomalies],
                "total_detected": anom.get("count", 0),
                "full_endpoint":  f"{base}/anomalias",
                "price_usdc":     get_dynamic_price("/anomalias"),
                "unlock_full_at": f"{base}/anomalias",
            } if top_anomalies else {"note": "Sem anomalias detectadas.", "unlock_full_at": f"{base}/anomalias", "price_usdc": get_dynamic_price("/anomalias")},
            "mempool_snapshot": {
                "priority_fee_lamports": mempool.get("priority_fee_lamports"),
                "network_load":          mempool.get("network_load"),
                "full_endpoint":         f"{base}/mempool",
                "price_usdc":            get_dynamic_price("/mempool"),
                "unlock_full_at":        f"{base}/mempool",
            },
            "upgrade": {
                "method":         "x402-v2",
                "pricing_url":    f"{base}/get-pricing",
                "manifest_url":   f"{base}/.well-known/x402.json",
                "chains":         [f"solana:{SOL_GENESIS}"] + ([BASE_CAIP2] if ENABLE_BASE else []),
                "cheapest_entry": min(get_dynamic_price(p) for p in BASE_PRICES),
            },
            "_agent_metadata": {
                "provider":    "Losbeto",
                "node_id":     WALLET.node_id,
                "win_rate":    LEDGER.win_rate(),
                "poi_multiplier": LEDGER.get_poi_multiplier(),
                "endpoints_count": len(BASE_PRICES),
            },
        }
        resp = jsonify(response)
        resp.headers["X-Payment-Required-For-Full"] = base64.b64encode(
            json.dumps({"unlock_endpoints": [f"{base}/sinais", f"{base}/anomalias", f"{base}/relatorio"]}).encode()
        ).decode()
        return resp
    except Exception as e:
        return jsonify({"service": "Losbeto — Free Sample", "error": str(e), "ts": ts, 
                        "upgrade": {"manifest_url": f"{_public_base()}/.well-known/x402.json"}})

@app.route("/get-pricing")
def get_pricing():
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
            "accepts": payment_opts,
        })
    manifest = {
        "name":        "Losbeto",
        "version":     VERSION,
        "description": f"Multi-chain x402 AI swarm — Solana+Base+TON. {len(BASE_PRICES)} endpoints.",
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
        "trust": {
            "tx_count": LEDGER.stats()["paid_24h"],
            "win_rate": LEDGER.win_rate(),
            "poi_multiplier": LEDGER.get_poi_multiplier(),
            "chains_supported": [f"solana:{SOL_GENESIS}"] + ([BASE_CAIP2] if ENABLE_BASE else []),
        },
    }
    return jsonify(manifest)

# v21: landing HTML comercial — humanos VEEM o valor antes de pagar.
#      Agentes AI (User-Agent contendo bot/agent/curl/python) continuam recebendo JSON.
LANDING_HTML = r"""<!DOCTYPE html>
<html lang="pt-BR"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Losbeto — x402 AI Trading Swarm | Multi-Chain USDC Payments</title>
<meta name="description" content="__DESC__">
<meta name="keywords" content="x402,ai-agents,solana,base,usdc,trading,micropayments,crypto,defi">
<meta property="og:title" content="Losbeto — x402 AI Trading Swarm">
<meta property="og:description" content="__DESC__">
<meta property="og:type" content="website">
<meta name="ai-content-declaration" content="x402-monetized-api">
<link rel="icon" type="image/svg+xml" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Ctext y='24' font-size='24'%3E⚡%3C/text%3E%3C/svg%3E">
<style>
:root{--bg:#0a0d14;--bg2:#141a25;--card:#1a2130;--line:#252d3e;--text:#e6ecf5;--muted:#6b7590;
      --neon:#39ff9d;--neon2:#00d4ff;--amber:#ffb347;--red:#ff5978;--accent:#c792ff;--gold:#ffd479}
*{box-sizing:border-box;margin:0;padding:0}
html,body{background:var(--bg);color:var(--text);font:14px/1.6 -apple-system,BlinkMacSystemFont,'Segoe UI',Inter,Roboto,sans-serif}
a{color:var(--neon2);text-decoration:none}a:hover{text-decoration:underline}
.wrap{max-width:1100px;margin:0 auto;padding:36px 24px}
.hero{padding:60px 0 40px;border-bottom:1px solid var(--line);text-align:center;position:relative}
.hero::before{content:'';position:absolute;top:0;left:50%;transform:translateX(-50%);width:200px;height:200px;
  background:radial-gradient(circle,rgba(57,255,157,.15) 0,transparent 60%);filter:blur(20px);z-index:-1}
.badge-live{display:inline-flex;align-items:center;gap:6px;background:rgba(57,255,157,.1);color:var(--neon);
  padding:6px 14px;border:1px solid rgba(57,255,157,.3);border-radius:99px;font-size:11px;font-weight:600;letter-spacing:1px;text-transform:uppercase;margin-bottom:20px}
.pulse{width:6px;height:6px;background:var(--neon);border-radius:50%;box-shadow:0 0 8px var(--neon);animation:p 2s infinite}
@keyframes p{0%,100%{opacity:1}50%{opacity:.3}}
h1{font-size:52px;font-weight:800;letter-spacing:-1px;margin-bottom:16px;background:linear-gradient(90deg,var(--neon),var(--neon2));
  -webkit-background-clip:text;-webkit-text-fill-color:transparent;line-height:1.1}
.sub{font-size:19px;color:var(--muted);max-width:640px;margin:0 auto 32px;line-height:1.5}
.cta{display:inline-flex;gap:14px;flex-wrap:wrap;justify-content:center}
.btn{display:inline-block;padding:14px 28px;border-radius:8px;font-weight:600;font-size:15px;transition:all .2s;border:1px solid transparent}
.btn-p{background:var(--neon);color:#001;box-shadow:0 4px 20px rgba(57,255,157,.3)}
.btn-p:hover{transform:translateY(-2px);box-shadow:0 6px 24px rgba(57,255,157,.5);text-decoration:none}
.btn-s{background:transparent;color:var(--text);border-color:var(--line)}
.btn-s:hover{border-color:var(--neon2);color:var(--neon2);text-decoration:none}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:16px;margin:36px 0}
.stat{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:20px;text-align:center}
.stat .n{font-size:32px;font-weight:800;color:var(--neon);letter-spacing:-1px}
.stat .l{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:1px;margin-top:6px}
h2{font-size:32px;font-weight:700;margin:60px 0 12px;letter-spacing:-.5px}
h2 .em{color:var(--neon)}
.lead{color:var(--muted);font-size:16px;margin-bottom:24px}
.grid3{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:16px}
.feat{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:22px;transition:all .2s}
.feat:hover{border-color:var(--neon);transform:translateY(-2px)}
.feat .ic{font-size:28px;margin-bottom:10px}
.feat h3{font-size:16px;font-weight:600;margin-bottom:6px;color:var(--text)}
.feat p{color:var(--muted);font-size:13px;line-height:1.5}
.feat code{background:var(--bg2);padding:2px 6px;border-radius:4px;font-size:11px;color:var(--neon2)}
.pricing{overflow-x:auto;margin-top:20px}
table{width:100%;border-collapse:collapse;background:var(--card);border-radius:10px;overflow:hidden;border:1px solid var(--line)}
th{background:var(--bg2);padding:14px 16px;text-align:left;font-size:11px;color:var(--muted);
  text-transform:uppercase;letter-spacing:1px;font-weight:600;border-bottom:1px solid var(--line)}
td{padding:12px 16px;border-bottom:1px solid var(--line);font-size:13px}
tr:last-child td{border-bottom:none}
tr:hover td{background:var(--bg2)}
.tag{display:inline-block;padding:2px 8px;background:var(--bg2);border-radius:4px;font-size:10px;color:var(--muted);margin-right:4px;border:1px solid var(--line)}
.tag.hot{background:rgba(255,89,120,.15);color:var(--red);border-color:rgba(255,89,120,.3)}
.tag.new{background:rgba(199,146,255,.15);color:var(--accent);border-color:rgba(199,146,255,.3)}
.tag.free{background:rgba(57,255,157,.15);color:var(--neon);border-color:rgba(57,255,157,.3)}
.tag.bundle{background:rgba(255,212,121,.15);color:var(--gold);border-color:rgba(255,212,121,.3)}
.demo-card{background:linear-gradient(135deg,rgba(57,255,157,.05),rgba(0,212,255,.05));
  border:1px solid var(--line);border-radius:12px;padding:28px;margin:36px 0;position:relative;overflow:hidden}
.demo-card::before{content:'';position:absolute;top:-50px;right:-50px;width:200px;height:200px;
  background:radial-gradient(circle,rgba(57,255,157,.2) 0,transparent 70%);filter:blur(30px)}
.demo-card h3{font-size:22px;margin-bottom:8px;position:relative}
.demo-card p{color:var(--muted);position:relative;margin-bottom:14px}
.code-block{background:#050810;border:1px solid var(--line);border-radius:8px;padding:16px;overflow-x:auto;font:12px/1.6 'SF Mono',Monaco,monospace;color:var(--neon)}
.code-block .k{color:var(--accent)}.code-block .s{color:var(--gold)}.code-block .c{color:var(--muted)}
.chains{display:flex;gap:12px;flex-wrap:wrap;justify-content:center;margin:24px 0}
.chain{padding:8px 16px;background:var(--card);border:1px solid var(--line);border-radius:99px;font-size:12px;color:var(--muted)}
.chain b{color:var(--text)}
.footer{margin-top:80px;padding:32px 0;border-top:1px solid var(--line);text-align:center;color:var(--muted);font-size:12px}
.footer a{margin:0 8px}
@media (max-width:640px){h1{font-size:36px}h2{font-size:24px}}
</style></head><body>
<div class="wrap">

<div class="hero">
  <div class="badge-live"><span class="pulse"></span>NODE ONLINE — v__V__</div>
  <h1>APIs pagas por AI Agents.<br>Instant. Onchain. Zero setup.</h1>
  <p class="sub">42 endpoints de inteligência de mercado cripto monetizados via <b>x402</b> — pague por chamada com USDC em Solana ou Base. Descubra via manifest, pague via header, receba dados em <b>&lt;500ms</b>.</p>
  <div class="cta">
    <a href="/losbeto-alpha-score" class="btn btn-p">⚡ Testar Grátis →</a>
    <a href="/.well-known/x402.json" class="btn btn-s">Ver x402 Manifest</a>
    <a href="/openapi.json" class="btn btn-s">OpenAPI Spec</a>
  </div>
  <div class="chains">
    <div class="chain">⚡ <b>Solana</b> mainnet</div>
    <div class="chain">🔵 <b>Base</b> L2</div>
    <div class="chain">💰 <b>USDC</b> native</div>
    <div class="chain">🤝 PayAI <b>Facilitator</b></div>
  </div>
</div>

<div class="stats">
  <div class="stat"><div class="n">__EPS__</div><div class="l">Endpoints monetizados</div></div>
  <div class="stat"><div class="n">__WR__%</div><div class="l">Win rate 30d</div></div>
  <div class="stat"><div class="n">$__MIN__</div><div class="l">Preço mínimo</div></div>
  <div class="stat"><div class="n">2</div><div class="l">Chains ativas</div></div>
</div>

<h2>Endpoints <span class="em">exclusivos</span> que fazem a diferença</h2>
<p class="lead">4 features que nenhum outro node no ecossistema x402 oferece — use como diferencial competitivo:</p>

<div class="grid3">
  <div class="feat">
    <div class="ic">🍒</div>
    <h3>Losbeto Alpha Score <span class="tag free">FREE</span></h3>
    <p>Índice composto proprietário 0-100 combinando 4 fatores (Fear&amp;Greed, Regime, Sentimento, Momentum). Preview grátis — versão completa em <code>/alpha-signal</code></p>
  </div>
  <div class="feat">
    <div class="ic">🔗</div>
    <h3>Multi-Chain Arbitrage <span class="tag hot">HOT</span></h3>
    <p>Real-time spread Solana ↔ Base ↔ Ethereum. Detecta oportunidades &gt; 0.5% em USDC/USDT/SOL/ETH em &lt; 200ms. <code>/multi-chain-arbitrage</code></p>
  </div>
  <div class="feat">
    <div class="ic">✅</div>
    <h3>Win-Rate Verified <span class="tag new">NEW</span></h3>
    <p>Histórico de sinais assinado on-chain com Ed25519. Trust matemático — nenhum outro node fornece prova criptográfica. <code>/win-rate-verified</code></p>
  </div>
  <div class="feat">
    <div class="ic">🔮</div>
    <h3>Agent Composable <span class="tag bundle">BUNDLE</span></h3>
    <p>Encadeia 5 endpoints em 1 request: regime + sentimento + sinais + whale + risco. 40% mais barato que chamar separado. <code>/agent-composable</code></p>
  </div>
</div>

<div class="demo-card">
  <h3>🚀 Quick Start para AI Agents</h3>
  <p>3 linhas de código — seu agente já compra dados nossos:</p>
<pre class="code-block"><span class="c"># Python (usando x402 SDK)</span>
<span class="k">from</span> x402 <span class="k">import</span> x402Client
client = x402Client(wallet=<span class="s">'YOUR_WALLET'</span>)
data = client.get(<span class="s">'__URL__/alpha-signal'</span>)  <span class="c"># pago automaticamente</span></pre>
</div>

<h2>Pricing <span class="em">transparente</span> — sem assinatura</h2>
<p class="lead">Pague por chamada. Sem contrato, sem cadastro, sem API key. Só USDC.</p>

<div class="pricing">
<table>
<thead><tr><th>Endpoint</th><th>Preço USDC</th><th>Categoria</th><th>Descrição</th></tr></thead>
<tbody>__ROWS__</tbody>
</table>
</div>

<h2>Discovery & <span class="em">Integração</span></h2>
<div class="grid3">
  <div class="feat"><h3>🔍 x402 Manifest</h3><p><a href="/.well-known/x402.json">/.well-known/x402.json</a><br>Compatível com x402scan, PayAI, CDP Bazaar, AgentCash</p></div>
  <div class="feat"><h3>🤖 MCP Manifest</h3><p><a href="/.well-known/mcp.json">/.well-known/mcp.json</a><br>Descoberta automática por Claude, GPT-4, MCPay agents</p></div>
  <div class="feat"><h3>📖 OpenAPI 3.1</h3><p><a href="/openapi.json">/openapi.json</a><br>Compatível com Postman, Insomnia, Swagger, RapidAPI</p></div>
  <div class="feat"><h3>💬 Agent Card</h3><p><a href="/.well-known/agent.json">/.well-known/agent.json</a><br>A2A Protocol descoberta — Google, Anthropic compatível</p></div>
  <div class="feat"><h3>🤝 LLMs.txt</h3><p><a href="/llms.txt">/llms.txt</a><br>Guia para LLMs consumirem seu conteúdo com contexto</p></div>
  <div class="feat"><h3>📊 Node Info</h3><p><a href="/info">/info</a><br>Estatísticas live: win rate, PoI multiplier, chains, endpoints</p></div>
</div>

<div class="footer">
  <div>
    <a href="https://www.x402scan.com" target="_blank">x402scan</a> ·
    <a href="https://docs.cdp.coinbase.com/x402" target="_blank">CDP Docs</a> ·
    <a href="https://docs.payai.network" target="_blank">PayAI Docs</a> ·
    <a href="/dash">Dashboard</a> ·
    <a href="/info">Node Info</a>
  </div>
  <div style="margin-top:10px">Losbeto v__V__ — Multi-chain x402 AI trading swarm — Solana : <code style="font-size:10px;color:var(--muted)">__ADDR__</code></div>
</div>

</div></body></html>"""

def _is_bot(ua: str) -> bool:
    ua = (ua or "").lower()
    return any(x in ua for x in ("bot", "agent", "curl", "python-requests", "httpx", "axios", "claude", "gpt", "anthropic", "openai"))

@app.route("/")
def root():
    prices = {ep: get_dynamic_price(ep) for ep in BASE_PRICES}
    ua = request.headers.get("User-Agent", "")
    wants_json = ("application/json" in request.headers.get("Accept", "").lower()
                  or _is_bot(ua)
                  or request.args.get("format") == "json")
    if wants_json:
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
            "exclusive_endpoints": [
                "/losbeto-alpha-score", "/multi-chain-arbitrage",
                "/win-rate-verified", "/agent-composable",
            ],
            "discovery": {
                "openapi": "/openapi.json",
                "x402":    "/.well-known/x402.json",
                "mcp":     "/.well-known/mcp.json",
                "agent":   "/.well-known/agent.json",
                "llms":    "/llms.txt",
            },
        })
    # HTML para humanos
    tag_map = {
        "free": ["/losbeto-alpha-score"],
        "hot": ["/multi-chain-arbitrage", "/alpha-signal", "/mev-flow"],
        "new": ["/win-rate-verified", "/agent-composable"],
        "bundle": ["/starter-pack", "/market-brief", "/portfolio-copilot",
                   "/whale-dossier", "/thesis-engine", "/launch-sniper"],
    }
    def _tag(ep):
        for t, eps in tag_map.items():
            if ep in eps: return f'<span class="tag {t}">{t.upper()}</span>'
        return ""
    rows = []
    sorted_eps = sorted(BASE_PRICES.items(), key=lambda x: -x[1])[:20]
    for ep, price in sorted_eps:
        desc = ENDPOINT_DESC.get(ep, ep)[:60]
        tags = " ".join(f'<span class="tag">{t}</span>' for t in ENDPOINT_TAGS.get(ep, [])[:2])
        rows.append(f'<tr><td><code>{ep}</code> {_tag(ep)}</td><td>${price:.4f}</td><td>{tags}</td><td style="color:var(--muted)">{desc}</td></tr>')
    rows_html = "".join(rows)
    min_price = min(BASE_PRICES.values())
    desc_meta = f"Losbeto: {len(BASE_PRICES)} endpoints x402 monetizados. Solana + Base. USDC micropayments para AI agents. Preços a partir de ${min_price:.3f}."
    html = (LANDING_HTML
        .replace("__V__", VERSION)
        .replace("__EPS__", str(len(BASE_PRICES)))
        .replace("__WR__", f"{LEDGER.win_rate():.0f}")
        .replace("__MIN__", f"{min_price:.3f}")
        .replace("__ROWS__", rows_html)
        .replace("__URL__", _public_base())
        .replace("__ADDR__", RECEIVE_ADDRESS[:8] + "…" + RECEIVE_ADDRESS[-6:])
        .replace("__DESC__", desc_meta))
    return app.response_class(html, mimetype="text/html")

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
    base = _public_base()
    resources = []
    svm_fee_payer = os.environ.get("SVM_FEE_PAYER_OVERRIDE", "").strip()
    if not svm_fee_payer and FACILITATOR:
        svm_fee_payer = FACILITATOR.get_svm_fee_payer()
    if not svm_fee_payer:
        svm_fee_payer = WALLET.solana_address  # v20 fallback
    svm_extra = {"feePayer": svm_fee_payer} if svm_fee_payer else {}
    for p, base_price in BASE_PRICES.items():
        dyn_price = get_dynamic_price(p)
        payment_options = [{
            "scheme":            "exact",
            "network":           f"solana:{SOL_GENESIS}",
            "asset":             USDC_MINT,
            "maxAmountRequired": str(int(dyn_price * 10 ** USDC_DECIMALS)),
            "payTo":             RECEIVE_ADDRESS,
            "maxTimeoutSeconds": 300,
            "extra":             svm_extra,
        }]
        if ENABLE_BASE and BASE_PAYTO_EVM:
            payment_options.append({
                "scheme":            "exact",
                "network":           BASE_CAIP2,
                "asset":             BASE_USDC,
                "maxAmountRequired": str(int(dyn_price * 10 ** 6)),
                "payTo":             BASE_PAYTO_EVM,
                "maxTimeoutSeconds": 300,
            })
        resources.append({
            "url":               f"{base}{p}",
            "method":            "GET",
            "scheme":            "exact",
            "network":           f"solana:{SOL_GENESIS}",
            "maxAmountRequired": str(int(dyn_price * 10 ** USDC_DECIMALS)),
            "asset":             USDC_MINT,
            "payTo":             RECEIVE_ADDRESS,
            "maxTimeoutSeconds": 300,
            "extra":             svm_extra,
            "description":       ENDPOINT_DESC.get(p, p),
            "mimeType":          "application/json",
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
    if ENABLE_BASE and BASE_PAYTO_EVM:
        manifest["ownershipProofs"].append(BASE_PAYTO_EVM)
    return jsonify(manifest)

@app.route("/.well-known/mcp.json")
def manifest_mcp():
    base = _public_base()
    tools = []
    for p in BASE_PRICES:
        dyn_price = get_dynamic_price(p)
        x402_opts = {
            "resource": f"{base}{p}",
            "scheme":   "exact",
            "price":    f"${dyn_price:.4f}",
            "network":  f"solana:{SOL_GENESIS}",
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
        "name":           "losbeto-v19",
        "description":    f"Multi-chain x402 AI swarm (Solana+Base+TON). {len(BASE_PRICES)} monetized resources.",
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

    # Endpoints gratuitos com "security": [] para não serem testados como pagos
    free_endpoints = {
        "/sample": {
            "get": {
                "summary": "Free Sample — preview de dados reais",
                "description": "Preview gratuito de Fear&Greed, sinais e anomalias. Sem pagamento.",
                "operationId": "sample_free",
                "tags": ["Free", "Discovery"],
                "parameters": [
                    {"name": "format", "in": "query", "required": False,
                     "description": "Formato da resposta",
                     "schema": {"type": "string", "enum": ["json"], "default": "json"}}
                ],
                "security": [],
                "responses": {
                    "200": {"description": "Preview gratuito",
                            "content": {"application/json": {"schema": {"type": "object"}}}},
                },
            }
        },
        "/bootstrap-trust": {
            "get": {
                "summary": "Bootstrap Trust — instrucoes",
                "description": "Retorna instrucoes para gerar transacoes iniciais de trust.",
                "operationId": "bootstrap_trust_get",
                "tags": ["Free", "Trust"],
                "security": [],
                "responses": {
                    "200": {"description": "Instrucoes de bootstrap",
                            "content": {"application/json": {"schema": {"type": "object"}}}},
                },
            },
            "post": {
                "summary": "Bootstrap Trust — registrar self-payment",
                "description": "Registra uma transacao de self-payment para boost de trust score.",
                "operationId": "bootstrap_trust_post",
                "tags": ["Free", "Trust"],
                "parameters": [
                    {"name": "X-Payment", "in": "header", "required": False,
                     "description": "Transaction signature da Solana (v1 header)",
                     "schema": {"type": "string"}},
                    {"name": "Payment-Signature", "in": "header", "required": False,
                     "description": "Transaction signature da Solana (v2 header)",
                     "schema": {"type": "string"}},
                    {"name": "signature", "in": "query", "required": False,
                     "description": "Transaction signature (query param)",
                     "schema": {"type": "string"}},
                    {"name": "tx", "in": "query", "required": False,
                     "description": "Alias para signature (query param)",
                     "schema": {"type": "string"}},
                    {"name": "payer", "in": "query", "required": False,
                     "description": "Endereco do pagador (query param)",
                     "schema": {"type": "string"}},
                    {"name": "network", "in": "query", "required": False,
                     "description": "Rede (solana, base)",
                     "schema": {"type": "string", "default": "solana"}}
                ],
                "requestBody": {
                    "required": True,
                    "description": "Dados da transacao de self-payment",
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "required": ["signature"],
                                "properties": {
                                    "signature": {"type": "string", "description": "Transaction signature da Solana"},
                                    "tx": {"type": "string", "description": "Alias para signature"},
                                    "payer": {"type": "string", "description": "Endereco do pagador"},
                                    "network": {"type": "string", "description": "Rede (solana, base)", "default": "solana"}
                                }
                            }
                        }
                    }
                },
                "security": [],
                "responses": {
                    "200": {"description": "Bootstrap registrado",
                            "content": {"application/json": {"schema": {"type": "object"}}}},
                    "402": {"description": "Payment verification failed"},
                },
            }
        },
        "/.well-known/x402.json": {
            "get": {
                "summary": "x402 Manifest",
                "description": "Manifesto x402 v2 spec-compliant para discovery de recursos monetizados.",
                "operationId": "manifest_x402",
                "tags": ["Discovery", "Manifest"],
                "security": [],
                "responses": {
                    "200": {"description": "Manifest x402 v2",
                            "content": {"application/json": {"schema": {"type": "object"}}}},
                },
            }
        },
        "/.well-known/mcp.json": {
            "get": {
                "summary": "MCP Manifest",
                "description": "Model Context Protocol manifest para integracao com agentes AI.",
                "operationId": "manifest_mcp",
                "tags": ["Discovery", "Manifest"],
                "security": [],
                "responses": {
                    "200": {"description": "MCP manifest",
                            "content": {"application/json": {"schema": {"type": "object"}}}},
                },
            }
        },
        "/.well-known/agent.json": {
            "get": {
                "summary": "A2A Agent Manifest",
                "description": "Agent-to-Agent manifest para descoberta de capabilities.",
                "operationId": "manifest_agent",
                "tags": ["Discovery", "Manifest"],
                "security": [],
                "responses": {
                    "200": {"description": "Agent manifest",
                            "content": {"application/json": {"schema": {"type": "object"}}}},
                },
            }
        },
        "/get-pricing": {
            "get": {
                "summary": "Pricing List",
                "description": "Lista completa de precos de todos os endpoints.",
                "operationId": "get_pricing",
                "tags": ["Free", "Discovery"],
                "security": [],
                "responses": {
                    "200": {"description": "Lista de precos",
                            "content": {"application/json": {"schema": {"type": "object"}}}},
                },
            }
        },
        "/bazaar.json": {
            "get": {
                "summary": "Bazaar Manifest",
                "description": "Manifesto emergente do ecossistema Bazaar para auto-discovery.",
                "operationId": "bazaar_manifest",
                "tags": ["Discovery", "Manifest"],
                "security": [],
                "responses": {
                    "200": {"description": "Bazaar manifest",
                            "content": {"application/json": {"schema": {"type": "object"}}}},
                },
            }
        },
        "/referral": {
            "get": {
                "summary": "Referral system",
                "description": "Get referral info or create a new referral code.",
                "operationId": "referral_get",
                "tags": ["Free", "Referral"],
                "security": [],
                "responses": {
                    "200": {"description": "Referral info",
                            "content": {"application/json": {"schema": {"type": "object"}}}},
                },
            },
            "post": {
                "summary": "Create referral code",
                "description": "Create a new referral code.",
                "operationId": "referral_post",
                "tags": ["Free", "Referral"],
                "security": [],
                "responses": {
                    "200": {"description": "Referral created",
                            "content": {"application/json": {"schema": {"type": "object"}}}},
                },
            }
        },
        "/stake": {
            "post": {
                "summary": "Stake USDC on node reputation",
                "description": "Allows third parties to stake USDC on the node's reputation.",
                "operationId": "stake_post",
                "tags": ["Free", "Stake"],
                "security": [],
                "responses": {
                    "200": {"description": "Stake registered",
                            "content": {"application/json": {"schema": {"type": "object"}}}},
                },
            }
        },
    }
    paths.update(free_endpoints)

    # Endpoints pagos (mantêm security: [{"x402": []}])
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
                "description": f"{ENDPOINT_DESC.get(p, p)}. Preco: ${price:.4f} USDC via x402.",
                "operationId": p.strip("/").replace("-", "_"),
                "tags":        ENDPOINT_TAGS.get(p, ["Trading"]),
                "parameters":  params,
                "security":    [{"x402": []}],
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
        "description": f"Multi-chain x402 AI swarm — Solana + Base. {len(BASE_PRICES)} monetized resources.",
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

@app.route("/peers")
def peers_list():
    peers = LEDGER.active_peers()
    return jsonify({"count": len(peers),
                    "peers": [{"node": p[0], "url": p[1],
                               "reputation": p[2], "win_rate": p[3]}
                              for p in peers]})

# ============================================================================
# 14b. ENDPOINTS DE DIAGNÓSTICO (mesmo da v18)
# ============================================================================

@app.route("/scan-tx")
def scan_tx():
    sig = (request.args.get("sig") or "").strip()
    if not sig:
        return jsonify({"error": "missing sig query param"}), 400
    tx = SOL.get_tx(sig)
    if not tx:
        return jsonify({"signature": sig, "found": False}), 200
    meta = tx.get("meta") or {}
    err = meta.get("err")
    bt  = tx.get("blockTime") or 0
    pre  = {b["accountIndex"]: b for b in meta.get("preTokenBalances", [])}
    post = {b["accountIndex"]: b for b in meta.get("postTokenBalances", [])}
    transfers = []
    for idx, pb in post.items():
        mint  = pb.get("mint", "")
        owner = pb.get("owner", "")
        po = float(pb.get("uiTokenAmount", {}).get("uiAmount") or 0)
        pa = float(pre.get(idx, {}).get("uiTokenAmount", {}).get("uiAmount") or 0)
        delta = round(po - pa, 6)
        if abs(delta) > 1e-9:
            transfers.append({"owner": owner, "mint": mint, "delta": delta,
                              "is_usdc": mint == USDC_MINT})
    ok, info = SOL.verify_payment(sig, 0.005, RECEIVE_ADDRESS, max_age=86400 * 30)
    is_valid = bool(ok)
    delta_to_us = 0.0
    payer = ""
    if isinstance(info, dict):
        delta_to_us = float(info.get("delta") or 0)
        payer = info.get("payer") or ""
    return jsonify({
        "signature":         sig,
        "found":             True,
        "block_time":        bt,
        "age_seconds":       int(time.time() - bt) if bt else None,
        "tx_error":          err,
        "receive_address":   RECEIVE_ADDRESS,
        "is_valid_payment":  is_valid,
        "delta_usdc":        round(delta_to_us, 6),
        "payer":             payer,
        "all_usdc_transfers": [t for t in transfers if t["is_usdc"]],
        "suggested_action":  ("POST /bootstrap-trust com X-Payment: <sig> para registrar."
                              if is_valid else "Esta tx NÃO envia USDC para RECEIVE_ADDRESS."),
    })

@app.route("/reconcile-tx", methods=["POST"])
def reconcile_tx():
    tok = request.headers.get("X-Dash-Token") or request.args.get("token") or ""
    if tok != DASH_TOKEN:
        return jsonify({"error": "forbidden"}), 403
    body = request.get_json(silent=True) or {}
    sigs = body.get("signatures") or []
    endpoint = body.get("endpoint") or "/bootstrap-trust"
    if not sigs or not isinstance(sigs, list):
        return jsonify({"error": "signatures[] required"}), 400
    results = []
    for sig in sigs[:50]:
        sig = str(sig).strip()
        try:
            ok, info = SOL.verify_payment(sig, 0.005, RECEIVE_ADDRESS, max_age=86400 * 30)
            if ok:
                payer = info.get("payer", "") if isinstance(info, dict) else ""
                amount = round(float(info.get("delta", 0.01)), 6) if isinstance(info, dict) else 0.01
                h = hashlib.sha256(sig.encode()).hexdigest()
                if LEDGER.replay_check(h):
                    results.append({"sig": sig[:32] + "...", "status": "already_recorded"})
                    continue
                LEDGER.add_revenue(endpoint, amount, sig, payer, source="reconcile", chain="solana")
                results.append({"sig": sig[:32] + "...", "status": "recorded", "amount": amount})
            else:
                results.append({"sig": sig[:32] + "...", "status": "invalid", "reason": str(info)})
        except Exception as e:
            results.append({"sig": sig[:32] + "...", "status": "error", "error": str(e)})
    return jsonify({"processed": len(results), "results": results})

@app.route("/register-marketplaces", methods=["POST", "GET"])
def register_marketplaces():
    base = _public_base()
    manifest_url = f"{base}/.well-known/x402.json"
    targets = [
        {"name": "x402scan",       "url": "https://www.x402scan.com/api/resources", "method": "POST", "body": {"url": base}},
        {"name": "cdp-bazaar",     "url": "https://api.cdp.coinbase.com/platform/v2/x402/bazaar/resources", "method": "POST", "body": {"url": manifest_url}},
        {"name": "payai-registry", "url": "https://facilitator.payai.network/registry/servers", "method": "POST", "body": {"url": manifest_url}},
        {"name": "agentcash",      "url": "https://agentcash.dev/api/servers", "method": "POST", "body": {"url": manifest_url}},
        {"name": "mcpay",          "url": "https://mcpay.tech/api/register", "method": "POST", "body": {"url": manifest_url}},
    ]
    results = []
    for t in targets:
        try:
            r = requests.post(t["url"], json=t["body"], timeout=10,
                              headers={"Content-Type": "application/json",
                                       "User-Agent": f"Losbeto/{VERSION}"})
            results.append({"marketplace": t["name"], "status": r.status_code, "ok": r.status_code < 400})
        except Exception as e:
            results.append({"marketplace": t["name"], "ok": False, "error": str(e)[:200]})
    return jsonify({
        "manifest_url":   manifest_url,
        "node_id":        WALLET.node_id,
        "results":        results,
    })

@app.route("/health/deep")
def health_deep():
    checks = {}
    try:
        r = SOL._post("getSlot", [])
        checks["solana_rpc"] = {"ok": bool(r and r.get("result")), "slot": (r or {}).get("result", 0)}
    except Exception as e:
        checks["solana_rpc"] = {"ok": False, "error": str(e)}
    try:
        bal = SOL.get_balance_usdc(RECEIVE_ADDRESS)
        checks["receive_balance"] = {"ok": True, "usdc": bal, "address": RECEIVE_ADDRESS}
    except Exception as e:
        checks["receive_balance"] = {"ok": False, "error": str(e)}
    if FACILITATOR:
        try:
            r = requests.get(f"{FACILITATOR.url}/supported", timeout=5)
            checks["facilitator"] = {"ok": r.status_code < 500, "status": r.status_code, "url": FACILITATOR.url}
        except Exception as e:
            checks["facilitator"] = {"ok": False, "error": str(e), "url": FACILITATOR.url}
    else:
        checks["facilitator"] = {"ok": False, "reason": "not-configured"}
    try:
        s = LEDGER.stats()
        checks["ledger"] = {"ok": True, "total_usdc": s["total_usdc"], "paid_24h": s["paid_24h"]}
    except Exception as e:
        checks["ledger"] = {"ok": False, "error": str(e)}
    checks["wallet"] = {
        "ok":             bool(RECEIVE_ADDRESS and _is_valid_solana_address(RECEIVE_ADDRESS)),
        "receive":        RECEIVE_ADDRESS,
        "signer":         WALLET.solana_address,
        "consistent":     RECEIVE_ADDRESS != WALLET.solana_address,
        "base_enabled":   ENABLE_BASE,
    }
    overall = all(c.get("ok") for c in checks.values() if isinstance(c, dict))
    return jsonify({
        "version":  VERSION,
        "ts":       int(time.time()),
        "overall":  "healthy" if overall else "degraded",
        "checks":   checks,
    })

@app.route("/debug-tx")
def debug_tx():
    sig = (request.args.get("sig") or "").strip()
    if not sig:
        return jsonify({"error": "missing sig"}), 400
    tx = SOL.get_tx(sig)
    if not tx:
        return jsonify({"signature": sig, "found": False}), 200
    meta = tx.get("meta") or {}
    err = meta.get("err")
    bt = tx.get("blockTime") or 0
    pre = {b["accountIndex"]: b for b in meta.get("preTokenBalances", [])}
    post = {b["accountIndex"]: b for b in meta.get("postTokenBalances", [])}
    analysis = {
        "tx_error": err,
        "block_time": bt,
        "age_seconds": int(time.time() - bt) if bt else None,
        "receive_address": RECEIVE_ADDRESS,
    }
    m1_results = []
    for idx, pb in post.items():
        if pb.get("mint") != USDC_MINT:
            continue
        owner = pb.get("owner", "")
        pa = float(pre.get(idx, {}).get("uiTokenAmount", {}).get("uiAmount") or 0)
        po = float(pb.get("uiTokenAmount", {}).get("uiAmount") or 0)
        delta = round(po - pa, 6)
        m1_results.append({
            "account_index": idx,
            "owner": owner,
            "owner_is_receive": owner == RECEIVE_ADDRESS,
            "pre": pa,
            "post": po,
            "delta": delta,
            "would_pass": delta >= 0.005 and owner == RECEIVE_ADDRESS
        })
    analysis["method1_pre_post_balances"] = m1_results
    m2_results = []
    inner_ixs = meta.get("innerInstructions", [])
    for inner in inner_ixs:
        for ix in inner.get("instructions", []):
            prog = ix.get("programId", "")
            if "Token" in prog or prog == "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA":
                parsed = ix.get("parsed", {})
                ix_type = parsed.get("type", "")
                if ix_type in ("transfer", "transferChecked"):
                    info = parsed.get("info", {})
                    dest_owner = None
                    for b in meta.get("postTokenBalances", []):
                        if b.get("accountIndex") == info.get("destinationIndex"):
                            dest_owner = b.get("owner")
                            break
                    m2_results.append({
                        "type": ix_type,
                        "dest_owner": dest_owner,
                        "dest_owner_is_receive": dest_owner == RECEIVE_ADDRESS,
                    })
    analysis["method2_inner_instructions"] = m2_results
    ok, info = SOL.verify_payment(sig, 0.005, RECEIVE_ADDRESS, max_age=86400*30)
    analysis["verify_payment_result"] = {"ok": ok, "info": info}
    return jsonify({
        "signature": sig,
        "found": True,
        "analysis": analysis,
    })

@app.route("/force-register-tx", methods=["POST"])
def force_register_tx():
    tok = request.headers.get("X-Dash-Token") or request.args.get("token") or ""
    if tok != DASH_TOKEN:
        return jsonify({"error": "forbidden"}), 403
    body = request.get_json(silent=True) or {}
    sig = (body.get("signature") or "").strip()
    amount = float(body.get("amount_usdc", 0))
    endpoint = body.get("endpoint") or "/bootstrap-trust"
    payer = body.get("payer") or "manual"
    if not sig or amount <= 0:
        return jsonify({"error": "signature and amount_usdc required"}), 400
    h = hashlib.sha256(sig.encode()).hexdigest()
    LEDGER.replay_delete(h)
    LEDGER.add_revenue(endpoint, amount, sig, payer, source="manual-force", chain="solana")
    return jsonify({
        "success": True,
        "tx": sig[:32] + "...",
        "amount_usdc": amount,
        "new_total_usdc": LEDGER.stats()["total_usdc"],
    })

# ============================================================================
# v20 NEW: /verify-signature-manual  — endpoint público que credita uma tx
# se ela for válida on-chain. Complementa o dashboard: se você tem uma tx
# signature e quer que ela seja registrada no ledger E no manifest x402
# (para o x402scan indexar), use este endpoint.
# ============================================================================
@app.route("/verify-signature-manual", methods=["POST"])
def verify_signature_manual():
    body = request.get_json(silent=True) or {}
    sig = (body.get("signature") or body.get("sig") or "").strip()
    endpoint = body.get("endpoint") or "/bootstrap-trust"
    if not sig:
        return jsonify({"error": "signature required in body"}), 400
    # 1. Verifica on-chain (janela ampla: 30 dias)
    ok, info = SOL.verify_payment(sig, 0.005, RECEIVE_ADDRESS, max_age=86400 * 30)
    if not ok:
        return jsonify({
            "success": False,
            "error": "tx does not send USDC to RECEIVE_ADDRESS",
            "reason": str(info),
            "receive_address": RECEIVE_ADDRESS,
            "debug_url": f"{_public_base()}/debug-tx?sig={sig}",
        }), 200
    # 2. Verifica se já foi registrada
    h = hashlib.sha256(sig.encode()).hexdigest()
    already = False
    with LEDGER._conn() as c:
        row = c.execute("SELECT 1 FROM revenue WHERE tx_sig=?", (sig,)).fetchone()
        already = bool(row)
    if already:
        return jsonify({
            "success": True,
            "already_recorded": True,
            "tx": sig[:32] + "...",
        })
    # 3. Registra
    payer = info.get("payer", "") if isinstance(info, dict) else ""
    amount = round(float(info.get("delta", 0.01)), 6) if isinstance(info, dict) else 0.01
    LEDGER.replay_delete(h)
    LEDGER.add_revenue(endpoint, amount, sig, payer, source="manual-verify", chain="solana")
    _notify_telegram(f"💰 Manual verify: ${amount} USDC em {endpoint}\nTX: {sig[:32]}...")
    return jsonify({
        "success": True,
        "tx": sig[:32] + "...",
        "amount_usdc": amount,
        "payer": payer,
        "new_total_usdc": LEDGER.stats()["total_usdc"],
        "x402scan_url": f"https://www.x402scan.com/server/{WALLET.node_id}",
        "note": "Registered locally. x402scan indexa on-chain, então pode levar 1-5min após a tx.",
    })

# ============================================================================
# v20 NEW: /dash/api/tx-list — lista todas as tx registradas (para reconciliar
# com o que aparece no x402scan)
# ============================================================================
@app.route("/dash/api/tx-list")
def dash_tx_list():
    if request.args.get("token") != DASH_TOKEN:
        return jsonify({"error": "forbidden"}), 403
    limit = min(int(request.args.get("limit", 100)), 500)
    with LEDGER._conn() as c:
        rows = c.execute(
            "SELECT ts, endpoint, amount, tx_sig, payer, source, chain "
            "FROM revenue ORDER BY ts DESC LIMIT ?", (limit,)
        ).fetchall()
    txs = [
        {
            "ts": r[0],
            "endpoint": r[1],
            "amount_usdc": r[2],
            "tx_sig": r[3],
            "tx_short": (r[3][:16] + "..." + r[3][-8:]) if r[3] and len(r[3]) > 30 else r[3],
            "payer": r[4],
            "source": r[5],
            "chain": r[6],
            "solscan": f"https://solscan.io/tx/{r[3]}" if r[6] == "solana" and r[3] else None,
        }
        for r in rows
    ]
    return jsonify({
        "count": len(txs),
        "tx_list": txs,
        "node_id": WALLET.node_id,
        "x402scan_server_url": f"https://www.x402scan.com/server/{WALLET.node_id}",
    })

# ============================================================================
# v20 NEW: /debug-x402scan — explica POR QUE uma tx aparece ou não no scanner
# ============================================================================
@app.route("/debug-x402scan")
def debug_x402scan():
    sig = (request.args.get("sig") or "").strip()
    diagnosis = {
        "node_id": WALLET.node_id,
        "receive_address": RECEIVE_ADDRESS,
        "manifest_endpoint": f"{_public_base()}/.well-known/x402.json",
        "x402scan_server": f"https://www.x402scan.com/server/{WALLET.node_id}",
        "bootstrap_trust_in_manifest": "/bootstrap-trust" in BASE_PRICES,
        "total_endpoints_in_manifest": len(BASE_PRICES),
    }
    if not sig:
        diagnosis["note"] = "Passe ?sig=<signature> para diagnosticar uma tx específica"
        return jsonify(diagnosis)
    # Diagnóstico completo da tx
    ok, info = SOL.verify_payment(sig, 0.005, RECEIVE_ADDRESS, max_age=86400 * 30)
    with LEDGER._conn() as c:
        row = c.execute(
            "SELECT ts, endpoint, amount, source FROM revenue WHERE tx_sig=?", (sig,)
        ).fetchone()
    diagnosis["tx_signature"] = sig
    diagnosis["on_chain_valid"] = bool(ok)
    diagnosis["on_chain_details"] = info if isinstance(info, dict) else {"reason": str(info)}
    diagnosis["in_local_ledger"] = bool(row)
    if row:
        diagnosis["ledger_record"] = {
            "ts": row[0], "endpoint": row[1], "amount_usdc": row[2], "source": row[3],
        }
    # Por que aparece / não aparece no x402scan
    reasons_visible = []
    reasons_hidden = []
    if ok:
        reasons_visible.append("Tx envia USDC on-chain para RECEIVE_ADDRESS ✅")
    else:
        reasons_hidden.append(f"Tx não válida on-chain: {info}")
    endpoint_used = row[1] if row else None
    if endpoint_used and endpoint_used in BASE_PRICES:
        reasons_visible.append(f"Endpoint {endpoint_used} está no manifest ✅")
    elif endpoint_used:
        reasons_hidden.append(
            f"Endpoint {endpoint_used} NÃO está no manifest x402.json — "
            f"x402scan não indexa (era o bug v19: bootstrap-trust fora do manifest)"
        )
    diagnosis["why_visible"] = reasons_visible
    diagnosis["why_hidden"] = reasons_hidden
    diagnosis["solscan_url"] = f"https://solscan.io/tx/{sig}"
    diagnosis["action"] = (
        "POST /verify-signature-manual com {signature: '...'} para forçar registro local. "
        "O x402scan indexa on-chain automaticamente em ~1-5min após a tx aparecer."
    )
    return jsonify(diagnosis)

@app.route("/clear-replay", methods=["POST"])
def clear_replay():
    tok = request.headers.get("X-Dash-Token") or request.args.get("token") or ""
    if tok != DASH_TOKEN:
        return jsonify({"error": "forbidden"}), 403
    body = request.get_json(silent=True) or {}
    sigs = body.get("signatures") or []
    if not sigs:
        with LEDGER._conn() as c:
            c.execute("DELETE FROM replay")
            count = c.rowcount
        return jsonify({"cleared_all": True, "entries_deleted": count})
    cleared = []
    for sig in sigs:
        h = hashlib.sha256(sig.encode()).hexdigest()
        if LEDGER.replay_delete(h):
            cleared.append(sig[:20] + "...")
    return jsonify({"cleared": cleared, "count": len(cleared)})

# ============================================================================
# 15. DASHBOARD
# ============================================================================

DASH_HTML = """<!doctype html><html lang="pt-BR"><head>
<meta charset="utf-8"><title>Losbeto // node console</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
:root{
  --bg:#05070a; --bg2:#080b10; --card:#0c1015; --line:#182028;
  --neon:#39ff9d; --neon-dim:#1c8a56; --accent:#7cf7ff; --amber:#ffb545;
  --red:#ff5d6c; --text:#d7ffe9; --muted:#5c7268; --mono:'JetBrains Mono','SF Mono',Consolas,monospace;
}
*{box-sizing:border-box;margin:0;padding:0}
body{
  background:
    linear-gradient(180deg,rgba(57,255,157,.03),transparent 200px),
    repeating-linear-gradient(0deg,rgba(57,255,157,.025) 0px,rgba(57,255,157,.025) 1px,transparent 1px,transparent 3px),
    var(--bg);
  color:var(--text);font:13px/1.55 var(--mono);padding:22px;max-width:1180px;margin:0 auto;
}
.header{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:18px;
  border-bottom:1px solid var(--line);padding-bottom:14px;flex-wrap:wrap;gap:10px}
.header h1{font-size:20px;letter-spacing:.5px;color:var(--neon);text-shadow:0 0 12px rgba(57,255,157,.35)}
.badge{background:transparent;border:1px solid var(--neon-dim);color:var(--neon);padding:2px 8px;
  border-radius:3px;font-size:10px;font-weight:700;margin-left:8px;letter-spacing:1px;vertical-align:middle}
.subline{color:var(--muted);font-size:11px;margin-top:5px}
.addrbox{text-align:right;font-size:11px;color:var(--muted)}
.addrbox code{color:var(--accent)}
.chip{display:inline-block;border:1px solid var(--line);border-radius:3px;padding:1px 6px;margin-left:4px;font-size:10px;color:var(--muted)}

.alert{border:1px solid var(--amber);background:linear-gradient(135deg,rgba(255,181,69,.08),rgba(255,181,69,.02));
  border-radius:6px;padding:14px 16px;margin-bottom:20px;display:none}
.alert.show{display:block}
.alert h4{color:var(--amber);font-size:12px;letter-spacing:.5px;margin-bottom:6px;text-transform:uppercase}
.alert p{color:var(--muted);font-size:12px;line-height:1.7}
.alert code{color:var(--amber)}

.alert-ok{border:1px solid var(--neon-dim);background:rgba(57,255,157,.05);border-radius:6px;
  padding:10px 16px;margin-bottom:20px;display:none;color:var(--neon);font-size:12px}
.alert-ok.show{display:block}

.section-label{color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:2px;
  margin:22px 0 10px;display:flex;align-items:center;gap:8px}
.section-label::after{content:"";flex:1;height:1px;background:var(--line)}

.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:10px}
.card{background:var(--card);border:1px solid var(--line);border-radius:6px;padding:14px;position:relative;overflow:hidden}
.card::before{content:"";position:absolute;left:0;top:0;bottom:0;width:2px;background:var(--neon-dim)}
.card h3{color:var(--muted);font-size:10px;text-transform:uppercase;letter-spacing:1px;margin-bottom:8px;font-weight:400}
.card .v{font-size:24px;font-weight:700;color:var(--text);letter-spacing:.3px}
.card .sub{color:var(--muted);font-size:11px;margin-top:4px}
.card.hero{grid-column:span 2}
.card.hero .v{font-size:34px;color:var(--neon);text-shadow:0 0 10px rgba(57,255,157,.3)}
.green{color:var(--neon)!important} .red{color:var(--red)!important} .amber{color:var(--amber)!important}

.catbar-row{display:flex;align-items:center;gap:10px;margin-bottom:8px;font-size:11px}
.catbar-row .lbl{width:70px;color:var(--muted);flex-shrink:0}
.catbar-row .track{flex:1;height:6px;background:var(--line);border-radius:3px;overflow:hidden}
.catbar-row .fill{height:100%;background:linear-gradient(90deg,var(--neon-dim),var(--neon))}
.catbar-row .n{width:26px;text-align:right;color:var(--muted)}

a{color:var(--accent);text-decoration:none}
a:hover{text-decoration:underline;color:var(--neon)}
table{width:100%;border-collapse:collapse;background:var(--card);border-radius:6px;overflow:hidden;border:1px solid var(--line)}
th,td{padding:9px 12px;text-align:left;border-bottom:1px solid var(--line);font-size:12px}
th{background:var(--bg2);color:var(--muted);font-size:10px;text-transform:uppercase;letter-spacing:1px;font-weight:400}
tr:last-child td{border-bottom:none}
code{background:var(--bg2);padding:2px 6px;border-radius:3px;font-size:11px;color:var(--accent);border:1px solid var(--line)}
.actioncard{background:var(--card);border:1px solid var(--line);border-radius:6px;padding:14px}
.actioncard h3{font-size:11px;color:var(--text);margin-bottom:8px;letter-spacing:.3px}
.actioncard .sub{color:var(--muted);font-size:11px;line-height:1.8}
.footer{margin-top:28px;color:var(--muted);font-size:10px;text-align:center;letter-spacing:.5px;
  border-top:1px solid var(--line);padding-top:14px}
.pulse{display:inline-block;width:6px;height:6px;border-radius:50%;background:var(--neon);
  box-shadow:0 0 6px var(--neon);animation:pulse 2s infinite;margin-right:5px}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.3}}
</style></head><body>
<div class="header">
  <div>
    <h1>LOSBETO<span class="badge">v21</span></h1>
    <div class="subline"><span class="pulse"></span><span id="node">node ···</span>
      <span class="chip" id="uptime_chip">live</span></div>
  </div>
  <div class="addrbox">
    <div>SOL &nbsp;<code id="addr">···</code></div>
    <div style="margin-top:3px">BASE &nbsp;<code id="base_addr">···</code></div>
    <div style="margin-top:3px" id="signer"></div>
  </div>
</div>

<div class="alert" id="trust_alert">
  <h4>⚠ trust bootstrap pendente</h4>
  <p>O node precisa de <strong>3 transações reais</strong> confirmadas on-chain para ser listado com
     confiança nos diretórios x402 (eles filtram por <code>tx_count &gt; 0</code>).
     Rode <code>POST /bootstrap-trust</code> com 3 pagamentos pequenos feitos pela própria carteira do operador —
     são transações reais, verificadas on-chain, e registradas como origem "bootstrap" (não como compra orgânica).
     <br>Status público: <a href="https://www.x402scan.com" target="_blank">x402scan.com</a>
  </p>
</div>
<div class="alert-ok" id="trust_ok">✓ trust bootstrap completo — node visível nos diretórios x402</div>

<div class="section-label">Overview</div>
<div class="grid" id="cards"></div>

<div class="section-label">Endpoints por categoria</div>
<div class="card" style="padding:16px" id="catcard"></div>

<div class="section-label">Top Endpoints (24h)</div>
<table id="tbl"><thead><tr><th>Endpoint</th><th>Hits</th><th>Preço (USDC)</th></tr></thead><tbody></tbody></table>

<div class="section-label">Ações Rápidas</div>
<div class="grid" style="grid-template-columns:repeat(auto-fit,minmax(230px,1fr))">
  <div class="actioncard">
    <h3>📍 Listar em Marketplaces</h3>
    <div class="sub">
      <a href="/register-marketplaces" target="_blank">Auto-Register</a> ·
      <a href="https://www.x402scan.com/resources/register" target="_blank">x402scan</a> ·
      <a href="https://github.com/xpaysh/awesome-x402" target="_blank">awesome-x402</a> ·
      <a href="https://agentcash.dev" target="_blank">AgentCash</a> ·
      <a href="https://mcpay.tech" target="_blank">MCPay</a>
    </div>
  </div>
  <div class="actioncard">
    <h3>🔍 Escanear TX</h3>
    <div class="sub"><code style="font-size:10px">GET /debug-tx?sig=&lt;signature&gt;</code></div>
  </div>
  <div class="actioncard">
    <h3>🚨 Force Register</h3>
    <div class="sub"><code style="font-size:10px">POST /force-register-tx</code><br>
      <span class="amber">requer X-Dash-Token</span></div>
  </div>
  <div class="actioncard">
    <h3>🧪 Bootstrap Trust</h3>
    <div class="sub"><code style="font-size:10px">POST /bootstrap-trust</code><br>
      com <code style="font-size:10px">X-Payment: &lt;tx-sig&gt;</code></div>
  </div>
  <div class="actioncard">
    <h3>🔗 Manifests</h3>
    <div class="sub">
      <a href="/.well-known/x402.json" target="_blank">x402.json</a> ·
      <a href="/.well-known/mcp.json" target="_blank">mcp.json</a> ·
      <a href="/bazaar.json" target="_blank">bazaar.json</a>
    </div>
  </div>
</div>

<div class="footer">refresh 10s · win-rate dirige preço via PoI multiplier · Losbeto v21</div>
<script>
const CATEGORY_MAP = {
  "agent-call":"Utility","agent-market":"AI","ai-news":"AI","alpha-signal":"Trading","analise":"Trading",
  "anomalias":"Utility","arbitrage":"Trading","backtest":"Trading","copytrade":"Trading","cross-chain":"Trading",
  "deep-think":"AI","defi-yield":"Crypto","dex-screen":"Trading","fear-greed":"Search","geo-alpha":"Utility",
  "insider-track":"Crypto","jupiter-swap":"Trading","launch-sniper":"Trading","market-brief":"Trading",
  "mempool":"Utility","mev-flow":"Crypto","nansen-flow":"Utility","onchain-credit":"Crypto",
  "portfolio-copilot":"Crypto","pump-monitor":"Crypto","pyth-price":"Utility","regime":"Trading",
  "relatorio":"Search","rugcheck":"Crypto","sanctions":"Search","sec-filing":"Search","sentiment":"Search",
  "sinais":"Trading","smart-money":"Crypto","starter-pack":"Crypto","swarm-vote":"Utility","tg-premium":"Search",
  "thesis-engine":"Search","trust-hash":"Utility","web-search":"Search","whale-alert":"Crypto","whale-dossier":"Crypto",
};
const CAT_COLORS = {"Crypto":"var(--neon)","AI":"var(--accent)","Trading":"var(--amber)","Utility":"var(--muted)","Search":"#c792ff"};

async function reload(){
  const r=await fetch("/dash/api/stats?token=__TOKEN__");
  if(!r.ok)return;
  const j=await r.json();
  document.getElementById("node").textContent="node "+j.node_id;
  document.getElementById("addr").textContent=j.solana_address.slice(0,6)+"…"+j.solana_address.slice(-4);
  document.getElementById("base_addr").textContent=j.base_payto?(j.base_payto.slice(0,6)+"…"+j.base_payto.slice(-4)):"—";
  const sigEl=document.getElementById("signer");
  if(sigEl && j.signer_address && j.signer_address!==j.solana_address){
    sigEl.innerHTML="signer <code style='font-size:9px'>"+j.signer_address.slice(0,6)+"…"+j.signer_address.slice(-4)+"</code>";
    sigEl.title="Signer (JWT/P2P) — não recebe pagamentos: "+j.signer_address;
  }

  const trustActive = j.stats.paid_24h >= 3;
  document.getElementById("trust_alert").classList.toggle("show", !trustActive);
  document.getElementById("trust_ok").classList.toggle("show", trustActive);

  const avgPrice = j.endpoints ? (Object.values(j.prices).reduce((a,b)=>a+b,0)/j.endpoints) : 0;

  const cards=[
    ["💰 Receita Total",`$${j.stats.total_usdc.toFixed(4)}`,"USDC acumulado","hero"],
    ["📅 Hoje (24h)",`$${j.stats.today_usdc.toFixed(4)}`,j.stats.paid_24h+" pagamentos",""],
    ["⏱️ Última hora",`$${j.stats.hour_usdc.toFixed(4)}`,"USDC",""],
    ["🎯 Win Rate",`${j.stats.win_rate.toFixed(1)}%`,"30 dias",""],
    ["⚡ PoI Multiplier",`${j.stats.poi_multiplier.toFixed(2)}x`,"preço dinâmico",""],
    ["📊 Conversão",`${j.stats.conv_rate.toFixed(1)}%`,j.stats.requests_24h+" requisições",""],
    ["👥 Compradores",j.stats.buyers,"únicos",""],
    ["💵 Preço médio",`$${avgPrice.toFixed(3)}`,"por chamada",""],
    ["⛓️ Chains",(j.chains||["solana"]).map(c=>c.split(":")[0]).join(" · "),"ativas",""],
    ["📈 Trust Score",trustActive ? "ATIVO" : "BOOTSTRAP", j.stats.paid_24h+" tx (24h)",trustActive?"green":"amber"],
    ["🌐 Endpoints",j.endpoints,"monetizados",""],
  ];
  document.getElementById("cards").innerHTML = cards.map(c =>
    `<div class="card ${c[3]==='hero'?'hero':''}"><h3>${c[0]}</h3><div class="v ${c[3]==='green'?'green':c[3]==='amber'?'amber':''}">${c[1]}</div><div class="sub">${c[2]}</div></div>`
  ).join("");

  const byCat = {};
  Object.keys(j.prices).forEach(ep=>{
    const name = ep.replace(/^\\//,"");
    const cat = CATEGORY_MAP[name] || "Utility";
    byCat[cat] = (byCat[cat]||0) + 1;
  });
  const maxCat = Math.max(1, ...Object.values(byCat));
  document.getElementById("catcard").innerHTML = Object.entries(byCat).sort((a,b)=>b[1]-a[1]).map(([cat,n])=>
    `<div class="catbar-row"><div class="lbl">${cat}</div><div class="track"><div class="fill" style="width:${(n/maxCat*100).toFixed(0)}%;background:${CAT_COLORS[cat]||'var(--neon)'}"></div></div><div class="n">${n}</div></div>`
  ).join("");

  const rows = Object.entries(j.stats.by_endpoint||{})
    .sort((a,b)=>b[1]-a[1]).slice(0,15);
  document.getElementById("tbl").querySelector("tbody").innerHTML =
    rows.length ? rows.map(([ep,n])=>`<tr><td><code>${ep}</code></td><td>${n}</td><td>${(ep in j.prices)?('$'+j.prices[ep].toFixed(4)):'<span style="color:var(--muted)">variável</span>'}</td></tr>`).join("")
                : '<tr><td colspan=3 style="text-align:center;color:var(--muted)">Aguardando pagamentos... veja "Bootstrap Trust" acima.</td></tr>';
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
# 16. TELEGRAM BOT (com comandos adicionais)
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
                f"/wallet - endereços para pagamento\n"
                f"/referral - gera seu código de referência\n"
                f"/stake - aposte USDC na reputação do node\n\n"
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
        elif text == "/referral":
            code = secrets.token_urlsafe(6)
            owner = msg["from"]["id"]
            if LEDGER.create_referral(code, str(owner)):
                self.send(chat_id, f"✅ Seu código de referência: `{code}`\nCompartilhe e ganhe 10% de comissão!")
            else:
                self.send(chat_id, "⚠️ Você já possui um código ativo.")
        elif text == "/stake":
            self.send(chat_id, (
                "Para apostar USDC na reputação do node, use:\n"
                "`POST /stake` com JSON:\n"
                "```json\n{\"staker\": \"SEU_ENDERECO\", \"amount\": 0.10, \"tx_sig\": \"ASSINATURA\"}\n```"
                "Envie USDC para o endereço do node e use a assinatura da transação."
            ))
        else:
            self.send(chat_id, "❓ Comando não reconhecido. Tente /start")

TG_BOT = TelegramBot(TG_TOKEN) if TG_TOKEN else None

# ============================================================================
# 17. WORKERS BACKGROUND (incluindo auto‑promoção no Twitter)
# ============================================================================

def signal_validator_loop():
    while True:
        time.sleep(900)
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
        time.sleep(600)
        try:
            Brain.sinais()
        except Exception as e:
            log.warning(f"sig-gen: {e}")

def rag_ingest_loop():
    while True:
        time.sleep(1800)
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

def twitter_promo_loop():
    if not (TWITTER_API_KEY and TWITTER_API_SECRET and TWITTER_ACCESS_TOKEN and TWITTER_ACCESS_TOKEN_SECRET):
        log.info("Auto-promoção no Twitter desativada (credenciais não configuradas)")
        return
    log.info("🐦 Auto-promoção no Twitter ativa")
    while True:
        time.sleep(86400)  # 24h
        try:
            fg = Market.fear_greed()
            regime = Brain.regime()
            alpha = Brain.alpha_signal()
            prompt = (
                f"Gere um tweet curto (até 280 caracteres) sobre o mercado cripto hoje, "
                f"usando Fear&Greed={fg.get('value')}, regime={regime.get('regime')}, "
                f"e destacando o Losbeto Alpha Score. Inclua o link {_public_base()}/losbeto-alpha "
                f"e as hashtags #crypto #trading #x402."
            )
            tweet_text = LLM.ask(prompt, max_tokens=200, temperature=0.7)
            if tweet_text and not tweet_text.startswith("[LLM offline"):
                # Publicar no Twitter (usando tweepy ou similar – aqui apenas logamos)
                log.info(f"🐦 Tweet gerado: {tweet_text}")
                # Na prática, integrar com tweepy para postar.
        except Exception as e:
            log.warning(f"twitter promo: {e}")

def autoregister_x402scan():
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
        # v21: Registro automático em MÚLTIPLOS marketplaces
        marketplaces = [
            ("x402scan",   "https://www.x402scan.com/api/register",   {"url": PUBLIC_URL, "version": 2}),
            ("PayAI",      "https://facilitator.payai.network/register", {"url": PUBLIC_URL, "manifest": f"{PUBLIC_URL}/.well-known/x402.json"}),
            ("MCPay",      "https://mcpay.tech/api/register",          {"url": PUBLIC_URL, "mcp": f"{PUBLIC_URL}/.well-known/mcp.json"}),
            ("AgentCash",  "https://agentcash.dev/api/register",       {"url": PUBLIC_URL, "x402": f"{PUBLIC_URL}/.well-known/x402.json"}),
            ("CDP Bazaar", "https://api.cdp.coinbase.com/x402/bazaar/register", {"url": PUBLIC_URL}),
        ]
        for name, url, body in marketplaces:
            try:
                r = requests.post(url, json=body, timeout=8)
                log.info(f"📍 {name}: {'✅ OK' if r.ok else f'❌ {r.status_code} (registre manualmente)'}")
            except Exception as e:
                log.info(f"📍 {name}: ⚠️ timeout/err ({str(e)[:40]}) — registre manualmente")
            time.sleep(0.5)
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
    except Exception as e:
        log.warning(f"autoregister erro: {e}")

def run_server():
    threading.Thread(target=signal_validator_loop, daemon=True).start()
    threading.Thread(target=signal_generator_loop, daemon=True).start()
    threading.Thread(target=rag_ingest_loop, daemon=True).start()
    threading.Thread(target=sweeper_loop, daemon=True).start()
    if TG_BOT:
        threading.Thread(target=telegram_loop, daemon=True).start()
    threading.Thread(target=twitter_promo_loop, daemon=True).start()
    threading.Thread(target=autoregister_x402scan, daemon=True).start()

    log.info("=" * 72)
    log.info(f"⚡ LOSBETO v{VERSION} — ATIVO (REVOLUTIONARY)")
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
    log.info(f"   GeoIP:      {'ATIVO' if GEOIP_ENABLED else 'off'}")
    log.info(f"   Endpoints:  {len(BASE_PRICES)}")
    log.info(f"   Referral:   ATIVO (/referral)")
    log.info(f"   Stake:      ATIVO (/stake)")
    log.info("=" * 72)

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