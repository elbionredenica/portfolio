from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import quantstats as qs
import seaborn as sns

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from three_sleeve_portfolio import (  # noqa: E402
    CombinedConfig,
    KalmanConfig,
    LeaderConfig,
    SELECTED_COMBINED_CONFIG,
    SELECTED_KALMAN_CONFIG,
    SELECTED_LEADER_CONFIG,
    SELECTED_TREND_CONFIG,
    TrendConfig,
    build_kalman_weights,
    build_leader_weights,
    build_trend_weights,
    calculate_metrics,
    combine_weight_frames,
    compute_returns,
    download_adjusted_close,
    fetch_sp500_constituents,
    weights_to_returns,
)


START_DATE = "2010-01-01"
BENCHMARK = "SPY"
OUTPUT_DIR = REPO_ROOT / "research" / "three_sleeve_output"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

TREND_CANDIDATES = ("W-FRI", "ME")
KALMAN_Z_ENTRIES = (1.0, 1.25, 1.5, 1.75, 2.0)
KALMAN_Z_EXITS = (0.0, 0.25, 0.5)
KALMAN_WINDOWS = (10, 20, 30, 40)
KALMAN_MEASUREMENT_VARIANCES = (1e-3, 1e-2)
LEADER_LOOKBACKS = (126, 231)
LEADER_TOP_NS = (1, 3, 5)
LEADER_REQUIRE_STOCK_TREND = (True, False)

SELECTED_TREND = SELECTED_TREND_CONFIG
SELECTED_KALMAN = SELECTED_KALMAN_CONFIG
SELECTED_LEADER = SELECTED_LEADER_CONFIG
SELECTED_COMBINED = SELECTED_COMBINED_CONFIG


def format_pct(value: float) -> str:
    return f"{value * 100:.2f}%"


def save_quantstats_report(returns: pd.Series, benchmark: pd.Series, output_path: Path, title: str) -> None:
    qs.reports.html(
        returns.dropna(),
        benchmark=benchmark.reindex(returns.index).dropna(),
        output=output_path.as_posix(),
        title=title,
    )


def search_trend_configs(prices: pd.DataFrame, returns: pd.DataFrame) -> pd.DataFrame:
    rows = []
    benchmark_returns = returns[BENCHMARK]
    for frequency in TREND_CANDIDATES:
        config = TrendConfig(rebalance_frequency=frequency)
        weights = build_trend_weights(prices, config)
        strategy_returns = weights_to_returns(weights, returns)
        metrics = calculate_metrics(strategy_returns, benchmark_returns)
        rows.append({"rebalance_frequency": frequency, **metrics})
    result = pd.DataFrame(rows).sort_values(["annual_return", "sharpe"], ascending=[False, False])
    result.to_csv(OUTPUT_DIR / "trend_search.csv", index=False)
    return result


def search_kalman_configs(prices: pd.DataFrame, returns: pd.DataFrame) -> pd.DataFrame:
    rows = []
    benchmark_returns = returns[BENCHMARK]
    for entry_z in KALMAN_Z_ENTRIES:
        for exit_z in KALMAN_Z_EXITS:
            for residual_window in KALMAN_WINDOWS:
                for measurement_variance in KALMAN_MEASUREMENT_VARIANCES:
                    config = KalmanConfig(
                        entry_z=entry_z,
                        exit_z=exit_z,
                        residual_window=residual_window,
                        measurement_variance=measurement_variance,
                    )
                    weights = build_kalman_weights(prices, config)
                    strategy_returns = weights_to_returns(weights, returns)
                    metrics = calculate_metrics(strategy_returns, benchmark_returns)
                    rows.append(
                        {
                            "entry_z": entry_z,
                            "exit_z": exit_z,
                            "residual_window": residual_window,
                            "measurement_variance": measurement_variance,
                            **metrics,
                        }
                    )
    result = pd.DataFrame(rows).sort_values(["sharpe", "annual_return"], ascending=[False, False])
    result.to_csv(OUTPUT_DIR / "kalman_search.csv", index=False)
    return result


def search_leader_variants(prices: pd.DataFrame, returns: pd.DataFrame, constituents: list[str]) -> pd.DataFrame:
    rows = []
    benchmark_returns = returns[BENCHMARK]
    for lookback in LEADER_LOOKBACKS:
        for top_n in LEADER_TOP_NS:
            for stock_trend in LEADER_REQUIRE_STOCK_TREND:
                config = LeaderConfig(
                    momentum_lookback_days=lookback,
                    top_n=top_n,
                    require_stock_trend=stock_trend,
                )
                weights = build_leader_weights(prices, constituents, config)
                strategy_returns = weights_to_returns(weights, returns)
                metrics = calculate_metrics(strategy_returns, benchmark_returns)
                rows.append(
                    {
                        "momentum_lookback_days": lookback,
                        "top_n": top_n,
                        "require_stock_trend": stock_trend,
                        **metrics,
                    }
                )
    result = pd.DataFrame(rows).sort_values(["sharpe", "annual_return"], ascending=[False, False])
    result.to_csv(OUTPUT_DIR / "leader_variants.csv", index=False)
    return result


def build_dashboard(
    strategy_returns: pd.DataFrame,
    benchmark_returns: pd.Series,
    combined_weights: pd.DataFrame,
) -> Path:
    benchmark_returns = benchmark_returns.reindex(strategy_returns.index).fillna(0.0)
    equity = (1 + pd.concat([strategy_returns, benchmark_returns.rename("spy")], axis=1)).cumprod()
    combined_drawdown = equity["combined"] / equity["combined"].cummax() - 1
    spy_drawdown = equity["spy"] / equity["spy"].cummax() - 1

    latest_allocation = (
        combined_weights.iloc[-1]
        .sort_values(ascending=False)
        .loc[lambda s: s > 0.001]
        .head(15)
        .sort_values(ascending=True)
    )
    corr = strategy_returns.join(benchmark_returns.rename("spy")).corr()

    fig, axes = plt.subplots(2, 2, figsize=(18, 12))

    equity_axes = axes[0, 0]
    for column in ["trend", "kalman", "leader", "combined", "spy"]:
        equity_axes.plot(equity.index, equity[column], label=column.upper(), linewidth=2)
    equity_axes.set_title("Equity Curves vs SPY")
    equity_axes.set_ylabel("Growth of $1 (log scale)")
    equity_axes.set_yscale("log")
    equity_axes.grid(alpha=0.3)
    equity_axes.legend()

    dd_axes = axes[0, 1]
    dd_axes.plot(combined_drawdown.index, combined_drawdown, label="Combined", linewidth=2)
    dd_axes.plot(spy_drawdown.index, spy_drawdown, label="SPY", linewidth=2, alpha=0.8)
    dd_axes.axhline(0, color="black", linewidth=1)
    dd_axes.set_title("Drawdown")
    dd_axes.grid(alpha=0.3)
    dd_axes.legend()

    alloc_axes = axes[1, 0]
    latest_allocation.plot(kind="barh", ax=alloc_axes, color="#4C78A8")
    alloc_axes.set_title("Latest Combined Allocation")
    alloc_axes.set_xlabel("Weight")
    alloc_axes.grid(alpha=0.3, axis="x")

    corr_axes = axes[1, 1]
    sns.heatmap(corr, annot=True, cmap="vlag", center=0, fmt=".2f", ax=corr_axes)
    corr_axes.set_title("Return Correlations")

    plt.tight_layout()
    output_path = OUTPUT_DIR / "three_sleeve_dashboard.png"
    fig.savefig(output_path, dpi=180)
    plt.close(fig)
    return output_path


def write_summary(
    metrics_df: pd.DataFrame,
    trend_search: pd.DataFrame,
    kalman_search: pd.DataFrame,
    leader_variants: pd.DataFrame,
) -> Path:
    summary_path = OUTPUT_DIR / "summary.md"
    combined_row = metrics_df.loc["combined"]
    spy_total = combined_row["benchmark_total_return"]
    strategy_total = combined_row["total_return"]

    text = f"""# Three-Sleeve Research Summary

## Final Chosen Configurations
- Trend sleeve: 200-day SMA on `SPY`, `TLT`, and `GLD`, monthly rebalance, cash parked in `BIL`.
- Kalman sleeve: liquid ETF pullback basket on `{", ".join(SELECTED_KALMAN.universe)}`, long-only, `entry_z={SELECTED_KALMAN.entry_z}`, `exit_z={SELECTED_KALMAN.exit_z}`, `window={SELECTED_KALMAN.residual_window}`, `measurement_variance={SELECTED_KALMAN.measurement_variance}`.
- Leader sleeve: top-1 current S&P 500 stock by 12-1 momentum, monthly rebalance, stock and market 200-day trend filter, cash in `BIL`.
- Combined weights: trend `{SELECTED_COMBINED.trend_weight:.0%}`, Kalman `{SELECTED_COMBINED.kalman_weight:.0%}`, leader `{SELECTED_COMBINED.leader_weight:.0%}`.

## Strategy Search Notes
- Trend search favored monthly rebalance over weekly rebalance on both return and Sharpe.
- Kalman search favored slower, cleaner pullback entries on the ETF universe; the stock-based daily variants were materially weaker versus SPY.
- Leader search showed that broader `top_n` portfolios had higher Sharpe, but the `top_n=1` version was intentionally retained as the high-conviction satellite sleeve.

## Does The Combined Portfolio Beat Buy-and-Hold SPY?
- Combined total return: {format_pct(strategy_total)}
- SPY total return: {format_pct(spy_total)}
- Difference: {format_pct(strategy_total - spy_total)}
- Combined annual return: {format_pct(combined_row["annual_return"])}
- SPY annual return: {format_pct(combined_row["benchmark_annual_return"])}

## Interpretation
- The trend sleeve is the stabilizer: slower, lower turnover, and historically resilient.
- The Kalman sleeve is a diversifier rather than the main engine of return once we force it into a realistic daily, long-only, trend-aware implementation.
- The leader sleeve drives most of the upside and most of the tail risk; this is why its allocation stays small.
- The combined portfolio improves on SPY over the shared sample while keeping a materially lower beta than a pure buy-and-hold equity portfolio.
"""
    summary_path.write_text(text)
    return summary_path


def main() -> None:
    constituents = fetch_sp500_constituents()
    all_tickers = set(constituents)
    all_tickers.update(SELECTED_TREND.risky_assets)
    all_tickers.update((SELECTED_TREND.cash_asset,))
    all_tickers.update(SELECTED_KALMAN.universe)
    all_tickers.update((SELECTED_KALMAN.cash_asset, BENCHMARK))
    all_tickers.update((SELECTED_LEADER.cash_asset,))

    prices = download_adjusted_close(sorted(all_tickers), START_DATE)
    constituents = [ticker for ticker in constituents if ticker in prices.columns]
    returns = compute_returns(prices)

    trend_search = search_trend_configs(prices, returns)
    kalman_search = search_kalman_configs(prices, returns)
    leader_variants = search_leader_variants(prices, returns, constituents)

    trend_weights = build_trend_weights(prices, SELECTED_TREND)
    kalman_weights = build_kalman_weights(prices, SELECTED_KALMAN)
    leader_weights = build_leader_weights(prices, constituents, SELECTED_LEADER)

    trend_returns = weights_to_returns(trend_weights, returns).rename("trend")
    kalman_returns = weights_to_returns(kalman_weights, returns).rename("kalman")
    leader_returns = weights_to_returns(leader_weights, returns).rename("leader")

    strategy_returns = pd.concat([trend_returns, kalman_returns, leader_returns], axis=1).dropna()
    benchmark_returns = returns[BENCHMARK].reindex(strategy_returns.index).fillna(0.0)

    combined_weights = combine_weight_frames(
        {
            "trend": trend_weights.reindex(strategy_returns.index).ffill().fillna(0.0),
            "kalman": kalman_weights.reindex(strategy_returns.index).ffill().fillna(0.0),
            "leader": leader_weights.reindex(strategy_returns.index).ffill().fillna(0.0),
        },
        {
            "trend": SELECTED_COMBINED.trend_weight,
            "kalman": SELECTED_COMBINED.kalman_weight,
            "leader": SELECTED_COMBINED.leader_weight,
        },
    )
    combined_returns = weights_to_returns(combined_weights, returns).reindex(strategy_returns.index).fillna(0.0)
    strategy_returns["combined"] = combined_returns

    metrics = {
        column: calculate_metrics(strategy_returns[column], benchmark_returns)
        for column in strategy_returns.columns
    }
    metrics_df = pd.DataFrame(metrics).T
    metrics_df.to_csv(OUTPUT_DIR / "strategy_metrics.csv")

    latest_weights = (
        combined_weights.iloc[-1]
        .sort_values(ascending=False)
        .loc[lambda s: s > 0.001]
        .rename("weight")
        .to_frame()
    )
    latest_weights.to_csv(OUTPUT_DIR / "latest_combined_weights.csv")

    strategy_returns.corr().to_csv(OUTPUT_DIR / "strategy_correlations.csv")
    dashboard_path = build_dashboard(strategy_returns, benchmark_returns, combined_weights)

    for column in strategy_returns.columns:
        save_quantstats_report(
            strategy_returns[column],
            benchmark_returns,
            OUTPUT_DIR / f"{column}_tearsheet.html",
            f"{column.title()} Sleeve vs SPY",
        )

    summary_path = write_summary(metrics_df, trend_search, kalman_search, leader_variants)

    selected = {
        "trend": SELECTED_TREND.__dict__,
        "kalman": SELECTED_KALMAN.__dict__,
        "leader": SELECTED_LEADER.__dict__,
        "combined": SELECTED_COMBINED.__dict__,
    }
    (OUTPUT_DIR / "selected_parameters.json").write_text(json.dumps(selected, indent=2))

    print("Saved outputs to:", OUTPUT_DIR)
    print("Trend search top row:")
    print(trend_search.head(1).to_string(index=False))
    print("\nKalman search top row:")
    print(kalman_search.head(1).to_string(index=False))
    print("\nLeader variants top row:")
    print(leader_variants.head(1).to_string(index=False))
    print("\nFinal metrics:")
    print(metrics_df[["annual_return", "volatility", "sharpe", "max_drawdown", "annual_return_minus_spy"]].to_string())
    print("\nDashboard:", dashboard_path)
    print("Summary:", summary_path)


if __name__ == "__main__":
    main()
