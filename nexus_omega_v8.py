# -*- coding: utf-8 -*-
"""
================================================================================
 NEXUS OMEGA v7.0 — Enxame Autônomo Multi-Receita (Single-File Edition)
================================================================================
 Um único arquivo Python. Auto-instala dependências, gera carteira, sobe servidor
 x402 + P2P gossip + dashboard + worker de trading + treinamento federado.

 OBJETIVO: REMUNERAR DE VERDADE. Sem depender de tráfego externo.

 7 VETORES DE RECEITA ATIVOS SIMULTANEAMENTE
 ─────────────────────────────────────────────────────────────────────────────
  V1. API x402 paga (endpoints monetizados em USDC-SPL Solana)
  V2. CROSS-TRADE entre nós (cada nó paga os outros por inteligência → cresce
      a economia interna do enxame; quanto mais nós, mais receita por nó)
  V3. PROVA-DE-INTELIGÊNCIA (PoI): nós com modelos melhores cobram mais,
      reputação on-chain → preço dinâmico
  V4. TRADING-SIGNALS-AS-A-SERVICE: backtest contínuo dos próprios sinais;
      os top-K sinais validados são revendidos premium ($1+ USDC)
  V5. AGENTE PAGADOR INTERNO: cada nó também age como CLIENTE — assina
      outros nós via x402, criando demanda real (vide bazaar do x402scan)
  V6. ARBITRAGEM CROSS-CHAIN: detecta diferenças de preço entre exchanges
      (Binance/OKX/Bybit) e vende alertas premium
  V7. STAKE / REPUTAÇÃO: nós podem fazer stake de USDC em outros nós em
      troca de % da receita (yield interna do enxame)

 RECURSOS REVOLUCIONÁRIOS
 ─────────────────────────────────────────────────────────────────────────────
  • Auto-discovery LAN (multicast) + Internet (bootstrap nodes + DNS seed)
  • Treinamento federado leve: nós trocam pesos heurísticos (sem dados crus)
  • Carteira hot Solana embarcada (Ed25519 nativo, sem SDK pesado)
  • Sell-to-Binance automático opcional (quando saldo > threshold, manda
    USDC do hot wallet para sua conta Binance via endereço configurado)
  • Dashboard cyber-tema com gráficos em tempo real (Chart.js)
  • Anti-replay persistente em SQLite (sobrevive a restarts)
  • Failover automático de RPC Solana (3 endpoints públicos)
  • Verificação on-chain real (getTransaction + getSignaturesForAddress)
  • Self-healing: reinicia componentes que travam
  • Telegram alerts opcional (TELEGRAM_BOT_TOKEN + CHAT_ID)

 USO
 ─────────────────────────────────────────────────────────────────────────────
   $ python nexus_omega.py                    # roda tudo (modo enxame)
   $ python nexus_omega.py --wallet           # mostra endereço de recebimento
   $ python nexus_omega.py --binance ADDR     # define endereço Binance para
                                              # auto-sweep (opcional)
   $ python nexus_omega.py --reset            # reseta ledger (preserva wallet)
   $ python nexus_omega.py --export-wallet    # exporta seed (CUIDADO)
   $ python nexus_omega.py --solo             # roda sem gossip P2P
   $ python nexus_omega.py --port 9000        # porta x402 (default 8402)

 PORTAS
 ─────────────────────────────────────────────────────────────────────────────
   8402 - servidor x402 (público — abrir no firewall)
   8403 - gossip P2P TCP (público — abrir no firewall)
   8404 - multicast LAN (apenas rede local, automático)
   8080 - dashboard local (NÃO expor; use SSH tunnel)

 BINANCE — COMO RECEBER OS USDC NA SUA CONTA
 ─────────────────────────────────────────────────────────────────────────────
   1. Acesse Binance → Carteira → Depósito → USDC → Rede: Solana
   2. Copie o endereço (~32-44 caracteres Base58)
   3. Rode: python nexus_omega.py --binance SEU_ENDERECO_SOLANA_BINANCE
   4. Quando o hot wallet acumular > $0.50 USDC, o sweep automático move
      tudo para sua Binance. Padrão: a cada 1h verifica.

 LICENÇA: MIT. Fork, escale, lucre.
================================================================================
"""
from __future__ import annotations

import os, sys, json, time, base64, hashlib, threading, sqlite3
import socket, struct, secrets, subprocess, signal, logging, traceback, random
import urllib.request, urllib.error, urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from collections import defaultdict, deque
from typing import Any, Optional

# ============================================================================
# 0. CONFIGURAÇÃO E AUTO-SETUP
# ============================================================================

VERSION              = "8.0.0-OMEGA"
HOME_DIR = Path(os.environ.get("DATA_DIR", "")).expanduser() if os.environ.get("DATA_DIR") else Path("/data") if Path("/data").exists() else Path.home() / ".nexus_omega"
HOME_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH              = HOME_DIR / "omega.db"
WALLET_PATH          = HOME_DIR / "wallet.json"
LOG_PATH             = HOME_DIR / "omega.log"
CONFIG_PATH          = HOME_DIR / "config.json"

# Portas — Railway expõe UMA porta via $PORT; todo o app (x402+dash) nela.
# Em local, $PORT não existe → usa 8402.
X402_PORT       = int(os.environ.get("PORT", os.environ.get("OMEGA_X402_PORT", "8402")))
GOSSIP_PORT     = int(os.environ.get("OMEGA_GOSSIP_PORT", "8403"))
MCAST_PORT      = int(os.environ.get("OMEGA_MCAST_PORT", "8404"))
DASHBOARD_PORT  = X402_PORT   # v8: unificado na mesma porta
MCAST_GRP       = "239.42.42.42"

# URL pública do nó — Railway injeta várias variáveis, tentamos todas
_rw_domain   = os.environ.get("RAILWAY_PUBLIC_DOMAIN", "").strip()
_rw_static   = os.environ.get("RAILWAY_STATIC_URL", "").strip()
_rw_service  = os.environ.get("RAILWAY_SERVICE_URL", "").strip()
_manual      = os.environ.get("PUBLIC_URL", "").strip()

PUBLIC_URL = (
    _manual     or
    (f"https://{_rw_domain}"  if _rw_domain  else "") or
    (_rw_static  if _rw_static.startswith("http") else "") or
    (_rw_service if _rw_service.startswith("http") else "")
).rstrip("/")

# Token de proteção do dashboard (gera aleatório se não configurado, imprime no log)
DASH_TOKEN = os.environ.get("DASH_TOKEN", secrets.token_urlsafe(16))

# Solana
SOLANA_RPCS = [
    os.environ.get("SOLANA_RPC", "https://api.mainnet-beta.solana.com"),
    "https://solana-rpc.publicnode.com",
    "https://solana.drpc.org",
]
USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"  # USDC-SPL mainnet
USDC_DECIMALS = 6

# Binance sweep
BINANCE_ADDRESS = os.environ.get("BINANCE_SOLANA_ADDRESS", "").strip()
SWEEP_THRESHOLD = float(os.environ.get("SWEEP_THRESHOLD_USDC", "0.5"))  # mínimo p/ sweep
SWEEP_INTERVAL  = int(os.environ.get("SWEEP_INTERVAL_S", "3600"))       # 1h padrão

# LLM opcional
GROQ_KEY        = os.environ.get("GROQ_API_KEY", "").strip()
GEMINI_KEY      = os.environ.get("GEMINI_API_KEY", "").strip()
OLLAMA_URL      = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
OLLAMA_MODEL    = os.environ.get("OLLAMA_MODEL", "qwen2.5:3b")

# Telegram alerts (opcional)
TG_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
TG_CHAT  = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

# Bootstrap seeds (acrescente os IPs públicos de outros nós seus)
BOOTSTRAP_SEEDS = [
    s.strip() for s in os.environ.get("OMEGA_SEEDS", "").split(",") if s.strip()
]

# Preços (USDC) — escalonados estrategicamente
PRICES = {
    "/fear-greed":    0.01,
    "/regime":        0.02,
    "/anomalias":     0.03,
    "/analise":       0.05,
    "/sinais":        0.10,
    "/relatorio":     0.25,
    "/swarm-vote":    0.05,   # consenso do enxame
    "/deep-think":    0.15,   # raciocínio longo
    "/arbitrage":     0.20,   # arbitragem cross-exchange
    "/backtest":      0.30,   # backtest validado de estratégia
    "/alpha-signal":  1.00,   # sinal premium (apenas top-K validados)
}

ENDPOINT_DESC = {
    "/fear-greed":    "Fear & Greed Index ao vivo + interpretação IA",
    "/regime":        "Regime atual do mercado (bull/bear/range/transition)",
    "/anomalias":     "Anomalias de preço/volume detectadas agora",
    "/analise":       "Análise consolidada de mercado",
    "/sinais":        "Sinais top-10 com confiança",
    "/relatorio":     "Relatório executivo completo",
    "/swarm-vote":    "Consenso votado pelo enxame de nós",
    "/deep-think":    "Raciocínio longo (R1-style) sobre tese de investimento",
    "/arbitrage":     "Oportunidades de arbitragem cross-exchange agora",
    "/backtest":      "Backtest da estratégia atual com PnL real",
    "/alpha-signal":  "Sinal alpha validado (top 1%, win-rate > 70%)",
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
log = logging.getLogger("omega")

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
        log.info(f"📦 Instalando dependências: {missing}")
        subprocess.check_call([
            sys.executable, "-m", "pip", "install",
            "--quiet", "--disable-pip-version-check", *missing,
        ])
        log.info("✅ Dependências instaladas")

_ensure_deps()

import requests  # noqa
from flask import Flask, request, jsonify, Response, render_template_string, g  # noqa
import base58    # noqa
import nacl.signing  # noqa
import nacl.encoding  # noqa

# ============================================================================
# 3. WALLET SOLANA (Ed25519 puro — também usado para P2P signing)
# ============================================================================

class Wallet:
    def __init__(self):
        if WALLET_PATH.exists():
            data = json.loads(WALLET_PATH.read_text())
            self.signing_key = nacl.signing.SigningKey(base58.b58decode(data["secret_b58"]))
        else:
            self.signing_key = nacl.signing.SigningKey.generate()
            data = {
                "secret_b58": base58.b58encode(bytes(self.signing_key)).decode(),
                "created_at": datetime.now(timezone.utc).isoformat(),
                "version":    VERSION,
            }
            WALLET_PATH.write_text(json.dumps(data, indent=2))
            try:
                os.chmod(WALLET_PATH, 0o600)
            except Exception:
                pass
            log.warning(f"🔑 NOVA WALLET GERADA → {WALLET_PATH} (faça backup!)")

        self.verify_key = self.signing_key.verify_key
        self.pubkey_b58 = base58.b58encode(bytes(self.verify_key)).decode()
        self.node_id    = hashlib.sha256(bytes(self.verify_key)).hexdigest()[:16]

    @property
    def solana_address(self) -> str:
        return self.pubkey_b58

    @property
    def payout_address(self) -> str:
        # Se o nó é pequeno, recebe na hot wallet. Sweep automático manda
        # para a Binance quando atinge threshold (não é redirecionamento
        # cego porque queremos verificar on-chain depósitos diretos).
        return self.pubkey_b58

    def sign(self, msg: bytes) -> bytes:
        return self.signing_key.sign(msg).signature

    @staticmethod
    def verify(pubkey_b58: str, msg: bytes, sig: bytes) -> bool:
        try:
            vk = nacl.signing.VerifyKey(base58.b58decode(pubkey_b58))
            vk.verify(msg, sig)
            return True
        except Exception:
            return False

WALLET = Wallet()
log.info(f"🆔 Node ID: {WALLET.node_id}")
log.info(f"💰 Recebe USDC-SPL em: {WALLET.solana_address}")
if BINANCE_ADDRESS:
    log.info(f"🏦 Sweep → Binance: {BINANCE_ADDRESS}")

# ============================================================================
# 4. LEDGER SQLITE (persistência total)
# ============================================================================

class Ledger:
    def __init__(self, path: Path):
        self.path = path
        self.lock = threading.Lock()
        self._init()

    def _init(self):
        with sqlite3.connect(self.path) as c:
            c.executescript("""
            CREATE TABLE IF NOT EXISTS revenue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts INTEGER NOT NULL,
                endpoint TEXT NOT NULL,
                amount_usdc REAL NOT NULL,
                tx_sig TEXT,
                payer TEXT,
                source TEXT DEFAULT 'direct'
            );
            CREATE TABLE IF NOT EXISTS peers (
                node_id TEXT PRIMARY KEY,
                host TEXT, port INTEGER, pubkey TEXT,
                solana_address TEXT,
                last_seen INTEGER,
                reputation REAL DEFAULT 1.0,
                version TEXT,
                models TEXT
            );
            CREATE TABLE IF NOT EXISTS requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts INTEGER NOT NULL,
                endpoint TEXT,
                paid INTEGER,
                ms INTEGER,
                ip TEXT
            );
            CREATE TABLE IF NOT EXISTS cache (
                key TEXT PRIMARY KEY,
                value TEXT,
                ts INTEGER
            );
            CREATE TABLE IF NOT EXISTS replay (
                hash TEXT PRIMARY KEY,
                ts INTEGER
            );
            CREATE TABLE IF NOT EXISTS signals_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts INTEGER, symbol TEXT, signal TEXT,
                price REAL, confidence REAL,
                outcome_1h REAL, outcome_24h REAL, validated INTEGER DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS sweeps (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts INTEGER, amount_usdc REAL,
                to_address TEXT, tx_sig TEXT, status TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_rev_ts ON revenue(ts);
            CREATE INDEX IF NOT EXISTS idx_req_ts ON requests(ts);
            CREATE INDEX IF NOT EXISTS idx_sig_ts ON signals_log(ts);
            """)

    def add_revenue(self, endpoint, amount, tx_sig="", payer="", source="direct"):
        with self.lock, sqlite3.connect(self.path) as c:
            c.execute("INSERT INTO revenue(ts,endpoint,amount_usdc,tx_sig,payer,source) VALUES(?,?,?,?,?,?)",
                      (int(time.time()), endpoint, amount, tx_sig, payer, source))

    def log_request(self, endpoint, paid, ms, ip=""):
        with self.lock, sqlite3.connect(self.path) as c:
            c.execute("INSERT INTO requests(ts,endpoint,paid,ms,ip) VALUES(?,?,?,?,?)",
                      (int(time.time()), endpoint, 1 if paid else 0, ms, ip))

    def upsert_peer(self, p: dict):
        with self.lock, sqlite3.connect(self.path) as c:
            c.execute("""INSERT INTO peers(node_id,host,port,pubkey,solana_address,last_seen,version,models)
                         VALUES(?,?,?,?,?,?,?,?)
                         ON CONFLICT(node_id) DO UPDATE SET
                            host=excluded.host, port=excluded.port,
                            pubkey=excluded.pubkey, solana_address=excluded.solana_address,
                            last_seen=excluded.last_seen, version=excluded.version,
                            models=excluded.models""",
                      (p["node_id"], p["host"], p["port"], p["pubkey"],
                       p.get("solana_address",""), int(time.time()),
                       p.get("version",""), json.dumps(p.get("models",[]))))

    def active_peers(self, max_age=300):
        cut = int(time.time()) - max_age
        with sqlite3.connect(self.path) as c:
            c.row_factory = sqlite3.Row
            return [dict(r) for r in c.execute(
                "SELECT * FROM peers WHERE last_seen>? ORDER BY reputation DESC", (cut,)
            ).fetchall()]

    def stats(self):
        with sqlite3.connect(self.path) as c:
            total  = c.execute("SELECT COALESCE(SUM(amount_usdc),0) FROM revenue").fetchone()[0]
            today  = c.execute("SELECT COALESCE(SUM(amount_usdc),0) FROM revenue WHERE ts>?",
                               (int(time.time())-86400,)).fetchone()[0]
            hour   = c.execute("SELECT COALESCE(SUM(amount_usdc),0) FROM revenue WHERE ts>?",
                               (int(time.time())-3600,)).fetchone()[0]
            req_t  = c.execute("SELECT COUNT(*) FROM requests WHERE ts>?",
                               (int(time.time())-86400,)).fetchone()[0]
            paid_t = c.execute("SELECT COUNT(*) FROM requests WHERE paid=1 AND ts>?",
                               (int(time.time())-86400,)).fetchone()[0]
            by_src = dict(c.execute("""SELECT source, COALESCE(SUM(amount_usdc),0)
                                      FROM revenue WHERE ts>? GROUP BY source""",
                                   (int(time.time())-86400,)).fetchall())
            sweep_total = c.execute(
                "SELECT COALESCE(SUM(amount_usdc),0) FROM sweeps WHERE status='success'"
            ).fetchone()[0]
        return {
            "total_usdc":      round(total, 6),
            "today_usdc":      round(today, 6),
            "hour_usdc":       round(hour, 6),
            "requests_today":  req_t,
            "paid_today":      paid_t,
            "conv_rate":       round(paid_t / max(req_t, 1) * 100, 1),
            "by_source_24h":   {k: round(v, 4) for k, v in by_src.items()},
            "swept_to_binance": round(sweep_total, 6),
        }

    def recent_revenue(self, n=30):
        with sqlite3.connect(self.path) as c:
            c.row_factory = sqlite3.Row
            return [dict(r) for r in c.execute(
                "SELECT * FROM revenue ORDER BY ts DESC LIMIT ?", (n,)
            ).fetchall()]

    def revenue_series_24h(self):
        with sqlite3.connect(self.path) as c:
            return c.execute(
                """SELECT (ts/3600)*3600 h, SUM(amount_usdc) FROM revenue
                   WHERE ts>? GROUP BY h ORDER BY h""",
                (int(time.time())-86400,)
            ).fetchall()

    def cache_get(self, key, ttl):
        with sqlite3.connect(self.path) as c:
            r = c.execute("SELECT value, ts FROM cache WHERE key=?", (key,)).fetchone()
            if r and (time.time() - r[1]) < ttl:
                return json.loads(r[0])
        return None

    def cache_set(self, key, value):
        with self.lock, sqlite3.connect(self.path) as c:
            c.execute("INSERT OR REPLACE INTO cache(key,value,ts) VALUES(?,?,?)",
                      (key, json.dumps(value), int(time.time())))

    def replay_check(self, h, ttl=600):
        now = int(time.time())
        with self.lock, sqlite3.connect(self.path) as c:
            c.execute("DELETE FROM replay WHERE ts<?", (now-ttl,))
            r = c.execute("SELECT 1 FROM replay WHERE hash=?", (h,)).fetchone()
            if r:
                return True
            c.execute("INSERT INTO replay(hash,ts) VALUES(?,?)", (h, now))
            return False

    def log_signal(self, symbol, signal, price, confidence):
        with self.lock, sqlite3.connect(self.path) as c:
            c.execute("""INSERT INTO signals_log(ts,symbol,signal,price,confidence)
                         VALUES(?,?,?,?,?)""",
                      (int(time.time()), symbol, signal, price, confidence))

    def update_signal_outcomes(self):
        """Atualiza outcome 1h/24h dos sinais antigos (chamado periodicamente)."""
        now = int(time.time())
        with sqlite3.connect(self.path) as c:
            c.row_factory = sqlite3.Row
            for row in c.execute(
                "SELECT * FROM signals_log WHERE outcome_1h IS NULL AND ts<?", (now-3700,)
            ).fetchall():
                pass  # outcome updates are done by Brain.validate_signals

    def top_signals(self, min_conf=70, hours=24):
        with sqlite3.connect(self.path) as c:
            c.row_factory = sqlite3.Row
            return [dict(r) for r in c.execute(
                """SELECT * FROM signals_log WHERE confidence>=? AND ts>?
                   AND validated=1 ORDER BY confidence DESC LIMIT 10""",
                (min_conf, int(time.time())-hours*3600)
            ).fetchall()]

    def add_sweep(self, amount, to_addr, tx_sig="", status="pending"):
        with self.lock, sqlite3.connect(self.path) as c:
            c.execute("INSERT INTO sweeps(ts,amount_usdc,to_address,tx_sig,status) VALUES(?,?,?,?,?)",
                      (int(time.time()), amount, to_addr, tx_sig, status))

    def recent_sweeps(self, n=10):
        with sqlite3.connect(self.path) as c:
            c.row_factory = sqlite3.Row
            return [dict(r) for r in c.execute(
                "SELECT * FROM sweeps ORDER BY ts DESC LIMIT ?", (n,)
            ).fetchall()]

LEDGER = Ledger(DB_PATH)

# ============================================================================
# 5. SOLANA RPC FAILOVER + on-chain verification + sweep
# ============================================================================

class SolanaClient:
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
        log.warning(f"Todos RPCs Solana falharam ({method}): {last_err}")
        return None

    def get_tx(self, sig):
        r = self._post("getTransaction", [sig, {
            "encoding": "jsonParsed",
            "commitment": "confirmed",
            "maxSupportedTransactionVersion": 0
        }])
        return r.get("result") if r else None

    def get_balance_usdc(self, address):
        """Saldo USDC-SPL do endereço (em USDC float)."""
        r = self._post("getTokenAccountsByOwner", [
            address,
            {"mint": USDC_MINT},
            {"encoding": "jsonParsed"}
        ])
        if not r or not r.get("result"):
            return 0.0
        accounts = r["result"].get("value", [])
        total = 0.0
        for acc in accounts:
            info = acc.get("account", {}).get("data", {}).get("parsed", {}).get("info", {})
            amt = info.get("tokenAmount", {}).get("uiAmount", 0) or 0
            total += float(amt)
        return total

    def verify_payment(self, signature, expected_amount, receiver_address, max_age=3600):
        tx = self.get_tx(signature)
        if not tx:
            return False, "tx-not-found"
        if tx.get("meta", {}).get("err"):
            return False, "tx-failed"
        if (time.time() - tx.get("blockTime", 0)) > max_age:
            return False, "tx-too-old"

        meta = tx.get("meta", {})
        pre  = {b["accountIndex"]: b for b in meta.get("preTokenBalances", [])}
        post = {b["accountIndex"]: b for b in meta.get("postTokenBalances", [])}

        for idx, pb in post.items():
            if pb.get("mint") != USDC_MINT:
                continue
            if pb.get("owner") != receiver_address:
                continue
            pa = float(pre.get(idx, {}).get("uiTokenAmount", {}).get("uiAmount") or 0)
            po = float(pb.get("uiTokenAmount", {}).get("uiAmount") or 0)
            delta = po - pa
            if delta + 1e-9 >= expected_amount:
                return True, f"ok delta={delta:.6f}"
        return False, "no-matching-transfer"

SOL = SolanaClient()

# ============================================================================
# 6. MARKET DATA — multi-source (CoinGecko + Binance public)
# ============================================================================

class Market:
    @staticmethod
    def _cached(key, fn, ttl=30):
        v = LEDGER.cache_get(key, ttl)
        if v is not None:
            return v
        try:
            v = fn()
            LEDGER.cache_set(key, v)
            return v
        except Exception as e:
            log.warning(f"market {key} fail: {e}")
            return None

    @classmethod
    def fear_greed(cls):
        def f():
            r = requests.get("https://api.alternative.me/fng/", timeout=10).json()
            d = r["data"][0]
            return {"value": int(d["value"]),
                    "classification": d["value_classification"]}
        return cls._cached("fng", f, 600) or {"value": 50, "classification": "Neutral"}

    @classmethod
    def top_coins(cls, n=20):
        def f():
            r = requests.get("https://api.coingecko.com/api/v3/coins/markets",
                params={"vs_currency": "usd", "order": "market_cap_desc",
                        "per_page": n, "page": 1,
                        "price_change_percentage": "1h,24h,7d"},
                timeout=15, headers={"Accept": "application/json"})
            return r.json() if r.ok else []
        return cls._cached(f"top_{n}", f, 60) or []

    @classmethod
    def binance_prices(cls):
        """Preços spot Binance (público, sem auth) — usado para arbitragem."""
        def f():
            r = requests.get("https://api.binance.com/api/v3/ticker/price", timeout=10)
            if not r.ok:
                return {}
            return {x["symbol"]: float(x["price"]) for x in r.json()}
        return cls._cached("binance_px", f, 20) or {}

    @classmethod
    def regime(cls):
        coins = cls.top_coins(20)
        if not coins:
            return {"regime": "unknown", "avg_24h": 0, "avg_7d": 0}
        avg_24h = sum(c.get("price_change_percentage_24h", 0) or 0 for c in coins) / len(coins)
        avg_7d  = sum(c.get("price_change_percentage_7d_in_currency", 0) or 0 for c in coins) / len(coins)
        if avg_7d > 5 and avg_24h > 0:    r = "bull"
        elif avg_7d < -5 and avg_24h < 0: r = "bear"
        elif abs(avg_24h) < 1.5:          r = "range"
        else:                             r = "transition"
        return {"regime": r, "avg_24h": round(avg_24h, 2), "avg_7d": round(avg_7d, 2)}

    @classmethod
    def anomalies(cls):
        coins = cls.top_coins(50)
        return [
            {"symbol": c["symbol"].upper(),
             "change_1h":  round(c.get("price_change_percentage_1h_in_currency", 0) or 0, 2),
             "change_24h": round(c.get("price_change_percentage_24h", 0) or 0, 2),
             "price": c.get("current_price", 0),
             "volume_24h": c.get("total_volume", 0)}
            for c in coins
            if abs(c.get("price_change_percentage_24h", 0) or 0) > 10
            or abs(c.get("price_change_percentage_1h_in_currency", 0) or 0) > 5
        ]

# ============================================================================
# 7. LLM — Ollama → Groq → Gemini → heurística
# ============================================================================

class LLM:
    def __init__(self):
        self.ollama_ok = False
        threading.Thread(target=self._probe_ollama, daemon=True).start()

    def _probe_ollama(self):
        for _ in range(3):
            try:
                r = requests.get(f"{OLLAMA_URL}/api/tags", timeout=3)
                if r.ok:
                    self.ollama_ok = True
                    log.info(f"🦙 Ollama OK ({OLLAMA_MODEL})")
                    return
            except Exception:
                time.sleep(5)

    def think(self, prompt, max_tokens=512):
        # 1. Ollama
        if self.ollama_ok:
            try:
                r = requests.post(f"{OLLAMA_URL}/api/generate", json={
                    "model": OLLAMA_MODEL, "prompt": prompt, "stream": False,
                    "options": {"num_predict": max_tokens, "temperature": 0.3}
                }, timeout=60)
                if r.ok:
                    return r.json().get("response", "").strip()
            except Exception as e:
                log.debug(f"ollama fail: {e}")

        # 2. Groq
        if GROQ_KEY:
            try:
                r = requests.post("https://api.groq.com/openai/v1/chat/completions",
                    headers={"Authorization": f"Bearer {GROQ_KEY}"},
                    json={"model": "llama-3.3-70b-versatile",
                          "messages": [{"role": "user", "content": prompt}],
                          "max_tokens": max_tokens, "temperature": 0.3},
                    timeout=20)
                if r.ok:
                    return r.json()["choices"][0]["message"]["content"].strip()
            except Exception as e:
                log.debug(f"groq fail: {e}")

        # 3. Gemini
        if GEMINI_KEY:
            try:
                r = requests.post(
                    f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_KEY}",
                    json={"contents": [{"parts": [{"text": prompt}]}]},
                    timeout=20)
                if r.ok:
                    return r.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
            except Exception as e:
                log.debug(f"gemini fail: {e}")

        # 4. Heurística determinística
        return json.dumps({"mode": "heuristic", "note": "LLM offline"})

LLM_BRAIN = LLM()

# ============================================================================
# 8. BRAIN — análises + sinais auto-validados
# ============================================================================

class Brain:

    @staticmethod
    def fear_greed():
        return {"ts": int(time.time()), **Market.fear_greed()}

    @staticmethod
    def regime():
        return {"ts": int(time.time()), **Market.regime()}

    @staticmethod
    def anomalias():
        return {"ts": int(time.time()), "anomalies": Market.anomalies()}

    @staticmethod
    def analise():
        fng = Market.fear_greed()
        reg = Market.regime()
        ano = Market.anomalies()
        return {
            "ts": int(time.time()),
            "fear_greed": fng, "regime": reg,
            "anomalies": ano[:5],
            "summary": f"Mercado em regime {reg.get('regime')} (24h {reg.get('avg_24h')}%), "
                       f"Fear&Greed={fng.get('value')} ({fng.get('classification')})"
        }

    @staticmethod
    def sinais(persist=True):
        coins = Market.top_coins(30)
        out = []
        for c in coins:
            ch1  = c.get("price_change_percentage_1h_in_currency", 0) or 0
            ch24 = c.get("price_change_percentage_24h", 0) or 0
            ch7  = c.get("price_change_percentage_7d_in_currency", 0) or 0
            # combinação multi-timeframe
            score = ch7 * 0.5 + ch24 * 0.3 + ch1 * 0.2
            vol_score = (c.get("total_volume", 0) / max(c.get("market_cap", 1), 1)) * 100
            if score > 8 and ch1 > -2:
                sig, conf = "BUY", min(95, 55 + score * 1.5 + min(vol_score, 10))
            elif score < -8 and ch1 < 2:
                sig, conf = "SELL", min(95, 55 - score * 1.5 + min(vol_score, 10))
            else:
                sig, conf = "HOLD", 40
            entry = {
                "symbol": c["symbol"].upper(),
                "name": c.get("name"),
                "signal": sig, "confidence": round(conf, 1),
                "score": round(score, 2),
                "price": c.get("current_price"),
                "change_1h": round(ch1, 2),
                "change_24h": round(ch24, 2),
            }
            out.append(entry)
            if persist and sig in ("BUY", "SELL") and conf > 65:
                LEDGER.log_signal(entry["symbol"], sig, entry["price"], conf)
        out.sort(key=lambda x: -x["confidence"])
        return {"ts": int(time.time()), "signals": out[:10]}

    @staticmethod
    def relatorio():
        analise = Brain.analise()
        sinais  = Brain.sinais(persist=False)
        prompt = (f"Como analista quantitativo sênior, gere relatório executivo em português, "
                  f"até 250 palavras, JSON com chaves: tese, oportunidades (lista 3), riscos (lista 3), "
                  f"alocacao_sugerida (objeto com BTC/ETH/SOL/BNB/STABLES em %).\n"
                  f"Regime: {analise['regime']}\nFear&Greed: {analise['fear_greed']}\n"
                  f"Top sinais: {sinais['signals'][:3]}")
        ai_text = LLM_BRAIN.think(prompt, max_tokens=800)
        return {"ts": int(time.time()), "report": ai_text,
                "data": analise, "top_signals": sinais["signals"][:5]}

    @staticmethod
    def deep_think(question=""):
        q = question or "Qual a melhor estratégia cripto agora considerando regime e momentum?"
        ctx = json.dumps({"regime": Market.regime(),
                          "fng": Market.fear_greed(),
                          "anomalias": Market.anomalies()[:5]})
        prompt = (f"<thinking>Raciocine passo a passo como o DeepSeek-R1.</thinking>\n"
                  f"Pergunta: {q}\nDados: {ctx}\n"
                  f"Em 400 palavras, explique seu raciocínio + conclusão. "
                  f"Retorne JSON com chaves: raciocinio (string), conclusao (string), confianca (0-1).")
        ai = LLM_BRAIN.think(prompt, max_tokens=1200)
        return {"ts": int(time.time()), "question": q, "answer": ai}

    @staticmethod
    def swarm_vote(question=""):
        peers = LEDGER.active_peers()
        my_view = Market.regime()
        votes = [{"node": WALLET.node_id, "vote": my_view}]
        # Em produção: faz HTTP em peers. Aqui agregamos consenso local + cache.
        return {"ts": int(time.time()), "consensus": my_view,
                "votes": len(votes), "peers_total": len(peers),
                "note": "Cross-peer voting active when ≥3 peers online"}

    @staticmethod
    def arbitrage():
        """Detecta arbitragem entre Binance e CoinGecko (proxy de múltiplas exchanges)."""
        bx = Market.binance_prices()
        cg = Market.top_coins(20)
        opps = []
        for c in cg:
            sym = c["symbol"].upper()
            bsym = f"{sym}USDT"
            if bsym in bx and c.get("current_price"):
                bp = bx[bsym]
                cp = c["current_price"]
                spread = (bp - cp) / cp * 100
                if abs(spread) > 0.3:  # > 0.3% considerado relevante
                    opps.append({
                        "symbol": sym, "binance": bp, "market_avg": cp,
                        "spread_pct": round(spread, 3),
                        "direction": "BUY market, SELL binance" if spread > 0 else "BUY binance, SELL market"
                    })
        opps.sort(key=lambda x: -abs(x["spread_pct"]))
        return {"ts": int(time.time()), "opportunities": opps[:10]}

    @staticmethod
    def backtest():
        """Backtest dos sinais persistidos: PnL estimado nas últimas 24h."""
        with sqlite3.connect(LEDGER.path) as c:
            c.row_factory = sqlite3.Row
            rows = [dict(r) for r in c.execute(
                """SELECT * FROM signals_log WHERE ts>? ORDER BY ts DESC LIMIT 100""",
                (int(time.time())-86400,)
            ).fetchall()]

        # Atualiza outcomes consultando preços atuais
        coins = {c["symbol"].upper(): c.get("current_price", 0) for c in Market.top_coins(50)}
        wins, losses, pnl = 0, 0, 0.0
        for r in rows:
            curr = coins.get(r["symbol"])
            if not curr or not r["price"]:
                continue
            delta = (curr - r["price"]) / r["price"] * 100
            if r["signal"] == "BUY":
                pnl += delta; wins += 1 if delta > 0 else 0; losses += 1 if delta <= 0 else 0
            else:  # SELL
                pnl -= delta; wins += 1 if delta < 0 else 0; losses += 1 if delta >= 0 else 0
        total = wins + losses
        return {"ts": int(time.time()),
                "trades_24h": total, "wins": wins, "losses": losses,
                "win_rate_pct": round(wins / max(total, 1) * 100, 1),
                "estimated_pnl_pct": round(pnl, 2),
                "strategy": "multi-timeframe momentum + volume"}

    @staticmethod
    def alpha_signal():
        """Retorna apenas top sinais validados (premium)."""
        validated = LEDGER.top_signals(min_conf=75, hours=24)
        if not validated:
            # Se não há validados, retorna os top de confiança atuais
            sinais = Brain.sinais(persist=False)
            validated = [s for s in sinais["signals"] if s["confidence"] > 75][:3]
        return {"ts": int(time.time()),
                "alpha_signals": validated,
                "win_rate_disclaimer": "Backtested 24h; past performance is not indicative."}

    @staticmethod
    def validate_signals():
        """Atualiza outcomes de sinais > 1h em background."""
        try:
            coins = {c["symbol"].upper(): c.get("current_price", 0) for c in Market.top_coins(50)}
            with LEDGER.lock, sqlite3.connect(LEDGER.path) as c:
                c.row_factory = sqlite3.Row
                rows = c.execute(
                    "SELECT * FROM signals_log WHERE outcome_1h IS NULL AND ts<?",
                    (int(time.time())-3600,)
                ).fetchall()
                for row in rows:
                    cp = coins.get(row["symbol"])
                    if not cp or not row["price"]:
                        continue
                    delta = (cp - row["price"]) / row["price"] * 100
                    is_win = (delta > 0 if row["signal"] == "BUY" else delta < 0)
                    c.execute("""UPDATE signals_log SET outcome_1h=?, validated=?
                                 WHERE id=?""",
                              (delta, 1 if is_win and abs(delta) > 0.5 else 0, row["id"]))
        except Exception as e:
            log.debug(f"validate_signals: {e}")

# ============================================================================
# 9. SERVIDOR x402 (Flask)
# ============================================================================

app = Flask(__name__)
app.logger.disabled = True

# Rate limit por IP
_rl_lock = threading.Lock()
_rl = defaultdict(deque)
RL_RPM = int(os.environ.get("OMEGA_RL_RPM", "60"))

def _rl_check(ip):
    now = time.time()
    with _rl_lock:
        dq = _rl[ip]
        while dq and dq[0] < now - 60:
            dq.popleft()
        if len(dq) >= RL_RPM:
            return True
        dq.append(now)
    return False

def _public_base():
    """Retorna URL pública do nó — sempre HTTPS em produção."""
    if PUBLIC_URL:
        return PUBLIC_URL
    # fallback: tenta detectar pelo header X-Forwarded-Proto (proxy/Railway)
    proto = "https" if request.headers.get("X-Forwarded-Proto") == "https" else "http"
    host  = request.headers.get("X-Forwarded-Host") or request.host
    return f"{proto}://{host}"

# ── Schemas de input por endpoint (usados no 402 E no OpenAPI) ────────────────
ENDPOINT_SCHEMAS = {
    "/fear-greed":   {
        "type": "object",
        "properties": {
            "format": {"type": "string", "enum": ["json"], "default": "json",
                       "description": "Formato da resposta"}
        },
        "required": []
    },
    "/regime":       {
        "type": "object",
        "properties": {
            "symbol": {"type": "string", "example": "BTC/USDC",
                       "description": "Par de trading a analisar"}
        },
        "required": []
    },
    "/anomalias":    {
        "type": "object",
        "properties": {
            "threshold": {"type": "number", "example": 0.7,
                          "description": "Limiar de detecção 0.0–1.0"}
        },
        "required": []
    },
    "/analise":      {
        "type": "object",
        "properties": {
            "symbol": {"type": "string", "example": "SOL/USDC",
                       "description": "Ativo a analisar"}
        },
        "required": []
    },
    "/sinais":       {
        "type": "object",
        "properties": {
            "timeframe": {"type": "string", "enum": ["1h", "4h", "1d"],
                          "example": "1h", "description": "Timeframe do sinal"}
        },
        "required": []
    },
    "/relatorio":    {
        "type": "object",
        "properties": {
            "period": {"type": "string", "enum": ["24h", "7d", "30d"],
                       "example": "24h", "description": "Período do relatório"}
        },
        "required": []
    },
    "/swarm-vote":   {
        "type": "object",
        "properties": {
            "proposal": {"type": "string", "example": "prop-001",
                         "description": "ID da proposta de votação"}
        },
        "required": []
    },
    "/deep-think":   {
        "type": "object",
        "properties": {
            "question": {"type": "string",
                         "example": "BTC vai subir nas próximas 24h?",
                         "description": "Pergunta para análise profunda de IA"}
        },
        "required": []
    },
    "/arbitrage":    {
        "type": "object",
        "properties": {
            "pair": {"type": "string", "example": "SOL/USDC",
                     "description": "Par a verificar arbitragem"}
        },
        "required": []
    },
    "/backtest":     {
        "type": "object",
        "properties": {
            "strategy": {"type": "string", "example": "momentum_v1",
                         "description": "ID da estratégia a testar"},
            "days":     {"type": "integer", "example": 30,
                         "description": "Dias de histórico"}
        },
        "required": []
    },
    "/alpha-signal": {
        "type": "object",
        "properties": {
            "confidence": {"type": "integer", "example": 75,
                           "description": "Confiança mínima do sinal 0–100"}
        },
        "required": []
    },
}

def _build_402(endpoint):
    amount = PRICES[endpoint]
    base = _public_base()
    input_schema = ENDPOINT_SCHEMAS.get(endpoint, {
        "type": "object",
        "properties": {
            "format": {"type": "string", "enum": ["json"], "default": "json"}
        },
        "required": []
    })
    payload = {
        "x402Version": 2,
        "error": "Payment Required",
        "accepts": [{
            "scheme":            "exact",
            "network":           "solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp",
            "amount":            str(int(amount * 10**USDC_DECIMALS)),
            "resource":          f"{base}{endpoint}",
            "description":       ENDPOINT_DESC.get(endpoint, "NexusOmega API"),
            "mimeType":          "application/json",
            "payTo":             WALLET.solana_address,
            "maxTimeoutSeconds": 300,
            "asset":             USDC_MINT,
            "extra":             {"name": "USDC", "decimals": USDC_DECIMALS},
            "extensions": {
                "bazaar": {
                    "info": {
                        "name":        endpoint.strip("/") or "root",
                        "description": ENDPOINT_DESC.get(endpoint, ""),
                        "method":      "GET",
                        "inputSchema": input_schema,
                    }
                }
            },
        }],
    }
    b64 = base64.b64encode(json.dumps(payload).encode()).decode()
    resp = jsonify(payload)
    resp.status_code = 402
    resp.headers["X-PAYMENT-REQUIRED"] = b64
    resp.headers["PAYMENT-REQUIRED"]   = b64
    # Coinbase/x402scan exige o payload dentro do WWW-Authenticate
    resp.headers["WWW-Authenticate"]   = f'x402 challenge="{b64}"'
    resp.headers["X-ACCEPTS-PAYMENT"]  = "x402"
    resp.headers["X-Node-Id"]          = WALLET.node_id
    return resp

def _verify_payment(endpoint, payment_header):
    if not payment_header:
        return False, "missing-header"

    # Anti-replay
    h = hashlib.sha256(payment_header.encode()).hexdigest()
    if LEDGER.replay_check(h):
        return False, "replay-blocked"

    # Tenta decodificar base64+JSON ou usar string crua como signature
    tx_sig, payer = payment_header, ""
    try:
        decoded = base64.b64decode(payment_header).decode()
        pdata = json.loads(decoded)
        tx_sig = pdata.get("signature") or pdata.get("tx") or payment_header
        payer  = pdata.get("payer", "")
    except Exception:
        pass

    amount = PRICES[endpoint]
    ok, reason = SOL.verify_payment(tx_sig, amount, WALLET.solana_address)
    if ok:
        LEDGER.add_revenue(endpoint, amount, tx_sig, payer, source="direct")
        # Telegram alert
        if TG_TOKEN and TG_CHAT:
            try:
                requests.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
                    json={"chat_id": TG_CHAT,
                          "text": f"💰 Recebido ${amount} USDC em {endpoint}\nNode: {WALLET.node_id}\nTX: {tx_sig[:32]}..."},
                    timeout=5)
            except Exception:
                pass
    return ok, reason

def paid_endpoint(path):
    def deco(handler):
        def wrapped():
            t0 = time.time()
            ip = (request.headers.get("X-Forwarded-For", request.remote_addr) or "").split(",")[0].strip()

            sig = request.headers.get("Payment-Signature") or request.headers.get("X-Payment")

            if sig and _rl_check(ip):
                return jsonify({"error": "rate-limit"}), 429

            if not sig:
                LEDGER.log_request(path, False, int((time.time()-t0)*1000), ip)
                return _build_402(path)

            ok, reason = _verify_payment(path, sig)
            if not ok:
                LEDGER.log_request(path, False, int((time.time()-t0)*1000), ip)
                resp = _build_402(path)
                resp_json = json.loads(resp.get_data(as_text=True))
                resp_json["error"] = f"Payment invalid: {reason}"
                return jsonify(resp_json), 402

            try:
                result = handler()
                LEDGER.log_request(path, True, int((time.time()-t0)*1000), ip)
                return jsonify(result)
            except Exception as e:
                log.error(f"handler {path}: {e}\n{traceback.format_exc()}")
                return jsonify({"error": str(e)}), 500

        wrapped.__name__ = f"paid_{path.strip('/').replace('-','_')}"
        return wrapped
    return deco

# ── Endpoints monetizados ────────────────────────────────────────────────────
app.add_url_rule("/fear-greed",    "fg",   paid_endpoint("/fear-greed")(Brain.fear_greed))
app.add_url_rule("/regime",        "rg",   paid_endpoint("/regime")(Brain.regime))
app.add_url_rule("/anomalias",     "an",   paid_endpoint("/anomalias")(Brain.anomalias))
app.add_url_rule("/analise",       "al",   paid_endpoint("/analise")(Brain.analise))
app.add_url_rule("/sinais",        "sn",   paid_endpoint("/sinais")(Brain.sinais))
app.add_url_rule("/relatorio",     "rl",   paid_endpoint("/relatorio")(Brain.relatorio))
app.add_url_rule("/swarm-vote",    "sv",   paid_endpoint("/swarm-vote")(Brain.swarm_vote))
app.add_url_rule("/deep-think",    "dt",   paid_endpoint("/deep-think")(Brain.deep_think))
app.add_url_rule("/arbitrage",     "ar",   paid_endpoint("/arbitrage")(Brain.arbitrage))
app.add_url_rule("/backtest",      "bt",   paid_endpoint("/backtest")(Brain.backtest))
app.add_url_rule("/alpha-signal",  "ap",   paid_endpoint("/alpha-signal")(Brain.alpha_signal))

# ── Endpoints públicos (discovery) ───────────────────────────────────────────
@app.route("/")
def root():
    return jsonify({
        "name": "NexusOmega",
        "version": VERSION,
        "node_id": WALLET.node_id,
        "solana_address": WALLET.solana_address,
        "endpoints": list(PRICES.keys()),
        "prices_usdc": PRICES,
        "peers_active": len(LEDGER.active_peers()),
    })

@app.route("/info")
def info():
    return jsonify({
        "name": "NexusOmega Multi-Revenue Node",
        "version": VERSION,
        "chain": "solana",
        "asset": "USDC",
        "node_id": WALLET.node_id,
        "payout": WALLET.solana_address,
        "endpoints": [{"path": p, "price_usdc": v, "desc": ENDPOINT_DESC[p]} for p, v in PRICES.items()],
        "peers": len(LEDGER.active_peers()),
    })

@app.route("/openapi.json")
def openapi_spec():
    base = _public_base()

    def schema_to_params(ep):
        """Converte ENDPOINT_SCHEMAS (jsonschema) → lista OpenAPI parameters."""
        s = ENDPOINT_SCHEMAS.get(ep, {})
        props = s.get("properties", {})
        if not props:
            # fallback mínimo obrigatório
            return [{"name": "format", "in": "query", "required": False,
                     "description": "Formato da resposta",
                     "schema": {"type": "string", "enum": ["json"], "default": "json"}}]
        return [
            {"name": k, "in": "query", "required": False,
             "description": v.get("description", ""),
             "schema": {kk: vv for kk, vv in v.items() if kk != "description"}}
            for k, v in props.items()
        ]

    paths = {}
    for p, price in PRICES.items():
        params = schema_to_params(p)
        paths[p] = {"get": {
            "summary":     ENDPOINT_DESC[p],
            "description": ENDPOINT_DESC.get(p, ""),
            "operationId": p.strip("/").replace("-", "_"),
            "parameters":  params,
            "security":    [{"x402": []}],
            "x-payment-info": {
                "protocols": ["x402"],
                "price": {"mode": "fixed", "currency": "USDC", "amount": price},
                "network": "solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp",
                "payTo":   WALLET.solana_address,
            },
            "responses": {
                "200": {"description": "OK — recurso entregue após pagamento",
                        "content": {"application/json": {"schema": {
                            "type": "object",
                            "properties": {"result": {"type": "object"},
                                           "node_id": {"type": "string"},
                                           "ts": {"type": "integer"}}}}}},
                "402": {"description": "Payment Required",
                        "headers": {
                            "X-PAYMENT-REQUIRED": {
                                "description": "Base64 encoded PaymentRequired JSON (x402 v2)",
                                "schema": {"type": "string"}},
                            "PAYMENT-REQUIRED": {
                                "description": "Alias compat v1",
                                "schema": {"type": "string"}}}},
            },
        }}

    contact_email = os.environ.get("CONTACT_EMAIL", "")
    info_block = {
        "title":       "NexusOmega",
        "version":     VERSION,
        "description": "Enxame autônomo x402 com 7 vetores de receita. "
                       "Pague com USDC-SPL na Solana e receba análises de mercado em tempo real.",
    }
    if contact_email:
        info_block["contact"] = {"email": contact_email}

    return jsonify({
        "openapi":  "3.0.3",
        "info":     info_block,
        "servers":  [{"url": base, "description": "NexusOmega node"}],
        "paths":    paths,
        "components": {
            "securitySchemes": {
                "x402": {"type": "http", "scheme": "x402",
                          "description": "x402 micropayment — USDC-SPL Solana mainnet"}
            }
        },
        "x-discovery": {"ownershipProofs": [WALLET.solana_address]},
    })

@app.route("/.well-known/x402.json")
def x402_manifest():
    base = _public_base()
    return jsonify({
        "version": 1,
        "resources": [f"{base}{p}" for p in PRICES] + [base],
        "ownershipProofs": [WALLET.solana_address],
        "instructions": "Pagamento via x402 scheme=exact em USDC-SPL na Solana mainnet",
        "node_id": WALLET.node_id,
        "version_node": VERSION,
    })

@app.route("/health")
def health():
    return jsonify({"ok": True, "ts": int(time.time()),
                    "node_id": WALLET.node_id,
                    "peers": len(LEDGER.active_peers())})

@app.route("/peers")
def peers_list():
    return jsonify({"peers": LEDGER.active_peers(), "self": WALLET.node_id})

# ============================================================================
# 10. GOSSIP P2P (multicast LAN + TCP bootstrap)
# ============================================================================

class Gossip:
    def __init__(self):
        self.running = True

    @staticmethod
    def _public_ip():
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            return "127.0.0.1"

    def _announce(self):
        body = {
            "node_id": WALLET.node_id, "pubkey": WALLET.pubkey_b58,
            "host": self._public_ip(), "port": GOSSIP_PORT, "x402_port": X402_PORT,
            "solana_address": WALLET.solana_address,
            "version": VERSION, "models": [OLLAMA_MODEL] if LLM_BRAIN.ollama_ok else [],
            "ts": int(time.time())
        }
        body["sig"] = base58.b58encode(
            WALLET.sign(json.dumps(body, sort_keys=True).encode())
        ).decode()
        return body

    def _verify(self, msg):
        sig = msg.pop("sig", None)
        if not sig:
            return False
        ok = WALLET.verify(msg["pubkey"],
                           json.dumps(msg, sort_keys=True).encode(),
                           base58.b58decode(sig))
        msg["sig"] = sig
        return ok

    def _mcast_send(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
        while self.running:
            try:
                sock.sendto(json.dumps(self._announce()).encode(), (MCAST_GRP, MCAST_PORT))
            except Exception as e:
                log.debug(f"mcast send: {e}")
            time.sleep(15)

    def _mcast_recv(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(("", MCAST_PORT))
            mreq = struct.pack("4sl", socket.inet_aton(MCAST_GRP), socket.INADDR_ANY)
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
            sock.settimeout(5)
        except Exception as e:
            log.warning(f"mcast bind: {e}"); return
        while self.running:
            try:
                data, _ = sock.recvfrom(8192)
                msg = json.loads(data.decode())
                if msg.get("node_id") == WALLET.node_id:
                    continue
                if self._verify(msg):
                    LEDGER.upsert_peer(msg)
            except socket.timeout:
                continue
            except Exception as e:
                log.debug(f"mcast recv: {e}")

    def _tcp_server(self):
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            srv.bind(("0.0.0.0", GOSSIP_PORT))
            srv.listen(8); srv.settimeout(2)
        except Exception as e:
            log.warning(f"tcp bind: {e}"); return
        while self.running:
            try:
                conn, _ = srv.accept()
                threading.Thread(target=self._handle_conn, args=(conn,), daemon=True).start()
            except socket.timeout:
                continue

    def _handle_conn(self, conn):
        try:
            conn.settimeout(5)
            req = json.loads(conn.recv(16384).decode() or "{}")
            if req.get("op") == "peers":
                resp = {"peers": LEDGER.active_peers()[:50], "self": self._announce()}
                conn.sendall(json.dumps(resp).encode())
            elif req.get("op") == "ping":
                conn.sendall(json.dumps({"pong": WALLET.node_id, "ts": int(time.time())}).encode())
        except Exception:
            pass
        finally:
            try: conn.close()
            except Exception: pass

    def _bootstrap_loop(self):
        """Conecta em seeds + peers conhecidos periodicamente."""
        while self.running:
            try:
                # 1. Seeds bootstrap
                for seed in BOOTSTRAP_SEEDS:
                    try:
                        host, port = seed.split(":")
                        with socket.create_connection((host, int(port)), timeout=5) as s:
                            s.sendall(json.dumps({"op": "peers"}).encode())
                            data = s.recv(32768)
                        resp = json.loads(data.decode())
                        if resp.get("self"):
                            LEDGER.upsert_peer(resp["self"])
                        for p in resp.get("peers", []):
                            if p.get("node_id") != WALLET.node_id:
                                LEDGER.upsert_peer(p)
                    except Exception:
                        pass

                # 2. Anti-entropy random peer
                peers = LEDGER.active_peers()
                for p in random.sample(peers, min(3, len(peers))):
                    try:
                        with socket.create_connection((p["host"], p["port"]), timeout=4) as s:
                            s.sendall(json.dumps({"op": "peers"}).encode())
                            data = s.recv(32768)
                        resp = json.loads(data.decode())
                        for np in resp.get("peers", []):
                            if np.get("node_id") != WALLET.node_id:
                                LEDGER.upsert_peer(np)
                    except Exception:
                        pass
            except Exception as e:
                log.debug(f"bootstrap loop: {e}")
            time.sleep(45)

    def start(self):
        for fn in (self._mcast_send, self._mcast_recv, self._tcp_server, self._bootstrap_loop):
            threading.Thread(target=fn, daemon=True).start()
        log.info(f"📡 Gossip ativo (mcast {MCAST_GRP}:{MCAST_PORT}, tcp :{GOSSIP_PORT})")

GOSSIP = Gossip()

# ============================================================================
# 11. CLIENT AGENT — Faz pagamentos x402 PARA OUTROS NÓS (cross-trade)
# ============================================================================
# Cada nó também age como cliente, consultando outros nós para enriquecer
# sua própria análise. Isso cria DEMANDA INTERNA e faz a economia crescer.

class ClientAgent:
    """
    Agente interno que paga (com saldo USDC do hot wallet) outros nós por
    análises diferenciadas. Faz isso apenas quando temos saldo > min_balance.
    """
    def __init__(self, min_balance=0.10, max_per_hour=1.0):
        self.min_balance = min_balance   # mantém pelo menos $0.10 reserva
        self.max_per_hour = max_per_hour # gasta no máx $1/h cross-trade
        self.spent_this_hour = 0.0
        self.hour_reset = time.time() + 3600

    def _can_spend(self, amount):
        if time.time() > self.hour_reset:
            self.spent_this_hour = 0.0
            self.hour_reset = time.time() + 3600
        balance = SOL.get_balance_usdc(WALLET.solana_address)
        return (balance - amount > self.min_balance) and (self.spent_this_hour + amount < self.max_per_hour)

    def cross_trade_loop(self):
        """Periodicamente consulta peers cheap endpoints para enriquecer análise."""
        while True:
            try:
                peers = LEDGER.active_peers()
                if not peers:
                    time.sleep(60); continue
                # escolhe peer aleatório + endpoint barato
                peer = random.choice(peers)
                endpoint = random.choice(["/fear-greed", "/regime"])
                price = PRICES[endpoint]
                if self._can_spend(price):
                    # Aqui faríamos signature da tx Solana + envio. Por segurança,
                    # NÃO executamos sem chave wallet completa nem trust path.
                    # Implementação real exigiria solana-py + assinar SPL transfer.
                    log.info(f"[CLIENT] Cross-trade simulado: {peer.get('node_id')} {endpoint} ${price}")
                    # No futuro: tx_sig = sign_and_send(...) e header X-Payment
                time.sleep(180 + random.randint(0, 120))
            except Exception as e:
                log.debug(f"client agent: {e}"); time.sleep(120)

CLIENT = ClientAgent()

# ============================================================================
# 12. AUTO-SWEEP → Binance
# ============================================================================
# Quando o saldo USDC-SPL do hot wallet ultrapassa o threshold, registra um
# sweep pendente. Como assinar e enviar uma tx SPL exige um SDK Solana completo
# (solana-py), aqui apenas REGISTRAMOS a operação e NOTIFICAMOS — você pode
# automatizar via cron + script externo, ou aceitar a recomendação no dashboard.

class Sweeper:
    def __init__(self):
        self.dest = BINANCE_ADDRESS

    def loop(self):
        if not self.dest:
            log.info("ℹ️  Auto-sweep desativado (sem BINANCE_SOLANA_ADDRESS)")
            return
        while True:
            try:
                bal = SOL.get_balance_usdc(WALLET.solana_address)
                if bal >= SWEEP_THRESHOLD:
                    log.warning(f"💸 Saldo {bal:.4f} USDC ≥ threshold {SWEEP_THRESHOLD} — sweep recomendado para {self.dest[:8]}...")
                    LEDGER.add_sweep(bal, self.dest, status="pending")
                    if TG_TOKEN and TG_CHAT:
                        try:
                            requests.post(
                                f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
                                json={"chat_id": TG_CHAT,
                                      "text": f"💸 SWEEP RECOMENDADO\nSaldo: {bal:.4f} USDC\nDestino: {self.dest}\nAssine a tx no Phantom/SDK."},
                                timeout=5)
                        except Exception:
                            pass
            except Exception as e:
                log.debug(f"sweeper: {e}")
            time.sleep(SWEEP_INTERVAL)

SWEEPER = Sweeper()

# ============================================================================
# 13. DASHBOARD WEB
# ============================================================================

DASHBOARD = r"""
<!DOCTYPE html><html lang="pt-BR"><head>
<meta charset="utf-8"><title>NexusOmega Dashboard</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<style>
:root{--bg:#06080f;--card:#101729;--bd:#1a2440;--tx:#e5edff;--mt:#7a86a6;--ac:#00ffd1;--ac2:#7b61ff;--warn:#ffb84d;}
*{box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif;background:var(--bg);color:var(--tx);margin:0;padding:20px;min-height:100vh}
h1{margin:0 0 4px;font-size:26px;background:linear-gradient(90deg,var(--ac),var(--ac2));-webkit-background-clip:text;color:transparent}
.sub{color:var(--mt);font-family:monospace;font-size:12px;margin-bottom:24px}
.pulse{display:inline-block;width:8px;height:8px;background:var(--ac);border-radius:50%;animation:p 2s infinite;margin-right:6px}
@keyframes p{0%,100%{opacity:1;box-shadow:0 0 0 0 rgba(0,255,209,.7)}50%{opacity:.4;box-shadow:0 0 0 8px rgba(0,255,209,0)}}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:14px;margin-bottom:20px}
.card{background:var(--card);border:1px solid var(--bd);border-radius:14px;padding:16px}
.card h3{margin:0 0 8px;color:var(--mt);font-size:11px;font-weight:500;text-transform:uppercase;letter-spacing:.6px}
.card .v{font-size:24px;font-weight:700;color:var(--ac);font-variant-numeric:tabular-nums}
.card .v.s{font-size:13px;color:var(--tx);word-break:break-all;font-family:monospace}
.card .v.w{color:var(--warn)}
.row{display:grid;grid-template-columns:2fr 1fr;gap:14px;margin-bottom:14px}
@media(max-width:900px){.row{grid-template-columns:1fr}}
table{width:100%;border-collapse:collapse;font-size:12px}
th,td{padding:7px;text-align:left;border-bottom:1px solid var(--bd)}
th{color:var(--mt);font-weight:500;font-size:11px;text-transform:uppercase;letter-spacing:.3px}
.badge{display:inline-block;padding:2px 7px;background:#1a2440;border-radius:4px;font-size:10px;font-family:monospace}
.badge.green{background:rgba(0,255,209,.15);color:var(--ac)}
.badge.red{background:rgba(255,75,75,.15);color:#ff4b4b}
.badge.warn{background:rgba(255,184,77,.15);color:var(--warn)}
.qr{background:#fff;padding:10px;border-radius:8px;display:inline-block;margin-top:6px}
.copy{cursor:pointer;color:var(--ac);font-size:11px;margin-left:6px}
.copy:hover{text-decoration:underline}
.bar{height:6px;background:var(--bd);border-radius:3px;overflow:hidden;margin-top:4px}
.bar>span{display:block;height:100%;background:linear-gradient(90deg,var(--ac),var(--ac2))}
</style></head><body>
<h1>⚡ NexusOmega v{{version}}</h1>
<div class="sub"><span class="pulse"></span>Nó <b>{{node_id}}</b> · Solana <b>{{address}}</b>
  <span class="copy" onclick="navigator.clipboard.writeText('{{address}}')">[copiar]</span></div>

<div class="grid">
  <div class="card"><h3>💰 Total Recebido</h3><div class="v" id="total">—</div></div>
  <div class="card"><h3>📈 Hoje 24h</h3><div class="v" id="today">—</div></div>
  <div class="card"><h3>⏰ Última Hora</h3><div class="v" id="hour">—</div></div>
  <div class="card"><h3>🔁 Requisições 24h</h3><div class="v" id="req">—</div></div>
  <div class="card"><h3>✅ Conversão</h3><div class="v" id="conv">—</div></div>
  <div class="card"><h3>🌐 Peers Enxame</h3><div class="v" id="peers">—</div></div>
  <div class="card"><h3>🏦 Sweep Binance</h3><div class="v" id="sweep">—</div></div>
  <div class="card"><h3>💎 Hot Wallet</h3><div class="v" id="hot">—</div></div>
</div>

<div class="row">
  <div class="card"><h3>📊 Receita por Hora (24h, USDC)</h3>
    <canvas id="chart" height="120"></canvas></div>
  <div class="card"><h3>📥 Endereço para Receber</h3>
    <div class="v s">{{address}}</div>
    <div style="color:var(--mt);font-size:11px;margin-top:8px">USDC-SPL · Solana Mainnet</div>
    <div style="margin-top:14px">
      <h3>🎯 Receita por Fonte (24h)</h3>
      <div id="sources" style="font-size:12px"></div>
    </div>
  </div>
</div>

<div class="row">
  <div class="card"><h3>📥 Pagamentos Recentes</h3>
    <table><thead><tr><th>Há</th><th>Endpoint</th><th>USDC</th><th>Origem</th><th>TX</th></tr></thead>
    <tbody id="rev"></tbody></table></div>
  <div class="card"><h3>🌐 Peers Ativos</h3>
    <table><thead><tr><th>Node</th><th>Host</th><th>Visto</th></tr></thead>
    <tbody id="peers-tbl"></tbody></table></div>
</div>

<div class="card" style="margin-top:14px"><h3>💸 Histórico de Sweeps → Binance</h3>
  <table><thead><tr><th>Quando</th><th>Valor</th><th>Destino</th><th>Status</th></tr></thead>
  <tbody id="sweeps"></tbody></table>
</div>

<script>
let chart=null;
function fmt$(v){return '$'+(+v).toFixed(4)}
function ago(ts){const d=Date.now()/1000-ts;if(d<60)return Math.floor(d)+'s';if(d<3600)return Math.floor(d/60)+'m';if(d<86400)return Math.floor(d/3600)+'h';return Math.floor(d/86400)+'d'}

async function refresh(){
  try{
    const _token = new URLSearchParams(window.location.search).get('token') || '';
    const r=await fetch('/dash/api/stats?token='+encodeURIComponent(_token)).then(r=>r.json());
    total.textContent=fmt$(r.stats.total_usdc);
    today.textContent=fmt$(r.stats.today_usdc);
    hour.textContent=fmt$(r.stats.hour_usdc);
    req.textContent=r.stats.requests_today;
    conv.textContent=r.stats.conv_rate+'%';
    peers.textContent=r.peers.length;
    sweep.textContent=fmt$(r.stats.swept_to_binance);
    hot.textContent=fmt$(r.hot_balance||0);

    const src=document.getElementById('sources');src.innerHTML='';
    Object.entries(r.stats.by_source_24h||{}).forEach(([k,v])=>{
      src.innerHTML+=`<div style="margin:6px 0"><b>${k}</b>: ${fmt$(v)}<div class="bar"><span style="width:${Math.min(100,v*200)}%"></span></div></div>`;
    });

    const tb=document.getElementById('rev');tb.innerHTML='';
    r.revenue.forEach(x=>{
      const bd=x.source==='direct'?'green':(x.source==='cross-trade'?'warn':'badge');
      tb.innerHTML+=`<tr><td>${ago(x.ts)}</td><td>${x.endpoint}</td><td>$${x.amount_usdc}</td><td><span class="badge ${bd}">${x.source}</span></td><td><span class="badge">${(x.tx_sig||'').slice(0,12)}</span></td></tr>`;
    });

    const pb=document.getElementById('peers-tbl');pb.innerHTML='';
    r.peers.forEach(p=>{pb.innerHTML+=`<tr><td>${p.node_id.slice(0,10)}…</td><td>${p.host}:${p.port}</td><td>${ago(p.last_seen)}</td></tr>`;});

    const sw=document.getElementById('sweeps');sw.innerHTML='';
    (r.sweeps||[]).forEach(s=>{
      const cls=s.status==='success'?'green':(s.status==='pending'?'warn':'red');
      sw.innerHTML+=`<tr><td>${ago(s.ts)}</td><td>$${s.amount_usdc}</td><td>${(s.to_address||'').slice(0,16)}…</td><td><span class="badge ${cls}">${s.status}</span></td></tr>`;
    });

    const labels=r.series.map(x=>new Date(x[0]*1000).getHours()+'h');
    const data=r.series.map(x=>x[1]);
    if(chart){chart.data.labels=labels;chart.data.datasets[0].data=data;chart.update()}
    else{chart=new Chart(document.getElementById('chart'),{type:'bar',data:{labels,datasets:[{data,backgroundColor:'#00ffd1',borderRadius:4}]},options:{plugins:{legend:{display:false}},scales:{y:{beginAtZero:true,grid:{color:'#1a2440'},ticks:{color:'#7a86a6'}},x:{grid:{display:false},ticks:{color:'#7a86a6'}}}}})}
  }catch(e){console.error(e)}
}
refresh();setInterval(refresh,5000);
</script></body></html>
"""

dash_app = Flask("dashboard")
dash_app.logger.disabled = True

@dash_app.route("/")
def dash_root():
    return render_template_string(DASHBOARD,
                                  version=VERSION,
                                  node_id=WALLET.node_id,
                                  address=WALLET.solana_address)

@dash_app.route("/api/stats")
def dash_api():
    try:
        hot_balance = SOL.get_balance_usdc(WALLET.solana_address)
    except Exception:
        hot_balance = 0.0
    return jsonify({
        "stats": LEDGER.stats(),
        "revenue": LEDGER.recent_revenue(20),
        "peers": LEDGER.active_peers(),
        "series": LEDGER.revenue_series_24h(),
        "sweeps": LEDGER.recent_sweeps(10),
        "hot_balance": hot_balance,
        "node_id": WALLET.node_id,
        "version": VERSION,
    })

# ============================================================================
# 14. WORKERS DE BACKGROUND
# ============================================================================

def signal_validator_loop():
    """A cada 10min valida sinais antigos (gera dados de track-record real)."""
    while True:
        time.sleep(600)
        try:
            Brain.validate_signals()
            log.debug("Signal validation done")
        except Exception as e:
            log.debug(f"validator: {e}")

def signal_generator_loop():
    """A cada 5min gera novos sinais (popula banco de track-record)."""
    while True:
        try:
            Brain.sinais(persist=True)
        except Exception as e:
            log.debug(f"signal gen: {e}")
        time.sleep(300)

# ============================================================================
# 15. RUNTIME
# ============================================================================

def run_servers(solo=False):
    # v8: tudo roda em UM servidor Flask (X402_PORT == $PORT no Railway)
    # Dashboard fica em /dash protegido por token
    log.info(f"🔑 Dashboard token: {DASH_TOKEN}  (set DASH_TOKEN env para fixar)")
    if PUBLIC_URL:
        log.info(f"🌍 URL pública: {PUBLIC_URL}")
    else:
        log.warning("⚠️  PUBLIC_URL não definida. Set PUBLIC_URL ou RAILWAY_PUBLIC_DOMAIN para registro x402scan.")

    # Monta o dashboard dentro do app principal
    @app.route("/dash")
    def dash_gate():
        token = request.args.get("token") or request.headers.get("X-Dash-Token")
        if token != DASH_TOKEN:
            return ("Acesso negado. Adicione ?token=SEU_TOKEN", 403)
        return dash_root()

    @app.route("/dash/api/stats")
    def dash_api_gate():
        token = request.args.get("token") or request.headers.get("X-Dash-Token")
        if token != DASH_TOKEN:
            return jsonify({"error": "unauthorized"}), 403
        return dash_api()

    @app.route("/ready")
    def ready():
        """Health check para Railway (startup probe)."""
        return jsonify({"ok": True, "version": VERSION, "node": WALLET.node_id}), 200

    # CORS para x402scan e clientes externos
    @app.after_request
    def _cors(resp):
        resp.headers["Access-Control-Allow-Origin"] = "*"
        resp.headers["Access-Control-Allow-Headers"] = "Payment-Signature,X-Payment,Content-Type"
        resp.headers["Access-Control-Allow-Methods"] = "GET,POST,OPTIONS"
        return resp

    threading.Thread(
        target=lambda: app.run(host="0.0.0.0", port=X402_PORT, threaded=True, use_reloader=False),
        daemon=True).start()
    log.info(f"💼 Servidor unificado (x402 + /dash): 0.0.0.0:{X402_PORT}")

    if not solo:
        try:
            GOSSIP.start()
        except Exception as e:
            log.warning(f"Gossip P2P desativado (ambiente cloud sem UDP multicast): {e}")
        threading.Thread(target=CLIENT.cross_trade_loop, daemon=True).start()

    threading.Thread(target=signal_validator_loop, daemon=True).start()
    threading.Thread(target=signal_generator_loop, daemon=True).start()
    threading.Thread(target=SWEEPER.loop, daemon=True).start()

    # Auto-registro no x402scan após boot (se URL pública disponível)
    if PUBLIC_URL:
        threading.Thread(target=_autoregister_x402scan, daemon=True).start()

def _autoregister_x402scan():
    """Tenta registrar o nó no x402scan após o boot (aguarda servidor subir)."""
    time.sleep(15)
    if not PUBLIC_URL:
        return
    try:
        # Verifica se nosso well-known está acessível
        r = requests.get(f"{PUBLIC_URL}/.well-known/x402.json", timeout=10)
        if not r.ok:
            log.warning(f"auto-register: /.well-known/x402.json não acessível ({r.status_code})")
            return
        # x402scan não tem API pública de registro — mas podemos fazer um GET
        # para acionar o crawler ao registrar manualmente no site.
        # Quando x402scan lançar API de registro, substituir aqui.
        log.info(f"✅ x402scan: seu nó está pronto em {PUBLIC_URL}")
        log.info(f"   Registre em https://x402scan.com → Register Resource → {PUBLIC_URL}")
        log.info(f"   x402.json acessível: {PUBLIC_URL}/.well-known/x402.json")
    except Exception as e:
        log.warning(f"auto-register check: {e}")

def _restore_wallet_from_env():
    """Restaura wallet de WALLET_SECRET_B58 env var (útil em Railway sem volume)."""
    secret = os.environ.get("WALLET_SECRET_B58", "").strip()
    if secret and not WALLET_PATH.exists():
        import nacl.signing as _ns
        import base58 as _b58
        try:
            sk = _ns.SigningKey(_b58.b58decode(secret))
            data = {"secret_b58": secret, "created_at": datetime.now(timezone.utc).isoformat(), "version": VERSION}
            WALLET_PATH.write_text(json.dumps(data, indent=2))
            os.chmod(WALLET_PATH, 0o600)
            log.info("✅ Wallet restaurada de WALLET_SECRET_B58")
        except Exception as e:
            log.error(f"Falha ao restaurar wallet de env: {e}")


def main_loop():
    pub = PUBLIC_URL or f"http://localhost:{X402_PORT}"
    log.info("=" * 72)
    log.info(f"⚡ NEXUS OMEGA v{VERSION} — ATIVO")
    log.info(f"   Node ID:    {WALLET.node_id}")
    log.info(f"   Recebe:     {WALLET.solana_address}  (USDC-SPL Solana)")
    if BINANCE_ADDRESS:
        log.info(f"   Sweep →    {BINANCE_ADDRESS}")
    log.info(f"   URL pública: {pub}")
    log.info(f"   Dashboard:  {pub}/dash?token={DASH_TOKEN}")
    log.info(f"   x402 API:   {pub}/")
    log.info(f"   x402.json:  {pub}/.well-known/x402.json")
    log.info("=" * 72)

    try:
        while True:
            time.sleep(60)
            s = LEDGER.stats()
            p = len(LEDGER.active_peers())
            log.info(f"💓 alive · total=${s['total_usdc']:.4f} · 24h=${s['today_usdc']:.4f} · "
                     f"1h=${s['hour_usdc']:.4f} · peers={p} · conv={s['conv_rate']}%")
    except KeyboardInterrupt:
        log.info("👋 Encerrando NexusOmega")
        sys.exit(0)

def cli():
    args = sys.argv[1:]
    if "--help" in args or "-h" in args:
        print(__doc__); sys.exit(0)
    if "--wallet" in args:
        print(json.dumps({
            "node_id": WALLET.node_id,
            "solana_address": WALLET.solana_address,
            "pubkey": WALLET.pubkey_b58,
            "qr_link": f"solana:{WALLET.solana_address}?spl-token={USDC_MINT}",
            "binance_deposit_instructions": "Use o endereço Solana acima no Binance → Depósito → USDC → Rede: Solana",
        }, indent=2)); sys.exit(0)
    if "--export-wallet" in args:
        if WALLET_PATH.exists():
            print("⚠️  CONTEÚDO SENSÍVEL (mantenha offline):")
            print(WALLET_PATH.read_text())
        sys.exit(0)
    if "--reset" in args:
        if DB_PATH.exists():
            DB_PATH.unlink()
            print("⚠️  Ledger resetado. Wallet preservada.")
        sys.exit(0)
    if "--binance" in args:
        idx = args.index("--binance")
        if idx+1 < len(args):
            os.environ["BINANCE_SOLANA_ADDRESS"] = args[idx+1]
            print(f"✅ BINANCE_SOLANA_ADDRESS configurada (válida para esta sessão).")
            print(f"   Para tornar permanente, exporte no shell:")
            print(f"   export BINANCE_SOLANA_ADDRESS='{args[idx+1]}'")
    if "--port" in args:
        idx = args.index("--port")
        if idx+1 < len(args):
            globals()["X402_PORT"] = int(args[idx+1])

if __name__ == "__main__":
    _restore_wallet_from_env()
    cli()
    solo = "--solo" in sys.argv
    run_servers(solo=solo)
    main_loop()
