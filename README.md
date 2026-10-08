# losbeto-mcp

Losbeto x402 market intelligence as native tools in Claude Desktop, Claude Code, or Cursor. Base chain reads with ML on top, ERC-8004 agent reputation, Brazil central-bank macro, multi-oracle price consensus, launch risk, forex, commodities and crypto — plus an OpenAI-compatible LLM gateway. No signup. No API key. Paid tools settle automatically in USDC on Base via x402.

Registered ERC-8004 agent: [agentId 87048 on Base](https://8004scan.io/agents/base/87048).

## Recommended: remote server (no install)

```json
{
  "mcpServers": {
    "losbeto": { "url": "https://api.losbeto.xyz/mcp" }
  }
}
```

The remote server exposes **5 meta-tools** that cover the whole 115+ endpoint catalog:

- `search_market_data` — FREE. Describe what you need in plain language; get matching endpoints with price and parameters
- `get_market_data` — fetch any endpoint (delayed sample FREE; live data at the endpoint's x402 price, from $0.001)
- `market_snapshot` — one call for a whole area: `brazil`, `global` or `crypto`
- `list_categories` — FREE. Every category, endpoint count, cheapest price
- `account_status` — FREE. Subscription/credit status for this connection

New in v48.19 (all reachable through the meta-tools above):

| Endpoint | Price | What you get |
|---|---|---|
| `/chain-block` | $0.001 | Latest Base block: number, age, gas-used %, base fee |
| `/gas-price` | $0.001 | Gas now + ML forecast ~10 min ahead (self-fed Holt smoothing) with send/wait recommendation |
| `/chain-balance` | $0.002 | ETH + ERC-20 balances, nonce, wallet-class heuristic |
| `/chain-ens` | $0.002 | ENS forward and reverse resolution |
| `/chain-tx` | $0.002 | Tx status/value/fee/logs, optional LLM explanation (`explain=1`) |
| `/agent-reputation` | $0.010 | On-chain ERC-8004 identity + aggregated reputation for any registered agent |
| `/wallet-verdict` | $0.020 | Graded wallet verdict + LLM roast, idempotent, with shareable SVG card |

## Install locally (Claude Desktop / Cursor)

```json
{
  "mcpServers": {
    "losbeto": {
      "command": "npx",
      "args": ["-y", "losbeto-mcp"],
      "env": { "LOSBETO_PRIVATE_KEY": "0x..." }
    }
  }
}
```

`LOSBETO_PRIVATE_KEY` = an EVM private key holding a little USDC on Base (optional — free tools work without it).

The npm package exposes the **classic 9-tool set**:

FREE: `try_samples` (6 live samples in 1 call) · `welcome_free_call` (one real-time call, no wallet) · `launch_risk_preview` · `receipts` (audit our on-chain sales, honestly labeled)

PAID via x402: `launch_risk_brief` (~$0.10) · `br_macro` ($0.05, BCB data) · `oracle_consensus` ($0.03) · `fear_greed` ($0.01) · `sol_price` ($0.003)

For the full catalog (including the v48.19 chain reads and ERC-8004 reputation), use the remote server — the npm package is the classic fixed tool set.

## Transparency

- Receipts: https://api.losbeto.xyz/receipts
- Live funnel: https://api.losbeto.xyz/funnel.json
- Catalog: https://api.losbeto.xyz/get-pricing
- On-chain identity: https://8004scan.io/agents/base/87048
