import os
from dataclasses import dataclass
from dotenv import load_dotenv
from alpaca.trading.client import TradingClient


@dataclass(frozen=True)
class AlpacaConfig:
    api_key: str
    api_secret: str
    paper: bool
    base_url: str


def _get_env_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def load_config() -> AlpacaConfig:
    load_dotenv()

    api_key = os.getenv("ALPACA_API_KEY", "").strip()
    api_secret = os.getenv("ALPACA_API_SECRET", "").strip()
    paper_value = os.getenv("ALPACA_PAPER")
    base_url_value = os.getenv("ALPACA_BASE_URL")
    paper = _get_env_bool(paper_value if paper_value and paper_value.strip() else None, default=True)
    base_url = (
        base_url_value.strip()
        if base_url_value and base_url_value.strip()
        else "https://paper-api.alpaca.markets"
    )

    missing = [name for name, value in {
        "ALPACA_API_KEY": api_key,
        "ALPACA_API_SECRET": api_secret,
    }.items() if not value]
    if missing:
        missing_list = ", ".join(missing)
        raise RuntimeError(
            f"Missing required environment variables: {missing_list}. "
            "Create a .env file (see .env.example)."
        )

    return AlpacaConfig(
        api_key=api_key,
        api_secret=api_secret,
        paper=paper,
        base_url=base_url,
    )


def get_trading_client() -> TradingClient:
    cfg = load_config()
    return TradingClient(
        api_key=cfg.api_key,
        secret_key=cfg.api_secret,
        paper=cfg.paper,
        url_override=cfg.base_url,
    )
