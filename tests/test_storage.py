import storage


def test_equity_round_trip():
    conn = storage.init_db(":memory:")
    assert storage.get_current_equity(conn) == (0.0, 0.0)

    storage.record_equity(conn, "2026-08-25T00:00:00+00:00", 50.0, 0.0)
    storage.record_equity(conn, "2026-08-25T00:10:00+00:00", 52.0, 0.0)

    assert storage.get_current_equity(conn) == (52.0, 0.0)


def test_trade_open_and_close_round_trip():
    conn = storage.init_db(":memory:")
    cycle_id = storage.record_cycle(conn, "2026-08-25T00:00:00+00:00", 100, "[]")

    trade_id = storage.record_trade_open(
        conn, cycle_id, "0x1", "Will X happen?", "yes", 0.42, 3.0, 12.0, 0.8,
        "2026-08-25T00:00:00+00:00",
    )

    open_trades = storage.get_open_trades(conn)
    assert len(open_trades) == 1
    assert open_trades[0]["id"] == trade_id
    assert open_trades[0]["market_id"] == "0x1"
    assert open_trades[0]["direction"] == "yes"
    assert open_trades[0]["entry_price"] == 0.42
    assert open_trades[0]["size_usd"] == 3.0

    storage.record_trade_close(conn, trade_id, 0.50, 0.57, "2026-08-25T02:00:00+00:00")

    assert storage.get_open_trades(conn) == []
