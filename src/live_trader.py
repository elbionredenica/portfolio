import time
import os
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, timezone

import alpaca.data as alpaca_data
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.enums import DataFeed
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce

# We load directly from env variables (GitHub Actions Secrets)
API_KEY = os.getenv('ALPACA_API_KEY')
API_SECRET = os.getenv('ALPACA_API_SECRET')

# Configuration - Relative to this file's directory
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CSV_PATH = os.path.join(BASE_DIR, '../research/mega_pipeline/top20_unique_equities_30_60_1y.csv')
TOTAL_CAPITAL = 75000.0  # Total strategy allocation
LOOKBACK_BARS = 60      # Number of recent 30-min bars to fetch to warm up Kalman

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

def calculate_current_state(close_prices: pd.Series, p_var: float, m_var: float, z_thresh: float, wd: int) -> int:
    """
    Runs the kalman math on historical prices and returns the latest target position:
     1  (Long)
    -1  (Short)
     0  (Flat)
    """
    if len(close_prices) < wd + 5:
        return 0

    kf = SingleStateKalmanFilter(p_var, m_var)
    kf.posteri_estimate = float(close_prices.iloc[0])

    errors = np.zeros(len(close_prices))
    for i, p in enumerate(close_prices.values):
        k = kf.input_latest_measurement(float(p))
        errors[i] = float(p) - k

    df_temp = pd.DataFrame({'price': close_prices.values, 'error': errors}, index=close_prices.index)
    df_temp['error_std'] = df_temp['error'].rolling(window=int(wd)).std()

    z_scores = np.zeros(len(df_temp))
    mask = df_temp['error_std'].values != 0
    z_scores[mask] = df_temp['error'].values[mask] / df_temp['error_std'].values[mask]

    # Replay state machine
    current_pos = 0
    for z in z_scores:
        if z > z_thresh and current_pos <= 0:
            current_pos = -1
        elif z < -z_thresh and current_pos >= 0:
            current_pos = 1
        elif current_pos == -1 and z < 0:
            current_pos = 0
        elif current_pos == 1 and z > 0:
            current_pos = 0

    return current_pos

def run_portfolio_cycle():
    print(f"\n[{datetime.now().isoformat()}] Waking up to process 30-min iteration.")
    
    # 1. Load configuration
    if not os.path.exists(CSV_PATH):
        print(f"Error: Strategy config CSV missing at {CSV_PATH}")
        return
        
    config_df = pd.read_csv(CSV_PATH)
    trading_client = TradingClient(API_KEY, API_SECRET, paper=True)
    data_client = StockHistoricalDataClient(API_KEY, API_SECRET)

    # Note: Only using regular market hours implies checking if market is open.
    clock = trading_client.get_clock()
    if not clock.is_open:
        print("Market is currently closed. Sleeping until next cycle.")
        return

    # 2. Re-evaluate each symbol
    now_utc = datetime.now(timezone.utc)
    
    # Snap end_dt to the most recent 30-minute boundary to protect against GitHub Action delays.
    # If the action triggers at 10:42, we only want data up to 10:30 to avoid an incomplete bar.
    minute_boundary = 30 if now_utc.minute >= 30 else 0
    end_dt = now_utc.replace(minute=minute_boundary, second=0, microsecond=0)
    
    # Give plenty of time to get ~60 30-min bars (60 bars * 30 min = 30 hours of trading time -> ~5 days)
    start_dt = end_dt - timedelta(days=10)

    # Cancel all pending orders first to clear stale state
    print("Canceling all open orders...")
    trading_client.cancel_orders()

    # Get current positions
    positions = {p.symbol: p for p in trading_client.get_all_positions()}

    for _, row in config_df.iterrows():
        sym = row['symbol']
        m_var = float(row['m_var'])
        z_thresh = float(row['z_thresh'])
        wd = int(row['window'])

        try:
            req = StockBarsRequest(
                symbol_or_symbols=sym,
                timeframe=TimeFrame(1, TimeFrameUnit.Minute),
                start=start_dt,
                end=end_dt,
                feed=DataFeed.IEX
            )
            bars = data_client.get_stock_bars(req).df
            
            if bars.empty:
                continue
                
            if isinstance(bars.index, pd.MultiIndex):
                bars = bars.reset_index(level='symbol', drop=True)
                
            # Construct 30-minute bars manually to match backtest logic exactly
            close_prices = bars['close'].resample('30min').last().dropna()
            
            if len(close_prices) < wd + 5:
                print(f"[{sym}] Not enough bars for window. Skipping.")
                continue

            # Run Math
            target_state = calculate_current_state(
                close_prices=close_prices,
                p_var=1e-5,
                m_var=m_var,
                z_thresh=z_thresh,
                wd=wd
            )

            # Execution logic
            current_qty = float(positions[sym].qty) if sym in positions else 0.0
            last_price = close_prices.iloc[-1]
            
            # Dollar amount per position (Paper Trading size)
            num_assets = len(config_df)
            slot_size_usd = TOTAL_CAPITAL / num_assets
            
            # Translate states dynamically (1 = long, -1 = short, 0 = flat)
            if target_state == 1:
                target_qty = int(slot_size_usd / last_price)
            elif target_state == -1:
                target_qty = -int(slot_size_usd / last_price)
            else:
                target_qty = 0

            # Delta needed
            qty_delta = target_qty - current_qty

            if qty_delta == 0:
                # No change needed
                continue
            
            print(f"[{sym}] Target State: {target_state} | Curr Qty: {current_qty} | Target Qty: {target_qty} | Delta: {qty_delta}")
            
            # Placing the order
            side = OrderSide.BUY if qty_delta > 0 else OrderSide.SELL
            qty = abs(qty_delta)
            
            order = MarketOrderRequest(
                symbol=sym,
                qty=qty,
                side=side,
                time_in_force=TimeInForce.DAY
            )
            trading_client.submit_order(order_data=order)
            print(f"[{sym}] -> Order Submitted: {side.name} {qty}")
            
        except Exception as e:
            print(f"[{sym}] Failed to process: {e}")

def main():
    if not API_KEY or not API_SECRET:
        print("Error: ALPACA_API_KEY and ALPACA_API_SECRET must be set via environment variables.")
        return

    print("Running Live Kalman Portfolio Trader...")
    
    df = pd.read_csv(CSV_PATH)
    num_assets = df.shape[0]
    slot_size = TOTAL_CAPITAL / num_assets
    print(f"Capital: ${TOTAL_CAPITAL}, assets: {num_assets}, approx ${slot_size:.2f} per asset.")
    
    # Run a single cycle - triggered by GitHub Actions
    run_portfolio_cycle()

if __name__ == "__main__":
    main()