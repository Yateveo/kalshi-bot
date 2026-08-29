import json
from pathlib import Path

import pytest

import scanner

MARKETS_FIXTURE = Path(__file__).parent / "fixtures" / "markets_sample.json"
TRADES_FIXTURE = Path(__file__).parent / "fixtures" / "trades_sample.json"


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


class FakeSession:
    """Routes GET requests to the right fixture payload based on URL."""

    def __init__(self, markets_payload, trades_payload):
        self._markets_payload = markets_payload
        self._trades_payload = trades_payload
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, params))
        if url == scanner.KALSHI_TRADES_URL:
            return FakeResponse(self._trades_payload)
        return FakeResponse(self._markets_payload)


def _load(path):
    return json.loads(path.read_text())


def test_fetch_open_markets_parses_kalshi_api_shape():
    session = FakeSession(_load(MARKETS_FIXTURE), _load(TRADES_FIXTURE))

    markets = scanner.fetch_open_markets(session=session)

    assert len(markets) == 2
    highny = next(m for m in markets if m.market_id == "KXHIGHNY-26AUG30-T80")
    assert highny.question == "Will it hit 80F or above in NYC tomorrow?"
    assert highny.yes_price == pytest.approx(0.42)  # last_price_dollars
    assert highny.price_reference == pytest.approx(0.30)  # earliest trade in the window
    assert highny.volume_24h == pytest.approx(15000.0)


def test_fetch_open_markets_queries_markets_by_the_tickers_that_actually_traded():
    session = FakeSession(_load(MARKETS_FIXTURE), _load(TRADES_FIXTURE))

    scanner.fetch_open_markets(session=session)

    markets_call = next(c for c in session.calls if c[0] == scanner.KALSHI_MARKETS_URL)
    requested_tickers = markets_call[1]["tickers"].split(",")
    assert set(requested_tickers) == {"KXHIGHNY-26AUG30-T80", "KXBTCZ-26AUG30-T120000"}
    assert markets_call[1]["mve_filter"] == "exclude"


def test_fetch_open_markets_returns_empty_when_nothing_traded_recently():
    session = FakeSession(_load(MARKETS_FIXTURE), {"trades": []})

    markets = scanner.fetch_open_markets(session=session)

    assert markets == []
    # never even queries /markets if there's no traded-ticker universe to look up
    assert not any(c[0] == scanner.KALSHI_MARKETS_URL for c in session.calls)


def test_fetch_open_markets_falls_back_to_bid_ask_midpoint_when_untraded():
    # ticker traded (so it's in the universe) but last_price_dollars is 0
    # (e.g. only a fresh quote posted since the trade)
    trades_payload = {"trades": [
        {"ticker": "0x1", "yes_price_dollars": "0.35", "created_time": "2026-08-30T09:00:00Z"},
    ]}
    markets_payload = {"markets": [{
        "ticker": "0x1",
        "title": "q",
        "yes_bid_dollars": "0.40",
        "yes_ask_dollars": "0.44",
        "last_price_dollars": "0.0000",
        "volume_24h_fp": "0.00",
        "rules_primary": "r",
    }]}
    session = FakeSession(markets_payload, trades_payload)

    markets = scanner.fetch_open_markets(session=session)

    assert markets[0].yes_price == pytest.approx(0.42)  # midpoint of 0.40/0.44
    assert markets[0].price_reference == pytest.approx(0.35)  # from the trade


def test_fetch_open_markets_batches_ticker_queries():
    many_tickers = [f"T{i}" for i in range(120)]
    trades_payload = {"trades": [
        {"ticker": t, "yes_price_dollars": "0.50", "created_time": "2026-08-30T09:00:00Z"}
        for t in many_tickers
    ]}
    session = FakeSession({"markets": []}, trades_payload)

    scanner.fetch_open_markets(session=session)

    markets_calls = [c for c in session.calls if c[0] == scanner.KALSHI_MARKETS_URL]
    assert len(markets_calls) == 3  # 120 tickers / batch size 50 -> 3 batches
    for call in markets_calls:
        assert len(call[1]["tickers"].split(",")) <= scanner.TICKER_BATCH_SIZE


def test_earliest_trade_prices_picks_the_earliest_by_created_time():
    trades = [
        {"ticker": "A", "yes_price_dollars": "0.50", "created_time": "2026-08-30T09:45:00Z"},
        {"ticker": "A", "yes_price_dollars": "0.30", "created_time": "2026-08-30T09:00:00Z"},
        {"ticker": "B", "yes_price_dollars": "0.10", "created_time": "2026-08-30T09:10:00Z"},
    ]

    result = scanner._earliest_trade_prices(trades)

    assert result == {"A": pytest.approx(0.30), "B": pytest.approx(0.10)}


def test_compute_mispricing_pct_measures_gap_from_reference_price():
    market = scanner.Market(
        market_id="0x1", question="q", yes_price=0.42,
        volume_24h=15000.0, price_reference=0.30, resolution_criteria="r",
    )
    # (0.42 - 0.30) / 0.30 * 100 = 40.0
    assert scanner.compute_mispricing_pct(market) == pytest.approx(40.0)


def test_shortlist_candidates_filters_and_ranks_by_mispricing():
    big_gap = scanner.Market("0x1", "big", 0.42, 15000.0, 0.30, "r")   # ~40%
    small_gap = scanner.Market("0x2", "small", 0.55, 500000.0, 0.54, "r")  # ~1.8%
    mid_gap = scanner.Market("0x3", "mid", 0.20, 1000.0, 0.18, "r")    # ~11%

    shortlist = scanner.shortlist_candidates(
        [big_gap, small_gap, mid_gap], threshold_pct=8.0, top_n=8,
    )

    assert [m.market_id for m in shortlist] == ["0x1", "0x3"]
