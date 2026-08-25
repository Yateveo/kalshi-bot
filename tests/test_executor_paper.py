import pytest

import analyst
import executor_paper
import scanner
import storage


def test_execute_paper_trade_logs_a_yes_side_fill():
    conn = storage.init_db(":memory:")
    cycle_id = storage.record_cycle(conn, "2026-08-25T00:00:00+00:00", 10, "[]")
    market = scanner.Market("0x1", "Will X happen?", 0.42, 15000.0, 0.30, "r")
    decision = analyst.Decision("0x1", True, "yes", 0.8, "clear edge")

    fill = executor_paper.execute_paper_trade(
        conn, cycle_id, market, decision, size_usd=3.0, mispricing_pct=40.0,
        ts="2026-08-25T00:00:00+00:00",
    )

    assert fill.fill_price == 0.42
    assert fill.size_usd == 3.0
    open_trades = storage.get_open_trades(conn)
    assert len(open_trades) == 1
    assert open_trades[0]["id"] == fill.trade_id


def test_execute_paper_trade_logs_a_no_side_fill_as_inverse_price():
    conn = storage.init_db(":memory:")
    cycle_id = storage.record_cycle(conn, "2026-08-25T00:00:00+00:00", 10, "[]")
    market = scanner.Market("0x1", "Will X happen?", 0.42, 15000.0, 0.30, "r")
    decision = analyst.Decision("0x1", True, "no", 0.8, "clear edge")

    fill = executor_paper.execute_paper_trade(
        conn, cycle_id, market, decision, size_usd=3.0, mispricing_pct=40.0,
        ts="2026-08-25T00:00:00+00:00",
    )

    assert fill.fill_price == pytest.approx(0.58)  # 1 - 0.42


def test_close_paper_trade_computes_pnl_from_price_move():
    conn = storage.init_db(":memory:")
    cycle_id = storage.record_cycle(conn, "2026-08-25T00:00:00+00:00", 10, "[]")
    trade_id = storage.record_trade_open(
        conn, cycle_id, "0x1", "q", "yes", 0.40, 4.0, 40.0, 0.8,
        "2026-08-25T00:00:00+00:00",
    )

    # entry at 0.40 with $4 stake -> 10 shares; price rises to 0.50 -> $5 exit value
    pnl = executor_paper.close_paper_trade(
        conn, trade_id, current_price=0.50, entry_price=0.40, size_usd=4.0,
        ts="2026-08-25T02:00:00+00:00",
    )

    assert pnl == pytest.approx(1.0)
    assert storage.get_open_trades(conn) == []
