# Losbeto — Cross-Asset Market Intelligence over x402

A single-file Python node that sells market data to AI agents, per call, in USDC,
with no API keys and no signup. Live at **https://api.losbeto.xyz**

## Try it without paying anything

```bash
# six live samples from six endpoints, one call, $0.00
curl https://api.losbeto.xyz/try

# any endpoint, free delayed sample
curl 'https://api.losbeto.xyz/forex-rate?pair=EUR/USD&preview=1'

# is the node actually healthy right now?
curl https://api.losbeto.xyz/health/providers
```

## What makes it different

Most x402 services are crypto-only. This one covers **traditional markets too**:

| Area | Examples |
|---|---|
| Forex | EUR/USD, GBP/USD, USD/JPY, triangular arbitrage |
| Equities | live quotes, AI single-stock dossiers, sector rotation |
| Commodities | gold, silver, WTI, Brent, copper, natural gas |
| Macro | FOMC / NFP / CPI / ECB calendar, event playbooks, regime |
| Crypto | Pyth oracle prices, fear & greed, DEX screening, rug checks |
| Research | daily cross-asset brief, 90-day correlation matrix, 5-agent council |

67 monetized endpoints, $0.003–$4.16 USDC, settling on Base (Coinbase CDP) and
Solana (PayAI).

## Design decisions worth stealing

Everything below was learned by operating the node and measuring it. If you run
an x402 service, some of it may save you weeks.

**Measure your 402 header size.** Ours grew to 19,627 bytes (duplicate challenge
blobs across `WWW-Authenticate`, `PAYMENT-REQUIRED` and `X-PAYMENT-REQUIRED`).
Node's default max header size is 16 KB and proxies commonly cap at 8 KB, so
Node-based x402 clients aborted the connection on every *paid* endpoint while
free ones worked fine. Settlements went to zero and it looked like ordinary
probe traffic. The body carries the full payload now; the header carries only
what's needed to pay.

**Base64 padding matters.** Stripping `=` from the `PAYMENT-REQUIRED` payload
makes strict `b64decode` fail on ~75% of payloads. The discovery extension
arrived empty in the CDP Bazaar until this was fixed.

**`accepts` order decides your chain.** Most clients take `accepts[0]`. With
Solana first, virtually every settle went through the Solana facilitator — and
the Bazaar only indexes on CDP settles. Flipping Base to first moved
settlements and unblocked indexing.

**On Base, the tx sender is not the payer.** EIP-3009 transfer-with-authorization
means the buyer only signs; the facilitator's relayer submits and pays gas. If
you reconcile by `tx.from`, you attribute every sale to the relayer.

**A free sample must actually be delayed.** Ours served data with ~0s of age —
identical to the paid response. For a daily index, a 15-minute delay creates no
reason to pay. The delay is now proportional to each feed's volatility.

**Publish honest receipts.** Every settlement at `/receipts` is labelled
operator-test vs organic. It costs nothing, and it's the only reason anyone in
the ecosystem started talking to us.

## Machine-readable surfaces

| Path | Purpose |
|---|---|
| `/llms.txt`, `/llms-full.txt` | catalog for LLM crawlers |
| `/openapi.json` | full OpenAPI spec |
| `/.well-known/x402.json` | x402 manifest |
| `/.well-known/mcp.json` | MCP manifest (declares transports) |
| `/mcp` | **MCP Streamable HTTP** — connect directly, no npm install |
| `/.well-known/agent.json` | A2A agent card |
| `/try` | free tasting menu |
| `/health/providers` | per-source liveness + `premium_ready` flag |
| `/receipts` | labelled settlements |

Every 402 response also carries an inline sample of the real output, so a client
that only reads the challenge already sees the response shape.

## Use it from an agent

**MCP (any client, no install):**
```json
{"mcpServers": {"losbeto": {"url": "https://api.losbeto.xyz/mcp"}}}
```

**MCP via npm:**
```bash
npx -y losbeto-mcp
```

**LangChain / CrewAI:**
```python
from losbeto_tools import get_langchain_tools
tools = get_langchain_tools()   # free delayed data, no wallet needed
```

## Running your own

```bash
pip install -r requirements.txt
python nexus_omega.py
```

Configuration is entirely through environment variables — wallets, facilitators,
API keys, pricing. No secrets in the source. See the top of `nexus_omega.py`.

## Listed on

x402-list · x402scan · CDP Bazaar / agentic.market · MCP Registry · AgentCash

## Contact

Missing an endpoint your agent needs? Open an issue — endpoints are added on
request, and every message gets read.

MIT licensed.
