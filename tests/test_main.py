import scanner
import storage


class FakeToolUseBlock:
    def __init__(self, input_data):
        self.type = "tool_use"
        self.input = input_data


class FakeResponse:
    def __init__(self, content):
        self.content = content


class FakeMessages:
    def __init__(self, decisions):
        self._decisions = decisions
        self._call_count = 0

    def create(self, **kwargs):
        decision = self._decisions[self._call_count]
        self._call_count += 1
        return FakeResponse([FakeToolUseBlock(decision)])


class FakeClient:
    def __init__(self, decisions):
        self.messages = FakeMessages(decisions)


class FakeCfg:
    mispricing_threshold_pct = 8.0
    shortlist_size = 8
    kelly_cap_pct = 6.0
    floor_usd = 50.0
    ceiling_usd = 75.0
    stop_loss_pct = 25.0
    telegram_bot_token = "tok"
    telegram_chat_id = "chat"


def test_run_cycle_opens_a_trade_and_records_equity(monkeypatch):
    import main as main_module

    conn = storage.init_db(":memory:")
    markets = [scanner.Market("0x1", "Will X happen?", 0.42, 15000.0, 0.30, "r")]
    monkeypatch.setattr(main_module.scanner, "fetch_open_markets", lambda: markets)

    sent_messages = []
    monkeypatch.setattr(
        main_module.notifier, "send_message",
        lambda token, chat_id, text: sent_messages.append(text),
    )

    fake_client = FakeClient([
        {"trade": True, "direction": "yes", "confidence": 0.8, "rationale": "clear edge"},
    ])

    result = main_module.run_cycle(FakeCfg(), conn, fake_client)

    assert result["trades_opened"] == 1
    assert len(sent_messages) == 1
    assert len(storage.get_open_trades(conn)) == 1
    equity_usd, reserved_usd = storage.get_current_equity(conn)
    assert equity_usd == 50.0  # opening a position doesn't change total equity
    assert reserved_usd == 0.0


def test_run_cycle_stops_out_a_losing_open_position(monkeypatch):
    import main as main_module

    conn = storage.init_db(":memory:")
    cycle_id = storage.record_cycle(conn, "2026-08-25T00:00:00+00:00", 1, "[]")
    storage.record_trade_open(
        conn, cycle_id, "0x1", "Will X happen?", "yes", 0.40, 4.0, 40.0, 0.8,
        "2026-08-25T00:00:00+00:00",
    )
    storage.record_equity(conn, "2026-08-25T00:00:00+00:00", 50.0, 0.0)

    # price crashed from 0.40 to 0.20 -> 50% drop, past the 25% stop-loss
    markets = [scanner.Market("0x1", "Will X happen?", 0.20, 15000.0, 0.20, "r")]
    monkeypatch.setattr(main_module.scanner, "fetch_open_markets", lambda: markets)
    monkeypatch.setattr(main_module.notifier, "send_message", lambda *a, **k: None)

    fake_client = FakeClient([])  # price stop-loss triggers first; no analyst call needed

    result = main_module.run_cycle(FakeCfg(), conn, fake_client)

    assert storage.get_open_trades(conn) == []
    assert result["equity_usd"] < 50.0


def test_run_cycle_exits_on_confidence_reversal_without_hitting_stop_loss(monkeypatch):
    import main as main_module

    conn = storage.init_db(":memory:")
    cycle_id = storage.record_cycle(conn, "2026-08-25T00:00:00+00:00", 1, "[]")
    storage.record_trade_open(
        conn, cycle_id, "0x1", "Will X happen?", "yes", 0.40, 4.0, 40.0, 0.8,
        "2026-08-25T00:00:00+00:00",
    )
    storage.record_equity(conn, "2026-08-25T00:00:00+00:00", 50.0, 0.0)

    # price barely moved (well within the 25% stop-loss), so only a
    # confidence reversal should trigger the exit
    markets = [scanner.Market("0x1", "Will X happen?", 0.38, 15000.0, 0.38, "r")]
    monkeypatch.setattr(main_module.scanner, "fetch_open_markets", lambda: markets)
    monkeypatch.setattr(main_module.notifier, "send_message", lambda *a, **k: None)

    # the position's mispricing is now ~0%, so it won't reappear on the
    # shortlist -- this decision is consumed solely by the open-position
    # re-check, and the analyst now sees the "no" side favored
    fake_client = FakeClient([
        {"trade": False, "direction": "no", "confidence": 0.3, "rationale": "edge reversed"},
    ])

    result = main_module.run_cycle(FakeCfg(), conn, fake_client)

    assert storage.get_open_trades(conn) == []


def test_compute_floor_reached_is_false_on_the_very_first_cycle():
    import main as main_module

    conn = storage.init_db(":memory:")  # no equity_history rows yet

    assert main_module.compute_floor_reached(conn, current_equity_usd=50.0, floor_usd=50.0) is False


def test_compute_floor_reached_latches_true_and_survives_a_later_dip():
    import main as main_module

    conn = storage.init_db(":memory:")
    # cycle 1: seed equity recorded below the floor (a loss happened)
    storage.record_equity(conn, "2026-08-25T00:00:00+00:00", 40.0, 0.0)
    assert main_module.compute_floor_reached(conn, current_equity_usd=40.0, floor_usd=50.0) is False

    # cycle 2: equity recovers to exactly the floor -- latch engages immediately,
    # using this cycle's live equity even before it's persisted
    assert main_module.compute_floor_reached(conn, current_equity_usd=50.0, floor_usd=50.0) is True
    storage.record_equity(conn, "2026-08-25T00:10:00+00:00", 50.0, 0.0)

    # cycle 3: a later losing streak drops equity back below the floor --
    # the latch must stay True (sticky), not un-latch
    assert main_module.compute_floor_reached(conn, current_equity_usd=35.0, floor_usd=50.0) is True
