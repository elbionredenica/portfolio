import argparse
import os
from alpaca.common.exceptions import APIError
from config import get_trading_client
from orders import buy_market, sell_market


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Manual buy/sell via Alpaca paper trading.")
    parser.add_argument("--symbol", default=os.getenv("DEFAULT_SYMBOL", "AAPL"))
    parser.add_argument("--side", choices=["buy", "sell"], required=True)
    parser.add_argument("--qty", type=int, default=int(os.getenv("DEFAULT_QTY", "1")))
    parser.add_argument("--force", action="store_true", help="Skip position checks.")
    parser.add_argument("--debug", action="store_true", help="Print account and positions info.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    client = get_trading_client()

    symbol = args.symbol.upper().strip()
    qty = args.qty

    if qty <= 0:
        raise ValueError("Quantity must be a positive integer.")

    if args.debug:
        account = client.get_account()
        positions = client.get_all_positions()
        print(
            "DEBUG account:",
            f"id={account.id}",
            f"status={account.status}",
            f"trading_blocked={account.trading_blocked}",
            f"buying_power={account.buying_power}",
            f"cash={account.cash}",
        )
        if positions:
            print("DEBUG positions:")
            for pos in positions:
                print(f" - {pos.symbol} qty={pos.qty} market_value={pos.market_value}")
        else:
            print("DEBUG positions: none")

    if not args.force:
        try:
            position = client.get_open_position(symbol)
            if args.side == "buy":
                print(f"Already holding {position.qty} shares of {symbol}. Use --force to buy anyway.")
                return
        except APIError:
            # No position exists; that's expected for a buy.
            position = None

        if args.side == "sell" and position is None:
            print(f"No open position for {symbol}. Use --force to sell anyway.")
            return

    if args.side == "buy":
        order_id = buy_market(client, symbol, qty)
        print(f"Submitted BUY order: {symbol} x{qty} (order_id={order_id})")
    else:
        order_id = sell_market(client, symbol, qty)
        print(f"Submitted SELL order: {symbol} x{qty} (order_id={order_id})")


if __name__ == "__main__":
    main()
