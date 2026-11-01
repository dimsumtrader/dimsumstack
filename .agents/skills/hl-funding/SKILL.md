---
name: hl-funding
description: Fetch and analyze hourly funding rates for perpetuals on Hyperliquid — crypto perps on the main dex plus equity/ETF/index, commodity, and FX perps on the trade.xyz (HIP-3) dex — using a bundled Python CLI with an --asset-class selector. Use when the user explicitly asks for funding rates or funding history on Hyperliquid (crypto or xyz perps), wants a funding master CSV (re)generated, or wants such a CSV analyzed.
---

# Hyperliquid funding rates (all asset classes)

Two jobs: (1) fetch hourly funding-rate history for a chosen asset class into
one master CSV, (2) answer analysis questions from that CSV.

## Run the fetch

The CLI lives at `scripts/hype_funding_rate.py` (relative to this skill's
base directory). Its `requests` dependency is declared in an embedded
PEP 723 header, so uv runs it with zero setup:

```bash
uv run scripts/hype_funding_rate.py --asset-class equity --days 30 --min-oi-usd 10000000
```

On machines without uv, any Python 3.9+ with `requests` installed runs it
directly:

```bash
python scripts/hype_funding_rate.py --asset-class equity --days 30 --min-oi-usd 10000000
```

If `uv` is not on PATH — common in fresh shells, since uv installs to
`~/.local/bin` by default — invoke it by absolute path (Windows:
`%USERPROFILE%\.local\bin\uv.exe run ...`, macOS/Linux:
`~/.local/bin/uv run ...`) or prepend that directory to PATH first.

| Flag | Default | Meaning |
|------|---------|---------|
| `--asset-class` | `equity` | Which markets to include — see table below. |
| `--days` | `30` | Lookback window in days, counting back from now (UTC). |
| `--min-oi-usd` | `10000000` | Keep only markets whose open interest (OI x mark price) clears this USD floor. Treated as 0 when `--coins` is given. |
| `--coins` | (none) | Comma-separated specific markets to include, by ticker or full name (`--coins BTC` or `--coins xyz:AAPL,AAPL`); skips the OI floor. |
| `--output` | derived | Destination CSV; overwritten each run. Defaults to `hl_<asset-class>_funding.csv` (e.g. `hl_equity_funding.csv`). |

Asset classes:

| Class | Dex | Contents |
|-------|-----|----------|
| `crypto` | main Hyperliquid dex | BTC, ETH, and other token perps (bare names, no prefix). |
| `equity` | trade.xyz | Single stocks, ETFs, equity indices (`xyz:AAPL`, `xyz:SP500`, ...). |
| `commodity` | trade.xyz | `xyz:GOLD`, `xyz:BRENTOIL`, `xyz:CL` (WTI crude), ... |
| `fx` | trade.xyz | `xyz:EUR`, `xyz:JPY`, `xyz:DXY`, ... |
| `other` | trade.xyz | Non-equity xyz listings that fit no class (`xyz:VIX`, `xyz:H100`). |
| `all` | both | Everything above combined — the `Asset_Class` column keeps it analyzable. |

Translate the user's request literally into flags — "crypto funding for the
last week, $500M+ OI only" becomes `--asset-class crypto --days 7
--min-oi-usd 500000000`. Any parameter the user doesn't specify takes the
default above; if the user doesn't name an asset class, ask which they want
unless context makes it obvious.

For single-market asks ("pull BTC funding", "funding for xyz:AAPL"), use
`--coins BTC` / `--coins AAPL` — it fetches just those markets instead of
the whole class, so prefer it over fetch-everything-then-filter.

Class boundaries live in the ticker sets at the top of the script
(`FX_TICKERS`, `COMMODITY_TICKERS`, `OTHER_TICKERS`). Note `xyz:CL` is WTI
crude oil, not Colgate-Palmolive. If a new xyz market appears in the wrong
class, add its ticker to the right set.

Open-interest magnitudes differ wildly by class — BTC's OI is in the
billions while most equities sit in the tens of millions — so the same
`--min-oi-usd` floor means very different things per class; when the user
asks for "the biggest" markets, prefer naming a count over reusing the
default floor. Runtime scales with coins x history depth (an `all` pull at
default thresholds spans both dexes and takes a while); the script prints
per-coin progress and ends with a summary block: coins with data, rows
written, and the covered UTC window. Report that summary back to the user.

## Output format

One row per market per hourly funding event:

| Column | Meaning |
|--------|---------|
| `Coin` | Full market name — `xyz:AAPL` on the xyz dex, `BTC` on the main dex. |
| `Asset_Class` | `crypto` / `equity` / `commodity` / `fx` / `other`. |
| `Timestamp_UTC` / `Date` / `Hour_UTC` | Event time plus derived date and hour columns. |
| `Funding_Rate_Pct` | Hourly funding as a percent (raw fraction x 100). Positive = longs pay shorts (long side is crowded); negative = shorts pay longs. |
| `Premium_Pct` | (mark - index) / index as a percent; `N/A` when the API returned no premium. |

## Analyzing

Read the CSV and answer from the data. Analysis needs `pandas` (the fetch
script itself only needs `requests`) — run snippets with
`uv run --with pandas python` on machines without a global pandas.

Baseline aggregation most questions start from:

```python
import pandas as pd
df = pd.read_csv("hl_equity_funding.csv")
per_coin = (df.groupby(["Asset_Class", "Coin"])["Funding_Rate_Pct"]
              .agg(["mean", "min", "max", "count"])
              .sort_values("mean"))
```

- **Ranking**: sort by mean funding — most negative = shorts paying most
  (cheapest leverage for longs), most positive = longs paying most.
- **Extremes**: flag rows where `abs(Funding_Rate_Pct)` is several times
  that coin's own trailing mean rather than using a global threshold, since
  funding magnitude varies hugely by coin.
- **Regime shifts**: compare each coin's last-24h mean against its
  full-window mean to spot fresh crowding, not just standing crowding.
- **Cross-class comparisons** (mainly `all` runs): group by `Asset_Class`
  before comparing — crypto and equity funding levels aren't calibrated to
  each other.
- Treat `N/A` in `Premium_Pct` as missing, never as zero.
