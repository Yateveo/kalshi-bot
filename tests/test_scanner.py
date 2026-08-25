import json
from pathlib import Path

import pytest

import scanner

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "markets_sample.json"


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, payload):
        self._payload = payload

    def get(self, url, params=None, timeout=None):
        return FakeResponse(self._payload)


def test_fetch_open_markets_parses_gamma_api_shape():
    payload = json.loads(FIXTURE_PATH.read_text())
    session = FakeSession(payload)

    markets = scanner.fetch_open_markets(session=session)

    assert len(markets) == 2
    assert markets[0].market_id == "0x1"
    assert markets[0].question == "Will it rain in NYC tomorrow?"
    assert markets[0].yes_price == 0.42
    assert markets[0].price_1h_ago == 0.30
    assert markets[0].volume_24h == 15000.0


def test_compute_mispricing_pct_measures_gap_from_recent_price():
    market = scanner.Market(
        market_id="0x1", question="q", yes_price=0.42,
        volume_24h=15000.0, price_1h_ago=0.30, resolution_criteria="r",
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
