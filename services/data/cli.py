"""TradNex data-service CLI.

Examples:
    python -m services.data.cli quote NVDA
    python -m services.data.cli quotes NVDA SPY AMD
    python -m services.data.cli bars NVDA --timeframe 1d --limit 50
    python -m services.data.cli chain NVDA --min-dte 3 --max-dte 14 --type call
    python -m services.data.cli account
    python -m services.data.cli movers
    python -m services.data.cli status
    python -m services.data.cli analyze NVDA --timeframe 1d --bars 200

Add --json to any command for raw JSON output.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from decimal import Decimal
from typing import Any

from shared.analytics import compute_full_analysis
from shared.clients.factory import make_market_data_client
from shared.clients.market_data import MarketDataClient
from shared.config import settings


def _serialize(obj: Any) -> Any:
    if hasattr(obj, "model_dump"):
        return obj.model_dump(mode="json")
    return obj


def _print_json(obj: Any) -> None:
    print(json.dumps(_serialize(obj), indent=2, default=str))


def _print_quote(quote: Any) -> None:
    print(f"  {quote.ticker}")
    print(f"    spot:           {quote.spot}")
    print(
        f"    bid / ask:      {quote.bid} / {quote.ask}  "
        f"(sizes {quote.bid_size}/{quote.ask_size})"
    )
    print(f"    day open:       {quote.day_open}")
    print(f"    day high / low: {quote.day_high} / {quote.day_low}")
    print(f"    prev close:     {quote.prev_close}")
    print(f"    day change:     {quote.day_change} ({quote.day_change_pct:.2f}%)")
    print(
        f"    volume:         {quote.volume:,}  "
        f"(avg30d {quote.avg_volume_30d:,}, ratio {quote.volume_vs_avg:.2f})"
    )
    print(f"    market open:    {quote.is_market_open}")
    print(f"    timestamp:      {quote.timestamp.isoformat()}")


async def _cmd_quote(client: MarketDataClient, args: argparse.Namespace) -> None:
    quote = await client.get_quote(args.ticker)
    if args.json:
        _print_json(quote)
        return
    print(f"Quote ({settings.DATA_CLIENT})")
    _print_quote(quote)


async def _cmd_quotes(client: MarketDataClient, args: argparse.Namespace) -> None:
    quotes = await client.get_quotes(args.tickers)
    if args.json:
        _print_json({t: q for t, q in quotes.items()})
        return
    print(f"Quotes ({settings.DATA_CLIENT})")
    for ticker in args.tickers:
        if ticker.upper() in quotes:
            _print_quote(quotes[ticker.upper()])


async def _cmd_bars(client: MarketDataClient, args: argparse.Namespace) -> None:
    bars = await client.get_bars(args.ticker, timeframe=args.timeframe, limit=args.limit)
    if args.json:
        _print_json(bars)
        return
    print(f"Bars ({settings.DATA_CLIENT}) {args.ticker} {args.timeframe} (last {len(bars)})")
    print(f"  {'time':<25}  {'open':>10}  {'high':>10}  {'low':>10}  {'close':>10}  {'volume':>12}")
    for bar in bars[-args.limit :]:
        print(
            f"  {bar.timestamp.isoformat():<25}  "
            f"{bar.open:>10}  {bar.high:>10}  {bar.low:>10}  {bar.close:>10}  {bar.volume:>12,}"
        )


async def _cmd_chain(client: MarketDataClient, args: argparse.Namespace) -> None:
    chain = await client.get_options_chain(
        args.ticker,
        min_dte=args.min_dte,
        max_dte=args.max_dte,
        contract_type=args.type,
    )
    if args.json:
        _print_json(chain)
        return
    print(
        f"Options chain ({settings.DATA_CLIENT}) {chain.underlying}  "
        f"spot={chain.spot_at_fetch}  contracts={len(chain.contracts)}  "
        f"expirations={len(chain.expirations)}"
    )
    print(
        f"  {'symbol':<22}  {'exp':<10}  {'DTE':>4}  {'type':<4}  "
        f"{'strike':>8}  {'bid':>6}  {'ask':>6}  {'mid':>6}  "
        f"{'iv':>6}  {'delta':>7}  {'OI':>6}"
    )
    for c in sorted(chain.contracts, key=lambda x: (x.expiration, x.contract_type, x.strike)):
        print(
            f"  {c.symbol:<22}  {c.expiration.isoformat():<10}  {c.dte:>4}  {c.contract_type:<4}  "
            f"{c.strike:>8}  {c.bid:>6}  {c.ask:>6}  {c.mid:>6.2f}  "
            f"{c.iv:>6.3f}  {c.delta:>7.3f}  {c.open_interest:>6}"
        )


async def _cmd_account(client: MarketDataClient, args: argparse.Namespace) -> None:
    state = await client.get_account_state()
    if args.json:
        _print_json(state)
        return
    print(f"Account ({settings.DATA_CLIENT})")
    print(f"  account_id:           {state.account_id}")
    print(f"  buying_power:         ${state.buying_power}")
    print(f"  cash:                 ${state.cash}")
    print(f"  equity:               ${state.equity}")
    margin_display = (
        state.margin_buying_power
        if state.margin_buying_power is not None
        else "cash account"
    )
    print(f"  margin_buying_power:  {margin_display}")
    print(f"  is_pdt:               {state.is_pdt}")
    print(f"  pdt_count_remaining:  {state.pdt_count_remaining}")
    print(f"  positions_count:      {state.positions_count}")


async def _cmd_movers(client: MarketDataClient, args: argparse.Namespace) -> None:
    movers = await client.get_movers()
    if args.json:
        _print_json(movers)
        return
    print(f"Movers ({settings.DATA_CLIENT})")
    for label, entries in (
        ("Most active", movers.most_active),
        ("Top gainers", movers.top_gainers),
        ("Top losers", movers.top_losers),
    ):
        print(f"  {label}:")
        for e in entries:
            print(
                f"    {e.ticker:<6}  last={e.last:>10}  change={e.change_pct:>7}%  "
                f"vol={e.volume:>12,}"
            )


async def _cmd_status(client: MarketDataClient, args: argparse.Namespace) -> None:
    status = await client.get_market_status()
    if args.json:
        _print_json(status)
        return
    print(f"Market status ({settings.DATA_CLIENT})")
    print(f"  is_open:        {status.is_open}")
    print(f"  is_pre_market:  {status.is_pre_market}")
    print(f"  is_post_market: {status.is_post_market}")
    print(f"  next_open:      {status.next_open.isoformat()}")
    print(f"  next_close:     {status.next_close.isoformat()}")


async def _cmd_analyze(client: MarketDataClient, args: argparse.Namespace) -> None:
    bars = await client.get_bars(args.ticker, timeframe=args.timeframe, limit=args.bars)
    fa = await compute_full_analysis(args.ticker, bars, timeframe=args.timeframe)
    if args.json:
        _print_json(fa)
        return

    rule = "─" * 60
    print(f"Full Analysis — {fa.ticker} ({fa.timeframe}, {fa.bars_count} bars)")
    print(rule)
    print(f"Spot: ${fa.spot}")
    print(f"Summary: {fa.summary}")
    print()

    print("Momentum:")
    print(f"  RSI({fa.rsi.period}):       {fa.rsi.latest}  {fa.rsi.trend}  {fa.rsi.regime}")
    print(
        f"  MACD:          line {fa.macd.latest_line}  signal {fa.macd.latest_signal}  "
        f"histogram {fa.macd.latest_histogram}  "
        f"({'line above signal' if fa.macd.line_above_signal else 'line below signal'})"
    )
    print()

    print("Trend:")
    print(f"  EMA9:          {fa.ema9.latest}")
    print(f"  EMA21:         {fa.ema21.latest}")
    print(f"  SMA50:         {fa.sma50.latest}")
    if fa.sma200 is not None:
        rel = "price above" if fa.above_200_sma else "price below"
        print(f"  SMA200:        {fa.sma200.latest}   ({rel})")
    else:
        print("  SMA200:        n/a (need 200+ bars)")
    print(
        f"  ADX({fa.adx.period}):       {fa.adx.latest_adx}  "
        f"{fa.adx.trend_strength} trend  {fa.adx.direction}"
    )
    print(
        f"  EMA9/21:       {fa.ema9_21_crossover}    "
        f"SMA50/200: {fa.sma50_200_crossover}"
    )
    print()

    print("Volatility:")
    print(
        f"  ATR({fa.atr.period}):       {fa.atr.latest}  "
        f"({fa.atr.latest_pct_of_spot}% of spot)  {fa.atr.regime} regime"
    )
    print(
        f"  Bollinger:     upper {fa.bollinger.latest_upper}, mid {fa.bollinger.latest_middle}, "
        f"lower {fa.bollinger.latest_lower}, bandwidth {fa.bollinger.bandwidth_pct}%, "
        f"position {fa.bollinger.position}"
    )
    if fa.garch is not None:
        print(
            f"  GARCH:         annualized vol {fa.garch.annualized_vol_forecast}, "
            f"persistence {fa.garch.persistence}, "
            f"half-life {fa.garch.half_life if fa.garch.half_life is not None else 'n/a'} days"
        )
    else:
        print("  GARCH:         fit failed")
    if fa.monte_carlo is not None:
        print(
            f"  Monte Carlo:   {fa.monte_carlo.horizon}d expected move "
            f"±{fa.monte_carlo.expected_move_pct}%, "
            f"p(up) {fa.monte_carlo.prob_above_current}, "
            f"p(>+5%) {fa.monte_carlo.prob_above_5pct}, bias {fa.monte_carlo.bias}"
        )
    else:
        print("  Monte Carlo:   skipped (no GARCH)")
    print()

    print("Levels:")
    fib = fa.fibonacci
    print(
        f"  Fibonacci:     swing high {fib.swing_high}, swing low {fib.swing_low} "
        f"({fib.swing_direction}, lookback {fib.lookback})"
    )
    print(
        f"                 retracements: 23.6% {fib.retracements[Decimal('0.236')]}, "
        f"50% {fib.retracements[Decimal('0.5')]}, "
        f"61.8% {fib.retracements[Decimal('0.618')]}"
    )
    sr = fa.support_resistance
    if sr.support_levels:
        print("  Support:       " + ", ".join(
            f"{lvl.price} ({lvl.touches} touches)" for lvl in sr.support_levels[:3]
        ))
    else:
        print("  Support:       (none detected)")
    if sr.resistance_levels:
        print("  Resistance:    " + ", ".join(
            f"{lvl.price} ({lvl.touches} touches)" for lvl in sr.resistance_levels[:3]
        ))
    else:
        print("  Resistance:    (none detected)")
    print()

    print("Volume:")
    if fa.vwap is not None:
        print(f"  VWAP:          {fa.vwap.latest}")
    else:
        print("  VWAP:          n/a (daily timeframe)")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="services.data.cli",
        description="TradNex data-service CLI",
    )
    parser.add_argument("--json", action="store_true", help="Raw JSON output")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("quote", help="Single ticker quote")
    p.add_argument("ticker")

    p = sub.add_parser("quotes", help="Batch quotes")
    p.add_argument("tickers", nargs="+")

    p = sub.add_parser("bars", help="OHLCV bars")
    p.add_argument("ticker")
    p.add_argument("--timeframe", default="1d", choices=["1m", "5m", "15m", "1h", "1d"])
    p.add_argument("--limit", type=int, default=50)

    p = sub.add_parser("chain", help="Options chain")
    p.add_argument("ticker")
    p.add_argument("--min-dte", type=int, default=None)
    p.add_argument("--max-dte", type=int, default=None)
    p.add_argument("--type", default="both", choices=["call", "put", "both"])

    sub.add_parser("account", help="Broker account state")
    sub.add_parser("movers", help="Most-active / top-gainer / top-loser lists")
    sub.add_parser("status", help="Market open/close status")

    p = sub.add_parser("analyze", help="Full Tier 2 analytics suite")
    p.add_argument("ticker")
    p.add_argument("--timeframe", default="1d", choices=["1m", "5m", "15m", "1h", "1d"])
    p.add_argument("--bars", type=int, default=300)

    return parser


_HANDLERS = {
    "quote": _cmd_quote,
    "quotes": _cmd_quotes,
    "bars": _cmd_bars,
    "chain": _cmd_chain,
    "account": _cmd_account,
    "movers": _cmd_movers,
    "status": _cmd_status,
    "analyze": _cmd_analyze,
}


async def _run(args: argparse.Namespace) -> None:
    client = make_market_data_client(settings)
    await _HANDLERS[args.cmd](client, args)


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    asyncio.run(_run(args))


if __name__ == "__main__":
    main()
