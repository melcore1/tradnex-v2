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
    python -m services.data.cli analyze-options NVDA
    python -m services.data.cli iv-rank NVDA
    python -m services.data.cli gex NVDA
    python -m services.data.cli snapshot-iv NVDA
    python -m services.data.cli regime NVDA
    python -m services.data.cli gap NVDA
    python -m services.data.cli halts
    python -m services.data.cli correlation NVDA AMD
    python -m services.data.cli correlation-matrix
    python -m services.data.cli portfolio-greeks
    python -m services.data.cli compute-correlations

Add --json to any command for raw JSON output.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from decimal import Decimal
from typing import Any

from shared.analytics import (
    compute_correlation_matrix,
    compute_full_analysis,
    compute_options_analysis,
    detect_gap,
    get_correlation_matrix,
    gex_per_strike,
    iv_rank,
)
from shared.analytics.options.portfolio_greeks_real import get_current_portfolio_greeks
from shared.clients.factory import make_halt_feed, make_market_data_client
from shared.clients.market_data import MarketDataClient
from shared.clients.mock_market_data import MockDataClient
from shared.config import settings
from shared.db import get_connection, run_migrations
from shared.services import (
    add_ticker_to_watchlist,
    add_to_universe,
    get_active_watchlist,
    get_universe,
    get_watchlist_history,
    remove_from_universe,
    remove_ticker_from_watchlist,
    set_watchlist,
)


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


def _ensure_mock_iv_seed(client: MarketDataClient) -> None:
    if isinstance(client, MockDataClient):
        run_migrations()
        client.seed_iv_history()


async def _cmd_analyze_options(client: MarketDataClient, args: argparse.Namespace) -> None:
    _ensure_mock_iv_seed(client)
    chain = await client.get_options_chain(args.ticker)
    bars = await client.get_bars(args.ticker, timeframe="1d", limit=300)
    fa = await compute_full_analysis(args.ticker, bars, timeframe="1d")
    conn = get_connection()
    try:
        oa = compute_options_analysis(chain, conn, garch_result=fa.garch)
    finally:
        conn.close()
    if args.json:
        _print_json(oa)
        return
    rule = "─" * 60
    print(f"Options Analysis — {oa.ticker}")
    print(rule)
    print(f"Spot: ${oa.spot}")
    print(f"Summary: {oa.summary}")
    print()

    print("GEX:")
    print(
        f"  net GEX:       {oa.gex.net_gex} ({oa.gex.regime}, {oa.gex.dealer_position})"
    )
    print(f"  call wall:     {oa.gex.call_wall}")
    print(f"  put wall:      {oa.gex.put_wall}")
    print(f"  gamma flip:    {oa.gex.gamma_flip}")
    print()

    print("IV:")
    print(
        f"  IV rank:       {oa.iv_rank.rank} ({oa.iv_rank.regime}, "
        f"{oa.iv_rank.data_points} pts over {oa.iv_rank.lookback_days}d)"
    )
    print(
        f"  IV percentile: {oa.iv_percentile.percentile}"
    )
    if oa.skew is not None:
        print(
            f"  skew:          put25Δ {oa.skew.put_25d_iv} / call25Δ {oa.skew.call_25d_iv}  "
            f"= {oa.skew.skew} ({oa.skew.regime})"
        )
    if oa.term_structure is not None:
        print(
            f"  term:          front {oa.term_structure.front_month_iv} / "
            f"back {oa.term_structure.back_month_iv}  slope {oa.term_structure.slope} "
            f"({oa.term_structure.regime})"
        )
    if oa.vrp is not None:
        print(
            f"  VRP:           IV30 {oa.vrp.atm_iv_30d} - realized "
            f"{oa.vrp.realized_vol_forecast} = {oa.vrp.vrp} ({oa.vrp.regime})"
        )
    print()

    print("Pain & flow:")
    print(
        f"  P/C OI ratio:  {oa.pc_ratio.oi_pc_ratio:.3f} ({oa.pc_ratio.regime_oi})"
    )
    print(
        f"  P/C vol ratio: {oa.pc_ratio.volume_pc_ratio:.3f} ({oa.pc_ratio.regime_volume})"
    )
    if oa.max_pain_per_expiration:
        first_exp, mp = next(iter(oa.max_pain_per_expiration.items()))
        print(
            f"  max pain ({first_exp}): {mp.max_pain_strike}  "
            f"distance {mp.distance_pct}%  ({mp.regime})"
        )
    if oa.expected_move_per_expiration:
        for exp, em in list(oa.expected_move_per_expiration.items())[:3]:
            print(
                f"  expected move ({exp}, {em.dte}d): ±${em.expected_move_dollars} "
                f"(±{em.expected_move_pct}%)"
            )
    print(
        f"  net premium:   call ${oa.net_premium_flow.total_call_premium} - "
        f"put ${oa.net_premium_flow.total_put_premium} = "
        f"{oa.net_premium_flow.net_premium} ({oa.net_premium_flow.direction})"
    )
    print(
        f"  UOA flagged:   {len(oa.unusual_activity.flagged_contracts)} contracts "
        f"({oa.unusual_activity.net_flow_direction})"
    )
    print()

    print("Greeks:")
    print(
        f"  ATM 2nd-order: vanna {oa.second_order_greeks_atm.vanna}  "
        f"charm {oa.second_order_greeks_atm.charm}/day  "
        f"vomma {oa.second_order_greeks_atm.vomma}  "
        f"speed {oa.second_order_greeks_atm.speed}"
    )
    print(
        f"  net chain:     Δ {oa.net_chain_greeks.net_chain_delta}  "
        f"Γ {oa.net_chain_greeks.net_chain_gamma}  "
        f"vega {oa.net_chain_greeks.net_chain_vega}  "
        f"θ {oa.net_chain_greeks.net_chain_theta}"
    )
    print()

    if oa.zero_dte is not None:
        print("0DTE:")
        z = oa.zero_dte
        print(
            f"  pin risk:      {z.pin_risk}  "
            f"(time to expiry {z.time_to_expiry_hours}h)"
        )
        print(f"  expected move: ±${z.expected_move} (±{z.expected_move_pct}%)")
        print(f"  γ concentration: {z.gamma_concentration}%")
        print(f"  key strikes:   {z.key_strikes}")


async def _cmd_iv_rank(client: MarketDataClient, args: argparse.Namespace) -> None:
    _ensure_mock_iv_seed(client)
    chain = await client.get_options_chain(args.ticker, max_dte=45)
    spot = chain.spot_at_fetch
    atm = min(chain.contracts, key=lambda c: abs(c.strike - spot))
    conn = get_connection()
    try:
        result = iv_rank(args.ticker, atm.iv, conn, lookback_days=args.lookback)
    finally:
        conn.close()
    if args.json:
        _print_json(result)
        return
    print(f"IV rank — {args.ticker}")
    print(f"  current IV:    {result.current_iv}")
    print(f"  rank:          {result.rank} ({result.regime})")
    print(f"  history range: [{result.iv_min_lookback}, {result.iv_max_lookback}]")
    print(f"  data points:   {result.data_points} over {result.lookback_days}d")


async def _cmd_gex(client: MarketDataClient, args: argparse.Namespace) -> None:
    chain = await client.get_options_chain(args.ticker)
    result = gex_per_strike(chain)
    if args.json:
        _print_json(result)
        return
    print(f"GEX — {result.underlying}  spot {result.spot}")
    print(f"  net GEX:        {result.net_gex} ({result.regime}, {result.dealer_position})")
    print(f"  call wall:      {result.call_wall}")
    print(f"  put wall:       {result.put_wall}")
    print(f"  gamma flip:     {result.gamma_flip}")
    if result.distance_to_call_wall_pct is not None:
        print(f"  to call wall:   {result.distance_to_call_wall_pct}%")
    if result.distance_to_put_wall_pct is not None:
        print(f"  to put wall:    {result.distance_to_put_wall_pct}%")
    if result.distance_to_flip_pct is not None:
        print(f"  to flip:        {result.distance_to_flip_pct}%")


async def _cmd_snapshot_iv(client: MarketDataClient, args: argparse.Namespace) -> None:
    from services.data.iv_snapshot_task import snapshot_iv_for_ticker

    run_migrations()
    if args.tickers:
        tickers = args.tickers
    else:
        tickers = ["NVDA", "SPY", "AAPL"]
    results = []
    for t in tickers:
        ok = await snapshot_iv_for_ticker(t, client)
        results.append((t, ok))
    if args.json:
        _print_json([{"ticker": t, "written": ok} for t, ok in results])
        return
    print(f"IV snapshot ({settings.DATA_CLIENT})")
    for t, ok in results:
        print(f"  {t}: {'written' if ok else 'skipped'}")


async def _cmd_regime(client: MarketDataClient, args: argparse.Namespace) -> None:
    _ensure_mock_iv_seed(client)
    bars = await client.get_bars(args.ticker, timeframe="1d", limit=300)
    chain = await client.get_options_chain(args.ticker)
    conn = get_connection()
    try:
        options = compute_options_analysis(chain, conn, garch_result=None)
    finally:
        conn.close()
    fa = await compute_full_analysis(args.ticker, bars, options_analysis=options)
    r = fa.regime
    if r is None:
        print("Regime: unable to classify")
        return
    if args.json:
        _print_json(r)
        return
    print(f"Regime — {r.ticker}")
    print(f"  overall:       {r.overall}  (confidence {r.confidence})")
    print(f"  trend:         {r.trend_regime}")
    print(f"  volatility:    {r.volatility_regime}")
    print(f"  gamma:         {r.gamma_regime}")
    print(f"  iv:            {r.iv_regime}")
    print(f"  signals used:  {', '.join(r.signals_used)}")
    print(f"  description:   {r.description}")


async def _cmd_gap(client: MarketDataClient, args: argparse.Namespace) -> None:
    quote = await client.get_quote(args.ticker)
    g = detect_gap(quote)
    if args.json:
        _print_json(g)
        return
    print(f"Gap — {g.ticker}")
    print(f"  prev close:    {g.prev_close}")
    print(f"  current:       {g.current_price}")
    print(f"  gap dollars:   {g.gap_dollars}")
    print(f"  gap pct:       {g.gap_pct}%")
    print(f"  severity:      {g.severity}  ({g.direction})")
    print(f"  alert:         {g.warrants_alert}")


async def _cmd_halts(_client: MarketDataClient, args: argparse.Namespace) -> None:
    feed = make_halt_feed(settings)
    if args.recent_hours:
        halts = await feed.get_recent_halts(hours=args.recent_hours)
    else:
        halts = await feed.get_active_halts()
    if args.json:
        _print_json([h.model_dump(mode="json") for h in halts])
        return
    print(f"Halts ({settings.HALT_FEED}) — {len(halts)}")
    for h in halts:
        active = "active" if h.is_active else "resumed"
        print(
            f"  {h.ticker:<6}  {h.halt_code:<6}  {active:<8}  "
            f"{h.halt_time.isoformat()}  {h.halt_reason}"
        )


async def _cmd_correlation(client: MarketDataClient, args: argparse.Namespace) -> None:
    conn = get_connection()
    try:
        cached = get_correlation_matrix([args.ticker_a, args.ticker_b], conn)
        value = cached.get(args.ticker_a, args.ticker_b)
        from_cache = value is not None
        if value is None:
            matrix = await compute_correlation_matrix(
                [args.ticker_a, args.ticker_b], client, lookback_days=args.lookback
            )
            value = matrix.get(args.ticker_a, args.ticker_b)
    finally:
        conn.close()
    if args.json:
        _print_json(
            {
                "a": args.ticker_a,
                "b": args.ticker_b,
                "value": str(value),
                "cached": from_cache,
            }
        )
        return
    src = "cache" if from_cache else "live"
    print(f"Correlation ({src}) — {args.ticker_a.upper()} vs {args.ticker_b.upper()}: {value}")


async def _cmd_correlation_matrix(_client: MarketDataClient, args: argparse.Namespace) -> None:
    from shared.clients.mock_market_data import DEFAULT_BASELINES

    conn = get_connection()
    try:
        tickers = list(DEFAULT_BASELINES.keys())
        matrix = get_correlation_matrix(tickers, conn)
    finally:
        conn.close()
    if args.json:
        _print_json(matrix)
        return
    print(f"Correlation matrix — {len(matrix.tickers)} tickers, lookback {matrix.lookback_days}d")
    if not matrix.tickers:
        print("  (cache empty — run `compute-correlations` first)")
        return
    print("  ", " ".join(f"{t:>6}" for t in matrix.tickers))
    for a in matrix.tickers:
        row = " ".join(
            f"{float(matrix.matrix.get(a, {}).get(b, Decimal('0'))):>6.2f}"
            for b in matrix.tickers
        )
        print(f"  {a:<4}", row)


async def _cmd_compute_correlations(client: MarketDataClient, args: argparse.Namespace) -> None:
    from services.data.correlation_task import run_correlation_task

    conn = get_connection()
    try:
        written = await run_correlation_task(client, conn, lookback_days=args.lookback)
    finally:
        conn.close()
    if args.json:
        _print_json({"rows_written": written})
        return
    print(f"Correlation task complete — wrote {written} rows for today")


async def _cmd_portfolio_greeks(client: MarketDataClient, args: argparse.Namespace) -> None:
    conn = get_connection()
    try:
        result = await get_current_portfolio_greeks(client, conn)
    finally:
        conn.close()
    if args.json:
        _print_json(result)
        return
    print(f"Portfolio Greeks — {result.positions_count} open positions")
    print(f"  net delta:     {result.net_delta}")
    print(f"  net gamma:     {result.net_gamma}")
    print(f"  net theta:     {result.net_theta}/day")
    print(f"  net vega:      {result.net_vega}")
    print(f"  net rho:       {result.net_rho}")
    print(f"  $ delta:       {result.dollar_delta}")
    print(f"  $ gamma (1%):  {result.dollar_gamma}")
    if result.concentration_warnings:
        for w in result.concentration_warnings:
            print(f"  warning:       {w}")


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

    p = sub.add_parser("analyze-options", help="Full Tier 3 options analytics")
    p.add_argument("ticker")

    p = sub.add_parser("iv-rank", help="IV rank for a ticker")
    p.add_argument("ticker")
    p.add_argument("--lookback", type=int, default=252)

    p = sub.add_parser("gex", help="GEX, walls, gamma flip")
    p.add_argument("ticker")

    p = sub.add_parser("snapshot-iv", help="Run IV snapshot once (writes to DB)")
    p.add_argument("tickers", nargs="*")

    p = sub.add_parser("regime", help="Composite regime classification (Tier 4)")
    p.add_argument("ticker")

    p = sub.add_parser("gap", help="Pre-market / overnight gap detection")
    p.add_argument("ticker")

    p = sub.add_parser("halts", help="Active / recent trading halts")
    p.add_argument("--recent-hours", type=int, default=None)

    p = sub.add_parser("correlation", help="Pairwise correlation between two tickers")
    p.add_argument("ticker_a")
    p.add_argument("ticker_b")
    p.add_argument("--lookback", type=int, default=30)

    sub.add_parser("correlation-matrix", help="Cached correlation matrix for the universe")

    p = sub.add_parser(
        "compute-correlations",
        help="Run the nightly correlation task once (writes to DB)",
    )
    p.add_argument("--lookback", type=int, default=30)

    sub.add_parser("portfolio-greeks", help="Greeks across open positions")

    universe_p = sub.add_parser("universe", help="Static universe management")
    universe_sub = universe_p.add_subparsers(dest="action", required=True)
    universe_sub.add_parser("list", help="Show universe")
    a = universe_sub.add_parser("add", help="Add ticker to universe")
    a.add_argument("ticker")
    r = universe_sub.add_parser("remove", help="Remove ticker (cascades to watchlists)")
    r.add_argument("ticker")

    wl_p = sub.add_parser("watchlist", help="Daily watchlist management")
    wl_sub = wl_p.add_subparsers(dest="action", required=True)
    wl_sub.add_parser("show", help="Show today's active watchlist")
    s = wl_sub.add_parser("set", help="Replace today's watchlist")
    s.add_argument("tickers", nargs="+")
    s.add_argument("--notes", default=None)
    a2 = wl_sub.add_parser("add", help="Add a ticker to today's watchlist")
    a2.add_argument("ticker")
    r2 = wl_sub.add_parser("remove", help="Remove a ticker from today's watchlist")
    r2.add_argument("ticker")
    h = wl_sub.add_parser("history", help="Recent watchlist history")
    h.add_argument("--days", type=int, default=7)
    o = wl_sub.add_parser("override", help="Set per-ticker override on today's watchlist")
    o.add_argument("ticker")
    o.add_argument("--rsi-min", type=float, default=None)
    o.add_argument("--rsi-max", type=float, default=None)
    o.add_argument("--min-dte", type=int, default=None)
    o.add_argument("--max-dte", type=int, default=None)
    o.add_argument("--notes", default=None)
    o.add_argument(
        "--set",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="Generic override (repeatable)",
    )

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
    "analyze-options": _cmd_analyze_options,
    "iv-rank": _cmd_iv_rank,
    "gex": _cmd_gex,
    "snapshot-iv": _cmd_snapshot_iv,
    "regime": _cmd_regime,
    "gap": _cmd_gap,
    "halts": _cmd_halts,
    "correlation": _cmd_correlation,
    "correlation-matrix": _cmd_correlation_matrix,
    "compute-correlations": _cmd_compute_correlations,
    "portfolio-greeks": _cmd_portfolio_greeks,
    "universe": "DISPATCH",  # handled separately based on action
    "watchlist": "DISPATCH",
}


async def _cmd_universe(_client: MarketDataClient, args: argparse.Namespace) -> None:
    conn = get_connection()
    try:
        if args.action == "list":
            universe = await get_universe(conn)
            if args.json:
                _print_json({"universe": universe})
                return
            print(f"Universe ({len(universe)} tickers)")
            for t in universe:
                print(f"  {t}")
        elif args.action == "add":
            updated = await add_to_universe(conn, args.ticker)
            if args.json:
                _print_json({"action": "added", "ticker": args.ticker.upper(), "universe": updated})
                return
            print(f"Added {args.ticker.upper()} → universe now has {len(updated)} tickers")
        elif args.action == "remove":
            updated = await remove_from_universe(conn, args.ticker)
            if args.json:
                _print_json(
                    {"action": "removed", "ticker": args.ticker.upper(), "universe": updated}
                )
                return
            print(f"Removed {args.ticker.upper()} → universe now has {len(updated)} tickers")
    finally:
        conn.close()


def _parse_set_overrides(set_args: list[str]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for raw in set_args:
        if "=" not in raw:
            raise SystemExit(f"--set expects KEY=VALUE, got {raw!r}")
        key, _, value = raw.partition("=")
        # Try to coerce numeric values automatically
        coerced: Any = value
        try:
            coerced = int(value)
        except ValueError:
            try:
                coerced = float(value)
            except ValueError:
                pass
        out[key.strip()] = coerced
    return out


async def _cmd_watchlist(_client: MarketDataClient, args: argparse.Namespace) -> None:
    conn = get_connection()
    try:
        if args.action == "show":
            entry = await get_active_watchlist(conn)
            if args.json:
                _print_json(entry)
                return
            print(f"Watchlist {entry.date}  ({entry.created_by})")
            if entry.notes:
                print(f"  notes: {entry.notes}")
            for t in entry.tickers:
                overrides = entry.per_ticker_overrides.get(t)
                if overrides:
                    print(f"  {t}  overrides={overrides}")
                else:
                    print(f"  {t}")
            if not entry.tickers:
                print("  (empty)")
        elif args.action == "set":
            entry = await set_watchlist(conn, args.tickers, notes=args.notes)
            if args.json:
                _print_json(entry)
                return
            print(f"Watchlist set for {entry.date}: {entry.tickers}")
        elif args.action == "add":
            entry = await add_ticker_to_watchlist(conn, args.ticker)
            if args.json:
                _print_json(entry)
                return
            print(f"Added {args.ticker.upper()} to {entry.date}: now {entry.tickers}")
        elif args.action == "remove":
            entry = await remove_ticker_from_watchlist(conn, args.ticker)
            if args.json:
                _print_json(entry)
                return
            print(f"Removed {args.ticker.upper()} from {entry.date}: now {entry.tickers}")
        elif args.action == "history":
            history = await get_watchlist_history(conn, days=args.days)
            if args.json:
                _print_json(history)
                return
            print(f"Watchlist history (last {args.days} days)")
            for e in history:
                print(f"  {e.date}  {e.created_by:<22}  {len(e.tickers)} tickers  {e.tickers}")
        elif args.action == "override":
            overrides: dict[str, Any] = {}
            if args.rsi_min is not None:
                overrides["rsi_min"] = args.rsi_min
            if args.rsi_max is not None:
                overrides["rsi_max"] = args.rsi_max
            if args.min_dte is not None:
                overrides["min_dte"] = args.min_dte
            if args.max_dte is not None:
                overrides["max_dte"] = args.max_dte
            if args.notes is not None:
                overrides["notes"] = args.notes
            overrides.update(_parse_set_overrides(args.set))
            if not overrides:
                raise SystemExit(
                    "No overrides given. Use --rsi-min, --rsi-max, --min-dte, --max-dte, "
                    "--notes, or --set KEY=VALUE."
                )
            entry = await add_ticker_to_watchlist(conn, args.ticker, overrides=overrides)
            if args.json:
                _print_json(entry)
                return
            print(
                f"Set overrides for {args.ticker.upper()} on {entry.date}: "
                f"{entry.per_ticker_overrides[args.ticker.upper()]}"
            )
    finally:
        conn.close()


_HANDLERS["universe"] = _cmd_universe  # type: ignore[assignment]
_HANDLERS["watchlist"] = _cmd_watchlist  # type: ignore[assignment]


async def _run(args: argparse.Namespace) -> None:
    run_migrations()
    client = make_market_data_client(settings)
    await _HANDLERS[args.cmd](client, args)


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    asyncio.run(_run(args))


if __name__ == "__main__":
    main()
