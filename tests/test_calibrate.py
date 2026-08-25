import calibrate
import storage


def _closed_trade(conn, cycle_id, mispricing_pct, pnl_usd, ts_opened, ts_closed):
    trade_id = storage.record_trade_open(
        conn, cycle_id, "0x1", "q", "yes", 0.40, 4.0, mispricing_pct, 0.8, ts_opened,
    )
    storage.record_trade_close(conn, trade_id, 0.45, pnl_usd, ts_closed)


def test_build_report_buckets_by_threshold_and_hold_time():
    conn = storage.init_db(":memory:")
    cycle_id = storage.record_cycle(conn, "2026-08-25T00:00:00+00:00", 1, "[]")

    _closed_trade(conn, cycle_id, mispricing_pct=4.0, pnl_usd=-0.50,
                   ts_opened="2026-08-25T00:00:00+00:00", ts_closed="2026-08-25T01:00:00+00:00")
    _closed_trade(conn, cycle_id, mispricing_pct=10.0, pnl_usd=1.20,
                   ts_opened="2026-08-25T00:00:00+00:00", ts_closed="2026-08-25T00:30:00+00:00")

    report = calibrate.build_report(conn)

    assert "0-5%: 1 trades, avg P&L $-0.50" in report
    assert "8-15%: 1 trades, avg P&L $1.20" in report
    assert "0-2h: 2 trades" in report
