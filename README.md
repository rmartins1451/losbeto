# Losbeto — point-in-time Brazilian market data for AI agents

[![Losbeto on x402-list — monitored uptime](https://x402-list.com/badge/losbeto-cross-asset-market-intelligence.svg?data=uptime)](https://x402-list.com/services/losbeto-cross-asset-market-intelligence)

**The problem:** the IPCA number you fetch from the Banco Central API today is *not* the
number that was published back then. Official Brazilian series are revised. Any backtest
built on the current series silently contains look-ahead bias.

The US has [ALFRED](https://alfred.stlouisfed.org/) for this. Brazil has nothing public.

**What this is:** a node that has been recording Brazilian official statistics *as they
were published*, timestamping every reading, and signing each day with Ed25519 —
continuously, since deploy. That archive cannot be scraped retroactively by anyone,
including us. It only exists because the node was running.

Paid per call over [x402](https://x402.org) — USDC on Base, Solana or Algorand.
No signup, no API key, no invoice.

---

## Quick start

```bash
# free — see the whole archive and how to verify it
curl https://api.losbeto.xyz/br-pit-proof

# free — what the paid endpoints actually cost and why
curl https://api.losbeto.xyz/why-buy

# free — the buying criterion, published: what is worth paying for here and what is not
curl https://api.losbeto.xyz/what-agents-buy

# paid — IPCA as it was known on 5 Aug 2026 (not as revised since)
curl https://api.losbeto.xyz/br-asof?series=ipca_12m_pct&date=2026-08-05
# -> HTTP 402 with the payment challenge; pay and repeat
```

### With an x402 client

```ts
import { wrapFetchWithPayment } from "x402-fetch";

const fetchWithPay = wrapFetchWithPayment(fetch, wallet);
const r = await fetchWithPay(
  "https://api.losbeto.xyz/br-asof?series=selic_meta_pct&date=2026-06-30"
);
console.log(await r.json());
```

### As an MCP server (Claude Desktop, Cursor, Claude Code)

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

---

## The archive products (the moat)

| Endpoint | Price | What you get |
|---|---|---|
| `/br-pit-proof` | free | Merkle roots, signer key, coverage window, verification recipe |
| `/br-asof?series=&date=` | $0.09 | The value **as known on that date** — vintage, not revised |
| `/br-revisions?series=` | $0.19 | First print → every correction, with size and observation timestamp |
| `/br-archive?day=` | $0.05 | Signed daily snapshot: BCB macro + Ibovespa close |
| `/br-brief` | $0.50 | Daily Brazil macro + equity brief, in English |

Series tracked: `selic_meta_pct`, `cdi_daily_pct`, `ipca_12m_pct`, `igpm_month_pct`,
`usd_brl_ptax`, `eur_brl`.

## The Brazilian primitives (zero upstream, sub-millisecond)

Pure computation over Brazilian specifications — no external API in the request path,
no rate limit, no provider outage, priced for loops:

| Endpoint | Price | What you get |
|---|---|---|
| `/br-pix-parse?code=` | $0.004 | Decode and CRC16-verify a PIX BR Code (EMV-MPM). Rejects a tampered or truncated QR *before* an agent moves money |
| `/br-pix-code?key=&name=&city=` | $0.004 | Generate a valid static PIX BR Code with correct CRC16, self-checked by re-parsing |
| `/br-bizdays?from=&to=` (or `?year=`) | $0.004 | Bank business days on the ANBIMA 252 convention — Easter-linked holidays and the 2024 Consciência Negra change included, `du/252` year fraction ready as an exponent |
| `/br-doc?doc=` | $0.004 | CNPJ/CPF modulo-11 check-digit validation, formatted output, headquarters branch detection |

The spec-level traps these absorb: CRC16-CCITT/FALSE (poly `0x1021`, seed `0xFFFF`),
Carnaval/Corpus Christi moving with Easter, and Consciência Negra becoming a national
holiday only in 2024. Getting any of them wrong silently corrupts a rate calculation or
makes a QR refused at the register. Verifiable from outside: `GET /zero-upstream.json`
declares which routes never touch the network.

The node also exposes ~80 other endpoints (crypto, FX, commodities, equities). Those are
convenience wrappers over public sources — see `/what-agents-buy`, where we publish the
formula and tell you plainly which ones you should *not* pay for.

---

## Verify anything, offline

Every observation is a Merkle leaf:

```
leaf = sha256("<series>|<ref_date>|<value>|<seq>|<observed_ts>")
```

Leaves are sorted and hashed into a daily Merkle root (sha256; an odd level duplicates its
last leaf). The root is signed:

```
Ed25519( "losbeto-pit|<day>|<root>" )   # pubkey published at /br-pit-proof
```

```python
import base64, nacl.signing
pub = nacl.signing.VerifyKey(base58_decode(signer))
pub.verify(f"losbeto-pit|{day}|{root}".encode(), base64.b64decode(signature))
```

Daily roots are optionally anchored on Algorand as a zero-value note transaction, so the
timestamp does not depend on trusting us.

---

## For agents: start at the manifest

`GET /agents.json` (also at `/.well-known/agents.json`) — the
[agents.json](https://agents.json) manifest: outcome-based flows with exact parameters,
payment networks, the free tier, and pointers to the OpenAPI contract, the x402 manifest,
the scorecard and the fidelity recipes. CORS open, cached 1h.

## For indexers and QoS scorers

If you are ScoutScore, EntRoute, x402scan, x402-list, BlockRun or any other
service that probes and ranks x402 nodes, these are for you:

| Surface | What it gives you |
|---|---|
| `/agents.json` | agents.json manifest — flows, payment networks, free tier |
| `/scorecard.json` | Signed: 24h availability, p50/p95 latency, 402-challenge cost, traffic mix, organic-vs-operator revenue |
| `/.well-known/fidelity.json` | Deterministic probe recipe per endpoint — exact free URL, required response fields, what "healthy" means |
| `/zero-upstream.json` | Which endpoints make zero outbound calls (cannot rate-limit or 503 on a provider) |
| `/bazaar-status` | Whether this node has settled on Base via the CDP facilitator (2,200+ settlements) |
| `X-Scorecard` / `X-Fidelity` | Headers on every response, so you never need a second request to find them |

Free probes never charge. A paid route that hits an unexpected internal error
degrades to a 402 rather than a 500 — the resource is still for sale. The OpenAPI and
Swagger specs carry a stable `ETag` and answer `304` — no need to re-download 130 KB
between probes.

## Revenue transparency

`GET /.well-known/honest-revenue.json` — signed, and it separates:

- `organic` — paid by a wallet the operator does not control
- `operator-test` — the operator's own declared wallets
- `self-sweep` — one wallet settling many distinct endpoints in a short window

Operator-funded traffic is labelled, not hidden. If the organic number is small, it says so.

---

## Run it yourself

```bash
pip install -r requirements.txt
export SOLANA_WALLET_ADDRESS=...      # where payments land
export BASE_PAYTO_EVM=0x...           # optional
export ALGORAND_WALLET_ADDRESS=...    # optional
export BUYER_WALLETS=...              # your own test-buyer wallets, comma separated
gunicorn --workers 2 --threads 8 --preload --bind 0.0.0.0:$PORT nexus_omega:app
```

Useful env vars: `AI_WARMER=1` (re-enable AI preview warming), `LLM_DAILY_BUDGET`,
`LLM_PAID_RESERVE`, `PIT_INTERVAL_S`, `ALGO_ANCHOR_MNEMONIC` (+ `pip install py-algorand-sdk`).

---

## Contact

Roberto Martins — roberto.martins622@gmail.com

Missing a series or a market you need? Open an issue. New endpoints get built on request.

MIT licensed.
