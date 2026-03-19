import os
import pandas as pd
import glob
import matplotlib.pyplot as plt

RESULTS_DIR = "pipeline_results"
TOP_CONFIGS_OUT = "top20_global_configs_30_60_1y.csv"
TOP_UNIQUE_OUT = "top20_unique_equities_30_60_1y.csv"

def construct_and_chart_target_portfolio():
    print("Aggregating all symbol results...")
    csv_files = glob.glob(os.path.join(RESULTS_DIR, "*.csv"))
    
    if not csv_files:
        print(f"No CSVs found in {RESULTS_DIR}/. Run sp500_mega_pipeline.py first.")
        return
        
    all_data = []
    for f in csv_files:
        all_data.append(pd.read_csv(f))
        
    master_df = pd.concat(all_data, ignore_index=True)
    print(f"Loaded {len(master_df)} total backtest geometries.")
    
    # -----------------------------------------------------------------
    # STEP 1: Filter down to Global Top 20 
    # Excluding 1-Min, 5-Min, 15-Min to find viable swing trades
    # -----------------------------------------------------------------
    print("\nFiltering for the Top 20 Global Settings on 1-Year Horizon (30-Min & 60-Min ONLY)...")
    df_1y_high_tf = master_df[(master_df['lookback'] == '1Year') & (master_df['timeframe'].isin(['30Min', '60Min']))]
    
    # Sort by Sharpe Ratio (best parameter rows, duplicates allowed)
    ranked = df_1y_high_tf.sort_values(by='sharpe', ascending=False).copy()
    top_20_global = ranked.head(20)
    print("\n=== GLOBAL TOP 20 EQUITIES & PARAMETERS ===")
    print(top_20_global[['symbol', 'timeframe', 'sharpe', 'total_return', 'alpha', 'win_rate', 'total_trades']].to_string(index=False))

    # Pick a single best configuration per symbol, then keep top 20 symbols globally.
    best_per_symbol = ranked.drop_duplicates(subset=['symbol'], keep='first')
    top_20_unique = best_per_symbol.head(20).copy()

    print("\n=== TOP 20 UNIQUE EQUITIES (BEST CONFIG PER SYMBOL) ===")
    print(top_20_unique[['symbol', 'timeframe', 'm_var', 'z_thresh', 'window', 'sharpe', 'total_return', 'alpha', 'win_rate', 'total_trades']].to_string(index=False))

    top_20_global.to_csv(TOP_CONFIGS_OUT, index=False)
    top_20_unique.to_csv(TOP_UNIQUE_OUT, index=False)

    print(f"\nSaved: {TOP_CONFIGS_OUT}")
    print(f"Saved: {TOP_UNIQUE_OUT}")
    
    print("\nNext Phase: Using these exact 20 rows to pull their historical returns array, average them at every timestamp natively, and plot the master graph vs SPY.")
    print("(Use the unique-equity CSV for equal-weight trading across 20 distinct symbols.)")

if __name__ == '__main__':
    construct_and_chart_target_portfolio()