# High-Frequency Kalman Filter Pipeline Review

## Process Overview
To rigorously evaluate a Single-State Kalman Filter Mean Reversion strategy across the entire stock market, we built a highly parallelized "Mega Pipeline" brute-forcing the entire S&P 500 universe (~503 tickers).

**The Pipeline executed:**
- **Data Extracted:** Last 1 Year of 1-Minute Trade Data from Alpaca for all 503 S&P Constituents.
- **Constraints Tested:** 3 Lookback Regimes (1-Month, 6-Month, 1-Year).
- **Timeframes Evaluated:** 1-Min, 5-Min, 15-Min, 30-Min, and 60-Min arrays.
- **Parameters Tested:** Grid-search permutations of Measurement Variances (`1e-3`, `1e-2`, `1e-1`), Z-scores (`1.0, 1.5, 2.0`), and Rolling Windows (`10, 20, 30`).
- **Scale:** Analyzed over **163,215** distinct backtest geometries natively against the S&P 500 baseline using a multiprocessing engine.

**Execution Details:**
- **Time to Completion:** The multiprocessing loop took approximately **3 Hours and 52 Minutes** to calculate against 163,215 parameter arrays.
- **Output:** Extracted into hundreds of CSV files inside `research/mega_pipeline/pipeline_results`.

## Results & Analysis
The `portfolio_constructor.py` script aggregated the global results and filtered for the absolute **Global Top 20 Configurations** ordered by Sharpe Ratio out of the 163,215 tested loops.

### The Top Outputs (1-Year Lookback)
*All dominant strategies gravitated back to the 1-Minute timeframe.*

| Symbol | Sharpe Ratio | Total Return (1Yr) | Win Rate | Total Trades |
|--------|--------------|--------------------|----------|--------------|
| WBD    | 15.41        | 2,949%             | 52.5%    | 36,885       |
| CSCO   | 14.58        | 56.0%              | 50.8%    | 36,841       |
| KHC    | 14.29        | 47.3%              | 51.5%    | 33,783       |
| PCG    | 14.14        | 120.6%             | 51.7%    | 26,850       |
| HAL    | 13.74        | 446.4%             | 51.2%    | 33,235       |
| WMT    | 13.64        | 32.7%              | 51.1%    | 44,190       |

## Final Verdict: "Does it make sense to go with this kind of trading?"

No, not in its current state as a retail algorithmic trader. Here is the quantitative breakdown of why these results, while mathematically accurate to the data, are **synthetic traps**:

### 1. The Win Rate vs. Trade Volume Paradox
Look at the `Total Trades` column. CSCO executed **36,841 trades** in a single year across a 1-Minute chart. That is roughly **150 trades per day**.

Now look at the `Win Rate`. CSCO's optimal win rate was **50.8%**. You are making millions of tiny, sub-penny profit flips where you only win 50.8% of the time. 

### 2. Transaction Friction (The Maker/Taker Problem)
This backtest assumes you get filled at exactly the close price of the minute candle with zero commissions. In reality, to execute a mean-reverting trade aggressively 150 times a day, you have to cross the Bid/Ask spread (you pay the "Taker" fee). 
If the bid-ask spread on CSCO is just \$0.01:
- You pay \$0.01 per share to enter.
- You pay \$0.01 per share to exit.
- `36,841 trades * $0.02 slip = catastrophic total capital loss.`

A 50.8% win rate strategy at 1-minute frequencies is highly profitable for **Market Makers** (because *they* capture the spread and get paid rebates by the exchange). For retail traders who *cross* the spread via an API like Alpaca, it translates to bleeding capital by death-from-a-thousand-cuts.

### 3. Execution Latency
By the time the Alpaca WebSocket tells your Python `trade.py` script that WBD hit a Z-score of 2.0, the algorithmic HFT funds in New Jersey have already executed the trade and arbed away the differential. You will suffer negative slippage.

### Pivot Update: 30-Min / 60-Min Only

We re-ran portfolio construction with a strict filter to 1-year horizon and only `30Min` / `60Min` regimes. This is a deliberate shift away from microstructure-sensitive 1-minute behavior.

Observed top-ranked rows were still concentrated in a few symbols (e.g., repeated `KMI`, `DOC`, `EXC`) because the global ranking was selecting **parameter rows**, not unique assets.

To align with live deployment intent (trade a basket of 20 names), the constructor now exports two artifacts:

1. `top20_global_configs_30_60_1y.csv`: best 20 parameter rows globally (duplicates allowed).
2. `top20_unique_equities_30_60_1y.csv`: best single config per symbol, then top 20 symbols by Sharpe.

This removes duplicate-symbol concentration risk and produces a true 20-asset candidate portfolio for equal-weight reconstruction.

### Deployment Guidance

1. Build the portfolio from `top20_unique_equities_30_60_1y.csv`.
2. Reconstruct each selected strategy return path from raw prices using its exact parameters (`m_var`, `z_thresh`, `window`, `timeframe`).
3. Equal-weight across the 20 strategy return series at each timestamp and compare to resampled SPY baseline.

*Recommendation for `trade.py`: default to high-timeframe (30-minute / 60-minute) execution and enforce one active configuration per symbol to avoid hidden over-concentration.*