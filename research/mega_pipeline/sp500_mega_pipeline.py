import os
import time
import requests
import io
import itertools
import warnings
import numpy as np
import pandas as pd
from tqdm import tqdm
from datetime import datetime, timedelta
import concurrent.futures
import multiprocessing
from dotenv import load_dotenv

# Alpaca imports
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

warnings.filterwarnings('ignore')

# -------------------------------------------------------------
# 0. Global Setup & Auth
# -------------------------------------------------------------
load_dotenv('../../.env')
API_KEY = os.getenv('ALPACA_API_KEY')
API_SECRET = os.getenv('ALPACA_API_SECRET')
client = StockHistoricalDataClient(API_KEY, API_SECRET)

RESULTS_DIR = "pipeline_results"
os.makedirs(RESULTS_DIR, exist_ok=True)

# -------------------------------------------------------------
# 1. Kalman Filter Engine
# -------------------------------------------------------------
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

def calculate_metrics(strat_returns, bench_returns):
    aligned = pd.concat([strat_returns.rename('strat'), bench_returns.rename('bench')], axis=1).fillna(0)
    strat = aligned['strat']
    bench = aligned['bench']
    
    total_ret = (1 + strat).prod() - 1
    cum_ret = (1 + strat).cumprod()
    
    peak = cum_ret.cummax()
    drawdown = (cum_ret - peak) / peak
    max_dd = drawdown.min()
    
    cov = np.cov(strat, bench)[0][1] if len(strat) > 1 else 0
    var = np.var(bench) if len(bench) > 1 else 0
    beta = cov / var if var != 0 else 0
    
    bench_ret = (1 + bench).prod() - 1
    alpha = total_ret - (beta * bench_ret)
    
    sharpe = (strat.mean() / strat.std()) * np.sqrt(len(strat)) if strat.std() != 0 else 0
    
    downside_returns = strat[strat < 0]
    sortino = (strat.mean() / downside_returns.std()) * np.sqrt(len(strat)) if len(downside_returns) > 0 and downside_returns.std() != 0 else 0
    
    active_trades = strat[strat != 0]
    win_rate = len(active_trades[active_trades > 0]) / len(active_trades) if len(active_trades) > 0 else 0
    
    return {
        'total_return': total_ret,
        'max_drawdown': max_dd,
        'beta': beta,
        'alpha': alpha,
        'sharpe': sharpe,
        'sortino': sortino,
        'win_rate': win_rate,
        'total_trades': len(active_trades) // 2
    }

def run_kalman_iteration(df, p_var, m_var, z_thresh, wd):
    """Core logic mapped to a single pandas dataframe."""
    kf = SingleStateKalmanFilter(p_var, m_var)
    kf.posteri_estimate = df.iloc[0]
    
    errors = np.zeros(len(df))
    for i, p in enumerate(df.values):
        k = kf.input_latest_measurement(p)
        errors[i] = p - k
        
    df_temp = pd.DataFrame({'price': df.values, 'error': errors}, index=df.index)
    df_temp['error_std'] = df_temp['error'].rolling(window=wd).std()
    
    # Safe divide
    z_scores = np.zeros(len(df_temp))
    mask = df_temp['error_std'].values != 0
    z_scores[mask] = df_temp['error'].values[mask] / df_temp['error_std'].values[mask]
    
    positions = np.zeros(len(df_temp))
    current_pos = 0
    for i in range(len(z_scores)):
        z = z_scores[i]
        if z > z_thresh and current_pos <= 0:
            current_pos = -1 
        elif z < -z_thresh and current_pos >= 0:
            current_pos = 1  
        elif current_pos == -1 and z < 0:
            current_pos = 0  
        elif current_pos == 1 and z > 0:
            current_pos = 0  
        positions[i] = current_pos
        
    df_temp['position'] = pd.Series(positions).shift(1).fillna(0).values
    df_temp['returns'] = df_temp['position'] * df_temp['price'].pct_change().fillna(0)
    return df_temp['returns']

# -------------------------------------------------------------
# 2. Fetching Engine (Robust 1-yr chunking)
# -------------------------------------------------------------
def fetch_1y_1min_data(symbol):
    """
    Fetches 1 year of 1-min data. 
    Chunks into smaller segments to respect payload limits.
    """
    end_dt = datetime.now()
    start_dt = end_dt - timedelta(days=365)
    
    chunks = []
    current_start = start_dt
    
    # Fetch year by year (just 1 iteration now)
    for _ in range(1):
        current_end = current_start + timedelta(days=365)
        if current_end > end_dt:
            current_end = end_dt
            
        req = StockBarsRequest(
            symbol_or_symbols=symbol,
            timeframe=TimeFrame.Minute,
            start=current_start,
            end=current_end
        )
        try:
            bars = client.get_stock_bars(req).df
            if not bars.empty:
                bars = bars.reset_index(level='symbol')
                chunks.append(bars['close'])
        except Exception as e:
            # Most common error: Symbol didn't exist back then or is fully missing
            if 'not found' not in str(e).lower():
                time.sleep(1) # Backoff for rate limits
        
        current_start = current_end
        time.sleep(0.1) # Small sleep to respect 200 API req / min
        
    if not chunks:
        return pd.Series(dtype=float)
        
    return pd.concat(chunks).sort_index()

# -------------------------------------------------------------
# 3. SPY Baseline Loading
# -------------------------------------------------------------
if __name__ == '__main__':
    print("Pre-loading 1 Year of SPY Benchmark data...")
    spy_1m = fetch_1y_1min_data("SPY")

# -------------------------------------------------------------
# 4. Mega Pipeline Worker
# -------------------------------------------------------------
def process_symbol(args):
    symbol, spy_1m_data = args
    out_file = os.path.join(RESULTS_DIR, f"{symbol}_grid_results.csv")
    if os.path.exists(out_file):
        return  # Skip if already done
        
    print(f"[{symbol}] Fetching 1Y data...")
    raw_1m = fetch_1y_1min_data(symbol)
    if raw_1m.empty or len(raw_1m) < 1000:
        print(f"[{symbol}] Insufficient data. Skipping.")
        return
        
    # Slicing datasets (1mo, 6mo, 1y)
    end_dt = raw_1m.index[-1]
    datasets = {
        '1Month': raw_1m.loc[end_dt - timedelta(days=30):],
        '6Month': raw_1m.loc[end_dt - timedelta(days=180):],
        '1Year': raw_1m
    }
    
    timeframes = {
        '1Min': '1min',
        '5Min': '5min',
        '15Min': '15min',
        '30Min': '30min',
        '60Min': '60min'
    }
    
    # Params Grid
    p_var = 1e-5
    m_vars = [1e-3, 1e-2, 1e-1]
    z_thresholds = [1.0, 1.5, 2.0]
    windows = [10, 20, 30]
    grid = list(itertools.product(m_vars, z_thresholds, windows))
    
    symbol_results = []
    
    for lookback_name, data in datasets.items():
        if len(data) < 500: continue # Skip if standard data is missing
            
        for tf_name, tf_rule in timeframes.items():
            print(f"[{symbol}] Evaluating {lookback_name} | {tf_name} ...")
            # Resample asset
            res_close = data.resample(tf_rule).last().dropna()
            
            # Resample corresponding SPY benchmark exactly
            spy_slice = spy_1m_data.loc[data.index[0]:data.index[-1]]
            res_spy = spy_slice.resample(tf_rule).last().dropna().pct_change().dropna()
            
            # Align indices 
            common_idx = res_close.index.intersection(res_spy.index)
            if len(common_idx) < 100: continue
            res_close = res_close.loc[common_idx]
            res_spy = res_spy.loc[common_idx]
            
            # Run parameter grid
            for m_var, z_thresh, wd in grid:
                strat_rets = run_kalman_iteration(res_close, p_var, m_var, z_thresh, wd)
                metrics = calculate_metrics(strat_rets, res_spy)
                
                # Check Buy & Hold baseline
                bnh_ret = (res_close.iloc[-1] / res_close.iloc[0]) - 1
                
                if metrics['total_return'] != 0:
                    symbol_results.append({
                        'symbol': symbol,
                        'lookback': lookback_name,
                        'timeframe': tf_name,
                        'm_var': m_var,
                        'z_thresh': z_thresh,
                        'window': wd,
                        'total_return': metrics['total_return'],
                        'buy_and_hold_return': bnh_ret,
                        'sharpe': metrics['sharpe'],
                        'sortino': metrics['sortino'],
                        'alpha': metrics['alpha'],
                        'beta': metrics['beta'],
                        'max_drawdown': metrics['max_drawdown'],
                        'win_rate': metrics['win_rate'],
                        'total_trades': metrics['total_trades']
                    })
                    
    if symbol_results:
        # Save exact findings for this symbol so we don't lose memory if the script crashes
        df_res = pd.DataFrame(symbol_results)
        df_res.to_csv(out_file, index=False)
        print(f"[{symbol}] Saved {len(df_res)} configurations.")

# -------------------------------------------------------------
# 5. Main Execution
# -------------------------------------------------------------
if __name__ == '__main__':
    print("Scraping S&P 500 constituents...")
    url = 'https://en.wikipedia.org/wiki/List_of_S%26P_500_companies'
    headers = {'User-Agent': 'Mozilla/5.0'}
    response = requests.get(url, headers=headers)
    sp500_table = pd.read_html(io.StringIO(response.text))[0]
    tickers = sp500_table['Symbol'].str.replace('.', '-', regex=False).tolist()
    
    print(f"Starting Mega-Pipeline for {len(tickers)} symbols...")
    print("This runs locally on every param combination across 5 timeframes and 3 lookback periods (1M, 6M, 1Y).")
    print("Results are saved symbol-by-symbol to the 'pipeline_results/' folder.")
    
    # Parallelizing at the symbol level.
    # By using ProcessPoolExecutor, we use all CPU cores. 
    # Max API concurrency is kept reasonable.
    max_workers = min(multiprocessing.cpu_count() - 1, 8) 
    
    tasks = [(sym, spy_1m) for sym in tickers]
    
    with concurrent.futures.ProcessPoolExecutor(max_workers=max_workers) as executor:
        # Wrap in TQDM for progress tracking
        list(tqdm(executor.map(process_symbol, tasks), total=len(tasks)))
        
    print("\n\n===== MEGA-PIPELINE FINISHED =====")
    print("Run the next script to aggregate these results, find the Top 20, and construct the final portfolio!")