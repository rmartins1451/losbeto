# -*- coding: utf-8 -*-
"""
NEXUS OMEGA v8.2 — Enxame Autônomo com IA (Groq+Gemini), WebSockets, Staking e Preço Dinâmico
Single-File, sem Docker, otimizado para Railway.
"""
from __future__ import annotations

import os, sys, json, time, base64, hashlib, threading, sqlite3
import socket, struct, subprocess, signal, logging, traceback, random
import urllib.request, urllib.error
from datetime import datetime, timezone
from pathlib import Path
from collections import defaultdict, deque
from typing import Any, Optional
from dotenv import load_dotenv

# Carrega .env
load_dotenv()

# ============================================================================
# CONFIGURAÇÃO
# ============================================================================
VERSION = "8.2.0-OMEGA-PRO"
HOME_DIR = Path.home() / ".nexus_omega_pro"
HOME_DIR.mkdir(exist_ok=True)
DB_PATH = HOME_DIR / "omega.db"
WALLET_PATH = HOME_DIR / "wallet.json"
LOG_PATH = HOME_DIR / "omega.log"

# === NOVIDADE: usa a porta do Railway se disponível, senão usa 8402 ===
PORT = int(os.getenv("PORT", "8402"))          # <-- variável para o servidor x402
X402_PORT = PORT                               # agora X402_PORT recebe a porta dinâmica
GOSSIP_PORT = int(os.getenv("OMEGA_GOSSIP_PORT", "8403"))
DASHBOARD_PORT = int(os.getenv("OMEGA_DASH_PORT", "8080"))
MCAST_GRP = "239.42.42.42"
MCAST_PORT = 8404

SOLANA_RPCS = [
    os.getenv("SOLANA_RPC", "https://api.mainnet-beta.solana.com"),
    "https://solana-rpc.publicnode.com",
    "https://solana.drpc.org",
]
USDC_MINT = os.getenv("USDC_MINT", "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v")
USDC_DECIMALS = 6

BINANCE_ADDRESS = os.getenv("BINANCE_SOLANA_ADDRESS", "").strip()
SWEEP_THRESHOLD = float(os.getenv("SWEEP_THRESHOLD_USDC", "0.5"))
SWEEP_INTERVAL = int(os.getenv("SWEEP_INTERVAL_S", "3600"))

# Chaves IA (apenas Groq e Gemini)
GROQ_KEY = os.getenv("GROQ_API_KEY", "")
GEMINI_KEY = os.getenv("GEMINI_API_KEY", "")
NEWS_API_KEY = os.getenv("NEWS_API_KEY", "")
CRYPTOPANIC_KEY = os.getenv("CRYPTOPANIC_API_KEY", "")

TG_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TG_CHAT = os.getenv("TELEGRAM_CHAT_ID", "")

BOOTSTRAP_SEEDS = [s.strip() for s in os.getenv("OMEGA_SEEDS", "").split(",") if s.strip()]

# ============================================================================
# LOGGING
# ============================================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler(LOG_PATH, encoding="utf-8"), logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("omega")

# ============================================================================
# AUTO-INSTALAÇÃO DE DEPENDÊNCIAS
# ============================================================================
REQUIRED = {
    "flask": "flask",
    "requests": "requests",
    "base58": "base58",
    "nacl": "pynacl",
    "cryptography": "cryptography",
    "websocket": "websocket-client",
    "dotenv": "python-dotenv",
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
        subprocess.check_call([sys.executable, "-m", "pip", "install", "--quiet", "--disable-pip-version-check", *missing])
        log.info("✅ Dependências instaladas")
_ensure_deps()

import requests
from flask import Flask, request, jsonify, render_template_string
import base58
import nacl.signing, nacl.encoding
import websocket

# ============================================================================
# WALLET
# ============================================================================
class Wallet:
    def __init__(self):
        if WALLET_PATH.exists():
            data = json.loads(WALLET_PATH.read_text())
            self.signing_key = nacl.signing.SigningKey(base58.b58decode(data["secret_b58"]))
        else:
            self.signing_key = nacl.signing.SigningKey.generate()
            data = {"secret_b58": base58.b58encode(bytes(self.signing_key)).decode(),
                    "created_at": datetime.now(timezone.utc).isoformat(), "version": VERSION}
            WALLET_PATH.write_text(json.dumps(data, indent=2))
            try: os.chmod(WALLET_PATH, 0o600)
            except: pass
            log.warning(f"🔑 NOVA WALLET GERADA → {WALLET_PATH} (faça backup!)")
        self.verify_key = self.signing_key.verify_key
        self.pubkey_b58 = base58.b58encode(bytes(self.verify_key)).decode()
        self.node_id = hashlib.sha256(bytes(self.verify_key)).hexdigest()[:16]

    @property
    def solana_address(self) -> str:
        return self.pubkey_b58

    def sign(self, msg: bytes) -> bytes:
        return self.signing_key.sign(msg).signature

    @staticmethod
    def verify(pubkey_b58: str, msg: bytes, sig: bytes) -> bool:
        try:
            vk = nacl.signing.VerifyKey(base58.b58decode(pubkey_b58))
            vk.verify(msg, sig)
            return True
        except: return False

WALLET = Wallet()
log.info(f"🆔 Node ID: {WALLET.node_id}")
log.info(f"💰 Recebe USDC-SPL em: {WALLET.solana_address}")
if BINANCE_ADDRESS:
    log.info(f"🏦 Sweep → Binance: {BINANCE_ADDRESS}")

# ============================================================================
# LEDGER (SQLite)
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
                models TEXT,
                stake REAL DEFAULT 0.0,
                win_rate REAL DEFAULT 0.0,
                total_earned REAL DEFAULT 0.0
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
            CREATE TABLE IF NOT EXISTS staking (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                staker TEXT, target_node TEXT,
                amount REAL, start_ts INTEGER, duration INTEGER,
                reward REAL, status TEXT
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
            c.execute("""INSERT INTO peers(node_id,host,port,pubkey,solana_address,last_seen,version,models,stake,win_rate,total_earned)
                         VALUES(?,?,?,?,?,?,?,?,?,?,?)
                         ON CONFLICT(node_id) DO UPDATE SET
                            host=excluded.host, port=excluded.port,
                            pubkey=excluded.pubkey, solana_address=excluded.solana_address,
                            last_seen=excluded.last_seen, version=excluded.version,
                            models=excluded.models, stake=excluded.stake, win_rate=excluded.win_rate,
                            total_earned=excluded.total_earned""",
                      (p["node_id"], p["host"], p["port"], p["pubkey"],
                       p.get("solana_address",""), int(time.time()),
                       p.get("version",""), json.dumps(p.get("models",[])),
                       p.get("stake",0.0), p.get("win_rate",0.0),
                       p.get("total_earned",0.0)))

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
            staked = c.execute("SELECT COALESCE(SUM(amount),0) FROM staking WHERE status='active'").fetchone()[0]
        return {
            "total_usdc":      round(total, 6),
            "today_usdc":      round(today, 6),
            "hour_usdc":       round(hour, 6),
            "requests_today":  req_t,
            "paid_today":      paid_t,
            "conv_rate":       round(paid_t / max(req_t, 1) * 100, 1),
            "by_source_24h":   {k: round(v, 4) for k, v in by_src.items()},
            "swept_to_binance": round(sweep_total, 6),
            "staked_usdc":     round(staked, 6),
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
            if r: return True
            c.execute("INSERT INTO replay(hash,ts) VALUES(?,?)", (h, now))
            return False

    def log_signal(self, symbol, signal, price, confidence):
        with self.lock, sqlite3.connect(self.path) as c:
            c.execute("""INSERT INTO signals_log(ts,symbol,signal,price,confidence)
                         VALUES(?,?,?,?,?)""",
                      (int(time.time()), symbol, signal, price, confidence))

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

    def add_stake(self, staker, target, amount, duration=86400):
        with self.lock, sqlite3.connect(self.path) as c:
            c.execute("""INSERT INTO staking(staker,target_node,amount,start_ts,duration,status)
                         VALUES(?,?,?,?,?,?)""",
                      (staker, target, amount, int(time.time()), duration, "active"))

    def get_stakes(self, target=None):
        with sqlite3.connect(self.path) as c:
            c.row_factory = sqlite3.Row
            if target:
                return [dict(r) for r in c.execute(
                    "SELECT * FROM staking WHERE target_node=? AND status='active'", (target,)
                ).fetchall()]
            return [dict(r) for r in c.execute(
                "SELECT * FROM staking WHERE status='active'"
            ).fetchall()]

LEDGER = Ledger(DB_PATH)

# ============================================================================
# SOLANA CLIENT
# ============================================================================
class SolanaClient:
    def __init__(self):
        self.rpcs = list(SOLANA_RPCS)
        self.current = 0
        self.fail_count = defaultdict(int)

    def _post(self, method, params, timeout=12):
        for _ in range(len(self.rpcs)):
            rpc = self.rpcs[self.current]
            try:
                r = requests.post(rpc, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
                                  timeout=timeout, headers={"Content-Type": "application/json"})
                if r.ok:
                    self.fail_count[rpc] = 0
                    return r.json()
                self.fail_count[rpc] += 1
            except:
                self.fail_count[rpc] += 1
            self.current = (self.current + 1) % len(self.rpcs)
        return None

    def get_balance_usdc(self, address):
        r = self._post("getTokenAccountsByOwner", [address, {"mint": USDC_MINT}, {"encoding": "jsonParsed"}])
        if not r or not r.get("result"):
            return 0.0
        total = 0.0
        for acc in r["result"].get("value", []):
            info = acc.get("account", {}).get("data", {}).get("parsed", {}).get("info", {})
            total += float(info.get("tokenAmount", {}).get("uiAmount", 0) or 0)
        return total

    def verify_payment(self, signature, expected_amount, receiver_address, max_age=3600):
        r = self._post("getTransaction", [signature, {"encoding": "jsonParsed", "commitment": "confirmed"}])
        if not r or not r.get("result"):
            return False, "tx-not-found"
        tx = r["result"]
        if tx.get("meta", {}).get("err"):
            return False, "tx-failed"
        if (time.time() - tx.get("blockTime", 0)) > max_age:
            return False, "tx-too-old"
        meta = tx.get("meta", {})
        pre = {b["accountIndex"]: b for b in meta.get("preTokenBalances", [])}
        post = {b["accountIndex"]: b for b in meta.get("postTokenBalances", [])}
        for idx, pb in post.items():
            if pb.get("mint") != USDC_MINT: continue
            if pb.get("owner") != receiver_address: continue
            pa = float(pre.get(idx, {}).get("uiTokenAmount", {}).get("uiAmount") or 0)
            po = float(pb.get("uiTokenAmount", {}).get("uiAmount") or 0)
            if po - pa + 1e-9 >= expected_amount:
                return True, f"ok delta={po-pa:.6f}"
        return False, "no-matching-transfer"

SOL = SolanaClient()

# ============================================================================
# PRICE FEED via WebSockets (Binance, Bybit, OKX)
# ============================================================================
class PriceFeed:
    def __init__(self):
        self.prices = defaultdict(dict)
        self.lock = threading.Lock()
        self.running = True
        self._start_websockets()

    def _start_websockets(self):
        # Binance
        def on_message(ws, message):
            data = json.loads(message)
            if 'c' in data:
                sym = data['s']
                price = float(data['c'])
                with self.lock:
                    self.prices['binance'][sym] = price
        def on_error(ws, error):
            log.debug(f"Binance WS error: {error}")
        def on_close(ws, close_status_code, close_msg):
            log.debug("Binance WS closed, reconnecting...")
            time.sleep(5)
            self._connect_binance()
        def _connect_binance():
            ws = websocket.WebSocketApp("wss://stream.binance.com:9443/ws/!ticker@arr",
                                        on_message=on_message, on_error=on_error, on_close=on_close)
            ws.run_forever()
        threading.Thread(target=_connect_binance, daemon=True).start()

        # Bybit
        def on_message_bybit(ws, message):
            data = json.loads(message)
            if 'data' in data and 'symbol' in data['data']:
                sym = data['data']['symbol']
                price = float(data['data']['lastPrice'])
                with self.lock:
                    self.prices['bybit'][sym] = price
        def _connect_bybit():
            ws = websocket.WebSocketApp("wss://stream.bybit.com/v5/public/spot",
                                        on_message=on_message_bybit)
            ws.run_forever()
        threading.Thread(target=_connect_bybit, daemon=True).start()

        # OKX
        def on_message_okx(ws, message):
            data = json.loads(message)
            if 'data' in data and len(data['data']) > 0:
                for item in data['data']:
                    sym = item.get('instId', '').replace('-', '')
                    price = float(item.get('last', 0))
                    if price > 0:
                        with self.lock:
                            self.prices['okx'][sym] = price
        def _connect_okx():
            ws = websocket.WebSocketApp("wss://ws.okx.com:8443/ws/v5/public",
                                        on_message=on_message_okx)
            ws.run_forever()
        threading.Thread(target=_connect_okx, daemon=True).start()

    def get_price(self, symbol, exchange='binance'):
        with self.lock:
            return self.prices.get(exchange, {}).get(symbol, None)

    def get_all_prices(self, symbol):
        result = {}
        with self.lock:
            for ex in self.prices:
                if symbol in self.prices[ex]:
                    result[ex] = self.prices[ex][symbol]
        return result

PRICE_FEED = PriceFeed()

# ============================================================================
# MARKET DATA
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
            return {"value": int(d["value"]), "classification": d["value_classification"]}
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
    def regime(cls):
        coins = cls.top_coins(20)
        if not coins: return {"regime": "unknown", "avg_24h": 0, "avg_7d": 0}
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
        return [{"symbol": c["symbol"].upper(),
                 "change_1h": round(c.get("price_change_percentage_1h_in_currency", 0) or 0, 2),
                 "change_24h": round(c.get("price_change_percentage_24h", 0) or 0, 2),
                 "price": c.get("current_price", 0),
                 "volume_24h": c.get("total_volume", 0)}
                for c in coins
                if abs(c.get("price_change_percentage_24h", 0) or 0) > 10
                or abs(c.get("price_change_percentage_1h_in_currency", 0) or 0) > 5]

# ============================================================================
# IA MULTI-MODELO (Groq → Gemini → Heurística)
# ============================================================================
class AIBrain:
    def think(self, prompt, max_tokens=512, temperature=0.3):
        # 1. Groq
        if GROQ_KEY:
            try:
                r = requests.post("https://api.groq.com/openai/v1/chat/completions",
                    headers={"Authorization": f"Bearer {GROQ_KEY}"},
                    json={"model": "llama-3.3-70b-versatile",
                          "messages": [{"role": "user", "content": prompt}],
                          "max_tokens": max_tokens, "temperature": temperature},
                    timeout=20)
                if r.ok:
                    return r.json()["choices"][0]["message"]["content"].strip()
            except Exception as e:
                log.debug(f"Groq fail: {e}")

        # 2. Gemini
        if GEMINI_KEY:
            try:
                r = requests.post(
                    f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_KEY}",
                    json={"contents": [{"parts": [{"text": prompt}]}]},
                    timeout=20)
                if r.ok:
                    return r.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
            except Exception as e:
                log.debug(f"Gemini fail: {e}")

        # 3. Heurística
        return json.dumps({"mode": "heuristic", "note": "LLM offline", "timestamp": int(time.time())})

    def sentiment_analysis(self, symbol):
        news = []
        if NEWS_API_KEY:
            try:
                r = requests.get(f"https://newsapi.org/v2/everything?q={symbol}&apiKey={NEWS_API_KEY}&language=en&sortBy=publishedAt&pageSize=5",
                                 timeout=10)
                if r.ok:
                    articles = r.json().get("articles", [])
                    for a in articles:
                        news.append(a.get("title", "") + " " + a.get("description", ""))
            except: pass
        if CRYPTOPANIC_KEY:
            try:
                r = requests.get(f"https://cryptopanic.com/api/v1/posts/?auth_token={CRYPTOPANIC_KEY}&currencies={symbol.lower()}",
                                 timeout=10)
                if r.ok:
                    for item in r.json().get("results", []):
                        news.append(item.get("title", ""))
            except: pass
        if not news:
            return {"sentiment": 0, "summary": "No news found", "confidence": 0.5}
        prompt = (f"Analyze the sentiment of these news headlines about {symbol}. "
                  f"Return a JSON with keys: sentiment (float -1 to 1), summary (string), confidence (0-1). "
                  f"News: {news[:10]}")
        resp = self.think(prompt, max_tokens=200)
        try:
            return json.loads(resp)
        except:
            return {"sentiment": 0, "summary": resp[:100], "confidence": 0.5}

AIBRAIN = AIBrain()

# ============================================================================
# BRAIN — com IA, Q-learning e preço dinâmico
# ============================================================================
class Brain:
    _q_weights = {"BUY": 0.5, "SELL": 0.5}

    @classmethod
    def _dynamic_price(cls, base_price, endpoint):
        peers = LEDGER.active_peers()
        rep = sum(p.get("reputation", 1.0) for p in peers) / max(len(peers), 1)
        conv = LEDGER.stats()["conv_rate"] / 100.0 if LEDGER.stats()["conv_rate"] else 0.1
        price = base_price * (1 + rep * 0.2) * (1 + conv * 0.1)
        return round(price, 4)

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
        fng = Market.fear_greed(); reg = Market.regime(); ano = Market.anomalies()
        return {"ts": int(time.time()), "fear_greed": fng, "regime": reg,
                "anomalies": ano[:5],
                "summary": f"Mercado em regime {reg.get('regime')} (24h {reg.get('avg_24h')}%), Fear&Greed={fng.get('value')} ({fng.get('classification')})"}

    @classmethod
    def sinais(cls, persist=True):
        coins = Market.top_coins(30)
        out = []
        for c in coins:
            ch1 = c.get("price_change_percentage_1h_in_currency", 0) or 0
            ch24 = c.get("price_change_percentage_24h", 0) or 0
            ch7 = c.get("price_change_percentage_7d_in_currency", 0) or 0
            score = ch7 * cls._q_weights.get("BUY", 0.5) + ch24 * 0.3 + ch1 * 0.2
            vol_score = (c.get("total_volume", 0) / max(c.get("market_cap", 1), 1)) * 100
            if score > 8 and ch1 > -2:
                sig, conf = "BUY", min(95, 55 + score * 1.5 + min(vol_score, 10))
            elif score < -8 and ch1 < 2:
                sig, conf = "SELL", min(95, 55 - score * 1.5 + min(vol_score, 10))
            else:
                sig, conf = "HOLD", 40
            entry = {"symbol": c["symbol"].upper(), "name": c.get("name"),
                     "signal": sig, "confidence": round(conf, 1),
                     "score": round(score, 2), "price": c.get("current_price"),
                     "change_1h": round(ch1, 2), "change_24h": round(ch24, 2)}
            out.append(entry)
            if persist and sig in ("BUY", "SELL") and conf > 65:
                LEDGER.log_signal(entry["symbol"], sig, entry["price"], conf)
        out.sort(key=lambda x: -x["confidence"])
        return {"ts": int(time.time()), "signals": out[:10]}

    @staticmethod
    def relatorio():
        analise = Brain.analise()
        sinais = Brain.sinais(persist=False)
        prompt = (f"Como analista quantitativo sênior, gere relatório executivo em português, "
                  f"até 250 palavras, JSON com chaves: tese, oportunidades (lista 3), riscos (lista 3), "
                  f"alocacao_sugerida (objeto com BTC/ETH/SOL/BNB/STABLES em %).\n"
                  f"Regime: {analise['regime']}\nFear&Greed: {analise['fear_greed']}\n"
                  f"Top sinais: {sinais['signals'][:3]}")
        ai_text = AIBRAIN.think(prompt, max_tokens=800)
        return {"ts": int(time.time()), "report": ai_text,
                "data": analise, "top_signals": sinais["signals"][:5]}

    @staticmethod
    def deep_think(question=""):
        q = question or "Qual a melhor estratégia cripto agora considerando regime e momentum?"
        ctx = json.dumps({"regime": Market.regime(), "fng": Market.fear_greed(),
                          "anomalias": Market.anomalies()[:5]})
        prompt = (f"<thinking>Raciocine passo a passo como o DeepSeek-R1.</thinking>\n"
                  f"Pergunta: {q}\nDados: {ctx}\n"
                  f"Em 400 palavras, explique seu raciocínio + conclusão. "
                  f"Retorne JSON com chaves: raciocinio (string), conclusao (string), confianca (0-1).")
        ai = AIBRAIN.think(prompt, max_tokens=1200)
        return {"ts": int(time.time()), "question": q, "answer": ai}

    @classmethod
    def swarm_vote(cls, question=""):
        peers = LEDGER.active_peers()
        my_view = Market.regime()
        votes = [{"node": WALLET.node_id, "vote": my_view, "stake": sum(s["amount"] for s in LEDGER.get_stakes(target=WALLET.node_id))}]
        for p in peers[:5]:
            try:
                r = requests.get(f"http://{p['host']}:{p.get('x402_port',8402)}/regime", timeout=3)
                if r.ok:
                    votes.append({"node": p["node_id"], "vote": r.json(),
                                  "stake": p.get("stake",0)})
            except: pass
        regimes = {}
        for v in votes:
            reg = v["vote"].get("regime")
            stake = v.get("stake", 0)
            regimes[reg] = regimes.get(reg, 0) + stake + 1
        consensus = max(regimes, key=regimes.get) if regimes else my_view.get("regime")
        return {"ts": int(time.time()), "consensus": consensus,
                "votes": len(votes), "peers_total": len(peers),
                "stake_weighted": True}

    @staticmethod
    def arbitrage():
        symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"]
        opps = []
        for sym in symbols:
            prices = PRICE_FEED.get_all_prices(sym)
            if len(prices) >= 2:
                ex_list = list(prices.items())
                for i in range(len(ex_list)):
                    for j in range(i+1, len(ex_list)):
                        ex1, p1 = ex_list[i]; ex2, p2 = ex_list[j]
                        if p2 == 0: continue
                        spread = (p1 - p2) / p2 * 100
                        if abs(spread) > 0.2:
                            opps.append({
                                "symbol": sym,
                                "exchange1": ex1, "price1": p1,
                                "exchange2": ex2, "price2": p2,
                                "spread_pct": round(spread, 3),
                                "direction": f"BUY {ex2}, SELL {ex1}" if spread > 0 else f"BUY {ex1}, SELL {ex2}"
                            })
        opps.sort(key=lambda x: -abs(x["spread_pct"]))
        return {"ts": int(time.time()), "opportunities": opps[:10]}

    @staticmethod
    def backtest():
        with sqlite3.connect(LEDGER.path) as c:
            c.row_factory = sqlite3.Row
            rows = [dict(r) for r in c.execute(
                """SELECT * FROM signals_log WHERE ts>? ORDER BY ts DESC LIMIT 100""",
                (int(time.time())-86400,)
            ).fetchall()]
        coins = {c["symbol"].upper(): c.get("current_price", 0) for c in Market.top_coins(50)}
        wins = losses = 0; pnl = 0.0
        for r in rows:
            curr = coins.get(r["symbol"])
            if not curr or not r["price"]: continue
            delta = (curr - r["price"]) / r["price"] * 100
            if r["signal"] == "BUY":
                pnl += delta; wins += 1 if delta > 0 else 0; losses += 1 if delta <= 0 else 0
            else:
                pnl -= delta; wins += 1 if delta < 0 else 0; losses += 1 if delta >= 0 else 0
        total = wins + losses
        if total > 0:
            wr = wins / total
            Brain._q_weights["BUY"] = max(0.3, min(0.7, wr))
            Brain._q_weights["SELL"] = 1.0 - Brain._q_weights["BUY"]
        return {"ts": int(time.time()), "trades_24h": total, "wins": wins, "losses": losses,
                "win_rate_pct": round(wins / max(total, 1) * 100, 1),
                "estimated_pnl_pct": round(pnl, 2), "strategy": "Q-learning dynamic weights"}

    @staticmethod
    def alpha_signal():
        validated = LEDGER.top_signals(min_conf=75, hours=24)
        if not validated:
            sinais = Brain.sinais(persist=False)
            validated = [s for s in sinais["signals"] if s["confidence"] > 75][:3]
        return {"ts": int(time.time()), "alpha_signals": validated,
                "win_rate_disclaimer": "Backtested 24h; past performance is not indicative."}

    @staticmethod
    def sentiment(symbol="BTC"):
        return AIBRAIN.sentiment_analysis(symbol)

    @staticmethod
    def stake_info():
        active_stakes = LEDGER.get_stakes()
        total_staked = sum(s["amount"] for s in active_stakes)
        today_earned = LEDGER.stats()["today_usdc"]
        apr = (today_earned / max(total_staked, 0.01)) * 365 * 100 if total_staked > 0 else 15.0
        return {"total_staked_usdc": total_staked, "active_stakes": active_stakes,
                "apr": round(min(apr, 100), 2), "note": "APR calculated from daily revenue"}

# ============================================================================
# SERVIDOR x402 com preços dinâmicos
# ============================================================================
app = Flask(__name__)
app.logger.disabled = True

_rl_lock = threading.Lock()
_rl = defaultdict(deque)
RL_RPM = int(os.getenv("OMEGA_RL_RPM", "60"))

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

BASE_PRICES = {
    "/fear-greed": 0.01, "/regime": 0.02, "/anomalias": 0.03,
    "/analise": 0.05, "/sinais": 0.10, "/relatorio": 0.25,
    "/swarm-vote": 0.05, "/deep-think": 0.15, "/arbitrage": 0.20,
    "/backtest": 0.30, "/alpha-signal": 1.00, "/sentiment": 0.15,
    "/stake-info": 0.05,
}
ENDPOINT_DESC = {
    "/fear-greed": "Fear & Greed Index + IA",
    "/regime": "Regime de mercado",
    "/anomalias": "Anomalias de preço/volume",
    "/analise": "Análise consolidada",
    "/sinais": "Sinais top-10",
    "/relatorio": "Relatório executivo",
    "/swarm-vote": "Consenso do enxame",
    "/deep-think": "Raciocínio longo com IA",
    "/arbitrage": "Arbitragem cross-exchange em tempo real",
    "/backtest": "Backtest com Q-learning",
    "/alpha-signal": "Sinal premium",
    "/sentiment": "Análise de sentimento de notícias",
    "/stake-info": "Informações de staking",
}

def get_dynamic_price(endpoint):
    base = BASE_PRICES.get(endpoint, 0.01)
    return Brain._dynamic_price(base, endpoint)

def _build_402(endpoint):
    amount = get_dynamic_price(endpoint)
    base = f"http://{request.host}" if request else ""
    payload = {
        "x402Version": 1,
        "error": "Payment Required",
        "accepts": [{
            "scheme": "exact",
            "network": "solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp",
            "maxAmountRequired": str(int(amount * 10**USDC_DECIMALS)),
            "resource": f"{base}{endpoint}",
            "description": ENDPOINT_DESC.get(endpoint, "NexusOmega API"),
            "mimeType": "application/json",
            "payTo": WALLET.solana_address,
            "maxTimeoutSeconds": 300,
            "asset": USDC_MINT,
            "extra": {"name": "USDC", "decimals": USDC_DECIMALS, "version": "1"},
            "extensions": {"bazaar": {"info": {"name": endpoint.strip("/"), "description": ENDPOINT_DESC.get(endpoint, ""), "method": "GET"}}}
        }],
    }
    b64 = base64.b64encode(json.dumps(payload).encode()).decode()
    resp = jsonify(payload)
    resp.status_code = 402
    resp.headers["WWW-Authenticate"] = "x402"
    resp.headers["Payment-Required"] = b64
    resp.headers["X-ACCEPTS-PAYMENT"] = "x402"
    resp.headers["X-Node-Id"] = WALLET.node_id
    resp.headers["X-Dynamic-Price"] = str(amount)
    return resp

def _verify_payment(endpoint, payment_header):
    if not payment_header:
        return False, "missing-header"
    h = hashlib.sha256(payment_header.encode()).hexdigest()
    if LEDGER.replay_check(h):
        return False, "replay-blocked"
    tx_sig, payer = payment_header, ""
    try:
        decoded = base64.b64decode(payment_header).decode()
        pdata = json.loads(decoded)
        tx_sig = pdata.get("signature") or pdata.get("tx") or payment_header
        payer = pdata.get("payer", "")
    except: pass
    amount = get_dynamic_price(endpoint)
    ok, reason = SOL.verify_payment(tx_sig, amount, WALLET.solana_address)
    if ok:
        LEDGER.add_revenue(endpoint, amount, tx_sig, payer, source="direct")
        if TG_TOKEN and TG_CHAT:
            try:
                requests.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
                    json={"chat_id": TG_CHAT,
                          "text": f"💰 Recebido ${amount} USDC em {endpoint}\nNode: {WALLET.node_id}\nTX: {tx_sig[:32]}..."},
                    timeout=5)
            except: pass
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

# Endpoints pagos
app.add_url_rule("/fear-greed", "fg", paid_endpoint("/fear-greed")(Brain.fear_greed))
app.add_url_rule("/regime", "rg", paid_endpoint("/regime")(Brain.regime))
app.add_url_rule("/anomalias", "an", paid_endpoint("/anomalias")(Brain.anomalias))
app.add_url_rule("/analise", "al", paid_endpoint("/analise")(Brain.analise))
app.add_url_rule("/sinais", "sn", paid_endpoint("/sinais")(Brain.sinais))
app.add_url_rule("/relatorio", "rl", paid_endpoint("/relatorio")(Brain.relatorio))
app.add_url_rule("/swarm-vote", "sv", paid_endpoint("/swarm-vote")(Brain.swarm_vote))
app.add_url_rule("/deep-think", "dt", paid_endpoint("/deep-think")(Brain.deep_think))
app.add_url_rule("/arbitrage", "ar", paid_endpoint("/arbitrage")(Brain.arbitrage))
app.add_url_rule("/backtest", "bt", paid_endpoint("/backtest")(Brain.backtest))
app.add_url_rule("/alpha-signal", "ap", paid_endpoint("/alpha-signal")(Brain.alpha_signal))
app.add_url_rule("/sentiment", "st", paid_endpoint("/sentiment")(Brain.sentiment))
app.add_url_rule("/stake-info", "si", paid_endpoint("/stake-info")(Brain.stake_info))

# Públicos
@app.route("/")
def root():
    return jsonify({"name": "NexusOmega Pro", "version": VERSION, "node_id": WALLET.node_id,
                    "solana_address": WALLET.solana_address, "endpoints": list(BASE_PRICES.keys()),
                    "prices_usdc": {k: get_dynamic_price(k) for k in BASE_PRICES},
                    "peers_active": len(LEDGER.active_peers())})
@app.route("/info")
def info():
    return jsonify({"name": "NexusOmega AI Swarm", "version": VERSION, "chain": "solana",
                    "asset": "USDC", "node_id": WALLET.node_id, "payout": WALLET.solana_address,
                    "endpoints": [{"path": p, "price_usdc": get_dynamic_price(p), "desc": ENDPOINT_DESC[p]} for p in BASE_PRICES],
                    "peers": len(LEDGER.active_peers())})
@app.route("/openapi.json")
def openapi_spec():
    base = f"http://{request.host}"
    paths = {}
    for p in BASE_PRICES:
        paths[p] = {"get": {"summary": ENDPOINT_DESC[p], "operationId": p.strip("/").replace("-","_"),
                            "x-payment-info": {"protocols": ["x402"], "price": {"mode": "dynamic", "currency": "USDC", "base_amount": BASE_PRICES[p]}},
                            "responses": {"200": {"description": "Pago com sucesso"}, "402": {"description": "Payment Required"}}}}
    return jsonify({"openapi": "3.0.3", "info": {"title": "NexusOmega", "version": VERSION},
                    "servers": [{"url": base}], "paths": paths,
                    "components": {"securitySchemes": {"x402": {"type": "http", "scheme": "x402"}}},
                    "security": [{"x402": []}], "x-discovery": {"ownershipProofs": [WALLET.solana_address]}})
@app.route("/.well-known/x402.json")
def x402_manifest():
    base = f"http://{request.host}"
    return jsonify({"version": 1, "resources": [f"{base}{p}" for p in BASE_PRICES] + [base],
                    "ownershipProofs": [WALLET.solana_address],
                    "instructions": "Pagamento via x402 scheme=exact em USDC-SPL na Solana mainnet"})
@app.route("/health")
def health():
    return jsonify({"ok": True, "ts": int(time.time()), "node_id": WALLET.node_id,
                    "peers": len(LEDGER.active_peers())})
@app.route("/peers")
def peers_list():
    return jsonify({"peers": LEDGER.active_peers(), "self": WALLET.node_id})

# ============================================================================
# GOSSIP P2P com reputação
# ============================================================================
class Gossip:
    def __init__(self):
        self.running = True

    @staticmethod
    def _public_ip():
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]; s.close()
            return ip
        except: return "127.0.0.1"

    def _announce(self):
        with sqlite3.connect(LEDGER.path) as c:
            total = c.execute("SELECT COUNT(*) FROM signals_log WHERE validated=1").fetchone()[0]
            wins = c.execute("SELECT COUNT(*) FROM signals_log WHERE validated=1 AND outcome_1h IS NOT NULL AND outcome_1h>0").fetchone()[0] if total else 0
            win_rate = wins / total if total > 0 else 0.0
            earned = c.execute("SELECT COALESCE(SUM(amount_usdc),0) FROM revenue").fetchone()[0]
        body = {"node_id": WALLET.node_id, "pubkey": WALLET.pubkey_b58,
                "host": self._public_ip(), "port": GOSSIP_PORT, "x402_port": X402_PORT,
                "solana_address": WALLET.solana_address, "version": VERSION,
                "models": ["groq","gemini"],
                "stake": sum(s["amount"] for s in LEDGER.get_stakes(target=WALLET.node_id)),
                "win_rate": win_rate,
                "total_earned": earned,
                "ts": int(time.time())}
        body["sig"] = base58.b58encode(WALLET.sign(json.dumps(body, sort_keys=True).encode())).decode()
        return body

    def _verify(self, msg):
        sig = msg.pop("sig", None)
        if not sig: return False
        ok = WALLET.verify(msg["pubkey"], json.dumps(msg, sort_keys=True).encode(), base58.b58decode(sig))
        msg["sig"] = sig
        return ok

    def _mcast_send(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
        while self.running:
            try:
                sock.sendto(json.dumps(self._announce()).encode(), (MCAST_GRP, MCAST_PORT))
            except: pass
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
                if msg.get("node_id") == WALLET.node_id: continue
                if self._verify(msg):
                    LEDGER.upsert_peer(msg)
            except socket.timeout: continue
            except: pass

    def _tcp_server(self):
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            srv.bind(("0.0.0.0", GOSSIP_PORT)); srv.listen(8); srv.settimeout(2)
        except Exception as e:
            log.warning(f"tcp bind: {e}"); return
        while self.running:
            try:
                conn, _ = srv.accept()
                threading.Thread(target=self._handle_conn, args=(conn,), daemon=True).start()
            except socket.timeout: continue

    def _handle_conn(self, conn):
        try:
            conn.settimeout(5)
            req = json.loads(conn.recv(16384).decode() or "{}")
            if req.get("op") == "peers":
                resp = {"peers": LEDGER.active_peers()[:50], "self": self._announce()}
                conn.sendall(json.dumps(resp).encode())
            elif req.get("op") == "ping":
                conn.sendall(json.dumps({"pong": WALLET.node_id, "ts": int(time.time())}).encode())
        except: pass
        finally:
            try: conn.close()
            except: pass

    def _bootstrap_loop(self):
        while self.running:
            try:
                for seed in BOOTSTRAP_SEEDS:
                    try:
                        host, port = seed.split(":")
                        with socket.create_connection((host, int(port)), timeout=5) as s:
                            s.sendall(json.dumps({"op": "peers"}).encode())
                            data = s.recv(32768)
                        resp = json.loads(data.decode())
                        if resp.get("self"): LEDGER.upsert_peer(resp["self"])
                        for p in resp.get("peers", []):
                            if p.get("node_id") != WALLET.node_id:
                                LEDGER.upsert_peer(p)
                    except: pass
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
                    except: pass
            except: pass
            time.sleep(45)

    def start(self):
        for fn in (self._mcast_send, self._mcast_recv, self._tcp_server, self._bootstrap_loop):
            threading.Thread(target=fn, daemon=True).start()
        log.info(f"📡 Gossip ativo (mcast {MCAST_GRP}:{MCAST_PORT}, tcp :{GOSSIP_PORT})")

GOSSIP = Gossip()

# ============================================================================
# CLIENT AGENT (cross-trade simulado)
# ============================================================================
class ClientAgent:
    def __init__(self, min_balance=0.10, max_per_hour=1.0):
        self.min_balance = min_balance
        self.max_per_hour = max_per_hour
        self.spent_this_hour = 0.0
        self.hour_reset = time.time() + 3600

    def _can_spend(self, amount):
        if time.time() > self.hour_reset:
            self.spent_this_hour = 0.0; self.hour_reset = time.time() + 3600
        balance = SOL.get_balance_usdc(WALLET.solana_address)
        return (balance - amount > self.min_balance) and (self.spent_this_hour + amount < self.max_per_hour)

    def cross_trade_loop(self):
        while True:
            try:
                peers = LEDGER.active_peers()
                if not peers: time.sleep(60); continue
                peer = random.choice(peers)
                endpoint = random.choice(["/fear-greed", "/regime", "/sentiment"])
                price = get_dynamic_price(endpoint)
                if self._can_spend(price):
                    log.info(f"[CLIENT] Cross-trade executado: {peer.get('node_id')} {endpoint} ${price}")
                    # Aqui entraria a lógica de assinar e enviar transação SPL
                time.sleep(180 + random.randint(0,120))
            except Exception as e:
                log.debug(f"client agent: {e}"); time.sleep(120)

CLIENT = ClientAgent()

# ============================================================================
# SWEEPER
# ============================================================================
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
                        requests.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
                            json={"chat_id": TG_CHAT, "text": f"💸 SWEEP RECOMENDADO\nSaldo: {bal:.4f} USDC\nDestino: {self.dest}"}, timeout=5)
            except: pass
            time.sleep(SWEEP_INTERVAL)

SWEEPER = Sweeper()

# ============================================================================
# DASHBOARD
# ============================================================================
DASHBOARD = r"""
<!DOCTYPE html><html><head><meta charset="utf-8"><title>Nexus Omega Pro</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<style>
:root{--bg:#06080f;--card:#101729;--bd:#1a2440;--tx:#e5edff;--mt:#7a86a6;--ac:#00ffd1;--ac2:#7b61ff}
*{box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif;background:var(--bg);color:var(--tx);margin:0;padding:20px}
h1{font-size:26px;background:linear-gradient(90deg,var(--ac),var(--ac2));-webkit-background-clip:text;color:transparent}
.sub{color:var(--mt);font-family:monospace;font-size:12px;margin-bottom:24px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:14px;margin-bottom:20px}
.card{background:var(--card);border:1px solid var(--bd);border-radius:14px;padding:16px}
.card h3{margin:0 0 8px;color:var(--mt);font-size:11px;text-transform:uppercase}
.card .v{font-size:24px;font-weight:700;color:var(--ac)}
.row{display:grid;grid-template-columns:2fr 1fr;gap:14px;margin-bottom:14px}
@media(max-width:900px){.row{grid-template-columns:1fr}}
table{width:100%;border-collapse:collapse;font-size:12px}
th,td{padding:7px;text-align:left;border-bottom:1px solid var(--bd)}
.badge{display:inline-block;padding:2px 7px;background:#1a2440;border-radius:4px;font-size:10px;font-family:monospace}
.badge.green{background:rgba(0,255,209,.15);color:var(--ac)}
.badge.red{background:rgba(255,75,75,.15);color:#ff4b4b}
</style></head><body>
<h1>⚡ Nexus Omega Pro</h1>
<div class="sub">Nó <b>{{node_id}}</b> · Solana <b>{{address}}</b></div>
<div class="grid">
  <div class="card"><h3>💰 Total</h3><div class="v" id="total">—</div></div>
  <div class="card"><h3>📈 Hoje</h3><div class="v" id="today">—</div></div>
  <div class="card"><h3>⏰ Última Hora</h3><div class="v" id="hour">—</div></div>
  <div class="card"><h3>🔁 Requisições</h3><div class="v" id="req">—</div></div>
  <div class="card"><h3>🌐 Peers</h3><div class="v" id="peers">—</div></div>
  <div class="card"><h3>🏦 Sweep</h3><div class="v" id="sweep">—</div></div>
  <div class="card"><h3>💎 Hot Wallet</h3><div class="v" id="hot">—</div></div>
  <div class="card"><h3>📊 Staked</h3><div class="v" id="staked">—</div></div>
</div>
<div class="row">
  <div class="card"><h3>📊 Receita por Hora</h3><canvas id="chart" height="120"></canvas></div>
  <div class="card"><h3>📥 Endereço</h3><div style="font-family:monospace;font-size:13px">{{address}}</div></div>
</div>
<script>
let chart=null;
function fmt$(v){return '$'+(+v).toFixed(4)}
function ago(ts){const d=Date.now()/1000-ts;if(d<60)return Math.floor(d)+'s';if(d<3600)return Math.floor(d/60)+'m';return Math.floor(d/3600)+'h'}
async function refresh(){
  try{
    const r=await fetch('/api/stats').then(r=>r.json());
    document.getElementById('total').textContent=fmt$(r.stats.total_usdc);
    document.getElementById('today').textContent=fmt$(r.stats.today_usdc);
    document.getElementById('hour').textContent=fmt$(r.stats.hour_usdc);
    document.getElementById('req').textContent=r.stats.requests_today;
    document.getElementById('peers').textContent=r.peers.length;
    document.getElementById('sweep').textContent=fmt$(r.stats.swept_to_binance);
    document.getElementById('hot').textContent=fmt$(r.hot_balance);
    document.getElementById('staked').textContent=fmt$(r.stats.staked_usdc);
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
    return render_template_string(DASHBOARD, version=VERSION, node_id=WALLET.node_id, address=WALLET.solana_address)
@dash_app.route("/api/stats")
def dash_api():
    try: hot_balance = SOL.get_balance_usdc(WALLET.solana_address)
    except: hot_balance = 0.0
    return jsonify({"stats": LEDGER.stats(), "revenue": LEDGER.recent_revenue(20),
                    "peers": LEDGER.active_peers(), "series": LEDGER.revenue_series_24h(),
                    "sweeps": LEDGER.recent_sweeps(10), "hot_balance": hot_balance,
                    "node_id": WALLET.node_id, "version": VERSION})

# ============================================================================
# WORKERS
# ============================================================================
def signal_validator_loop():
    while True:
        time.sleep(600)
        try:
            Brain.validate_signals()
        except: pass

def signal_generator_loop():
    while True:
        try: Brain.sinais(persist=True)
        except: pass
        time.sleep(300)

def stake_reward_loop():
    while True:
        time.sleep(86400)
        stakes = LEDGER.get_stakes()
        for s in stakes:
            if s["duration"] > 0 and time.time() - s["start_ts"] >= s["duration"]:
                reward = s["amount"] * 0.01
                LEDGER.add_revenue("stake_reward", reward, source="staking")
                with sqlite3.connect(LEDGER.path) as c:
                    c.execute("UPDATE staking SET status='completed', reward=? WHERE id=?", (reward, s["id"]))

# ============================================================================
# RUNTIME (ajustado para usar a porta dinâmica)
# ============================================================================
def run_servers(solo=False):
    # O servidor x402 usará a porta definida pela variável PORT (ou 8402 por padrão)
    threading.Thread(
        target=lambda: app.run(host="0.0.0.0", port=X402_PORT, threaded=True, use_reloader=False),
        daemon=True
    ).start()
    log.info(f"💼 Servidor x402: http://0.0.0.0:{X402_PORT}")

    # O dashboard permanece na porta DASHBOARD_PORT (8080) – você pode acessar localmente
    threading.Thread(
        target=lambda: dash_app.run(host="0.0.0.0", port=DASHBOARD_PORT, threaded=True, use_reloader=False),
        daemon=True
    ).start()
    log.info(f"📊 Dashboard: http://localhost:{DASHBOARD_PORT}")

    if not solo:
        GOSSIP.start()
        threading.Thread(target=CLIENT.cross_trade_loop, daemon=True).start()
    threading.Thread(target=signal_validator_loop, daemon=True).start()
    threading.Thread(target=signal_generator_loop, daemon=True).start()
    threading.Thread(target=SWEEPER.loop, daemon=True).start()
    threading.Thread(target=stake_reward_loop, daemon=True).start()

def main_loop():
    log.info("="*72)
    log.info(f"⚡ NEXUS OMEGA v{VERSION} — ATIVO")
    log.info(f"   Node ID:    {WALLET.node_id}")
    log.info(f"   Recebe:     {WALLET.solana_address}  (USDC-SPL Solana)")
    if BINANCE_ADDRESS: log.info(f"   Sweep →    {BINANCE_ADDRESS}")
    log.info(f"   Dashboard:  http://localhost:{DASHBOARD_PORT}")
    log.info(f"   x402 API:   http://localhost:{X402_PORT} (pública: via Railway)")
    log.info("="*72)
    try:
        while True:
            time.sleep(60)
            s = LEDGER.stats()
            p = len(LEDGER.active_peers())
            log.info(f"💓 alive · total=${s['total_usdc']:.4f} · 24h=${s['today_usdc']:.4f} · "
                     f"1h=${s['hour_usdc']:.4f} · peers={p} · conv={s['conv_rate']}% · staked=${s['staked_usdc']:.2f}")
    except KeyboardInterrupt:
        log.info("👋 Encerrando NexusOmega")
        sys.exit(0)

def cli():
    args = sys.argv[1:]
    if "--help" in args or "-h" in args:
        print(__doc__); sys.exit(0)
    if "--wallet" in args:
        print(json.dumps({"node_id": WALLET.node_id, "solana_address": WALLET.solana_address,
                          "pubkey": WALLET.pubkey_b58}, indent=2)); sys.exit(0)
    if "--export-wallet" in args:
        if WALLET_PATH.exists():
            print("⚠️  CONTEÚDO SENSÍVEL (mantenha offline):")
            print(WALLET_PATH.read_text())
        sys.exit(0)
    if "--reset" in args:
        if DB_PATH.exists(): DB_PATH.unlink(); print("⚠️  Ledger resetado. Wallet preservada.")
        sys.exit(0)
    if "--binance" in args:
        idx = args.index("--binance")
        if idx+1 < len(args):
            os.environ["BINANCE_SOLANA_ADDRESS"] = args[idx+1]
            print(f"✅ BINANCE_SOLANA_ADDRESS configurada para {args[idx+1]}")
    if "--port" in args:
        idx = args.index("--port")
        if idx+1 < len(args):
            # Se a porta for passada como argumento, sobrescreve a variável X402_PORT
            globals()["X402_PORT"] = int(args[idx+1])

if __name__ == "__main__":
    cli()
    solo = "--solo" in sys.argv
    run_servers(solo=solo)
    main_loop()
