import requests

TELEGRAM_API_URL = "https://api.telegram.org/bot{token}/sendMessage"


def send_message(bot_token: str, chat_id: str, text: str, session: requests.Session | None = None) -> None:
    session = session or requests.Session()
    url = TELEGRAM_API_URL.format(token=bot_token)
    resp = session.post(url, data={"chat_id": chat_id, "text": text}, timeout=10)
    resp.raise_for_status()


def format_trade_alert(
    question: str, direction: str, size_usd: float, confidence: float,
    equity_usd: float, floor_usd: float, ceiling_usd: float,
) -> str:
    return (
        f"TRADE: {direction.upper()} on \"{question}\"\n"
        f"Size: ${size_usd:.2f} | Confidence: {confidence:.0%}\n"
        f"Equity: ${equity_usd:.2f} (floor ${floor_usd:.0f} / ceiling ${ceiling_usd:.0f})"
    )


def format_error_alert(error_count: int, last_error: str) -> str:
    return f"Bot hit {error_count} consecutive errors. Last: {last_error}"
