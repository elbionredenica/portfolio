from __future__ import annotations

import time
from dataclasses import dataclass
from io import StringIO
from typing import Iterable

import numpy as np
import pandas as pd
import requests
import yfinance as yf


TRADING_DAYS_PER_YEAR = 252


@dataclass(frozen=True)
class TrendConfig:
    risky_assets: tuple[str, ...] = ("SPY", "TLT", "GLD")
    cash_asset: str = "BIL"
    sma_window: int = 200
    rebalance_frequency: str = "ME"


@dataclass(frozen=True)
class KalmanConfig:
    universe: tuple[str, ...] = (
        "SPY",
        "QQQ",
        "IWM",
        "XLF",
        "XLK",
        "XLE",
        "XLI",
        "XLV",
        "TLT",
        "GLD",
    )
    cash_asset: str = "BIL"
    trend_benchmark: str = "SPY"
    trend_window: int = 200
    process_variance: float = 1e-5
    measurement_variance: float = 1e-3
    entry_z: float = 2.0
    exit_z: float = 0.25
    residual_window: int = 10


@dataclass(frozen=True)
class LeaderConfig:
    benchmark_symbol: str = "SPY"
    cash_asset: str = "BIL"
    rebalance_frequency: str = "ME"
    momentum_lookback_days: int = 231
    skip_recent_days: int = 21
    top_n: int = 1
    trend_window: int = 200
    require_stock_trend: bool = True


@dataclass(frozen=True)
class CombinedConfig:
    trend_weight: float = 0.50
    kalman_weight: float = 0.35
    leader_weight: float = 0.15


SELECTED_TREND_CONFIG = TrendConfig(rebalance_frequency="ME")
SELECTED_KALMAN_CONFIG = KalmanConfig(
    entry_z=2.0,
    exit_z=0.25,
    residual_window=10,
    measurement_variance=1e-3,
)
SELECTED_LEADER_CONFIG = LeaderConfig(
    momentum_lookback_days=231,
    skip_recent_days=21,
    top_n=1,
    require_stock_trend=True,
)
SELECTED_COMBINED_CONFIG = CombinedConfig(
    trend_weight=0.50,
    kalman_weight=0.35,
    leader_weight=0.15,
)


@dataclass(frozen=True)
class SingleStateKalmanFilter:
    process_variance: float
    estimated_measurement_variance: float
    posteri_estimate: float = 0.0
    posteri_error_estimate: float = 1.0

    def input_latest_measurement(self, measurement: float) -> "SingleStateKalmanFilter":
        priori_estimate = self.posteri_estimate
        priori_error_estimate = self.posteri_error_estimate + self.process_variance
        blending_factor = priori_error_estimate / (
            priori_error_estimate + self.estimated_measurement_variance
        )
        posteri_estimate = priori_estimate + blending_factor * (measurement - priori_estimate)
        posteri_error_estimate = (1 - blending_factor) * priori_error_estimate
        return SingleStateKalmanFilter(
            process_variance=self.process_variance,
            estimated_measurement_variance=self.estimated_measurement_variance,
            posteri_estimate=posteri_estimate,
            posteri_error_estimate=posteri_error_estimate,
        )


def fetch_sp500_constituents() -> list[str]:
    response = requests.get(
        "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=30,
    )
    response.raise_for_status()
    table = pd.read_html(StringIO(response.text))[0]
    return [symbol.replace(".", "-") for symbol in table["Symbol"].tolist()]


def _extract_close_frame(raw_prices: pd.DataFrame | pd.Series, ordered: list[str]) -> pd.DataFrame:
    if isinstance(raw_prices, pd.Series):
        return raw_prices.to_frame(ordered[0])
    return raw_prices.reindex(columns=ordered)


def _download_close_batch(ordered: list[str], start: str, end: str | None = None) -> pd.DataFrame:
    raw_prices = yf.download(
        ordered,
        start=start,
        end=end,
        auto_adjust=True,
        progress=False,
        threads=False,
    )["Close"]
    return _extract_close_frame(raw_prices, ordered)


def download_adjusted_close(tickers: Iterable[str], start: str, end: str | None = None) -> pd.DataFrame:
    ordered = list(dict.fromkeys(tickers))
    prices = _download_close_batch(ordered, start=start, end=end)

    missing_symbols = prices.columns[prices.isna().all()].tolist()
    for symbol in missing_symbols:
        recovered = False
        for attempt in range(3):
            try:
                fallback = _download_close_batch([symbol], start=start, end=end)
                if not fallback.empty and fallback[symbol].notna().any():
                    prices[symbol] = fallback[symbol]
                    recovered = True
                    break
            except Exception as exc:
                if attempt == 2:
                    print(f"Warning: fallback download failed for {symbol}: {exc}")
                else:
                    time.sleep(1)
        if not recovered:
            print(f"Warning: no adjusted close history recovered for {symbol}.")

    prices = prices.sort_index().dropna(how="all")
    return prices.reindex(columns=ordered)


def compute_returns(prices: pd.DataFrame) -> pd.DataFrame:
    return prices.pct_change().fillna(0.0)


def calculate_metrics(returns: pd.Series, benchmark: pd.Series) -> dict[str, float]:
    aligned = pd.concat([returns.rename("strategy"), benchmark.rename("benchmark")], axis=1).dropna()
    strategy = aligned["strategy"]
    bench = aligned["benchmark"]

    total_return = float((1 + strategy).prod() - 1)
    bench_total_return = float((1 + bench).prod() - 1)
    years = max((aligned.index[-1] - aligned.index[0]).days / 365.25, 1 / 365.25)
    annual_return = float((1 + total_return) ** (1 / years) - 1)
    benchmark_annual_return = float((1 + bench_total_return) ** (1 / years) - 1)
    volatility = float(strategy.std(ddof=0) * np.sqrt(TRADING_DAYS_PER_YEAR))
    sharpe = float(annual_return / volatility) if volatility > 0 else np.nan
    equity = (1 + strategy).cumprod()
    drawdown = equity / equity.cummax() - 1
    benchmark_vol = float(bench.std(ddof=0) * np.sqrt(TRADING_DAYS_PER_YEAR))
    covariance = float(np.cov(strategy, bench, ddof=0)[0, 1]) if len(aligned) > 1 else np.nan
    benchmark_variance = float(np.var(bench, ddof=0)) if len(aligned) > 1 else np.nan
    beta = float(covariance / benchmark_variance) if benchmark_variance and benchmark_variance > 0 else np.nan
    var_95 = float(np.quantile(strategy, 0.05))

    return {
        "total_return": total_return,
        "annual_return": annual_return,
        "volatility": volatility,
        "sharpe": sharpe,
        "max_drawdown": float(drawdown.min()),
        "benchmark_total_return": bench_total_return,
        "benchmark_annual_return": benchmark_annual_return,
        "benchmark_volatility": benchmark_vol,
        "beta": beta,
        "daily_var_95": var_95,
        "return_minus_spy": total_return - bench_total_return,
        "annual_return_minus_spy": annual_return - benchmark_annual_return,
    }


def build_trend_weights(prices: pd.DataFrame, config: TrendConfig) -> pd.DataFrame:
    risky = list(config.risky_assets)
    relevant = prices[risky + [config.cash_asset]].copy()
    sma = relevant[risky].rolling(config.sma_window).mean()
    signal = (relevant[risky] > sma).astype(float)
    rebalance_signal = signal.resample(config.rebalance_frequency).last()
    weights = rebalance_signal.reindex(relevant.index).ffill().fillna(0.0)
    active = weights.sum(axis=1)
    weights = weights.div(active.replace(0, np.nan), axis=0).fillna(0.0)
    weights[config.cash_asset] = (active == 0).astype(float)
    return weights


def run_kalman_signal(
    close: pd.Series,
    trend_filter: pd.Series,
    config: KalmanConfig,
) -> pd.Series:
    clean = close.dropna()
    if clean.shape[0] < config.residual_window + 5:
        return pd.Series(0.0, index=close.index)

    filter_state = SingleStateKalmanFilter(
        process_variance=config.process_variance,
        estimated_measurement_variance=config.measurement_variance,
        posteri_estimate=float(clean.iloc[0]),
    )
    errors = np.zeros(len(clean), dtype=float)

    for idx, price in enumerate(clean.values.astype(float)):
        filter_state = filter_state.input_latest_measurement(price)
        errors[idx] = price - filter_state.posteri_estimate

    df = pd.DataFrame({"price": clean, "error": errors}, index=clean.index)
    df["error_std"] = df["error"].rolling(config.residual_window).std()
    df["z_score"] = np.where(df["error_std"] > 0, df["error"] / df["error_std"], 0.0)

    current_position = 0
    positions: list[float] = []
    for date, row in df.iterrows():
        allow_long = bool(trend_filter.reindex(df.index).fillna(False).loc[date])
        z_score = float(row["z_score"])
        if current_position == 0 and allow_long and z_score <= -config.entry_z:
            current_position = 1
        elif current_position == 1 and (z_score >= -config.exit_z or not allow_long):
            current_position = 0
        positions.append(float(current_position))

    return pd.Series(positions, index=df.index).reindex(close.index).ffill().fillna(0.0)


def build_kalman_weights(prices: pd.DataFrame, config: KalmanConfig) -> pd.DataFrame:
    trend_benchmark = prices[config.trend_benchmark]
    market_filter = (trend_benchmark > trend_benchmark.rolling(config.trend_window).mean()).fillna(False)

    weight_components: list[pd.Series] = []
    position_map: dict[str, pd.Series] = {}
    for symbol in config.universe:
        stock_trend = (prices[symbol] > prices[symbol].rolling(config.trend_window).mean()).fillna(False)
        trend_filter = market_filter & stock_trend
        position_map[symbol] = run_kalman_signal(prices[symbol], trend_filter, config)

    positions = pd.DataFrame(position_map).fillna(0.0)
    active = positions.sum(axis=1)
    weights = positions.div(active.replace(0, np.nan), axis=0).fillna(0.0)
    weights[config.cash_asset] = (active == 0).astype(float)
    return weights


def build_leader_weights(
    prices: pd.DataFrame,
    constituents: list[str],
    config: LeaderConfig,
) -> pd.DataFrame:
    benchmark = prices[config.benchmark_symbol]
    benchmark_filter = (benchmark > benchmark.rolling(config.trend_window).mean()).fillna(False)
    stock_trend = prices[constituents].gt(prices[constituents].rolling(config.trend_window).mean())
    momentum = prices[constituents].pct_change(config.momentum_lookback_days).shift(config.skip_recent_days)

    columns = constituents + [config.cash_asset]
    rebalance_weights = pd.DataFrame(0.0, index=prices.index, columns=columns)

    for rebalance_date in prices.resample(config.rebalance_frequency).last().index:
        idx = prices.index.searchsorted(rebalance_date, side="right") - 1
        if idx < 0:
            continue
        trade_date = prices.index[idx]
        if not bool(benchmark_filter.loc[trade_date]):
            rebalance_weights.loc[trade_date, config.cash_asset] = 1.0
            continue

        eligible = momentum.loc[trade_date].dropna()
        if config.require_stock_trend:
            trend_ok = stock_trend.loc[trade_date].reindex(eligible.index).fillna(False)
            eligible = eligible[trend_ok]

        if eligible.empty:
            rebalance_weights.loc[trade_date, config.cash_asset] = 1.0
            continue

        picks = eligible.nlargest(config.top_n).index.tolist()
        for symbol in picks:
            rebalance_weights.loc[trade_date, symbol] = 1.0 / config.top_n

    rebalance_weights = rebalance_weights[rebalance_weights.sum(axis=1) > 0]
    return rebalance_weights.reindex(prices.index).ffill().fillna(0.0)


def weights_to_returns(weights: pd.DataFrame, returns: pd.DataFrame) -> pd.Series:
    common = [column for column in weights.columns if column in returns.columns]
    shifted = weights[common].shift(1).fillna(0.0)
    return (shifted * returns[common]).sum(axis=1)


def combine_weight_frames(weight_frames: dict[str, pd.DataFrame], allocations: dict[str, float]) -> pd.DataFrame:
    all_columns: list[str] = []
    for frame in weight_frames.values():
        all_columns.extend(frame.columns.tolist())
    combined_columns = sorted(set(all_columns))
    combined_index = next(iter(weight_frames.values())).index

    combined = pd.DataFrame(0.0, index=combined_index, columns=combined_columns)
    for sleeve_name, frame in weight_frames.items():
        sleeve_weight = allocations[sleeve_name]
        aligned = frame.reindex(index=combined_index, columns=combined_columns).fillna(0.0)
        combined = combined.add(aligned * sleeve_weight, fill_value=0.0)
    return combined


def get_three_sleeve_tickers(
    leader_constituents: Iterable[str] | None = None,
    trend_config: TrendConfig = SELECTED_TREND_CONFIG,
    kalman_config: KalmanConfig = SELECTED_KALMAN_CONFIG,
    leader_config: LeaderConfig = SELECTED_LEADER_CONFIG,
) -> list[str]:
    tickers = set(trend_config.risky_assets)
    tickers.add(trend_config.cash_asset)
    tickers.update(kalman_config.universe)
    tickers.add(kalman_config.cash_asset)
    tickers.add(leader_config.benchmark_symbol)
    tickers.add(leader_config.cash_asset)
    if leader_constituents is not None:
        tickers.update(leader_constituents)
    return sorted(tickers)
