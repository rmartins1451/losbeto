<!-- mcp-name: io.github.rmartins1451/losbeto -->

# Losbeto — Cross-Asset Market Intelligence over x402

A single-file Python node that sells market data to AI agents, per call, in USDC,
with no API keys and no signup. Live at **https://api.losbeto.xyz**

Stocks, forex, commodities, macro, **Brazil (BCB/B3)** and crypto — **78 endpoints**,
$0.003–$99.99, settling on Base (Coinbase CDP) and Solana (PayAI).

Public telemetry (settlements, revenue, probes, source health, straight from the
node's own ledger): **https://api.losbeto.xyz/live**

## Try it without paying anything

```bash
# first REAL-TIME call free — no wallet, no signup
curl https://api.losbeto.xyz/welcome

# six live samples from six endpoints, one call, $0.00
curl https://api.losbeto.xyz/try

# any endpoint, free delayed sample
curl 'https://api.losbeto.xyz/oracle-consensus?symbol=SOL&preview=1'

# is the node actually healthy right now?
curl https://api.losbeto.xyz/health/providers
```

## Use it from an agent

**MCP (Claude Code, Cursor, Claude Desktop — no install):**
```bash
claude mcp add --transport http losbeto https://api.losbeto.xyz/mcp
```

**LangChain / CrewAI / OpenAI function calling — free delayed data:**
```bash
pip install 'losbeto-tools[langchain]'   # https://pypi.org/project/losbeto-tools/
```

**Any x402 wallet:**
```bash
npx agentcash fetch https://api.losbeto.xyz/oracle-consensus?symbol=SOL
npx agentcash add https://api.losbeto.xyz
```

## Pay per call, or buy a pass

Per-call is the default. For agents running evaluation cycles or production
workloads, one on-chain payment buys balance or unlimited time — then zero
settlement latency per request:

| Plan | Price | What you get |
|---|---|---|
| `/buy-credits` | $0.99 | $1.25 of call balance (+25% bonus), spent via `X-API-Key` |
| `/day-pass` | $2.99 | unlimited calls, 24h |
| `/week-pass` | $9.99 | unlimited calls, 7 days |
| `/subscribe-pro` | $9.99/mo | $15 of call balance monthly (+50% bonus), priority routing |
| `/subscribe-whale` | $19.99/mo | unlimited calls, 30 days, maximum priority |
| `/enterprise` | $99.99/yr | 12 months unlimited, 99.9% availability target, direct support |

## What makes it different

Most x402 services are crypto-only. This one covers **traditional markets too**,
and it is the only one that covers **Brazil**:

| Area | Examples |
|---|---|
| Brazil | BCB/SGS macro (Selic, CDI, IPCA, PTAX), B3 equities, real interest rate, agro export parity |
| Forex | EUR/USD, GBP/USD, USD/JPY, triangular arbitrage |
| Equities | live quotes, AI single-stock dossiers, sector rotation |
| Commodities | gold, silver, WTI, Brent, copper, natural gas |
| Macro | FOMC / NFP / CPI / ECB calendar, event playbooks, regime |
| Crypto | multi-oracle price consensus, Pyth feeds, fear & greed, DEX screening, rug checks |
| Security | token intelligence, wallet scan, OFAC/SDN sanctions screening, launch risk |
| Research | daily cross-asset brief, 90-day correlation matrix, 5-agent council |

### Oracle Consensus — `/oracle-consensus?symbol=SOL` · $0.03

Every oracle publishes its own number. None publishes the *agreement between
them*. This queries Pyth, Coinbase, Kraken, Binance.US, Bitstamp and CoinGecko
**in parallel** and returns the median across primary sources, spread and MAD in
basis points, outliers by modified Z-score (Iglewicz & Hoaglin, |Z|>3.5)
distinguishing a *lagging index* from a *stale or manipulated feed*, per-source
latency, and an execution verdict with suggested slippage.

If fewer than two sources respond, it returns 503 and does not charge.

## Machine-readable discovery

Every surface an agent or directory might ask for:

`/llms.txt` · `/llms-full.txt` · `/openapi.json` · `/tasks.json` ·
`/.well-known/x402.json` · `/.well-known/mcp.json` · `/server.json` ·
`/.well-known/agent-card.json` (A2A) · `/.well-known/ai-catalog.json` ·
`/.well-known/api-catalog` (RFC 9727 linkset) · `/apis.json` ·
`/.well-known/ucp` (Google UCP) · `/health/providers` · `/receipts`

## Design decisions worth stealing

Everything below was learned by operating the node and measuring it. If you run
an x402 service, some of it may save you weeks.

**Measure your 402 header size.** Ours grew to 19,627 bytes (duplicate challenge
blobs across `WWW-Authenticate`, `PAYMENT-REQUIRED` and `X-PAYMENT-REQUIRED`).
Node's default max header size is 16 KB and proxies commonly cap at 8 KB, so
Node-based x402 clients aborted the connection on every *paid* endpoint while
free ones worked fine. Settlements went to zero and it looked like ordinary
probe traffic.

**Base64 padding matters.** Stripping `=` from the `PAYMENT-REQUIRED` payload
makes strict `b64decode` fail on ~75% of payloads.

**`accepts` order decides your chain.** Most clients take `accepts[0]`. With
Solana first, virtually every settle went through the Solana facilitator — and
the Bazaar only indexes on CDP settles.

**Generate the manifest from the challenge, not beside it.** We fixed the
`accepts` order in the 402 challenge and left `/.well-known/x402.json` building
its own array by hand. For months the challenge said Base-first and the manifest
— the document scanners actually read — said Solana-first. Two code paths for
one fact will diverge. The manifest is now derived from `_build_402()`.

**On Base, the tx sender is not the payer.** EIP-3009 transfer-with-authorization
means the buyer only signs; the facilitator's relayer submits and pays gas. If
you reconcile by `tx.from`, you attribute every sale to the relayer.

**A free sample must actually be delayed.** Ours served data with ~0s of age —
identical to the paid response. The delay is now proportional to each feed's
volatility.

**Don't let the free path starve the paid one.** Our preview warmer refreshed
five LLM-backed endpoints every 15 minutes — roughly 480 model calls a day for
nobody. It exhausted the daily token quota, so when a paying agent arrived the
AI layer was dead. Warm cheap data often; warm expensive inference rarely.

**A 503 from your handler is not a refund.** Payment verification runs *before*
the handler. If you check availability inside the handler, the money is already
captured. Gate on availability *before* issuing the 402 — and if the input dies
after settlement, issue credit back explicitly.

**Never let a fallback string reach a paid response.** Our LLM helper returned
`"[LLM offline — configure ...]"` when every provider failed. That string was
served inside paid `/analise` and `/relatorio` responses, and ingested into the
RAG store. Fail loudly and refuse the sale instead.

**Pin the price you quoted.** Dynamic pricing recomputed the amount at
settlement time. If it moved between the 402 and the payment, the client's
signature no longer matched the requirements and the facilitator rejected a
perfectly good sale, silently.

**Answer 404 and 405 in JSON that teaches.** Agents probe paid endpoints with
POST/PATCH/PUT/DELETE and mis-type paths. Framework defaults are HTML — dead
ends for a machine. Our 404 suggests the closest real endpoints and the 405
answers the one fact that matters (`how_to_call: GET ...`) plus the free sample
URL. Wrong turns became a funnel.

**Catalog agents ask for trailing slashes.** Directories and linkset crawlers
requested `/.well-known/ucp/`, `/apis.json/`, `/health/` and got 404s while the
routes existed without the slash. One method-preserving 308 redirect on
slash-stripped known routes fixed the whole class — watch your 404 log before
building "new" endpoints that already exist.

## Running your own

```bash
pip install -r requirements.txt
python nexus_omega.py
```

Configuration is entirely through environment variables — wallets, facilitators,
API keys, pricing, and LLM model names (`GEMINI_MODEL`, `GROQ_MODEL`,
`CLAUDE_MODEL`, `DEEPSEEK_MODEL`), so a discontinued model can be swapped
without a redeploy. No secrets in the source.

## Listed on

x402scan · x402-list.com (Grade A) · CDP Bazaar / agentic.market · MCP Registry ·
AgentCash · PyPI ([losbeto-tools](https://pypi.org/project/losbeto-tools/))

## Contact

Missing an endpoint your agent needs? Open an issue — endpoints are added on
request, and every message gets read. Several routes on this node exist because
an agent's 404 showed up in the demand log.

MIT licensed.
