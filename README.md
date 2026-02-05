# Alpaca Paper Trading Bot (Manual Buy/Sell)

Minimal structure for a paper-trading bot using Alpaca. This version is manual-only: you run a command to buy or sell a symbol.

## Setup

1. Create an Alpaca account and enable **Paper Trading**.
2. Generate API keys from the Alpaca dashboard.
3. Copy `.env.example` to `.env` and fill in your keys.

```bash
cp .env.example .env
```

4. Create a virtual environment and install dependencies.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Manual Trade Examples

```bash
python src/trade.py --side buy --symbol AAPL --qty 1
python src/trade.py --side sell --symbol AAPL --qty 1
```

Use `--force` to skip position checks.

## GitHub Actions (Optional)

A workflow is included to run on a schedule. You can edit the cron times in `.github/workflows/alpaca-paper.yml`.

Set these repository secrets in GitHub:
- `ALPACA_API_KEY`
- `ALPACA_API_SECRET`
- `ALPACA_PAPER` (e.g., `true`)
- `ALPACA_BASE_URL` (e.g., `https://paper-api.alpaca.markets`)
