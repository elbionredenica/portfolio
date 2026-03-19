# %%
import os
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from dotenv import load_dotenv
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

# Load environment variables
load_dotenv(dotenv_path='../.env')
ALPACA_API_KEY = os.getenv("ALPACA_API_KEY")
ALPACA_API_SECRET = os.getenv("ALPACA_API_SECRET")

client = StockHistoricalDataClient(ALPACA_API_KEY, ALPACA_API_SECRET)

# Defining our Kalman Filter
class SingleStateKalmanFilter:
    def __init__(self, process_variance, estimated_measurement_variance):
        self.process_variance = process_variance
        self.estimated_measurement_variance = estimated_measurement_variance
        self.posteri_estimate = 0.0
        self.posteri_error_estimate = 1.0

    def input_latest_measurement(self, measurement):
        priori_estimate = self.posteri_estimate
        priori_error_estimate = self.posteri_error_estimate + self.process_variance
        blending_factor = priori_error_estimate / (priori_error_estimate + self.estimated_measurement_variance)
        self.posteri_estimate = priori_estimate + blending_factor * (measurement - priori_estimate)
        self.posteri_error_estimate = (1 - blending_factor) * priori_error_estimate
        return self.posteri_estimate

def enhanced_kalman_backtest(prices_series, process_variance=1e-5, measurement_variance=1e-3, z_threshold=1.5, window=20):
    if len(prices_series) < window + 5:
        return pd.Series(0, index=prices_series.index), np.zeros(len(prices_series))
        
    kf = SingleStateKalmanFilter(process_variance, measurement_variance)
    kalman_means = []
    errors = []
    
    kf.posteri_estimate = prices_series.iloc[0]
    for p in prices_series:
        k = kf.input_latest_measurement(p)
        kalman_means.append(k)
        errors.append(p - k)
        
    df = prices_series.to_frame(name='price')
    df['error'] = errors
    df['error_std'] = df['error'].rolling(window=window).std()
    df['z_score'] = (df['error'] / df['error_std']).fillna(0)
    
    # 1 for Long (Undervalued), -1 for Short (Overvalued)
    positions = np.zeros(len(df))
    z_scores = df['z_score'].values
    
    current_pos = 0
    for i in range(len(z_scores)):
        z = z_scores[i]
        if current_pos == 0:
            if z < -z_threshold:
                current_pos = 1
            elif z > z_threshold:
                current_pos = -1
        else:
            if current_pos == 1 and z >= 0:
                current_pos = 0
            elif current_pos == -1 and z <= 0:
                current_pos = 0
        positions[i] = current_pos
        
    df['position'] = positions
    df['returns'] = df['price'].pct_change().fillna(0)
    df['strat_returns'] = df['position'].shift(1) * df['returns']
    
    return df['strat_returns'].fillna(0), df['position'].values

# Metrics logic
def calculate_metrics(strat_returns, bench_returns):
    aligned = pd.concat([strat_returns.rename('strat'), bench_returns.rename('bench')], axis=1).fillna(0)
    strat = aligned['strat']
    bench = aligned['bench']
    
    total_ret = (1 + strat).prod() - 1
    cum_ret = (1 + strat).cumprod()
    peak = cum_ret.cummax()
    max_dd = ((cum_ret - peak) / peak).min()
    
    cov = np.cov(strat, bench)[0][1] if len(strat) > 1 else 0
    var = np.var(bench) if len(bench) > 1 else 0
    beta = cov / var if var != 0 else 0
    
    bench_ret = (1 + bench).prod() - 1
    alpha = total_ret - (beta * bench_ret)
    
    downside = strat[strat < 0]
    sortino = (strat.mean() / downside.std()) * np.sqrt(len(strat)) if not downside.empty and downside.std() != 0 else 0
    sharpe = (strat.mean() / strat.std()) * np.sqrt(len(strat)) if strat.std() != 0 else 0
    
    return total_ret * 100, max_dd * 100, sharpe, sortino, alpha * 100, beta, bench_ret * 100

# %%
# CONFIGURATION FOR LONG-TERM TESTS
# We test Top 5 highly liquid names to avoid hitting 5-year 5-min data rate limits.
# Included SPY strictly for the baseline Buy&Hold benchmark.
TEST_SYMBOLS = ["SPY", "QQQ", "AAPL", "MSFT", "NVDA", "AES"] 
YEARS_BACK = 3 # Can change to 1, 3, or 5
TEST_TIMEFRAMES = {
    "5Min": TimeFrame(5, TimeFrameUnit.Minute),
    "15Min": TimeFrame(15, TimeFrameUnit.Minute),
    "30Min": TimeFrame(30, TimeFrameUnit.Minute),
    "1Hour": TimeFrame(1, TimeFrameUnit.Hour),
}

end_dt = datetime.now()
start_dt = end_dt - timedelta(days=365 * YEARS_BACK)

print(f"Fetching {YEARS_BACK} Years of Data (${start_dt.strftime('%Y-%m-%d')} to {end_dt.strftime('%Y-%m-%d')})...")

results = []

for tf_name, timeframe in TEST_TIMEFRAMES.items():
    print(f"\n--- Testing Timeframe: {tf_name} ---")
    
    # 1. Fetch SPY Baseline data
    try:
        spy_req = StockBarsRequest(
            symbol_or_symbols="SPY",
            timeframe=timeframe,
            start=start_dt,
            end=end_dt
        )
        spy_bars = client.get_stock_bars(spy_req).df
        # Drop the symbol level from index mapping
        spy_bars = spy_bars.reset_index(level='symbol')
        spy_returns = spy_bars['close'].pct_change().dropna()
    except Exception as e:
        print(f"Failed to fetch SPY baseline for {tf_name}: {e}")
        continue
    
    # Run tests on symbols
    for symbol in TEST_SYMBOLS:
        print(f"Processing {symbol} ({tf_name})...")
        try:
            req = StockBarsRequest(
                symbol_or_symbols=symbol,
                timeframe=timeframe,
                start=start_dt,
                end=end_dt
            )
            bars = client.get_stock_bars(req).df
            if bars.empty:
                continue
                
            bars = bars.reset_index(level=0) # remove symbol from index
            price_series = bars['close']
            
            # Simple static parameters to test standard deviation threshold
            strat_ret, pos = enhanced_kalman_backtest(
                price_series, 
                process_variance=1e-5, 
                measurement_variance=0.01, # slightly higher for longer timeframe
                z_threshold=1.5, 
                window=20
            )
            
            total_ret, max_dd, sharpe, sortino, alpha, beta, bench_ret = calculate_metrics(strat_ret, spy_returns)
            
            # Check Buy and Hold purely on this stock
            bnh_ret = (price_series.iloc[-1] / price_series.iloc[0]) - 1
            
            results.append({
                "Symbol": symbol,
                "Timeframe": tf_name,
                "Strat Return (%)": round(total_ret, 2),
                "B&H Return (%)": round(bnh_ret * 100, 2),
                "SPY B&H (%)": round(bench_ret, 2),
                "Sharpe": round(sharpe, 2),
                "Max DD (%)": round(max_dd, 2),
                "Alpha vs SPY (%)": round(alpha, 2),
                "Beta": round(beta, 2),
                "Total Trades": int(np.sum(np.abs(np.diff(pos)))) // 2
            })
            
        except Exception as e:
            print(f"Error processing {symbol}: {e}")

# %%
# OUTPUT RESULTS
results_df = pd.DataFrame(results)

# Display comparisons
if not results_df.empty:
    print(f"\n======== {YEARS_BACK}-YEAR LONG-TERM COMPARISON RESULTS ========\n")
    print(results_df.to_string(index=False))
    
    # Save to CSV
    results_df.to_csv("longterm_multitf_benchmark.csv", index=False)
    print(f"\nSaved full {YEARS_BACK}-year comparisons to longterm_multitf_benchmark.csv")
else:
    print("\nNo results gathered. Check if data fetching worked.")

# %%