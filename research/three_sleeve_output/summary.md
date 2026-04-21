# Three-Sleeve Research Summary

## Final Chosen Configurations
- Trend sleeve: 200-day SMA on `SPY`, `TLT`, and `GLD`, monthly rebalance, cash parked in `BIL`.
- Kalman sleeve: liquid ETF pullback basket on `SPY, QQQ, IWM, XLF, XLK, XLE, XLI, XLV, TLT, GLD`, long-only, `entry_z=2.0`, `exit_z=0.25`, `window=10`, `measurement_variance=0.001`.
- Leader sleeve: top-1 current S&P 500 stock by 12-1 momentum, monthly rebalance, stock and market 200-day trend filter, cash in `BIL`.
- Combined weights: trend `50%`, Kalman `35%`, leader `15%`.

## Strategy Search Notes
- Trend search favored monthly rebalance over weekly rebalance on both return and Sharpe.
- Kalman search favored slower, cleaner pullback entries on the ETF universe; the stock-based daily variants were materially weaker versus SPY.
- Leader search showed that broader `top_n` portfolios had higher Sharpe, but the `top_n=1` version was intentionally retained as the high-conviction satellite sleeve.

## Does The Combined Portfolio Beat Buy-and-Hold SPY?
- Combined total return: 1096.18%
- SPY total return: 735.79%
- Difference: 360.39%
- Combined annual return: 16.46%
- SPY annual return: 13.92%

## Interpretation
- The trend sleeve is the stabilizer: slower, lower turnover, and historically resilient.
- The Kalman sleeve is a diversifier rather than the main engine of return once we force it into a realistic daily, long-only, trend-aware implementation.
- The leader sleeve drives most of the upside and most of the tail risk; this is why its allocation stays small.
- The combined portfolio improves on SPY over the shared sample while keeping a materially lower beta than a pure buy-and-hold equity portfolio.
