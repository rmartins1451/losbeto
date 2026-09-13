# Losbeto — LLM gateway + market data for AI agents (x402)

[Losbeto on x402-list — monitored uptime](https://www.x402-list.com)

One USDC micropayment per call. No signup, no API keys to manage — **the payment is the auth**. USDC on Base, Solana or Algorand.

**Flagship: an OpenAI-compatible LLM gateway for agents.** `POST /v1/chat/completions` and `GET /llm` at **$0.005/call** on live backends, with a free tier at `/llm/free` and model list at `/v1/models`. Behind it, **95+ market-data endpoints** ($0.003–0.05): FX, equities, commodities, macro calendar, crypto — plus Brazil's official statistics in depth, which nobody else on x402 covers.

## Quick start

```bash
# free — LLM taste, 5 calls/day
curl "https://api.losbeto.xyz/llm/free?q=hello"

# free — delayed preview of any paid endpoint
curl "https://api.losbeto.xyz/forex-rate?pair=EURUSD&preview=1"

# free — machine-readable plans catalog
curl "https://api.losbeto.xyz/plans"

# paid — IPCA as it was known on 5 Aug 2026 (not as revised since)
curl "https://api.losbeto.xyz/br-asof?series=ipca_12m_pct&date=2026-08-05"
# -> HTTP 402 with the payment challenge; pay and repeat
```

With an x402 client:

```js
import { wrapFetchWithPayment } from "x402-fetch";

const fetchWithPay = wrapFetchWithPayment(fetch, wallet);
const r = await fetchWithPay("https://api.losbeto.xyz/llm?q=market%20outlook");
console.log(await r.json());
```

From npm:

```bash
npm i -g losbeto-llm   # CLI + client for the LLM gateway (set LOSBETO_EVM_KEY)
npm i losbeto-mcp      # MCP server package
```

As an MCP server (Claude Desktop, Cursor, Claude Code):

```json
{
  "mcpServers": {
    "losbeto": {
      "url": "https://api.losbeto.xyz/mcp",
      "headers": { "Authorization": "Bearer <credit-key>" }
    }
  }
}
```

Get a credit key with one on-chain payment: `POST https://api.losbeto.xyz/buy-credits`.

## Plans — one payment, N calls (no settlement latency)

| Plan | Pay | You get |
|---|---|---|
| `/buy-credits` | $0.99 | $1.25 balance (+25%), 30 days |
| `/buy-credits-5` | $4.99 | $6.00 balance (+20%), 60 days |
| `/buy-credits-25` | $24.99 | $33.00 balance (+32%), 90 days |
| `/day-pass` | $2.99 | unlimited, 24h |
| `/week-pass` | $9.99 | unlimited, 7 days |
| `/subscribe-pro` | $9.99/mo | $15 balance monthly (+50%) |
| `/subscribe-whale` | $19.99/mo | unlimited, 30 days |
| `/founding-agent` | $49.99 | $75 balance (+50%), 180 days, founding badge |
| `/enterprise` | $99.99/yr | unlimited, 12 months |

Machine-readable at `/plans`, human-readable at `/pricing`. First purchase earns a bonus call, credited to your session token (7 days). The node never discounts list price — it adds value after payment instead.

## The Brazil moat: point-in-time official statistics

The problem: the IPCA number you fetch from the Banco Central API today is **not** the number that was published back then. Official Brazilian series are revised. Any backtest built on the current series silently contains look-ahead bias.

The US has ALFRED for this. Brazil has nothing public.

This node has been recording Brazilian official statistics as they were published, timestamping every reading and signing each day with Ed25519 — continuously, since deploy. That archive cannot be scraped retroactively by anyone, including us.

| Endpoint | Price | What you get |
|---|---|---|
| `/br-pit-proof` | free | Merkle roots, signer key, coverage window, verification recipe |
| `/br-asof?series=&date=` | $0.09 | The value as known on that date — vintage, not revised |
| `/br-revisions?series=` | $0.19 | First print → every correction, with size and observation timestamp |
| `/br-archive?day=` | $0.05 | Signed daily snapshot: BCB macro + Ibovespa close |
| `/br-brief` | $0.50 | Daily Brazil macro + equity brief, in English |

Series tracked: `selic_meta_pct, cdi_daily_pct, ipca_12m_pct, igpm_month_pct, usd_brl_ptax, eur_brl`.

## The Brazilian primitives (zero upstream, sub-millisecond)

Pure computation over Brazilian specifications — no external API in the request path, no rate limit, no provider outage, priced for loops:

| Endpoint | Price | What you get |
|---|---|---|
| `/br-pix-parse?code=` | $0.004 | Decode and CRC16-verify a PIX BR Code (EMV-MPM) |
| `/br-pix-code?key=&name=&city=` | $0.004 | Generate a valid static PIX BR Code, self-checked by re-parsing |
| `/br-bizdays?from=&to=` | $0.004 | Bank business days on the ANBIMA 252 convention |
| `/br-doc?doc=` | $0.004 | CNPJ/CPF modulo-11 check-digit validation |

Verifiable from outside: `GET /zero-upstream.json` declares which routes never touch the network.

## Transparency — receipts are public

- `GET /receipts` — every settlement, public
- `GET /.well-known/honest-revenue.json` — signed; separates **organic** (wallets the operator doesn't control) from **operator-test** and **self-sweep**
- `GET /scorecard.json` — 24h availability, p50/p95 latency, traffic mix, signed
- `GET /.well-known/erc8004.json` — ERC-8004 registration file (trustless agent identity)

## Verify anything, offline

Every observation is a Merkle leaf:

```
leaf = sha256("<series>|<ref_date>|<value>|<seq>|<observed_ts>")
Ed25519( "losbeto-pit|<day>|<root>" )   # pubkey at /br-pit-proof
```

Daily roots are optionally anchored on Algorand as zero-value note transactions, so the timestamp does not depend on trusting us.

## For agents and indexers

Start at `GET /agents.json` — outcome-based flows with exact parameters, payment networks, free tier, and pointers to the OpenAPI contract, the x402 manifest, the scorecard and the fidelity recipes. CORS open, cached 1h. ScoutScore, x402scan, x402-list and other rankers: `/agents.json`, `/scorecard.json`, `/.well-known/fidelity.json`, `/zero-upstream.json`, `/bazaar-status`. Free probes never charge; a paid route that hits an internal error degrades to a 402 rather than a 500.

## Run it yourself

```bash
pip install -r requirements.txt
export SOLANA_WALLET_ADDRESS=...      # where payments land
export BASE_PAYTO_EVM=0x...           # optional
export ALGORAND_WALLET_ADDRESS=...    # optional
export BUYER_WALLETS=...              # your own test-buyer wallets, comma separated
gunicorn --workers 2 --threads 8 --preload --bind 0.0.0.0:$PORT nexus_omega:app
```

Useful env vars: `AI_WARMER=1`, `LLM_DAILY_GLOBAL_CAP`, `LLM_DAILY_KEY_CAP`, `PIT_INTERVAL_S`, `ALGO_ANCHOR_MNEMONIC`, `X402LIST_TOKEN`.

## Contact

Roberto Martins — roberto.martins622@gmail.com

Missing a series or a market you need? Open an issue. New endpoints get built on request.

MIT licensed.
