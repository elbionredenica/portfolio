# Kalman Filter Mean Reversion

## Hypothesis
Single-asset mean reversion is a classic strategy but typically fails due to static parameters (like strict moving average lookback window). 
Using a **1-Dimensional Kalman Filter**, we can recursively infer the true underlying "hidden state" (the unobserved mean of the asset) amidst the "measurement noise" (market volatility). 

If the current market price aggressively jumps away from the Kalman filter's predicted state beyond a calculated Z-score, we expect it to revert back to the mean.

## Strategy Logic
1. Initial state estimation.
2. Continually update the predicted state and the state uncertainty at each time step (using a specified transition covariance/process noise relative to observation noise).
3. Compute the Error/Residual (Actual Price - Predicted Kalman Mean).
4. Compute the standard deviation of this error dynamically.
5. If Error > Threshold * StdDev: **Short the asset** (it's overvalued relative to dynamic mean).
6. If Error < -Threshold * StdDev: **Long the asset** (it's undervalued relative to dynamic mean).
7. Exit when Error reverts to 0.

## Parameters to Optimize
*   **Measurement Noise / Observation Covariance (R):** How much do we trust the current data price? High noise means we rely more on the model (slower adjusting mean).
*   **Process Noise / Transition Covariance (Q):** How fast do we assume the true mean can drift over time? High process noise means the mean will track the actual price very quickly.
*   **Entry Z-Score (Threshold):** How far extended must it be before entering a trade?

## Engineering Next Steps
1. Run historical backtests on top SPY stocks (AAPL, MSFT, VOO, etc.) using minute/hour data to gauge profitability.
2. If intraday (HFT-lite) frequencies are optimal, transition from REST API execution to **Alpaca WebSockets** to stream real-time price ticks and update the model state efficiently.
