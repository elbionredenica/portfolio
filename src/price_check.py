import os
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockLatestQuoteRequest
from config import load_config


def main() -> None:
    cfg = load_config()
    symbol = os.getenv("DEFAULT_SYMBOL", "VOO").upper().strip()

    data_client = StockHistoricalDataClient(cfg.api_key, cfg.api_secret)
    request = StockLatestQuoteRequest(symbol_or_symbols=[symbol])
    quotes = data_client.get_stock_latest_quote(request)

    if symbol not in quotes:
        raise RuntimeError(f"No quote returned for {symbol}.")

    quote = quotes[symbol]
    print(
        f"Latest quote for {symbol}: bid={quote.bid_price} ask={quote.ask_price} "
        f"bid_size={quote.bid_size} ask_size={quote.ask_size} timestamp={quote.timestamp}"
    )


if __name__ == "__main__":
    main()
