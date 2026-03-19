# S&P 500 Kalman Filter Mean Reversion Backtest Report

## 1. Executive Summary
This report summarizes the performance of a High-Frequency (1-Minute and 5-Minute) Statistical Arbitrage strategy based on a 1D Kalman Filter applied to the S&P 500 universe. The strategy aims to capture short-term mean-reverting price action. The backtest was conducted over a **14-day trailing period** of intraday data, sourced from Alpaca. An equal-weighted portfolio was constructed using the top 15 performing stocks based on risk-adjusted returns (Sharpe Ratio).

While individual theoretical outputs appear very high (Sharpe > 5.0, high annualized returns), these results require critical interpretation. High-Frequency Mean Reversion strategies in raw equities heavily suffer from transaction costs, bid-ask spread friction, and execution latency, which are not fully penalized in this idealized backtest.

## 2. Methodology & Parameters
The strategy uses a robust grid-search optimization pipeline:
- **Universe:** S&P 500 Constituents (Scraped dynamically from Wikipedia).
- **Timeframes Tested:** 1-Minute and 5-Minute bars.
- **Data Range:** 14 Calendar Days.
- **Core Engine:** 1D Kalman Filter used as a dynamic, adaptive moving average to track the 'hidden' true price.
- **Trading Logic:**
  - **Process Variance ($Q$):** Fixed at `1e-5` to assume a slowly changing true state.
  - **Measurement Variance ($R$):** Optimized grid `[0.001, 0.01, 0.1, 1.0]`. Controls how much noise vs signal the filter perceives.
  - **Z-Score Threshold:** Optimized grid `[1.0, 1.5, 2.0, 2.5]`. Standard deviations from the Kalman mean required to trigger a trade.
  - **Rolling Window:** Optimized grid `[10, 20, 30]`. Used to calculate the standard deviation for the Z-score.
  - **Entry/Exit:** Enter Long/Short when Z-score exceeds the threshold. Exit when price reverts to the Kalman mean.

## 3. Optimization Results: The Top 15 Equities
The optimization pipeline evaluated thousands of parameter combinations across the ~500 stocks. The top 15 results, ranked by Sharpe Ratio, predominantly favored the **1-Minute** timeframe, highlighting the ultra-short-term nature of the mean-reversion signal.

| Symbol | Timeframe | Sharpe | Sortino | Total Return (%) | Max Drawdown (%) | Win Rate | Opt R | Opt Z | Opt Window |
|--------|-----------|--------|---------|------------------|------------------|----------|-------|-------|------------|
| AES    | 1Min      | 12.08  | 6.15    | 35.90            | -0.63            | 72.39%   | 0.001 | 1.0   | 10         |
| NKE    | 1Min      | 7.36   | 8.57    | 62.99            | -2.14            | 54.10%   | 0.001 | 1.0   | 20         |
| NOW    | 1Min      | 6.38   | 6.29    | 100.93           | -6.24            | 53.84%   | 0.001 | 1.0   | 10         |
| AAPL   | 1Min      | 6.37   | 6.45    | 36.89            | -1.72            | 53.92%   | 0.001 | 1.0   | 10         |
| MSFT   | 1Min      | 5.84   | 6.19    | 35.21            | -2.81            | 53.90%   | 0.001 | 1.0   | 10         |
| NFLX   | 1Min      | 5.46   | 5.18    | 42.49            | -2.38            | 54.48%   | 0.001 | 1.0   | 20         |
| PANW   | 1Min      | 5.45   | 4.58    | 49.58            | -2.18            | 54.42%   | 0.001 | 2.0   | 10         |
| WMT    | 1Min      | 5.28   | 4.59    | 28.46            | -2.60            | 53.03%   | 0.001 | 1.5   | 20         |
| DVN    | 1Min      | 5.27   | 4.68    | 55.74            | -2.47            | 53.79%   | 0.001 | 1.0   | 10         |
| AMZN   | 1Min      | 5.24   | 5.20    | 40.19            | -2.25            | 53.67%   | 0.001 | 1.0   | 10         |
| UNH    | 1Min      | 5.19   | 4.77    | 32.09            | -3.23            | 54.10%   | 0.001 | 1.5   | 20         |
| PSKY   | 1Min      | 5.15   | 4.67    | 82.74            | -6.44            | 53.66%   | 0.001 | 1.0   | 10         |
| PYPL   | 1Min      | 5.12   | 4.06    | 56.60            | -2.67            | 54.03%   | 0.001 | 1.0   | 20         |
| SMCI   | 1Min      | 5.06   | 5.01    | 78.51            | -5.60            | 53.13%   | 0.001 | 1.0   | 10         |
| F      | 1Min      | 5.06   | 4.79    | 43.58            | -3.12            | 54.89%   | 0.001 | 1.0   | 10         |

*Note: Returns are over the 14-day sample period. Win rates hover marginally above 50% (avg ~54%).*

### Top 15 Equal-Weighted Portfolio Performance
When combined into an equal-weighted portfolio, the strategy achieved:
- **Cumulative Return (14 days):** ~54.8%
- **Portfolio Sharpe Ratio:** ~14.99
- **Portfolio Beta vs SPY:** Near zero ($\beta \approx 0.05$), indicating high market neutrality.
- **Portfolio Alpha:** ~54.8%

## 4. Interpretation & "Why these results might be misleading"

You noted that "the results are not that bet right?", which is an extremely astute quantitative observation. Although the Sharpe Ratios and Returns in the table above look incredible (Sharpe > 5.0 is essentially a money printer), **they are almost certainly illusory in a live trading environment** for the following reasons:

1. **Transaction Costs & Slippage:** The backtest assumes execution at the exact close price of the minute bar. In reality, HFT mean reversion requires crossing the bid-ask spread frequently. A 54% win rate with small profit margins per trade will likely be entirely consumed by spread costs, SEC fees, and routing fees.
2. **Execution Latency:** Mean reversion signals at the 1-minute level are fought over by sophisticated market makers. By the time our retail Python algorithm processes the tick and sends an order via the Alpaca REST/WebSocket API, the "reversion" has likely already occurred, resulting in immediate slippage.
3. **Overfitting (Curve Fitting):** We grid-searched thousands of parameter combinations and filtered for the top 15. It is highly probable that the specific `R=0.001`, `Z=1.0`, `Window=10` parameters simply perfectly fit the noise profile of the last 14 days rather than representing a durable, forward-looking edge.
4. **Volume Constraints:** Some stocks might not have sufficient liquidity precisely when the Kalman filter fires.
5. **Maker vs. Taker:** Retail accounts are almost always "liquidity takers" crossing the spread. Institutional HFTs act as "liquidity makers" and capture the spread, getting paid to execute these exact same trades.

## 5. Next Steps
To move this towards live trading in `src/trade.py`, we must:
1. **Implement Realistic Slippage:** Add a 1-2 bps cost per trade in the backtest to see if the edge survives.
2. **Move to Higher Timeframes:** The 1-minute edge is crowded. Shifting to 5-Minute or 15-Minute data reduces the impact of bid-ask spread friction.
3. **Out-of-Sample Testing:** We need to test the optimized parameters (`R=0.001, Z=1.0, W=10`) on a entirely different 14-day period to prove it wasn't just curve-fitted.
4. **WebSocket Integration:** Begin scaffolding `src/trade.py` using Alpaca's `StockDataStream` to ingest real-time ticks and process them through the Kalman state updates without relying on heavy historical batch downloads.
