# -*- coding: utf-8 -*-
"""
x402_nexusai_binance_v3.py — NexusAI como API paga via Binance x402 + BNB Chain
==================================================================================
MODO REAL (mainnet) — 100% Binance. Sem Coinbase. Sem Trust Wallet.
Recebe USDT/USDC diretamente na sua carteira da Binance (endereço BEP-20).

MELHORIAS v3 (em relação ao original):
  - Fix de UnicodeDecodeError no load_dotenv (encoding explicito)
  - NETWORK_MODE padrão agora é "mainnet"
  - Proteção anti-replay: pagamentos usados são descartados (TTL 10 min)
  - Janela on-chain ampliada de 20 para 50 blocos (~2.5 min)
  - Dados reais de preço via CoinGecko API (gratuito, sem chave)
  - Fear & Greed real via alternative.me API
  - Logs mais ricos (tx hash, valores, IPs)
  - Health check com detalhes de conectividade
  - Graceful shutdown via signal handlers
  - Arquivo .env criado automaticamente se ausente

COMO FUNCIONA:
  1. Agente externo chama GET /analise (sem header X-Payment)
  2. Servidor responde HTTP 402 + instruções de pagamento (BNB Chain)
  3. Agente paga via EIP-3009 ou Permit2 para o seu endereço BEP-20 da Binance
  4. Agente reenvia com header X-Payment preenchido
  5. Servidor verifica on-chain no BNB Chain via RPC público
  6. USDT cai direto na sua conta Binance — sem etapas extras

COMO PEGAR SEU ENDEREÇO BEP-20 NA BINANCE:
  1. Acesse binance.com → Carteira → Depósito
  2. Selecione USDT → Rede: BNB Smart Chain (BEP-20)
  3. Copie o endereço 0x... e cole em BINANCE_WALLET_ADDRESS no .env

INSTALAÇÃO:
  pip install flask web3 requests python-dotenv --break-system-packages

DEPLOY GRATUITO:
  railway.app → conecta GitHub → deploy automático → URL pública em minutos
  render.com  → alternativa igualmente gratuita

APÓS O DEPLOY:
  Registre sua URL em x402scan.com para outros agentes encontrarem sua API.

DOCUMENTAÇÃO:
  https://www.binance.com/en/blog/ecosystem/introducing-binance-x402
  https://docs.x402.org
"""

import os
import sys
import time
import json
import signal
import hashlib
import logging
import threading
from collections import defaultdict, deque
from functools import wraps
from datetime import datetime, timezone

import requests
from flask import Flask, jsonify, request, g

# ── ENCODING FIX ──────────────────────────────────────────────────────────────
# Corrige o UnicodeDecodeError que ocorre quando o .env tem caracteres
# especiais (acentos, etc.) salvos em Latin-1/Windows-1252.
# Tenta UTF-8 primeiro, depois Latin-1 como fallback.

def _load_dotenv_safe(path: str = ".env"):
    """Carrega variáveis de ambiente do .env com detecção automática de encoding."""
    if not os.path.exists(path):
        _create_default_env(path)
        return

    for enc in ("utf-8", "utf-8-sig", "latin-1", "cp1252"):
        try:
            from dotenv import dotenv_values
            vals = dotenv_values(path, encoding=enc)
            for k, v in vals.items():
                if k and v is not None and k not in os.environ:
                    os.environ[k] = v
            return
        except Exception:
            continue

    # Fallback manual: lê linha a linha ignorando erros
    try:
        with open(path, "rb") as f:
            for line in f:
                try:
                    decoded = line.decode("utf-8", errors="replace").strip()
                    if decoded and not decoded.startswith("#") and "=" in decoded:
                        key, _, val = decoded.partition("=")
                        key = key.strip()
                        val = val.strip().strip('"').strip("'")
                        if key and key not in os.environ:
                            os.environ[key] = val
                except Exception:
                    pass
    except Exception as e:
        print(f"[WARN] Não foi possível ler .env: {e}")


def _create_default_env(path: str = ".env"):
    """Cria um .env modelo se não existir."""
    template = """\
# ============================================================
# NexusAI x402 — Configuração de Ambiente
# ============================================================

# === OBRIGATÓRIO ===
# Sua carteira BEP-20 da Binance (Carteira → Depósito → USDT → BNB Smart Chain)
BINANCE_WALLET_ADDRESS=0x

# === MODO DE REDE ===
# "mainnet" para operar em real | "testnet" para testes
NETWORK_MODE=mainnet

# === CHAVES DE IA (pelo menos uma obrigatória) ===
GROQ_API_KEY=
GEMINI_API_KEY=

# === OPCIONAIS ===
PORT=5050
CACHE_TTL_SECONDS=60
RATE_LIMIT_RPM=30
PAYMENT_TOKEN=USDT
# PRICE_ANALISE=0.05
# PRICE_SINAIS=0.10
# PRICE_RELATORIO=0.25
# PRICE_FEAR_GREED=0.01
# PRICE_REGIME=0.02
# PRICE_ANOMALIAS=0.03
# BSC_RPC=https://bsc-dataseed1.binance.org/
# BINANCE_X402_FACILITATOR=
"""
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(template)
        print(f"[INFO] Arquivo .env criado em '{path}' — preencha BINANCE_WALLET_ADDRESS e GROQ_API_KEY antes de iniciar.")
    except Exception as e:
        print(f"[WARN] Não foi possível criar .env: {e}")


_load_dotenv_safe()

# ── LOGGING ESTRUTURADO ───────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("nexusai-x402")

# ── CONFIG PRINCIPAL ──────────────────────────────────────────────────────────

BINANCE_WALLET = os.getenv("BINANCE_WALLET_ADDRESS", "").strip()

GROQ_API_KEY   = os.getenv("GROQ_API_KEY", "").strip()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()

# Padrão agora é mainnet (modo real)
NETWORK_MODE = os.getenv("NETWORK_MODE", "mainnet").strip().lower()
BSC_CHAIN_ID = 56 if NETWORK_MODE == "mainnet" else 97

BSC_RPC = os.getenv(
    "BSC_RPC",
    "https://bsc-dataseed1.binance.org/" if NETWORK_MODE == "mainnet"
    else "https://data-seed-prebsc-1-s1.binance.org:8545/"
).strip()

NEXUSAI_PATH = os.getenv("NEXUSAI_PATH", "/home/user/defai_v4").strip()
PORT         = int(os.getenv("PORT", "5050"))
CACHE_TTL    = int(os.getenv("CACHE_TTL_SECONDS", "60"))
RATE_LIMIT_RPM = int(os.getenv("RATE_LIMIT_RPM", "30"))

PAYMENT_TOKEN = os.getenv("PAYMENT_TOKEN", "USDT").strip().upper()

# Decimais por token (USDT e USDC BEP-20 têm 18 decimais na BSC)
TOKEN_DECIMALS = {"USDT": 18, "USDC": 18, "BUSD": 18}

PAYMENT_TOKEN_CA = {
    "USDT": "0x55d398326f99059fF775485246999027B3197955",
    "USDC": "0x8AC76a51cc950d9822D68b83fE1Ad97B32Cd580d",
    "BUSD": "0xe9e7CEA3DedcA5984780Bafc599bD69ADd087D56",
}.get(PAYMENT_TOKEN, "0x55d398326f99059fF775485246999027B3197955")

TOKEN_DEC = TOKEN_DECIMALS.get(PAYMENT_TOKEN, 18)

PRICES = {
    "/fear-greed": os.getenv("PRICE_FEAR_GREED", "0.01"),
    "/regime":     os.getenv("PRICE_REGIME",     "0.02"),
    "/anomalias":  os.getenv("PRICE_ANOMALIAS",  "0.03"),
    "/analise":    os.getenv("PRICE_ANALISE",    "0.05"),
    "/sinais":     os.getenv("PRICE_SINAIS",     "0.10"),
    "/relatorio":  os.getenv("PRICE_RELATORIO",  "0.25"),
}

ENDPOINT_DESC = {
    "/fear-greed": "Fear & Greed Index processado pela IA",
    "/regime":     "Regime de mercado cripto atual",
    "/anomalias":  "Anomalias detectadas por z-score",
    "/analise":    "Análise completa de mercado",
    "/sinais":     "Sinais de trading com confiança",
    "/relatorio":  "Relatório premium completo",
}

# FLASK_SKIP_DOTENV=1 impede o Flask de chamar load_dotenv() internamente
# com encoding utf-8 fixo — nosso _load_dotenv_safe() já fez a leitura correta.
os.environ.setdefault("FLASK_SKIP_DOTENV", "1")

app = Flask(__name__)

# ── VALIDAÇÃO DE CONFIG ───────────────────────────────────────────────────────

def _validate_config():
    erros = []
    if not BINANCE_WALLET or BINANCE_WALLET in ("0x", ""):
        erros.append("BINANCE_WALLET_ADDRESS não configurado no .env")
    elif not BINANCE_WALLET.startswith("0x") or len(BINANCE_WALLET) != 42:
        erros.append("BINANCE_WALLET_ADDRESS inválido — deve ser 0x + 40 hex chars")
    if not GROQ_API_KEY and not GEMINI_API_KEY:
        erros.append("Configure pelo menos GROQ_API_KEY ou GEMINI_API_KEY no .env")
    if NETWORK_MODE not in ("mainnet", "testnet"):
        erros.append(f"NETWORK_MODE inválido: '{NETWORK_MODE}' (use mainnet ou testnet)")
    if erros:
        for e in erros:
            log.error(f"CONFIG: {e}")
        log.warning("Servidor iniciado com configuração incompleta — verifique o .env")
    return erros

# ── ANTI-REPLAY: pagamentos já utilizados ─────────────────────────────────────

_replay_lock   = threading.Lock()
_used_payments = {}          # hash → timestamp
_REPLAY_TTL    = 600         # 10 minutos

def _payment_hash(header: str) -> str:
    return hashlib.sha256(header.encode()).hexdigest()

def _is_replay(header: str) -> bool:
    """Retorna True se este exato pagamento já foi aceito antes (replay attack)."""
    ph  = _payment_hash(header)
    now = time.time()
    with _replay_lock:
        # Limpa entradas expiradas
        expired = [k for k, ts in _used_payments.items() if now - ts > _REPLAY_TTL]
        for k in expired:
            del _used_payments[k]
        if ph in _used_payments:
            return True
        _used_payments[ph] = now
    return False

# ── CACHE DE ANÁLISE ──────────────────────────────────────────────────────────

_cache_lock = threading.Lock()
_cache      = {"data": None, "ts": 0}

def _get_cached_analysis():
    with _cache_lock:
        if _cache["data"] and (time.time() - _cache["ts"]) < CACHE_TTL:
            return _cache["data"]
    return None

def _set_cache(data: dict):
    with _cache_lock:
        _cache["data"] = data
        _cache["ts"]   = time.time()

# ── RATE LIMITING POR IP ──────────────────────────────────────────────────────

_rl_lock  = threading.Lock()
_rl_store = defaultdict(deque)

def _is_rate_limited(ip: str) -> bool:
    now = time.time()
    with _rl_lock:
        dq = _rl_store[ip]
        while dq and dq[0] < now - 60:
            dq.popleft()
        if len(dq) >= RATE_LIMIT_RPM:
            return True
        dq.append(now)
    return False

# ── ANALYTICS EM MEMÓRIA ──────────────────────────────────────────────────────

_stats_lock = threading.Lock()
_stats = {
    "start_time":     time.time(),
    "total_requests": 0,
    "paid_requests":  0,
    "rejected_rl":    0,
    "replay_blocked": 0,
    "revenue_usdt":   0.0,
    "by_endpoint":    defaultdict(lambda: {"requests": 0, "paid": 0, "revenue": 0.0}),
    "cache_hits":     0,
    "cache_misses":   0,
}

def _record(endpoint: str, paid: bool, price: float = 0.0, cache_hit: bool = False):
    with _stats_lock:
        _stats["total_requests"] += 1
        _stats["by_endpoint"][endpoint]["requests"] += 1
        if paid:
            _stats["paid_requests"] += 1
            _stats["revenue_usdt"]  += price
            _stats["by_endpoint"][endpoint]["paid"]    += 1
            _stats["by_endpoint"][endpoint]["revenue"] += price
        if cache_hit:
            _stats["cache_hits"] += 1
        else:
            _stats["cache_misses"] += 1

# ── DADOS REAIS DE MERCADO (CoinGecko + Alternative.me) ──────────────────────

_market_cache      = {"data": None, "ts": 0}
_market_cache_lock = threading.Lock()
_MARKET_TTL        = 90  # segundos

def _fetch_real_market_data() -> dict:
    """Busca preços reais via CoinGecko (gratuito, sem API key) e Fear & Greed."""
    now = time.time()
    with _market_cache_lock:
        if _market_cache["data"] and now - _market_cache["ts"] < _MARKET_TTL:
            return _market_cache["data"]

    result = {"precos": {}, "fear_greed": {"value": 50, "label": "Neutral"}}

    # Preços via CoinGecko
    try:
        r = requests.get(
            "https://api.coingecko.com/api/v3/simple/price",
            params={
                "ids":              "bitcoin,ethereum,solana,binancecoin",
                "vs_currencies":    "usd",
                "include_24hr_change": "true",
            },
            timeout=8,
            headers={"Accept": "application/json"},
        )
        if r.ok:
            d = r.json()
            result["precos"] = {
                "BTC": {"usd": d.get("bitcoin",     {}).get("usd", 0), "change_24h": round(d.get("bitcoin",     {}).get("usd_24h_change", 0), 2)},
                "ETH": {"usd": d.get("ethereum",    {}).get("usd", 0), "change_24h": round(d.get("ethereum",    {}).get("usd_24h_change", 0), 2)},
                "SOL": {"usd": d.get("solana",      {}).get("usd", 0), "change_24h": round(d.get("solana",      {}).get("usd_24h_change", 0), 2)},
                "BNB": {"usd": d.get("binancecoin", {}).get("usd", 0), "change_24h": round(d.get("binancecoin", {}).get("usd_24h_change", 0), 2)},
            }
    except Exception as e:
        log.warning(f"CoinGecko indisponível: {e}")

    # Fear & Greed via alternative.me
    try:
        r2 = requests.get("https://api.alternative.me/fng/", timeout=6)
        if r2.ok:
            fg = r2.json()["data"][0]
            result["fear_greed"] = {
                "value": int(fg["value"]),
                "label": fg["value_classification"],
            }
    except Exception as e:
        log.warning(f"Fear & Greed API indisponível: {e}")

    with _market_cache_lock:
        _market_cache["data"] = result
        _market_cache["ts"]   = now

    return result

# ── VERIFICADOR x402 / BNB CHAIN ──────────────────────────────────────────────

class BinanceBSCVerifier:
    """
    Verifica pagamentos x402 diretamente no BNB Chain via web3.
    Sem dependência de SDK Coinbase ou Trust Wallet.
    Usa apenas web3.py + RPC público da Binance.
    """

    def __init__(self):
        self.w3        = None
        self.connected = False
        self._init_web3()

    def _init_web3(self):
        try:
            from web3 import Web3
            self.w3        = Web3(Web3.HTTPProvider(BSC_RPC, request_kwargs={"timeout": 12}))
            self.connected = self.w3.is_connected()
            status         = "conectado ✓" if self.connected else "offline"
            log.info(f"BNB Chain RPC ({NETWORK_MODE}): {status} → {BSC_RPC}")
        except ImportError:
            log.warning("web3 não instalado — verificação on-chain indisponível (pip install web3)")
        except Exception as e:
            log.warning(f"BNB Chain RPC indisponível: {e}")

    def build_402_payload(self, endpoint: str) -> dict:
        """Monta o payload HTTP 402 padrão x402 para o agente pagador."""
        price_float = float(PRICES[endpoint])
        price_wei   = int(price_float * 10 ** TOKEN_DEC)

        return {
            "x402Version": "1",
            "error":       "Payment Required",
            "accepts": [{
                "scheme":            "exact",
                "network":           "bsc" if NETWORK_MODE == "mainnet" else "bsc-testnet",
                "chainId":           BSC_CHAIN_ID,
                "maxAmountRequired": str(price_wei),
                "resource":          endpoint,
                "description":       ENDPOINT_DESC.get(endpoint, "NexusAI API"),
                "mimeType":          "application/json",
                "payTo":             BINANCE_WALLET,
                "maxTimeoutSeconds": 300,
                "asset":             PAYMENT_TOKEN_CA,
                "extra": {
                    "token":       PAYMENT_TOKEN,
                    "decimals":    TOKEN_DEC,
                    "facilitator": "binance-x402",
                    "network":     "BNB Smart Chain (BEP-20)",
                    "wallet_hint": "Use seu endereço BEP-20 — BNB Smart Chain",
                },
            }],
        }

    def verify(self, payment_header: str, endpoint: str) -> tuple:
        """
        Verifica o pagamento recebido no header X-Payment.

        Estratégia em 4 camadas:
          1. Anti-replay (bloqueia reuso do mesmo header)
          2. Validação estrutural do JSON
          3. Verificação via facilitador Binance x402 (se configurado)
          4. Verificação direta on-chain via eventos Transfer no BNB Chain
        """
        if not payment_header:
            return False, "Header X-Payment ausente"

        # 1. Anti-replay
        if _is_replay(payment_header):
            log.warning(f"Replay attack bloqueado: {endpoint}")
            with _stats_lock:
                _stats["replay_blocked"] += 1
            return False, "Pagamento já utilizado (replay bloqueado)"

        # 2. Parse e validação estrutural
        try:
            pdata = json.loads(payment_header)
        except (json.JSONDecodeError, TypeError):
            return False, "X-Payment: JSON inválido"

        required = ["protocol", "network", "amount", "recipient", "signature"]
        missing  = [f for f in required if f not in pdata]
        if missing:
            return False, f"X-Payment: campos ausentes {missing}"

        if pdata.get("protocol") != "x402":
            return False, "Protocolo inválido (esperado: x402)"

        if pdata.get("recipient", "").lower() != BINANCE_WALLET.lower():
            return False, f"Destinatário incorreto. Esperado: {BINANCE_WALLET}"

        price_wei   = int(float(PRICES[endpoint]) * 10 ** TOKEN_DEC)
        paid_amount = int(pdata.get("amount", "0"))
        if paid_amount < price_wei:
            return False, f"Valor insuficiente: {paid_amount} < {price_wei} wei"

        # 3. Verificação via facilitador Binance x402
        ok, msg = self._verify_via_facilitator(pdata, endpoint)
        if ok:
            return True, msg

        # 4. Fallback: verificação direta on-chain
        return self._verify_onchain(price_wei)

    def _verify_via_facilitator(self, pdata: dict, endpoint: str) -> tuple:
        """Chama o facilitador Binance x402 para verificação off-chain."""
        facilitator_url = os.getenv("BINANCE_X402_FACILITATOR", "").strip()
        if not facilitator_url:
            return False, "Facilitador Binance não configurado"
        try:
            resp = requests.post(
                facilitator_url,
                json={"payment": pdata, "resource": endpoint, "network": "bsc"},
                timeout=8,
                headers={"Content-Type": "application/json"},
            )
            if resp.ok:
                result = resp.json()
                if result.get("valid"):
                    log.info(f"Pagamento verificado pelo facilitador Binance: {endpoint}")
                    return True, "Verificado pelo facilitador Binance x402"
                return False, result.get("error", "Inválido pelo facilitador")
        except Exception as e:
            log.debug(f"Facilitador Binance indisponível: {e}")
        return False, "Facilitador indisponível"

    def _verify_onchain(self, price_wei: int) -> tuple:
        """
        Verifica transferência diretamente no BNB Chain.
        Janela ampliada: últimos 50 blocos (~2.5 minutos).
        """
        if not self.connected or not self.w3:
            if NETWORK_MODE == "testnet":
                log.info("TESTNET: pagamento simulado aceito")
                return True, "Pagamento aceito (modo testnet/simulação)"
            return False, "Verificação on-chain indisponível — configure web3"

        try:
            from web3 import Web3
            ERC20_ABI = [{
                "anonymous": False,
                "inputs": [
                    {"indexed": True,  "name": "from",  "type": "address"},
                    {"indexed": True,  "name": "to",    "type": "address"},
                    {"indexed": False, "name": "value", "type": "uint256"},
                ],
                "name": "Transfer", "type": "event",
            }]
            token   = self.w3.eth.contract(
                address=Web3.to_checksum_address(PAYMENT_TOKEN_CA),
                abi=ERC20_ABI
            )
            latest  = self.w3.eth.block_number
            # Janela de 50 blocos (~2.5 min na BSC)
            eventos = token.events.Transfer.get_logs(
                from_block=max(0, latest - 50),
                to_block=latest,
                argument_filters={"to": Web3.to_checksum_address(BINANCE_WALLET)},
            )
            for ev in eventos:
                if ev["args"]["value"] >= price_wei:
                    tx = ev["transactionHash"].hex()
                    log.info(f"Transferência on-chain confirmada: {tx} ({ev['args']['value'] / 10**TOKEN_DEC:.6f} {PAYMENT_TOKEN})")
                    return True, f"On-chain confirmado: {tx}"

            return False, "Nenhuma transferência on-chain encontrada nos últimos 50 blocos"
        except Exception as e:
            log.error(f"Erro verificação on-chain: {e}")
            return False, f"Erro on-chain: {e}"


verifier = BinanceBSCVerifier()

# ── DECORATOR payment_required (Binance x402) ─────────────────────────────────

def payment_required(endpoint: str):
    """
    Decorator que implementa o fluxo x402 completo para BNB Chain / Binance.

    Fluxo:
      Sem X-Payment  → HTTP 402 com instruções
      Com X-Payment  → verifica → entrega resultado ou rejeita
    """
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            ip    = (request.headers.get("X-Forwarded-For", request.remote_addr) or "unknown").split(",")[0].strip()
            price = float(PRICES.get(endpoint, "0.05"))

            if _is_rate_limited(ip):
                with _stats_lock:
                    _stats["rejected_rl"] += 1
                log.warning(f"Rate limit atingido: {ip} → {endpoint}")
                return jsonify({"error": "Too Many Requests", "retry_after": "60s"}), 429

            payment_header = request.headers.get("X-Payment")

            if not payment_header:
                _record(endpoint, paid=False)
                log.info(f"402 enviado → {ip} {endpoint} ({PRICES[endpoint]} {PAYMENT_TOKEN})")
                payload              = verifier.build_402_payload(endpoint)
                resp                 = jsonify(payload)
                resp.status_code     = 402
                resp.headers["X-ACCEPTS-PAYMENT"] = "x402"
                return resp

            valid, reason = verifier.verify(payment_header, endpoint)

            if not valid:
                log.warning(f"Pagamento inválido: {ip} {endpoint} → {reason}")
                payload              = verifier.build_402_payload(endpoint)
                payload["error"]     = f"Pagamento inválido: {reason}"
                payload["x402Debug"] = reason
                resp                 = jsonify(payload)
                resp.status_code     = 402
                return resp

            g.endpoint_price = price
            log.info(f"Pago ✓ {ip} {endpoint} → {PRICES[endpoint]} {PAYMENT_TOKEN}")
            return fn(*args, **kwargs)

        return wrapper
    return decorator

# ── FONTE DE DADOS: NEXUSAI / GROQ / GEMINI ──────────────────────────────────

def get_analysis() -> dict:
    """
    Tenta obter análise em ordem de prioridade:
      1. Cache (se ainda válido)
      2. NexusAI v4 local (importação direta)
      3. NexusAI v4 via HTTP (porta 8000)
      4. Groq llama-3.3-70b (com dados reais de mercado injetados)
      5. Gemini (fallback)
      6. Fallback absoluto (dados reais + regime neutro)
    """
    cached = _get_cached_analysis()
    if cached:
        _record("cache", paid=False, cache_hit=True)
        return cached

    _record("cache", paid=False, cache_hit=False)

    for fn in (_from_nexusai_local, _from_nexusai_http, _from_groq, _from_gemini):
        data = fn()
        if data:
            _set_cache(data)
            return data

    # Fallback absoluto com dados reais de preço
    data = _fallback_data()
    _set_cache(data)
    return data


def _base_payload(source: str) -> dict:
    return {
        "source":    source,
        "timestamp": int(time.time()),
        "datetime":  datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        "network":   "BNB Smart Chain",
        "token":     PAYMENT_TOKEN,
    }


def _from_nexusai_local():
    try:
        sys.path.insert(0, NEXUSAI_PATH)
        from core.brain_loader import BRAIN
        from data.market_data import get_fear_greed_sync, get_prices_sync

        prices = get_prices_sync()
        fg     = get_fear_greed_sync()

        def _p(coin):
            d = prices.get(coin, {})
            return {"usd": d.get("usd", 0), "change_24h": round(d.get("usd_24h_change", 0), 2)}

        data = _base_payload("NexusAI v4 — NEXUS SINGULARITY EDITION (local)")
        data.update({
            "regime":     BRAIN.last_regime or "recovery",
            "confianca":  round(BRAIN.last_confidence or 0.55, 4),
            "fear_greed": {"value": fg.get("value", 50), "label": fg.get("label", "Neutral")},
            "precos": {
                "BTC": _p("bitcoin"),
                "ETH": _p("ethereum"),
                "SOL": _p("solana"),
                "BNB": _p("binancecoin"),
            },
        })
        log.info("Fonte: NexusAI local")
        return data
    except Exception as e:
        log.debug(f"NexusAI local indisponível: {e}")
        return None


def _from_nexusai_http():
    try:
        r = requests.get("http://localhost:8000/internal/analysis", timeout=4)
        if r.ok:
            data = r.json()
            data["source"] = "NexusAI v4 (HTTP local)"
            log.info("Fonte: NexusAI HTTP local")
            return data
    except Exception:
        pass
    return None


def _from_groq():
    if not GROQ_API_KEY:
        return None
    try:
        # Injeta dados reais de mercado no prompt
        market = _fetch_real_market_data()
        precos_str = json.dumps(market.get("precos", {}), ensure_ascii=False)
        fg_str     = json.dumps(market.get("fear_greed", {}), ensure_ascii=False)

        prompt = (
            f"Você é um analista quantitativo de mercado cripto sênior. "
            f"Dados de mercado reais (agora): preços={precos_str}, fear_greed={fg_str}. "
            "Com base nesses dados REAIS, analise o mercado de BTC, ETH, SOL e BNB. "
            "Retorne APENAS JSON válido (sem markdown, sem explicações) com: "
            "regime (bull/bear/recovery/sideways), "
            "confianca (float 0.0-1.0), "
            "sentimento (bullish/bearish/neutral), "
            "acao (comprar/vender/aguardar), "
            "sinais (lista de até 3 strings objetivas), "
            "anomalias (lista de até 2 strings ou lista vazia), "
            "resumo (string max 120 palavras em português), "
            "precos (use os valores reais fornecidos acima)."
        )
        resp = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
            json={
                "model":       "llama-3.3-70b-versatile",
                "messages":    [{"role": "user", "content": prompt}],
                "max_tokens":  700,
                "temperature": 0.2,
            },
            timeout=20,
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"].strip()
        # Remove possíveis backticks de markdown
        if "```" in content:
            parts   = content.split("```")
            content = parts[1] if len(parts) > 1 else parts[0]
            if content.startswith("json"):
                content = content[4:]
        data = json.loads(content.strip())
        # Garante preços reais mesmo que o modelo tenha inventado
        if not data.get("precos") or not any(v.get("usd") for v in data.get("precos", {}).values()):
            data["precos"] = market.get("precos", {})
        if not data.get("fear_greed"):
            data["fear_greed"] = market.get("fear_greed", {})
        data.update(_base_payload("NexusAI x402 — Groq llama-3.3-70b"))
        log.info("Fonte: Groq llama-3.3-70b")
        return data
    except Exception as e:
        log.warning(f"Groq falhou: {e}")
        return None


def _from_gemini():
    if not GEMINI_API_KEY:
        return None
    try:
        market     = _fetch_real_market_data()
        precos_str = json.dumps(market.get("precos", {}), ensure_ascii=False)
        prompt = (
            f"Dados reais de mercado: {precos_str}. "
            "Analise o mercado cripto agora. Retorne APENAS JSON com: "
            "regime, confianca (0-1), sentimento, acao, sinais (lista), "
            "anomalias (lista), resumo (PT-BR max 100 palavras), "
            "precos com BTC/ETH/SOL/BNB (usd e change_24h)."
        )
        resp = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}",
            json={"contents": [{"parts": [{"text": prompt}]}]},
            timeout=20,
        )
        resp.raise_for_status()
        content = resp.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
        if "```" in content:
            parts   = content.split("```")
            content = parts[1] if len(parts) > 1 else parts[0]
            if content.startswith("json"):
                content = content[4:]
        data = json.loads(content.strip())
        if not data.get("precos") or not any(v.get("usd") for v in data.get("precos", {}).values()):
            data["precos"] = market.get("precos", {})
        data.update(_base_payload("NexusAI x402 — Gemini fallback"))
        log.info("Fonte: Gemini")
        return data
    except Exception as e:
        log.warning(f"Gemini falhou: {e}")
        return None


def _fallback_data() -> dict:
    """Fallback absoluto com dados reais de preço mas análise neutra."""
    log.error("Todos os provedores de IA falharam — retornando fallback com dados reais")
    market = _fetch_real_market_data()
    return {
        **_base_payload("NexusAI x402 — offline"),
        "regime":     "sideways",
        "confianca":  0.0,
        "sentimento": "neutral",
        "acao":       "aguardar",
        "sinais":     ["Serviço de IA temporariamente indisponível"],
        "anomalias":  [],
        "resumo":     "Análise indisponível no momento. Preços de mercado reais fornecidos.",
        "precos":     market.get("precos", {"BTC": {}, "ETH": {}, "SOL": {}, "BNB": {}}),
        "fear_greed": market.get("fear_greed", {"value": 50, "label": "Neutral"}),
        "erro":       "Todos os provedores de IA indisponíveis",
    }

# ── HELPERS DE RESPOSTA ───────────────────────────────────────────────────────

def _enrich(data: dict, endpoint: str) -> dict:
    """Adiciona metadados de pagamento à resposta."""
    data["pagamento"] = {
        "endpoint":    endpoint,
        "preco_pago":  f"{PRICES[endpoint]} {PAYMENT_TOKEN}",
        "rede":        "BNB Smart Chain (BEP-20)",
        "facilitador": "Binance x402",
        "modo":        NETWORK_MODE,
    }
    return data

# ── ENDPOINTS PAGOS ───────────────────────────────────────────────────────────

@app.route("/fear-greed")
@payment_required("/fear-greed")
def fear_greed():
    """Fear & Greed Index — 0.01 USDT"""
    data  = get_analysis()
    price = float(PRICES["/fear-greed"])
    _record("/fear-greed", paid=True, price=price)
    return jsonify(_enrich({
        "source":     data.get("source"),
        "timestamp":  data.get("timestamp"),
        "datetime":   data.get("datetime"),
        "fear_greed": data.get("fear_greed", {"value": 50, "label": "Neutral"}),
        "sentimento": data.get("sentimento", "neutral"),
    }, "/fear-greed"))


@app.route("/regime")
@payment_required("/regime")
def regime():
    """Regime de mercado — 0.02 USDT"""
    data  = get_analysis()
    price = float(PRICES["/regime"])
    _record("/regime", paid=True, price=price)
    return jsonify(_enrich({
        "source":     data.get("source"),
        "timestamp":  data.get("timestamp"),
        "datetime":   data.get("datetime"),
        "regime":     data.get("regime"),
        "confianca":  data.get("confianca"),
        "sentimento": data.get("sentimento", "neutral"),
        "acao":       data.get("acao", "aguardar"),
    }, "/regime"))


@app.route("/anomalias")
@payment_required("/anomalias")
def anomalias():
    """Anomalias detectadas — 0.03 USDT"""
    data  = get_analysis()
    price = float(PRICES["/anomalias"])
    _record("/anomalias", paid=True, price=price)
    return jsonify(_enrich({
        "source":    data.get("source"),
        "timestamp": data.get("timestamp"),
        "datetime":  data.get("datetime"),
        "anomalias": data.get("anomalias", []),
        "regime":    data.get("regime"),
        "confianca": data.get("confianca"),
    }, "/anomalias"))


@app.route("/analise")
@payment_required("/analise")
def analise():
    """Análise completa — 0.05 USDT"""
    data  = get_analysis()
    price = float(PRICES["/analise"])
    _record("/analise", paid=True, price=price)
    return jsonify(_enrich({
        "source":     data.get("source"),
        "timestamp":  data.get("timestamp"),
        "datetime":   data.get("datetime"),
        "regime":     data.get("regime"),
        "confianca":  data.get("confianca"),
        "fear_greed": data.get("fear_greed", {}),
        "sentimento": data.get("sentimento", "neutral"),
        "acao":       data.get("acao", "aguardar"),
        "sinais":     data.get("sinais", []),
        "precos":     data.get("precos", {}),
    }, "/analise"))


@app.route("/sinais")
@payment_required("/sinais")
def sinais():
    """Sinais de trading — 0.10 USDT"""
    data  = get_analysis()
    price = float(PRICES["/sinais"])
    _record("/sinais", paid=True, price=price)
    return jsonify(_enrich({
        "source":    data.get("source"),
        "timestamp": data.get("timestamp"),
        "datetime":  data.get("datetime"),
        "regime":    data.get("regime"),
        "confianca": data.get("confianca"),
        "acao":      data.get("acao", "aguardar"),
        "sinais":    data.get("sinais", []),
        "precos":    data.get("precos", {}),
    }, "/sinais"))


@app.route("/relatorio")
@payment_required("/relatorio")
def relatorio():
    """Relatório premium completo — 0.25 USDT"""
    data  = get_analysis()
    price = float(PRICES["/relatorio"])
    _record("/relatorio", paid=True, price=price)
    return jsonify(_enrich({
        "source":     data.get("source"),
        "timestamp":  data.get("timestamp"),
        "datetime":   data.get("datetime"),
        "regime":     data.get("regime"),
        "confianca":  data.get("confianca"),
        "fear_greed": data.get("fear_greed", {}),
        "sentimento": data.get("sentimento", "neutral"),
        "acao":       data.get("acao", "aguardar"),
        "sinais":     data.get("sinais", []),
        "anomalias":  data.get("anomalias", []),
        "precos":     data.get("precos", {}),
        "resumo":     data.get("resumo", ""),
    }, "/relatorio"))

# ── ENDPOINTS PÚBLICOS ────────────────────────────────────────────────────────

@app.route("/")
def info():
    """Discovery público — sem pagamento necessário."""
    return jsonify({
        "nome":        "NexusAI Crypto Intelligence API",
        "descricao":   "Análise autônoma de mercado cripto via IA. Powered by NexusAI v4.",
        "protocolo":   "x402",
        "versao":      "3.0.0",
        "facilitador": "Binance x402 (Binance Pay)",
        "rede":        "BNB Smart Chain (BEP-20)",
        "chain_id":    BSC_CHAIN_ID,
        "modo":        NETWORK_MODE,
        "carteira":    BINANCE_WALLET,
        "token":       PAYMENT_TOKEN,
        "token_ca":    PAYMENT_TOKEN_CA,
        "auth_types":  ["eip3009", "permit2-exact", "permit2-upto"],
        "endpoints": [
            {
                "path":   ep,
                "preco":  f"{PRICES[ep]} {PAYMENT_TOKEN}",
                "desc":   ENDPOINT_DESC[ep],
                "method": "GET",
            }
            for ep in PRICES
        ],
        "links": {
            "status":    "/status",
            "health":    "/health",
            "manifesto": "/.well-known/x402.json",
            "discovery": "https://x402scan.com",
            "docs":      "https://docs.x402.org",
        },
    })


@app.route("/status")
def status():
    """Status e analytics em tempo real — sem pagamento."""
    uptime_s = int(time.time() - _stats["start_time"])
    h, m, s  = uptime_s // 3600, (uptime_s % 3600) // 60, uptime_s % 60

    with _stats_lock:
        receita = _stats["revenue_usdt"]
        pagos   = _stats["paid_requests"]
        total   = _stats["total_requests"]
        por_ep  = {
            ep: {
                "chamadas": v["requests"],
                "pagas":    v["paid"],
                "receita":  f"{v['revenue']:.4f} {PAYMENT_TOKEN}",
            }
            for ep, v in _stats["by_endpoint"].items()
            if ep != "cache"
        }

    return jsonify({
        "status":       "online",
        "versao":       "3.0.0",
        "rede":         "BNB Smart Chain",
        "modo":         NETWORK_MODE,
        "bnb_chain":    {"rpc": BSC_RPC, "chain_id": BSC_CHAIN_ID, "conectado": verifier.connected},
        "carteira":     BINANCE_WALLET,
        "token":        PAYMENT_TOKEN,
        "uptime":       f"{h:02d}:{m:02d}:{s:02d}",
        "cache":        {"ttl_segundos": CACHE_TTL, "hits": _stats.get("cache_hits", 0)},
        "analytics": {
            "total_chamadas":   total,
            "chamadas_pagas":   pagos,
            "taxa_conversao":   f"{(pagos/total*100):.1f}%" if total > 0 else "0%",
            "receita_total":    f"{receita:.4f} {PAYMENT_TOKEN}",
            "rejeitados_rl":    _stats["rejected_rl"],
            "replay_bloqueados": _stats["replay_blocked"],
            "por_endpoint":     por_ep,
        },
    })


@app.route("/health")
def health():
    """Health check para Railway/Render/Docker."""
    market_ok = bool(_market_cache.get("data"))
    return jsonify({
        "ok":          True,
        "ts":          int(time.time()),
        "bnc_rpc":     verifier.connected,
        "market_data": market_ok,
        "modo":        NETWORK_MODE,
    }), 200


@app.route("/.well-known/x402.json")
def x402_manifest():
    """Manifesto x402 padrão — discovery automático por agentes."""
    return jsonify({
        "version":  "1.0",
        "provider": {
            "name":        "NexusAI Crypto Intelligence",
            "wallet":      BINANCE_WALLET,
            "network":     "bsc" if NETWORK_MODE == "mainnet" else "bsc-testnet",
            "chain_id":    BSC_CHAIN_ID,
            "currency":    PAYMENT_TOKEN,
            "token":       PAYMENT_TOKEN_CA,
            "facilitator": "binance-x402",
            "auth_types":  ["eip3009", "permit2-exact", "permit2-upto"],
        },
        "resources": [
            {
                "path":        ep,
                "price":       PRICES[ep],
                "currency":    PAYMENT_TOKEN,
                "token":       PAYMENT_TOKEN_CA,
                "description": ENDPOINT_DESC[ep],
                "method":      "GET",
            }
            for ep in PRICES
        ],
    })

# ── GRACEFUL SHUTDOWN ─────────────────────────────────────────────────────────

def _shutdown_handler(signum, frame):
    log.info(f"Sinal {signum} recebido — encerrando servidor...")
    sys.exit(0)

for _sig in (signal.SIGINT, signal.SIGTERM):
    try:
        signal.signal(_sig, _shutdown_handler)
    except (OSError, ValueError):
        pass

# ── INICIALIZAÇÃO ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    erros_config = _validate_config()

    # Pré-aquece cache de mercado em background
    threading.Thread(target=_fetch_real_market_data, daemon=True).start()

    receita_diaria_est = sum(float(p) * 10_000 for p in PRICES.values()) / len(PRICES)

    print("\n" + "═" * 66)
    print("  NexusAI x402 — Binance Pay + BNB Smart Chain  v3.0")
    print("═" * 66)
    print(f"  Carteira Binance (BEP-20) : {BINANCE_WALLET or '⚠  NÃO CONFIGURADA'}")
    print(f"  Rede                      : BNB Chain {'MAINNET ✓' if NETWORK_MODE == 'mainnet' else 'TESTNET (dev)'}")
    print(f"  Chain ID                  : {BSC_CHAIN_ID}")
    print(f"  Token de pagamento        : {PAYMENT_TOKEN} ({PAYMENT_TOKEN_CA[:12]}...)")
    print(f"  BNB Chain RPC             : {'Conectado ✓' if verifier.connected else 'Offline (simulação)'}")
    print(f"  Cache TTL                 : {CACHE_TTL}s")
    print(f"  Rate limit                : {RATE_LIMIT_RPM} req/min por IP")
    print(f"  Anti-replay               : Ativo (TTL {_REPLAY_TTL}s)")
    print(f"  Dados de mercado          : CoinGecko + Alternative.me (reais)")
    print()
    print("  Endpoints pagos:")
    for ep, price in PRICES.items():
        print(f"    GET {ep:<15} → {price:>5} {PAYMENT_TOKEN}   {ENDPOINT_DESC[ep]}")
    print()
    if erros_config:
        print("  ⚠  CONFIGURAÇÃO INCOMPLETA:")
        for e in erros_config:
            print(f"     • {e}")
        print()
    print("  Estimativa de receita (10.000 chamadas/dia):")
    print(f"    Receita diária estimada → ~${receita_diaria_est:.0f} USDT/dia")
    print()
    print("  Próximos passos:")
    print("  1. ✅ Configure BINANCE_WALLET_ADDRESS no .env")
    print("     → Binance → Carteira → Depósito → USDT → BNB Smart Chain")
    print("  2. ✅ Configure GROQ_API_KEY ou GEMINI_API_KEY no .env")
    print("  3. ✅ NETWORK_MODE=mainnet já é o padrão (modo real)")
    print("  4. ✅ Deploy: railway.app ou render.com")
    print("  5. ✅ Registre em x402scan.com")
    print("═" * 66 + "\n")

    app.run(host="0.0.0.0", port=PORT, debug=False)
