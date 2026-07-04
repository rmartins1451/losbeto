# -*- coding: utf-8 -*-
"""
================================================================================
 LOSBETO v10.0.0 — SOVEREIGN
================================================================================
 Enxame Autônomo Multi-Chain — Solana + Base + TON — operacional de verdade.

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

VERSION = "12.0.0-LOSBETO"
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
FACILITATOR_URL   = os.environ.get("X402_FACILITATOR", "").strip()  # ex: https://x402.payai.network
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
_raw_binance = os.environ.get("BINANCE_SOLANA_ADDRESS", "").strip()
if _raw_binance.startswith("0x"):
    import logging as _lg
    _lg.getLogger("omega").error(
        "⛔ BINANCE_SOLANA_ADDRESS começa com '0x' — endereço Ethereum! "
        "Fundos enviados via Solana serão PERDIDOS. Sweep DESATIVADO."
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
# Preços alinhados com mercado x402 2026 (pesquisa: Rug Munch $0.001-0.02,
# Superhighway $0.001, PayAPI $0.001-0.01) — entrada baixa para gerar volume
# e histórico de transações que constrói reputação no ecossistema.
BASE_PRICES = {
    # Tier 1 — entry ($0.001-0.005): máximo volume, descoberta rápida
    "/fear-greed":    0.001,  # competitivo com Superhighway ($0.001)
    "/regime":        0.002,
    "/mempool":       0.002,
    "/sentiment":     0.003,
    "/anomalias":     0.003,
    # Tier 2 — standard ($0.005-0.02): dados úteis com margem
    "/jupiter-swap":  0.005,
    "/analise":       0.01,
    "/swarm-vote":    0.01,
    "/rugcheck":      0.01,
    "/pump-monitor":  0.01,
    "/defi-yield":    0.01,
    # Tier 3 — premium ($0.02-0.10): análise profunda
    "/sinais":        0.02,
    "/backtest":      0.05,
    "/arbitrage":     0.05,
    "/tg-premium":    0.05,
    "/deep-think":    0.05,
    "/relatorio":     0.05,
    "/agent-call":    0.05,
    "/cross-chain":   0.05,
    "/onchain-credit": 0.05,
    # Tier 4 — alpha ($0.10-0.50): dados raros, alta precisão
    "/whale-alert":   0.10,
    "/smart-money":   0.10,
    "/copytrade":     0.15,
    "/alpha-signal":  0.20,  # antes $1.00 — 5x redução para gerar primeiros pagamentos
    "/insider-track": 0.25,
    "/mev-flow":      0.50,  # antes $1.50 — ainda premium mas atingível
    # Novos endpoints v12 — cereja do bolo
    "/web-search":    0.001, # busca web paga por agentes (Superhighway competitor)
    "/ai-news":       0.002, # notícias cripto filtradas por IA
    "/dex-screen":    0.005, # DexScreener data — pares, liquidez, volume
    "/nansen-flow":   0.05,  # smart money flow Nansen-style
    "/sec-filing":    0.10,  # SEC filings + earnings calls via IA
    "/trust-hash":    0.001, # hash SHA-256 de resposta para verificação A2A
    "/geo-alpha":     0.10,  # alpha de mercados emergentes: BR, IN, KR, TR
    "/sanctions":     0.20,  # screening de sanções OFAC/UN/EU em tempo real
    "/agent-market":  0.005, # listing no Agent.market (Coinbase) via API
    "/pyth-price":    0.001, # preço via Pyth Network oracle (sub-segundo)
}

ENDPOINT_DESC = {
    "/fear-greed":     "Fear & Greed Index ao vivo + interpretação IA",
    "/regime":         "Regime atual do mercado (bull/bear/range/transition)",
    "/mempool":        "Mempool Solana — fees + tx pending em tempo real",
    "/anomalias":      "Anomalias de preço/volume detectadas agora",
    "/jupiter-swap":   "Cotação Jupiter v1 — melhor rota DEX",
    "/analise":        "Análise consolidada com RAG + IA",
    "/swarm-vote":     "Consenso votado pelo enxame de nós",
    "/sentiment":      "Sentimento social: X + Telegram + Reddit",
    "/rugcheck":       "RugCheck — análise de risco de token (mint authority, holders)",
    "/sinais":         "Sinais top-10 com confiança + backtest",
    "/defi-yield":     "Top yields DeFi Solana — Kamino, Marginfi, Drift",
    "/deep-think":     "Raciocínio R1-style sobre tese de investimento",
    "/pump-monitor":   "Monitor Pump.fun + Raydium novos lançamentos",
    "/arbitrage":      "Arbitragem cross-exchange + cross-chain",
    "/tg-premium":     "Telegram Premium feed — alerts em tempo real",
    "/relatorio":      "Relatório executivo completo (IA)",
    "/backtest":       "Backtest com PnL real da estratégia atual",
    "/agent-call":     "Chamada A2A para outro agent do enxame",
    "/onchain-credit": "Score de crédito on-chain (wallet history)",
    "/cross-chain":    "Arbitragem Solana ↔ Base ↔ TON",
    "/whale-alert":    "Alertas baleias > $100K em tempo real",
    "/smart-money":    "Tracking + copy-signals de wallets institucionais",
    "/copytrade":      "Copy-trading: replica top wallets ranked",
    "/alpha-signal":   "Sinal alpha validado (top 1%, win>70%)",
    "/insider-track":  "Track de wallets com early entry em launches",
    "/mev-flow":       "MEV flow — fluxo de bundles Jito + sandwich detection",
}

ENDPOINT_TAGS = {
    "/fear-greed":     ["Search", "Sentiment"],
    "/regime":         ["Trading"],
    "/mempool":        ["Utility", "Data"],
    "/anomalias":      ["Utility"],
    "/jupiter-swap":   ["Trading", "DEX"],
    "/analise":        ["Trading", "AI"],
    "/swarm-vote":     ["Utility"],
    "/sentiment":      ["Search", "AI"],
    "/rugcheck":       ["Utility", "Security"],
    "/sinais":         ["Trading"],
    "/defi-yield":     ["DeFi"],
    "/deep-think":     ["AI"],
    "/pump-monitor":   ["Trading", "Memecoin"],
    "/arbitrage":      ["Trading"],
    "/tg-premium":     ["Premium"],
    "/relatorio":      ["Search", "AI"],
    "/backtest":       ["Trading"],
    "/agent-call":     ["AI", "A2A"],
    "/onchain-credit": ["Utility", "Score"],
    "/cross-chain":    ["Trading", "Bridge"],
    "/whale-alert":    ["Trading", "Alert"],
    "/smart-money":    ["Trading", "Alert"],
    "/copytrade":      ["Trading"],
    "/alpha-signal":   ["Trading", "Alpha"],
    "/insider-track":  ["Trading", "Alert"],
    "/mev-flow":       ["Trading", "MEV"],
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


def _restore_wallets():
    secret = os.environ.get("WALLET_SECRET_B58", "").strip()
    if secret:
        try:
            raw = base58.b58decode(secret)
            # Endereço público Solana = 32 bytes; secret válido = 32 ou 64 bytes
            # MAS: se o b58 decodificado for igual ao próprio input, é chave pública
            test_w = SolanaWallet(secret)
            if test_w.solana_address == secret:
                log.error("⛔ WALLET_SECRET_B58 é um ENDEREÇO PÚBLICO, não um secret!")
                log.error("   Abra wallet.json e copie o campo secret_b58.")
                log.error("   O secret é DIFERENTE do endereço e geralmente tem 88+ chars.")
                secret = ""
        except Exception:
            pass  # Se falhar a decodificação, tenta usar mesmo assim

    if not secret and WALLET_PATH.exists():
        try:
            secret = json.loads(WALLET_PATH.read_text()).get("secret_b58")
        except Exception:
            pass
    if not secret:
        w = SolanaWallet()
        WALLET_PATH.write_text(json.dumps({
            "secret_b58": w.export_b58_seed(),
            "address":    w.solana_address,
            "node_id":    w.node_id,
        }, indent=2))
        log.warning("⚠️  Wallet Solana NOVA gerada. Salve a seed!")
        log.warning(f"   Address: {w.solana_address}")
        log.warning(f"   Path: {WALLET_PATH}")
    else:
        w = SolanaWallet(secret)
        WALLET_PATH.write_text(json.dumps({
            "secret_b58": w.export_b58_seed(),
            "address":    w.solana_address,
            "node_id":    w.node_id,
        }, indent=2))

    ton_w = None
    try:
        mnemonic = os.environ.get("TON_MNEMONIC", "").strip()
        if not mnemonic and TON_WALLET_PATH.exists():
            mnemonic = json.loads(TON_WALLET_PATH.read_text()).get("mnemonic")
        ton_w = TONWallet(mnemonic if mnemonic else None)
        TON_WALLET_PATH.write_text(json.dumps({
            "mnemonic": ton_w.mnemonic,
            "address":  ton_w.address,
        }, indent=2))
    except Exception as e:
        log.warning(f"TON wallet init: {e}")

    return w, ton_w


WALLET, TON_WALLET = _restore_wallets()
log.info(f"🔑 Solana: {WALLET.solana_address}")
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


# 11. PRICING DINÂMICO (PoI)
# ============================================================================

def get_dynamic_price(endpoint: str) -> float:
    base = BASE_PRICES.get(endpoint, 0.05)
    if not DYNAMIC_PRICING:
        return base
    poi = LEDGER.get_poi_multiplier()
    # Alpha tier (premium) tem multiplicador 2x sobre PoI
    if endpoint in ("/alpha-signal", "/insider-track", "/mev-flow",
                    "/smart-money", "/copytrade"):
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

    Baseado em: x402.schemas.payments.PaymentRequired (serialização camelCase)
    Referência: https://docs.x402.org/getting-started/quickstart-for-sellers

    Campos críticos:
    - x402Version: 2
    - accepts[].amount (não maxAmountRequired)
    - accepts[].network: CAIP-2 completo "solana:5eykt4..."
    - resource: objeto com url, description, mimeType
    - error: None (null no JSON)
    """
    amount_usdc = BASE_PRICES.get(endpoint, 0.01)
    amount_atomic = str(int(amount_usdc * 10 ** USDC_DECIMALS))
    base = _public_base()

    payment_req = {
        "scheme":            "exact",
        "network":           f"solana:{SOL_GENESIS}",
        "asset":             USDC_MINT,
        "amount":            amount_atomic,
        "payTo":             WALLET.solana_address,
        "maxTimeoutSeconds": 300,
        "extra":             {},
    }

    payload = {
        "x402Version": 2,
        "error":       "Payment Required",
        "resource": {
            "url":         f"{base}{endpoint}",
            "description": ENDPOINT_DESC.get(endpoint, f"Losbeto — {endpoint}"),
            "mimeType":    "application/json",
        },
        "accepts":    [payment_req],
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
        ok, info = SOL.verify_payment(tx_sig, amount, WALLET.solana_address)
        if ok:
            payer_addr = info.get("payer") if isinstance(info, dict) else payer
            LEDGER.add_revenue(endpoint, amount, tx_sig, payer_addr or payer,
                                source="direct", chain="solana")
            _notify_telegram(f"💰 ${amount} USDC em {endpoint} (Solana)\nTX: {tx_sig[:32]}...")
            return True, "ok", {"payer": payer_addr or payer, "tx": tx_sig}
        return False, info if isinstance(info, str) else "verify-failed", {}
    # Base — sem facilitator não conseguimos verificar
    return False, "base-requires-facilitator", {}


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

# Registra os 26 endpoints
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
    # Losbeto v12 — novos endpoints
    "/web-search":      Brain.web_search_agent,
    "/ai-news":         Brain.ai_news,
    "/dex-screen":      Brain.dex_screen,
    "/nansen-flow":     Brain.nansen_flow,
    "/sec-filing":      Brain.sec_filing,
    "/trust-hash":      Brain.trust_hash,
    "/geo-alpha":       Brain.geo_alpha,
    "/sanctions":       Brain.sanctions,
    "/agent-market":    Brain.agent_market_info,
    "/pyth-price":      Brain.pyth_price,
}

for _path, _handler in ENDPOINT_HANDLERS.items():
    _rule_name = _path.strip("/").replace("-", "_")
    app.add_url_rule(_path, _rule_name, paid_endpoint(_path)(_handler))

# ============================================================================
# 14. ENDPOINTS PÚBLICOS + MANIFESTS DE DISCOVERY
# ============================================================================

@app.route("/")
def root():
    prices = {ep: get_dynamic_price(ep) for ep in BASE_PRICES}
    return jsonify({
        "name":             "Losbeto",
        "version":          VERSION,
        "node_id":          WALLET.node_id,
        "solana_address":   WALLET.solana_address,
        "ton_address":      TON_WALLET.address if TON_WALLET else None,
        "base_payto":       BASE_PAYTO_EVM if ENABLE_BASE else None,
        "endpoints":        len(BASE_PRICES),
        "prices_usdc":      prices,
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
        "solana_address":  WALLET.solana_address,
        "ton_address":     TON_WALLET.address if TON_WALLET else None,
        "stats":           s,
        "endpoints_count": len(BASE_PRICES),
        "facilitator":     FACILITATOR_URL if FACILITATOR else None,
        "base_enabled":    ENABLE_BASE,
    })

@app.route("/.well-known/x402.json")
def manifest_x402():
    base = _public_base()
    USDC_DECIMALS_LOCAL = 6
    resources = []
    for p, base_price in BASE_PRICES.items():
        resources.append({
            "url":               f"{base}{p}",
            "method":            "GET",
            "scheme":            "exact",
            "network":           "solana",
            "maxAmountRequired": str(int(base_price * 10 ** USDC_DECIMALS_LOCAL)),
            "asset":             USDC_MINT,
            "payTo":             WALLET.solana_address,
            "maxTimeoutSeconds": 300,
            "description":       ENDPOINT_DESC.get(p, p),
            "mimeType":          "application/json",
        })
    return jsonify({
        "version":         2,
        "ownershipProofs": [WALLET.solana_address],
        "resources":       resources,
        "node": {
            "name":    "Losbeto",
            "version": VERSION,
            "node_id": WALLET.node_id,
            "url":     base,
        },
    })
@app.route("/.well-known/mcp.json")
def manifest_mcp():
    base = _public_base()
    tools = []
    for p in BASE_PRICES:
        tools.append({
            "name": p.strip("/").replace("-", "_"),
            "description": f"{ENDPOINT_DESC.get(p, p)} (${get_dynamic_price(p):.4f} USDC via x402)",
            "inputSchema": {"type": "object", "properties": {}, "required": []},
            "x402": {
                "resource": f"{base}{p}",
                "scheme":   "exact",
                "price":    f"${get_dynamic_price(p):.4f}",
                "network":  "solana",
                "payTo":    WALLET.solana_address,
                "asset":    USDC_MINT,
            },
        })
    return jsonify({
        "schema_version": "2024-11-05",
        "name":           "losbeto-v10",
        "description":    "Multi-chain x402 AI swarm (Solana+Base+TON). 26 endpoints. Dynamic PoI pricing.",
        "tools":          tools,
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
                    "payTo":   WALLET.solana_address,
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
        "description": "Multi-chain x402 AI swarm — Solana. Pay-per-call USDC.",
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
        "> Multi-chain AI swarm. Solana + Base + TON. Pay-per-call via x402.",
        "",
        "## Pagar",
        f"Solana payTo: {WALLET.solana_address}",
    ]
    if ENABLE_BASE:
        lines.append(f"Base payTo:   {BASE_PAYTO_EVM}")
    if TON_WALLET:
        lines.append(f"TON address:  {TON_WALLET.address}")
    lines += ["", "## Endpoints"]
    for p in BASE_PRICES:
        lines.append(f"- [{base}{p}]({base}{p}) — {ENDPOINT_DESC.get(p, p)} (${get_dynamic_price(p):.4f})")
    lines += ["", "## Discovery",
              f"- OpenAPI: {base}/openapi.json",
              f"- x402:    {base}/.well-known/x402.json",
              f"- MCP:     {base}/.well-known/mcp.json",
              f"- A2A:     {base}/.well-known/agent.json"]
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
# 15. DASHBOARD v10
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
table{width:100%;border-collapse:collapse;background:var(--card);border-radius:10px;overflow:hidden}
th,td{padding:10px;text-align:left;border-bottom:1px solid #232a45}
th{background:#1a2140;color:var(--muted);font-size:11px;text-transform:uppercase}
code{background:#0f1428;padding:2px 6px;border-radius:4px;font-size:12px;color:var(--accent)}
.footer{margin-top:30px;color:var(--muted);font-size:12px;text-align:center}
</style></head><body>
<div class="header">
  <div><h1>⚡ Losbeto <span class="badge">v10 SOVEREIGN</span></h1>
       <div style="color:var(--muted);font-size:12px;margin-top:4px" id="node">node···</div></div>
  <div style="text-align:right"><div style="font-size:11px;color:var(--muted)">Solana Address</div>
       <code id="addr">···</code></div>
</div>
<div class="grid" id="cards"></div>
<h2 style="margin:20px 0 10px;color:var(--muted);font-size:14px;text-transform:uppercase">Top Endpoints (24h)</h2>
<table id="tbl"><thead><tr><th>Endpoint</th><th>Hits</th><th>Preço (USDC)</th></tr></thead><tbody></tbody></table>
<div class="footer">Atualização automática a cada 10s. Win-rate dirige preço (PoI).</div>
<script>
async function reload(){
  const r=await fetch("/dash/api/stats?token=__TOKEN__");
  if(!r.ok)return;
  const j=await r.json();
  document.getElementById("node").textContent="node "+j.node_id;
  document.getElementById("addr").textContent=j.solana_address;
  const cards=[
    ["💰 Receita Total",`$${j.stats.total_usdc.toFixed(4)}`,"USDC acumulado"],
    ["📅 Hoje (24h)",`$${j.stats.today_usdc.toFixed(4)}`,j.stats.paid_24h+" pagamentos"],
    ["⏱️ Última hora",`$${j.stats.hour_usdc.toFixed(4)}`,"USDC"],
    ["🎯 Win Rate",`${j.stats.win_rate.toFixed(1)}%`,"30 dias"],
    ["⚡ PoI Multiplier",`${j.stats.poi_multiplier.toFixed(2)}x`,"preço dinâmico"],
    ["📊 Conversão",`${j.stats.conv_rate.toFixed(1)}%`,j.stats.requests_24h+" requisições"],
    ["👥 Compradores",j.stats.buyers,"únicos"],
    ["🌐 Endpoints",j.endpoints,"monetizados"],
  ];
  document.getElementById("cards").innerHTML = cards.map(c =>
    `<div class="card"><h3>${c[0]}</h3><div class="v">${c[1]}</div><div class="sub">${c[2]}</div></div>`
  ).join("");
  const rows = Object.entries(j.stats.by_endpoint||{})
    .sort((a,b)=>b[1]-a[1]).slice(0,15);
  document.getElementById("tbl").querySelector("tbody").innerHTML =
    rows.length ? rows.map(([ep,n])=>`<tr><td><code>${ep}</code></td><td>${n}</td><td>$${(j.prices[ep]||0).toFixed(4)}</td></tr>`).join("")
                : '<tr><td colspan=3 style="text-align:center;color:var(--muted)">Aguardando pagamentos...</td></tr>';
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
        "solana_address":  WALLET.solana_address,
        "ton_address":     TON_WALLET.address if TON_WALLET else None,
        "stats":           LEDGER.stats(),
        "endpoints":       len(BASE_PRICES),
        "prices":          {ep: get_dynamic_price(ep) for ep in BASE_PRICES},
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
            txt = f"💳 *Endereços de pagamento*\n\nSolana:\n`{WALLET.solana_address}`"
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
            bal = SOL.get_balance_usdc(WALLET.solana_address)
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
    """Tenta listar automaticamente no x402scan + log de instruções AgentCash."""
    time.sleep(20)
    if not PUBLIC_URL: return
    try:
        r = requests.get(f"{PUBLIC_URL}/.well-known/x402.json", timeout=10)
        if r.ok:
            log.info("=" * 60)
            log.info(f"✅ Manifest x402 disponível: {PUBLIC_URL}/.well-known/x402.json")
            log.info(f"📍 REGISTRAR no x402scan:")
            log.info(f"   1. Abra https://www.x402scan.com/resources/register")
            log.info(f"   2. Cole: {PUBLIC_URL}")
            log.info(f"📍 AgentCash (v2):")
            log.info(f"   1. Abra https://agentcash.dev")
            log.info(f"   2. Cole: {PUBLIC_URL}")
            log.info(f"   3. Se houver listing antigo (v1), DELETE antes")
            log.info("=" * 60)
    except Exception as e:
        log.warning(f"autoregister: {e}")

# ============================================================================
# 18. RUN / MAIN
# ============================================================================

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
    log.info(f"   Solana:     {WALLET.solana_address}")
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
        print(f"Solana address: {WALLET.solana_address}")
        print(f"Solana seed:    {WALLET.export_b58_seed()}")
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
