from __future__ import annotations

import os
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.trading.requests import MarketOrderRequest

try:
    from config import get_trading_client, load_config
    from three_sleeve_portfolio import (
        SELECTED_COMBINED_CONFIG,
        SELECTED_KALMAN_CONFIG,
        SELECTED_LEADER_CONFIG,
        SELECTED_TREND_CONFIG,
        build_kalman_weights,
        build_leader_weights,
        build_trend_weights,
        combine_weight_frames,
        compute_returns,
        download_adjusted_close,
        fetch_sp500_constituents,
        get_three_sleeve_tickers,
    )
except ModuleNotFoundError:
    from src.config import get_trading_client, load_config
    from src.three_sleeve_portfolio import (
        SELECTED_COMBINED_CONFIG,
        SELECTED_KALMAN_CONFIG,
        SELECTED_LEADER_CONFIG,
        SELECTED_TREND_CONFIG,
        build_kalman_weights,
        build_leader_weights,
        build_trend_weights,
        combine_weight_frames,
        compute_returns,
        download_adjusted_close,
        fetch_sp500_constituents,
        get_three_sleeve_tickers,
    )


NEW_YORK_TZ = ZoneInfo("America/New_York")
LOOKBACK_CALENDAR_DAYS = 800
DEFAULT_DEPLOYMENT_FRACTION = 0.95
DEFAULT_SETTLE_WAIT_SECONDS = 10


@dataclass(frozen=True)
class OrderPlan:
    symbol: str
    current_qty: float
    target_qty: float
    delta_qty: float
    target_weight: float
    reference_price: float | None


def _get_env_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _normalize_qty(qty: float) -> float:
    rounded = round(qty)
    if abs(qty - rounded) < 1e-9:
        return float(int(rounded))
    return round(qty, 6)


def _format_qty(qty: float) -> str:
    normalized = _normalize_qty(qty)
    if abs(normalized - round(normalized)) < 1e-9:
        return str(int(round(normalized)))
    return f"{normalized:.6f}".rstrip("0").rstrip(".")


def _get_live_settings() -> tuple[bool, float, int]:
    dry_run = _get_env_bool(os.getenv("LIVE_TRADING_DRY_RUN"), default=False)
    deploy_fraction = float(os.getenv("LIVE_DEPLOYMENT_FRACTION", str(DEFAULT_DEPLOYMENT_FRACTION)))
    settle_wait_seconds = int(os.getenv("LIVE_TRADING_SETTLE_WAIT_SECONDS", str(DEFAULT_SETTLE_WAIT_SECONDS)))
    if not 0 < deploy_fraction <= 1:
        raise ValueError("LIVE_DEPLOYMENT_FRACTION must be between 0 and 1.")
    return dry_run, deploy_fraction, max(settle_wait_seconds, 0)


def build_latest_target_weights(as_of_date: date | None = None) -> tuple[pd.Timestamp, pd.Series, pd.Series]:
    trade_date = as_of_date or datetime.now(NEW_YORK_TZ).date()
    start_date = trade_date - timedelta(days=LOOKBACK_CALENDAR_DAYS)

    constituents = fetch_sp500_constituents()
    tickers = get_three_sleeve_tickers(constituents)
    prices = download_adjusted_close(
        tickers=tickers,
        start=start_date.isoformat(),
        end=trade_date.isoformat(),
    )
    if prices.empty:
        raise RuntimeError("No price history returned for three-sleeve target generation.")

    returns = compute_returns(prices)
    trend_weights = build_trend_weights(prices, SELECTED_TREND_CONFIG)
    kalman_weights = build_kalman_weights(prices, SELECTED_KALMAN_CONFIG)
    leader_weights = build_leader_weights(prices, constituents, SELECTED_LEADER_CONFIG)
    combined_weights = combine_weight_frames(
        {
            "trend": trend_weights,
            "kalman": kalman_weights,
            "leader": leader_weights,
        },
        {
            "trend": SELECTED_COMBINED_CONFIG.trend_weight,
            "kalman": SELECTED_COMBINED_CONFIG.kalman_weight,
            "leader": SELECTED_COMBINED_CONFIG.leader_weight,
        },
    )

    aligned = combined_weights.reindex(returns.index).ffill().fillna(0.0)
    signal_date = aligned.index[-1]
    if signal_date.date() >= trade_date:
        raise RuntimeError(
            "Target generation included same-day data. "
            "This would violate the T-1 decision rule."
        )

    latest_weights = aligned.loc[signal_date].fillna(0.0)
    latest_prices = prices.loc[signal_date].fillna(0.0)
    return signal_date, latest_weights, latest_prices


def build_target_quantities(
    target_weights: pd.Series,
    reference_prices: pd.Series,
    target_notional: float,
) -> dict[str, float]:
    targets: dict[str, float] = {}
    for symbol, weight in target_weights.items():
        if weight <= 0:
            continue
        price = float(reference_prices.get(symbol, 0.0))
        if price <= 0:
            raise RuntimeError(f"Missing or invalid reference price for target symbol {symbol}.")
        target_qty = int((target_notional * float(weight)) / price)
        targets[symbol] = float(target_qty)
    return targets


def build_order_plan(
    positions: dict[str, object],
    target_weights: pd.Series,
    target_quantities: dict[str, float],
    reference_prices: pd.Series,
) -> list[OrderPlan]:
    symbols = sorted(set(positions) | set(target_quantities))
    plans: list[OrderPlan] = []

    for symbol in symbols:
        current_qty = float(positions[symbol].qty) if symbol in positions else 0.0
        target_qty = float(target_quantities.get(symbol, 0.0))
        delta_qty = target_qty - current_qty
        if abs(delta_qty) < 1e-9:
            continue
        reference_price = float(reference_prices.get(symbol, 0.0)) or None
        plans.append(
            OrderPlan(
                symbol=symbol,
                current_qty=_normalize_qty(current_qty),
                target_qty=_normalize_qty(target_qty),
                delta_qty=_normalize_qty(delta_qty),
                target_weight=float(target_weights.get(symbol, 0.0)),
                reference_price=reference_price,
            )
        )

    return plans


def split_order_plan(order_plan: list[OrderPlan]) -> tuple[list[OrderPlan], list[OrderPlan], list[OrderPlan]]:
    sells = sorted(
        [plan for plan in order_plan if plan.delta_qty < 0],
        key=lambda plan: abs(plan.delta_qty) * float(plan.reference_price or 0.0),
        reverse=True,
    )
    covers = sorted(
        [plan for plan in order_plan if plan.delta_qty > 0 and plan.current_qty < 0],
        key=lambda plan: abs(plan.delta_qty) * float(plan.reference_price or 0.0),
        reverse=True,
    )
    buys = sorted(
        [plan for plan in order_plan if plan.delta_qty > 0 and plan.current_qty >= 0],
        key=lambda plan: abs(plan.delta_qty) * float(plan.reference_price or 0.0),
        reverse=True,
    )
    return sells, covers, buys


def submit_order_bucket(trading_client, bucket_name: str, plans: list[OrderPlan], dry_run: bool) -> None:
    if not plans:
        return
    for plan in plans:
        side = OrderSide.SELL if plan.delta_qty < 0 else OrderSide.BUY
        qty = abs(plan.delta_qty)
        print(
            f"{bucket_name} {plan.symbol}: current={_format_qty(plan.current_qty)} "
            f"target={_format_qty(plan.target_qty)} delta={_format_qty(plan.delta_qty)} "
            f"weight={plan.target_weight:.2%}"
        )
        if dry_run:
            continue
        order = MarketOrderRequest(
            symbol=plan.symbol,
            qty=qty,
            side=side,
            time_in_force=TimeInForce.DAY,
        )
        trading_client.submit_order(order_data=order)


def run_live_cycle() -> None:
    load_config()
    trading_client = get_trading_client()
    dry_run, deploy_fraction, settle_wait_seconds = _get_live_settings()

    clock = trading_client.get_clock()
    account = trading_client.get_account()
    trade_date = datetime.now(NEW_YORK_TZ).date()

    print(f"[{datetime.now().isoformat()}] Starting three-sleeve live cycle.")
    print(
        f"Account equity=${float(account.equity):,.2f}, cash=${float(account.cash):,.2f}, "
        f"buying_power=${float(account.buying_power):,.2f}, deploy_fraction={deploy_fraction:.0%}."
    )

    if not clock.is_open and not dry_run:
        print("Market is closed. Exiting without submitting orders.")
        return

    signal_date, latest_weights, reference_prices = build_latest_target_weights(as_of_date=trade_date)
    target_notional = float(account.equity) * deploy_fraction
    active_weights = latest_weights[latest_weights > 1e-6].sort_values(ascending=False)

    print(f"Using signal date {signal_date.date()} to trade on {trade_date}.")
    print(f"Target deployed notional: ${target_notional:,.2f}")
    print("Active target weights:")
    for symbol, weight in active_weights.items():
        print(f"  {symbol}: {weight:.2%}")

    positions = {position.symbol: position for position in trading_client.get_all_positions()}
    target_quantities = build_target_quantities(active_weights, reference_prices, target_notional)
    order_plan = build_order_plan(positions, latest_weights, target_quantities, reference_prices)

    if not order_plan:
        print("Current portfolio already matches the three-sleeve targets. No orders needed.")
        return

    print("Canceling any open orders before rebalancing...")
    if not dry_run:
        trading_client.cancel_orders()

    sells, covers, buys = split_order_plan(order_plan)

    submit_order_bucket(trading_client, "SELL", sells, dry_run=dry_run)
    if sells and (covers or buys) and not dry_run and settle_wait_seconds > 0:
        print(f"Waiting {settle_wait_seconds}s for sells to settle before covers/buys...")
        time.sleep(settle_wait_seconds)

    submit_order_bucket(trading_client, "COVER", covers, dry_run=dry_run)
    if covers and buys and not dry_run and settle_wait_seconds > 0:
        print(f"Waiting {settle_wait_seconds}s for covers to settle before new buys...")
        time.sleep(settle_wait_seconds)

    submit_order_bucket(trading_client, "BUY", buys, dry_run=dry_run)

    if dry_run:
        print("Dry run complete. No live orders were submitted.")
    else:
        print("Three-sleeve rebalance orders submitted.")


def main() -> None:
    run_live_cycle()


if __name__ == "__main__":
    main()
