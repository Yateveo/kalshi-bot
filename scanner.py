import time
from dataclasses import dataclass

import requests

KALSHI_MARKETS_URL = "https://external-api.kalshi.com/trade-api/v2/markets"
KALSHI_TRADES_URL = "https://external-api.kalshi.com/trade-api/v2/markets/trades"

TICKER_BATCH_SIZE = 50  # keep query strings comfortably under URL length limits


@dataclass
class Market:
    market_id: str
    question: str
    yes_price: float
    volume_24h: float
    price_reference: float
    resolution_criteria: str


def _mid_price(bid: float, ask: float) -> float:
    """Bid/ask midpoint, or 0.0 if either side has no quote yet."""
    if bid > 0 and ask > 0:
        return (bid + ask) / 2
    return 0.0


def _chunk(items: list, size: int) -> list[list]:
    return [items[i:i + size] for i in range(0, len(items), size)]


def _earliest_trade_prices(trades: list[dict]) -> dict[str, float]:
    """For each ticker, the price of its earliest trade in the given list."""
    earliest: dict[str, tuple[str, float]] = {}
    for t in trades:
        ticker = t["ticker"]
        ts = t["created_time"]
        price = float(t["yes_price_dollars"])
        if ticker not in earliest or ts < earliest[ticker][0]:
            earliest[ticker] = (ts, price)
    return {ticker: price for ticker, (_, price) in earliest.items()}


def _fetch_recent_trade_reference_prices(session: requests.Session, lookback_seconds: int = 3600) -> dict[str, float]:
    """Earliest known trade price per ticker within the lookback window.

    This also defines which tickers are worth scanning at all: Kalshi lists
    thousands of open markets, most with no recent activity, and a single
    unsorted page of them rarely overlaps with the ones actually trading.
    Starting from real trade prints instead gives both a live universe of
    active tickers and a real momentum reference in one call (Kalshi's
    previous_price_dollars field is not reliably populated, even for
    actively-traded markets -- observed empty across the board).
    """
    min_ts = int(time.time()) - lookback_seconds
    resp = session.get(KALSHI_TRADES_URL, params={"min_ts": min_ts, "limit": 1000}, timeout=10)
    resp.raise_for_status()
    return _earliest_trade_prices(resp.json()["trades"])


def fetch_open_markets(session: requests.Session | None = None) -> list[Market]:
    session = session or requests.Session()

    reference_prices = _fetch_recent_trade_reference_prices(session)
    if not reference_prices:
        return []

    tickers = list(reference_prices.keys())
    markets = []
    for batch in _chunk(tickers, TICKER_BATCH_SIZE):
        resp = session.get(
            KALSHI_MARKETS_URL,
            params={"tickers": ",".join(batch), "status": "open", "mve_filter": "exclude"},
            timeout=10,
        )
        resp.raise_for_status()
        for m in resp.json()["markets"]:
            yes_bid = float(m.get("yes_bid_dollars", 0.0))
            yes_ask = float(m.get("yes_ask_dollars", 0.0))
            last_price = float(m.get("last_price_dollars", 0.0))
            yes_price = last_price if last_price > 0 else _mid_price(yes_bid, yes_ask)

            ticker = m["ticker"]
            price_reference = reference_prices.get(ticker, yes_price)

            markets.append(Market(
                market_id=ticker,
                question=m.get("title", ticker),
                yes_price=yes_price,
                volume_24h=float(m.get("volume_24h_fp", 0.0)),
                price_reference=price_reference,
                resolution_criteria=m.get("rules_primary", ""),
            ))
    return markets


def compute_mispricing_pct(market: Market) -> float:
    """Momentum proxy: how far the current price has drifted from its
    earliest-seen price in the last hour, as a percentage. A large,
    un-caught-up move is our stand-in for 'the market hasn't priced this in
    yet.'"""
    if market.price_reference <= 0:
        return 0.0
    return abs(market.yes_price - market.price_reference) / market.price_reference * 100


def shortlist_candidates(markets: list[Market], threshold_pct: float, top_n: int) -> list[Market]:
    scored = [(compute_mispricing_pct(m), m) for m in markets]
    candidates = [(score, m) for score, m in scored if score >= threshold_pct]
    candidates.sort(key=lambda pair: pair[0], reverse=True)
    return [m for _, m in candidates[:top_n]]
