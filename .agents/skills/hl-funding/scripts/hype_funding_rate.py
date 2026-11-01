"""Fetch hourly funding-rate history for perpetuals on Hyperliquid into one
master CSV, scoped by asset class.

Asset classes:
  crypto     — perps on the main Hyperliquid dex (BTC, ETH, ...)
  equity     — equities / ETFs / equity indices on the trade.xyz (HIP-3) dex
  commodity  — commodity perps on trade.xyz (GOLD, BRENTOIL, WTI "CL", ...)
  fx         — FX perps on trade.xyz (EUR, JPY, DXY, ...)
  other      — xyz listings that fit none of the above (VIX, H100)
  all        — everything above combined

Usage:
    uv run hype_funding_rate.py [--asset-class equity] [--days 30]
                                [--min-oi-usd 10000000] [--output out.csv]
"""

# /// script
# requires-python = ">=3.9"
# dependencies = ["requests"]
# ///

from datetime import datetime, timedelta, timezone
import argparse
import requests
import csv
import time

INFO_URL = "https://api.hyperliquid.xyz/info"
HEADERS = {"Content-Type": "application/json"}

# The trade.xyz (HIP-3) dex lists several kinds of perp. Tickers (the part
# after the "xyz:" prefix) are classified into fx / commodity / other; every
# other xyz asset (single stocks, ETFs, broad equity indices) is equity.
# Add tickers here as new non-equity markets list.
FX_TICKERS = {"EUR", "JPY", "GBP", "KRW", "DXY"}
COMMODITY_TICKERS = {
    "GOLD", "SILVER", "COPPER", "NATGAS", "BRENTOIL",
    "CORN", "WHEAT", "PLATINUM", "PALLADIUM", "URANIUM",
    "ALUMINIUM", "TTF",
}
# "CL" looks like Colgate-Palmolive's NYSE ticker but is the WTI crude oil
# perp — its oracle (~$103) tracks crude against Brent (~$112), not the stock.
COMMODITY_TICKERS.add("CL")
# Volatility / compute listings that are neither equity nor commodity nor FX.
OTHER_TICKERS = {"VIX", "H100"}

ASSET_CLASSES = ["crypto", "equity", "commodity", "fx", "other", "all"]


def _post_with_retry(url, headers, payload, retries=3):
    """POST JSON with simple linear backoff so a transient 429/5xx doesn't
    abort a long-running scan partway through."""
    for attempt in range(retries):
        try:
            response = requests.post(url, headers=headers, json=payload)
            response.raise_for_status()
            return response.json()
        except requests.RequestException:
            if attempt == retries - 1:
                raise
            time.sleep(0.5 * (attempt + 1))


def classify_xyz_ticker(ticker: str) -> str:
    """Map a trade.xyz ticker to its asset class; anything not explicitly
    listed as fx/commodity/other is treated as equity."""
    if ticker in FX_TICKERS:
        return "fx"
    if ticker in COMMODITY_TICKERS:
        return "commodity"
    if ticker in OTHER_TICKERS:
        return "other"
    return "equity"


def scan_dex(dex, wanted_classes, min_oi_usd: float) -> list:
    """Scan one dex (None = main crypto dex, "xyz" = HIP-3 dex) and return
    [(coin_name, oi_usd, asset_class), ...] for markets whose class is
    wanted and whose open interest clears min_oi_usd."""
    payload = {"type": "metaAndAssetCtxs"}
    if dex:
        payload["dex"] = dex

    try:
        data = _post_with_retry(INFO_URL, HEADERS, payload)
        universe = data[0].get('universe', [])
        ctxs = data[1]
    except Exception as e:
        print(f"Error scanning {'main' if not dex else dex} dex: {e}")
        return []

    markets = []
    for i, ctx in enumerate(ctxs):
        coin_name = None
        try:
            entry = universe[i] if i < len(universe) else {}
            if entry.get('isDelisted') or ctx.get('isDelisted'):
                continue

            # On the xyz dex ctx['coin'] is None; the human-readable name
            # lives in universe[i]['name']. On the main dex ctx['coin'] is set.
            coin_name = ctx.get('coin') or entry.get('name')
            if not coin_name:
                continue

            if dex:
                ticker = coin_name.split(":", 1)[1] if coin_name.startswith("xyz:") else coin_name
                asset_class = classify_xyz_ticker(ticker)
            else:
                asset_class = "crypto"

            if asset_class not in wanted_classes:
                continue

            oi_usd = float(ctx.get('openInterest') or 0) * float(ctx.get('markPx') or 0)
            if oi_usd >= min_oi_usd:
                markets.append((coin_name, oi_usd, asset_class))
        except Exception as e:
            print(f"  Skipping malformed asset at index {i} ({coin_name}): {e}")
            continue

    return markets


def get_assets(asset_classes, min_oi_usd: float) -> list:
    """Collect qualifying markets across dexes for the requested classes."""
    wanted = set(asset_classes)
    markets = []
    if 'crypto' in wanted:
        markets += scan_dex(None, {'crypto'}, min_oi_usd)
    if wanted - {'crypto'}:
        markets += scan_dex('xyz', wanted - {'crypto'}, min_oi_usd)
    return markets


def fetch_funding_history(coin: str, start_time_ms: int, page_size: int = 500) -> list:
    """
    Pages through fundingHistory by advancing startTime past the last record's
    timestamp, until the window is exhausted. Returns all records in ascending
    order with no duplicates. page_size must be <= the API's max page size
    (Hyperliquid documents 500) so a full page is detected correctly.
    """
    cursor = start_time_ms
    all_records = []
    while True:
        payload = {"type": "fundingHistory", "coin": coin, "startTime": cursor}
        records = _post_with_retry(INFO_URL, HEADERS, payload)

        if not records:
            break

        all_records.extend(records)

        # A partial page means we've reached the end of available data
        if len(records) < page_size:
            break

        # Advance past the last record to avoid duplicating it on the next page
        next_cursor = records[-1]['time'] + 1
        if next_cursor <= cursor:  # safety: no forward progress, stop
            break
        cursor = next_cursor

        # Protect public node rate boundaries between pages
        time.sleep(0.2)

    return all_records

def aggregate_funding_to_master_csv(asset_class: str, days_ago: int, min_oi_usd: float, filename: str):
    """
    Loops through the selected markets, aggregates their historical hourly funding,
    and saves them out into a single master file for intraday macro analysis.
    """
    target_markets = get_assets([asset_class], min_oi_usd)
    if not target_markets:
        print(f"No markets matched asset class '{asset_class}' at your threshold of ${min_oi_usd:,.0f} USD Open Interest.")
        return

    print(f"Found {len(target_markets)} '{asset_class}' markets with Open Interest over ${min_oi_usd:,.0f}!")

    # Define timeline range
    start_time_dt = datetime.now(timezone.utc) - timedelta(days=days_ago)
    start_time_ms = int(start_time_dt.timestamp() * 1000)

    coins_with_data = 0
    coins_empty = 0
    coins_failed = 0
    rows_written = 0
    first_dt = None
    last_dt = None

    # Initialize master CSV file
    with open(filename, mode='w', newline='', encoding='utf-8') as file:
        writer = csv.writer(file)

        # Both rate and premium are written as percent (raw fraction x100)
        writer.writerow(["Coin", "Asset_Class", "Timestamp_UTC", "Date", "Hour_UTC", "Funding_Rate_Pct", "Premium_Pct"])

        for coin, oi, cls in target_markets:
            print(f" Fetching history for {coin:<10} | Current OI: ${oi:,.2f}")

            try:
                records = fetch_funding_history(coin, start_time_ms)

                if not records:
                    coins_empty += 1
                    continue

                coins_with_data += 1

                for record in records:
                    dt = datetime.fromtimestamp(record['time'] / 1000, tz=timezone.utc)

                    if first_dt is None or dt < first_dt:
                        first_dt = dt
                    if last_dt is None or dt > last_dt:
                        last_dt = dt

                    time_utc = dt.strftime('%Y-%m-%d %H:%M:%S')
                    date_str = dt.strftime('%Y-%m-%d')
                    hour_str = dt.strftime('%H:00')
                    funding_rate_pct = float(record['fundingRate']) * 100
                    premium_pct = float(record['premium']) * 100 if record.get('premium') is not None else 'N/A'

                    writer.writerow([coin, cls, time_utc, date_str, hour_str, funding_rate_pct, premium_pct])
                    rows_written += 1

            except Exception as e:
                coins_failed += 1
                print(f" Skipping {coin} due to API issues: {e}")

    print(f"\nDone! Master dataset saved cleanly to '{filename}'")
    print(f"  asset class     : {asset_class}")
    print(f"  coins with data : {coins_with_data} of {len(target_markets)} scanned"
          f" ({coins_empty} empty, {coins_failed} failed)")
    print(f"  rows written    : {rows_written}")
    if first_dt and last_dt:
        print(f"  window (UTC)    : {first_dt:%Y-%m-%d %H:%M} .. {last_dt:%Y-%m-%d %H:%M}")

def main():
    parser = argparse.ArgumentParser(
        description="Fetch hourly funding history for Hyperliquid perps "
                    "(crypto main dex + trade.xyz equity/commodity/fx dex) "
                    "into a single master CSV.")
    parser.add_argument("--asset-class", choices=ASSET_CLASSES, default="equity",
                        help="which markets to include (default: equity)")
    parser.add_argument("--days", type=int, default=30,
                        help="lookback window in days from now (default: 30)")
    parser.add_argument("--min-oi-usd", type=float, default=10_000_000,
                        help="minimum open interest in USD to include a market (default: 10,000,000)")
    parser.add_argument("--output", default=None,
                        help="destination CSV path, overwritten each run "
                             "(default: hl_<asset-class>_funding.csv)")
    args = parser.parse_args()

    filename = args.output
    if not filename:
        filename = f"hl_{args.asset_class}_funding.csv"

    aggregate_funding_to_master_csv(asset_class=args.asset_class, days_ago=args.days,
                                    min_oi_usd=args.min_oi_usd, filename=filename)

if __name__ == "__main__":
    main()
