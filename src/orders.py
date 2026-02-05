from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce


def buy_market(client: TradingClient, symbol: str, qty: int) -> str:
    order = MarketOrderRequest(
        symbol=symbol,
        qty=qty,
        side=OrderSide.BUY,
        time_in_force=TimeInForce.DAY,
    )
    submitted = client.submit_order(order_data=order)
    return submitted.id


def sell_market(client: TradingClient, symbol: str, qty: int) -> str:
    order = MarketOrderRequest(
        symbol=symbol,
        qty=qty,
        side=OrderSide.SELL,
        time_in_force=TimeInForce.DAY,
    )
    submitted = client.submit_order(order_data=order)
    return submitted.id
