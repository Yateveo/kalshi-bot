from dataclasses import dataclass

import requests

GAMMA_API_URL = "https://gamma-api.polymarket.com/markets"


@dataclass
class Market:
    market_id: str
    question: str
    yes_price: float
    volume_24h: float
    price_1h_ago: float
    resolution_criteria: str


def fetch_open_markets(session: requests.Session | None = None) -> list[Market]:
    session = session or requests.Session()
    resp = session.get(
        GAMMA_API_URL, params={"active": "true", "closed": "false"}, timeout=10,
    )
    resp.raise_for_status()
    raw_markets = resp.json()

    markets = []
    for m in raw_markets:
        markets.append(Market(
            market_id=m["id"],
            question=m["question"],
            yes_price=float(m["outcomePrices"][0]),
            volume_24h=float(m.get("volume24hr", 0.0)),
            price_1h_ago=float(m.get("oneHourPriceChange", m["outcomePrices"][0])),
            resolution_criteria=m.get("description", ""),
        ))
    return markets


def compute_mispricing_pct(market: Market) -> float:
    """Naive fair-value proxy: how far the current price has drifted from
    where it was an hour ago, as a percentage. A large, un-caught-up move
    is our stand-in for 'the market hasn't priced this in yet'."""
    if market.price_1h_ago <= 0:
        return 0.0
    return abs(market.yes_price - market.price_1h_ago) / market.price_1h_ago * 100


def shortlist_candidates(markets: list[Market], threshold_pct: float, top_n: int) -> list[Market]:
    scored = [(compute_mispricing_pct(m), m) for m in markets]
    candidates = [(score, m) for score, m in scored if score >= threshold_pct]
    candidates.sort(key=lambda pair: pair[0], reverse=True)
    return [m for _, m in candidates[:top_n]]
