# Polymarket Paper-Trading Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a self-hosted, paper-trading Polymarket agent that scans markets, uses Claude to reason about mispricings, sizes bets with a floor/ceiling-guarded Kelly rule, and reports results — no real money moves in this plan.

**Architecture:** A Python project run every 10 minutes by Windows Task Scheduler. Each cycle: fetch markets → check open positions for stop-loss exits → shortlist new mispricing candidates → ask Claude to evaluate the shortlist → size and simulate-fill any trades through a floor/ceiling risk guard → log everything to SQLite → notify Telegram. A separate offline script produces a calibration report after a week of data.

**Tech Stack:** Python 3.11+, `sqlite3` (stdlib), `pyyaml`, `anthropic` SDK, `requests` (Telegram), `pytest`.

**Spec:** [docs/superpowers/specs/2026-08-25-polymarket-paper-trading-bot-design.md](../specs/2026-08-25-polymarket-paper-trading-bot-design.md)

## Global Constraints

- Claude/the assistant never holds funds, wallet keys, or executes real trades — this plan builds paper mode only; `executor_live` stays a stub.
- Kelly position sizing hard-capped at 6% of bankroll (`kelly_cap_pct` in config, default `6.0`).
- Floor (default `$50`) and ceiling (default `$75`) equity guard: once equity reaches the floor, no trade may size below it; once equity reaches the ceiling, the amount above the floor sweeps to a non-tradable reserved balance.
- Stop-loss threshold default `25%` price drop from entry; also exit on confidence reversal.
- Mispricing shortlist threshold default `8%`, shortlist size default `8` markets per cycle.
- No live X/Twitter sentiment feed — mispricing signal comes from Polymarket's own price/volume momentum.
- No automated self-tuning of thresholds — `calibrate.py` produces a human-readable report only; the user edits `config.yaml` by hand.
- Telegram notifications on trades and repeated errors, plus a daily summary — not every no-op cycle.
- TDD throughout, heaviest coverage on `risk_guard.py` (this is the code that protects the user's money).
- All secrets (`ANTHROPIC_API_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`) live in a git-ignored `.env`; all tunable thresholds live in git-ignored `config.yaml` (an example file is committed).

---

## File Structure

```
F:/Trading/
├── config.py                  # Config dataclass + loader (yaml + .env)
├── config.example.yaml        # committed template for config.yaml
├── .env.example                # committed template for .env
├── .gitignore
├── requirements.txt
├── storage.py                  # SQLite schema + read/write helpers
├── scanner.py                  # market fetch + mispricing scoring
├── analyst.py                  # Claude prompt + structured decision parsing
├── risk_guard.py                # Kelly sizing, floor/ceiling, stop-loss (pure functions)
├── executor_paper.py            # simulated fills + P&L bookkeeping
├── notifier.py                  # Telegram message sending + formatting
├── main.py                      # orchestrates one cycle, STOP-file kill switch
├── calibrate.py                 # offline end-of-week report
├── run_cycle.ps1                 # Task Scheduler entrypoint wrapper
├── trading.db                    # created at runtime (git-ignored)
└── tests/
    ├── fixtures/
    │   └── markets_sample.json
    ├── test_config.py
    ├── test_storage.py
    ├── test_risk_guard.py
    ├── test_scanner.py
    ├── test_analyst.py
    ├── test_executor_paper.py
    ├── test_notifier.py
    ├── test_main.py
    └── test_calibrate.py
```

---

### Task 1: Project scaffolding & config loader

**Files:**
- Create: `requirements.txt`, `.gitignore`, `config.example.yaml`, `.env.example`, `config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `config.load_config(yaml_path: str = "config.yaml", env_path: str = ".env") -> Config`, where `Config` has fields `mispricing_threshold_pct: float`, `shortlist_size: int`, `kelly_cap_pct: float`, `floor_usd: float`, `ceiling_usd: float`, `stop_loss_pct: float`, `anthropic_api_key: str`, `telegram_bot_token: str`, `telegram_chat_id: str`.

- [ ] **Step 1: Create project files**

`requirements.txt`:
```
pyyaml>=6.0
anthropic>=0.40.0
requests>=2.31.0
pytest>=8.0.0
```

`.gitignore`:
```
.env
config.yaml
trading.db
__pycache__/
*.pyc
.venv/
```

`config.example.yaml`:
```yaml
mispricing_threshold_pct: 8.0
shortlist_size: 8
kelly_cap_pct: 6.0
floor_usd: 50.0
ceiling_usd: 75.0
stop_loss_pct: 25.0
```

`.env.example`:
```
ANTHROPIC_API_KEY=sk-ant-your-key-here
TELEGRAM_BOT_TOKEN=123456:your-bot-token-here
TELEGRAM_CHAT_ID=your-chat-id-here
```

- [ ] **Step 2: Write the failing test**

`tests/test_config.py`:
```python
from config import load_config


def test_load_config_reads_yaml_and_env(tmp_path, monkeypatch):
    yaml_path = tmp_path / "config.yaml"
    yaml_path.write_text(
        "mispricing_threshold_pct: 8.0\n"
        "shortlist_size: 8\n"
        "kelly_cap_pct: 6.0\n"
        "floor_usd: 50.0\n"
        "ceiling_usd: 75.0\n"
        "stop_loss_pct: 25.0\n"
    )
    env_path = tmp_path / ".env"
    env_path.write_text(
        "ANTHROPIC_API_KEY=test-key\n"
        "TELEGRAM_BOT_TOKEN=test-token\n"
        "TELEGRAM_CHAT_ID=12345\n"
    )
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)

    config = load_config(str(yaml_path), str(env_path))

    assert config.mispricing_threshold_pct == 8.0
    assert config.shortlist_size == 8
    assert config.kelly_cap_pct == 6.0
    assert config.floor_usd == 50.0
    assert config.ceiling_usd == 75.0
    assert config.stop_loss_pct == 25.0
    assert config.anthropic_api_key == "test-key"
    assert config.telegram_bot_token == "test-token"
    assert config.telegram_chat_id == "12345"
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'config'`

- [ ] **Step 4: Write minimal implementation**

`config.py`:
```python
import os
from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass
class Config:
    mispricing_threshold_pct: float
    shortlist_size: int
    kelly_cap_pct: float
    floor_usd: float
    ceiling_usd: float
    stop_loss_pct: float
    anthropic_api_key: str
    telegram_bot_token: str
    telegram_chat_id: str


def _load_env_file(env_path: str) -> None:
    path = Path(env_path)
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


def load_config(yaml_path: str = "config.yaml", env_path: str = ".env") -> Config:
    _load_env_file(env_path)

    with open(yaml_path) as f:
        raw = yaml.safe_load(f)

    return Config(
        mispricing_threshold_pct=raw["mispricing_threshold_pct"],
        shortlist_size=raw["shortlist_size"],
        kelly_cap_pct=raw["kelly_cap_pct"],
        floor_usd=raw["floor_usd"],
        ceiling_usd=raw["ceiling_usd"],
        stop_loss_pct=raw["stop_loss_pct"],
        anthropic_api_key=os.environ["ANTHROPIC_API_KEY"],
        telegram_bot_token=os.environ["TELEGRAM_BOT_TOKEN"],
        telegram_chat_id=os.environ["TELEGRAM_CHAT_ID"],
    )
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_config.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add requirements.txt .gitignore config.example.yaml .env.example config.py tests/test_config.py
git commit -m "feat: add project scaffolding and config loader"
```

---

### Task 2: Storage layer

**Files:**
- Create: `storage.py`
- Test: `tests/test_storage.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `storage.init_db(db_path: str) -> sqlite3.Connection`, `storage.record_equity(conn, ts: str, equity_usd: float, reserved_usd: float) -> int`, `storage.get_current_equity(conn) -> tuple[float, float]`, `storage.record_cycle(conn, ts: str, markets_scanned: int, shortlist_json: str) -> int`, `storage.record_trade_open(conn, cycle_id: int, market_id: str, question: str, direction: str, entry_price: float, size_usd: float, mispricing_pct: float, confidence: float, ts_opened: str) -> int`, `storage.record_trade_close(conn, trade_id: int, exit_price: float, pnl_usd: float, ts_closed: str) -> None`, `storage.get_open_trades(conn) -> list[sqlite3.Row]` (rows accessible by column name: `id`, `market_id`, `direction`, `entry_price`, `size_usd`).

- [ ] **Step 1: Write the failing test**

`tests/test_storage.py`:
```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_storage.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'storage'`

- [ ] **Step 3: Write minimal implementation**

`storage.py`:
```python
import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS equity_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    equity_usd REAL NOT NULL,
    reserved_usd REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS cycles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    markets_scanned INTEGER NOT NULL,
    shortlist_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cycle_id INTEGER NOT NULL,
    market_id TEXT NOT NULL,
    question TEXT NOT NULL,
    direction TEXT NOT NULL,
    entry_price REAL NOT NULL,
    size_usd REAL NOT NULL,
    mispricing_pct REAL NOT NULL,
    confidence REAL NOT NULL,
    status TEXT NOT NULL,
    exit_price REAL,
    pnl_usd REAL,
    ts_opened TEXT NOT NULL,
    ts_closed TEXT
);
"""


def init_db(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


def record_equity(conn: sqlite3.Connection, ts: str, equity_usd: float, reserved_usd: float) -> int:
    cur = conn.execute(
        "INSERT INTO equity_history (ts, equity_usd, reserved_usd) VALUES (?, ?, ?)",
        (ts, equity_usd, reserved_usd),
    )
    conn.commit()
    return cur.lastrowid


def get_current_equity(conn: sqlite3.Connection) -> tuple[float, float]:
    row = conn.execute(
        "SELECT equity_usd, reserved_usd FROM equity_history ORDER BY id DESC LIMIT 1"
    ).fetchone()
    if row is None:
        return (0.0, 0.0)
    return (row["equity_usd"], row["reserved_usd"])


def record_cycle(conn: sqlite3.Connection, ts: str, markets_scanned: int, shortlist_json: str) -> int:
    cur = conn.execute(
        "INSERT INTO cycles (ts, markets_scanned, shortlist_json) VALUES (?, ?, ?)",
        (ts, markets_scanned, shortlist_json),
    )
    conn.commit()
    return cur.lastrowid


def record_trade_open(
    conn: sqlite3.Connection, cycle_id: int, market_id: str, question: str,
    direction: str, entry_price: float, size_usd: float, mispricing_pct: float,
    confidence: float, ts_opened: str,
) -> int:
    cur = conn.execute(
        """INSERT INTO trades
           (cycle_id, market_id, question, direction, entry_price, size_usd,
            mispricing_pct, confidence, status, ts_opened)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'open', ?)""",
        (cycle_id, market_id, question, direction, entry_price, size_usd,
         mispricing_pct, confidence, ts_opened),
    )
    conn.commit()
    return cur.lastrowid


def record_trade_close(conn: sqlite3.Connection, trade_id: int, exit_price: float, pnl_usd: float, ts_closed: str) -> None:
    conn.execute(
        "UPDATE trades SET status='closed', exit_price=?, pnl_usd=?, ts_closed=? WHERE id=?",
        (exit_price, pnl_usd, ts_closed, trade_id),
    )
    conn.commit()


def get_open_trades(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM trades WHERE status='open'").fetchall()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_storage.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add storage.py tests/test_storage.py
git commit -m "feat: add SQLite storage layer"
```

---

### Task 3: Risk guard — Kelly sizing, floor/ceiling, stop-loss

**Files:**
- Create: `risk_guard.py`
- Test: `tests/test_risk_guard.py`

**Interfaces:**
- Consumes: nothing from earlier tasks (pure functions).
- Produces: `risk_guard.kelly_fraction(confidence: float, cap_pct: float) -> float`, `risk_guard.SizingResult` (fields `size_usd: float`, `blocked_reason: str | None`), `risk_guard.size_position(equity_usd: float, confidence: float, kelly_cap_pct: float, floor_usd: float, floor_reached: bool) -> SizingResult`, `risk_guard.apply_ceiling(equity_usd: float, reserved_usd: float, ceiling_usd: float, floor_usd: float) -> tuple[float, float]`, `risk_guard.should_stop_loss(entry_price: float, current_price: float, stop_loss_pct: float) -> bool`, `risk_guard.should_reverse_exit(original_confidence: float, new_confidence: float) -> bool`.

- [ ] **Step 1: Write failing tests for `kelly_fraction`**

`tests/test_risk_guard.py`:
```python
import pytest

import risk_guard


def test_kelly_fraction_scales_with_confidence():
    # f* = 2p - 1 for an even-money bet
    assert risk_guard.kelly_fraction(confidence=0.7, cap_pct=100.0) == pytest.approx(0.4)


def test_kelly_fraction_floors_at_zero_below_50_percent_confidence():
    assert risk_guard.kelly_fraction(confidence=0.4, cap_pct=100.0) == 0.0


def test_kelly_fraction_respects_cap():
    assert risk_guard.kelly_fraction(confidence=0.99, cap_pct=6.0) == pytest.approx(0.06)


def test_kelly_fraction_rejects_out_of_range_confidence():
    with pytest.raises(ValueError):
        risk_guard.kelly_fraction(confidence=1.5, cap_pct=6.0)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_risk_guard.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'risk_guard'`

- [ ] **Step 3: Implement `kelly_fraction`**

`risk_guard.py`:
```python
def kelly_fraction(confidence: float, cap_pct: float) -> float:
    """Kelly fraction for an even-money bet, capped at cap_pct of bankroll.

    Uses the simplified Kelly formula f* = 2p - 1 for an even-money
    outcome, floored at 0 (never size a bet against your own stated edge)
    and capped at cap_pct/100 regardless of how confident the edge is.
    """
    if not 0.0 <= confidence <= 1.0:
        raise ValueError(f"confidence must be in [0, 1], got {confidence}")
    raw = max(0.0, 2 * confidence - 1)
    return min(raw, cap_pct / 100.0)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_risk_guard.py -v`
Expected: 4 PASS

- [ ] **Step 5: Write failing tests for `size_position`**

Append to `tests/test_risk_guard.py`:
```python
def test_size_position_before_floor_reached_uses_full_kelly_size():
    result = risk_guard.size_position(
        equity_usd=50.0, confidence=0.8, kelly_cap_pct=6.0,
        floor_usd=50.0, floor_reached=False,
    )
    assert result.size_usd == pytest.approx(3.0)  # 50 * 0.06
    assert result.blocked_reason is None


def test_size_position_after_floor_reached_caps_at_headroom():
    # equity is only $2 above the floor; even a full Kelly-cap size ($3.12)
    # must be trimmed down to the $2 of headroom above the floor.
    result = risk_guard.size_position(
        equity_usd=52.0, confidence=0.8, kelly_cap_pct=6.0,
        floor_usd=50.0, floor_reached=True,
    )
    assert result.size_usd == pytest.approx(2.0)
    assert result.blocked_reason is None


def test_size_position_at_floor_blocks_new_risk():
    result = risk_guard.size_position(
        equity_usd=50.0, confidence=0.8, kelly_cap_pct=6.0,
        floor_usd=50.0, floor_reached=True,
    )
    assert result.size_usd == 0.0
    assert result.blocked_reason == "at_or_below_floor"


def test_size_position_zero_confidence_edge_blocks():
    result = risk_guard.size_position(
        equity_usd=50.0, confidence=0.5, kelly_cap_pct=6.0,
        floor_usd=50.0, floor_reached=False,
    )
    assert result.size_usd == 0.0
    assert result.blocked_reason == "zero_size"
```

- [ ] **Step 6: Run tests to verify they fail**

Run: `pytest tests/test_risk_guard.py -v`
Expected: FAIL with `AttributeError: module 'risk_guard' has no attribute 'SizingResult'`

- [ ] **Step 7: Implement `SizingResult` and `size_position`**

Append to `risk_guard.py`:
```python
from dataclasses import dataclass


@dataclass
class SizingResult:
    size_usd: float
    blocked_reason: str | None


def size_position(
    equity_usd: float, confidence: float, kelly_cap_pct: float,
    floor_usd: float, floor_reached: bool,
) -> SizingResult:
    fraction = kelly_fraction(confidence, kelly_cap_pct)
    proposed_size = equity_usd * fraction

    if floor_reached:
        headroom = equity_usd - floor_usd
        if headroom <= 0:
            return SizingResult(0.0, "at_or_below_floor")
        proposed_size = min(proposed_size, headroom)

    if proposed_size <= 0:
        return SizingResult(0.0, "zero_size")

    return SizingResult(proposed_size, None)
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `pytest tests/test_risk_guard.py -v`
Expected: 8 PASS

- [ ] **Step 9: Write failing tests for `apply_ceiling`**

Append to `tests/test_risk_guard.py`:
```python
def test_apply_ceiling_below_ceiling_is_a_no_op():
    equity, reserved = risk_guard.apply_ceiling(
        equity_usd=70.0, reserved_usd=0.0, ceiling_usd=75.0, floor_usd=50.0,
    )
    assert equity == 70.0
    assert reserved == 0.0


def test_apply_ceiling_at_or_above_ceiling_sweeps_profit_above_floor():
    equity, reserved = risk_guard.apply_ceiling(
        equity_usd=80.0, reserved_usd=0.0, ceiling_usd=75.0, floor_usd=50.0,
    )
    assert equity == 50.0
    assert reserved == 30.0


def test_apply_ceiling_accumulates_reserved_across_calls():
    equity, reserved = risk_guard.apply_ceiling(
        equity_usd=76.0, reserved_usd=30.0, ceiling_usd=75.0, floor_usd=50.0,
    )
    assert equity == 50.0
    assert reserved == 56.0
```

- [ ] **Step 10: Run tests to verify they fail**

Run: `pytest tests/test_risk_guard.py -v`
Expected: FAIL with `AttributeError: module 'risk_guard' has no attribute 'apply_ceiling'`

- [ ] **Step 11: Implement `apply_ceiling`**

Append to `risk_guard.py`:
```python
def apply_ceiling(
    equity_usd: float, reserved_usd: float, ceiling_usd: float, floor_usd: float,
) -> tuple[float, float]:
    """If equity is at/above the ceiling, sweep everything above the floor
    into the non-tradable reserved balance. Returns (tradable_equity, reserved_usd)."""
    if equity_usd < ceiling_usd:
        return (equity_usd, reserved_usd)
    sweep = equity_usd - floor_usd
    return (floor_usd, reserved_usd + sweep)
```

- [ ] **Step 12: Run tests to verify they pass**

Run: `pytest tests/test_risk_guard.py -v`
Expected: 11 PASS

- [ ] **Step 13: Write failing tests for stop-loss and reversal exit**

Append to `tests/test_risk_guard.py`:
```python
def test_should_stop_loss_triggers_past_threshold():
    assert risk_guard.should_stop_loss(entry_price=0.40, current_price=0.29, stop_loss_pct=25.0) is True


def test_should_stop_loss_does_not_trigger_within_threshold():
    assert risk_guard.should_stop_loss(entry_price=0.40, current_price=0.35, stop_loss_pct=25.0) is False


def test_should_stop_loss_rejects_nonpositive_entry_price():
    with pytest.raises(ValueError):
        risk_guard.should_stop_loss(entry_price=0.0, current_price=0.1, stop_loss_pct=25.0)


def test_should_reverse_exit_true_when_confidence_flips_sides():
    assert risk_guard.should_reverse_exit(original_confidence=0.8, new_confidence=0.3) is True


def test_should_reverse_exit_false_when_confidence_stays_on_same_side():
    assert risk_guard.should_reverse_exit(original_confidence=0.8, new_confidence=0.6) is False
```

- [ ] **Step 14: Run tests to verify they fail**

Run: `pytest tests/test_risk_guard.py -v`
Expected: FAIL with `AttributeError: module 'risk_guard' has no attribute 'should_stop_loss'`

- [ ] **Step 15: Implement stop-loss and reversal exit checks**

Append to `risk_guard.py`:
```python
def should_stop_loss(entry_price: float, current_price: float, stop_loss_pct: float) -> bool:
    if entry_price <= 0:
        raise ValueError("entry_price must be positive")
    drop_pct = (entry_price - current_price) / entry_price * 100
    return drop_pct >= stop_loss_pct


def should_reverse_exit(original_confidence: float, new_confidence: float) -> bool:
    """Exit if confidence has flipped to the other side of a coin-flip (0.5)."""
    return (original_confidence >= 0.5) != (new_confidence >= 0.5)
```

- [ ] **Step 16: Run full test file to verify everything passes**

Run: `pytest tests/test_risk_guard.py -v`
Expected: 16 PASS

- [ ] **Step 17: Commit**

```bash
git add risk_guard.py tests/test_risk_guard.py
git commit -m "feat: add risk guard with Kelly sizing, floor/ceiling, stop-loss"
```

---

### Task 4: Scanner — market fetch and mispricing scoring

**Files:**
- Create: `scanner.py`, `tests/fixtures/markets_sample.json`
- Test: `tests/test_scanner.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `scanner.Market` (dataclass: `market_id: str`, `question: str`, `yes_price: float`, `volume_24h: float`, `price_1h_ago: float`, `resolution_criteria: str`), `scanner.fetch_open_markets(session: requests.Session | None = None) -> list[Market]`, `scanner.compute_mispricing_pct(market: Market) -> float`, `scanner.shortlist_candidates(markets: list[Market], threshold_pct: float, top_n: int) -> list[Market]`.

- [ ] **Step 1: Add the fixture file**

`tests/fixtures/markets_sample.json`:
```json
[
  {
    "id": "0x1",
    "question": "Will it rain in NYC tomorrow?",
    "outcomePrices": ["0.42"],
    "volume24hr": 15000.0,
    "oneHourPriceChange": "0.30",
    "description": "Resolves YES if NOAA reports measurable precipitation."
  },
  {
    "id": "0x2",
    "question": "Will BTC close above $120k on Friday?",
    "outcomePrices": ["0.55"],
    "volume24hr": 500000.0,
    "oneHourPriceChange": "0.54",
    "description": "Resolves YES if Coinbase BTC-USD close >= 120000 on Friday."
  }
]
```

- [ ] **Step 2: Write failing tests**

`tests/test_scanner.py`:
```python
import json
from pathlib import Path

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
    assert scanner.compute_mispricing_pct(market) == pytest_approx(40.0)


def pytest_approx(value, rel=1e-6):
    import pytest
    return pytest.approx(value, rel=rel)


def test_shortlist_candidates_filters_and_ranks_by_mispricing():
    big_gap = scanner.Market("0x1", "big", 0.42, 15000.0, 0.30, "r")   # ~40%
    small_gap = scanner.Market("0x2", "small", 0.55, 500000.0, 0.54, "r")  # ~1.8%
    mid_gap = scanner.Market("0x3", "mid", 0.20, 1000.0, 0.18, "r")    # ~11%

    shortlist = scanner.shortlist_candidates(
        [big_gap, small_gap, mid_gap], threshold_pct=8.0, top_n=8,
    )

    assert [m.market_id for m in shortlist] == ["0x1", "0x3"]
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/test_scanner.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'scanner'`

- [ ] **Step 4: Implement `scanner.py`**

```python
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
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_scanner.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add scanner.py tests/test_scanner.py tests/fixtures/markets_sample.json
git commit -m "feat: add market scanner and mispricing scoring"
```

---

### Task 5: Analyst — Claude structured decision

**Files:**
- Create: `analyst.py`
- Test: `tests/test_analyst.py`

**Interfaces:**
- Consumes: `scanner.Market` from Task 4.
- Produces: `analyst.Decision` (dataclass: `market_id: str`, `trade: bool`, `direction: str`, `confidence: float`, `rationale: str`), `analyst.build_prompt(market: Market, mispricing_pct: float) -> str`, `analyst.analyze_market(client, market: Market, mispricing_pct: float) -> Decision` (where `client` is any object exposing `client.messages.create(**kwargs) -> response` with `response.content` a list of blocks having `.type` and `.input`).

- [ ] **Step 1: Write the failing test**

`tests/test_analyst.py`:
```python
import analyst
import scanner


class FakeToolUseBlock:
    def __init__(self, input_data):
        self.type = "tool_use"
        self.input = input_data


class FakeResponse:
    def __init__(self, content):
        self.content = content


class FakeMessages:
    def __init__(self, decision_input):
        self._decision_input = decision_input
        self.last_kwargs = None

    def create(self, **kwargs):
        self.last_kwargs = kwargs
        return FakeResponse([FakeToolUseBlock(self._decision_input)])


class FakeClient:
    def __init__(self, decision_input):
        self.messages = FakeMessages(decision_input)


def test_build_prompt_includes_key_market_facts():
    market = scanner.Market("0x1", "Will X happen?", 0.42, 15000.0, 0.30, "resolves on NOAA data")
    prompt = analyst.build_prompt(market, mispricing_pct=40.0)

    assert "Will X happen?" in prompt
    assert "resolves on NOAA data" in prompt
    assert "40.0%" in prompt


def test_analyze_market_parses_structured_decision():
    market = scanner.Market("0x1", "Will X happen?", 0.42, 15000.0, 0.30, "resolves on NOAA data")
    client = FakeClient({
        "trade": True, "direction": "yes", "confidence": 0.8, "rationale": "clear edge",
    })

    decision = analyst.analyze_market(client, market, mispricing_pct=40.0)

    assert decision.market_id == "0x1"
    assert decision.trade is True
    assert decision.direction == "yes"
    assert decision.confidence == 0.8
    assert decision.rationale == "clear edge"
    assert client.messages.last_kwargs["tool_choice"] == {"type": "tool", "name": "record_decision"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_analyst.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'analyst'`

- [ ] **Step 3: Implement `analyst.py`**

```python
from dataclasses import dataclass

from scanner import Market

DECISION_TOOL = {
    "name": "record_decision",
    "description": "Record a trade decision for a prediction market.",
    "input_schema": {
        "type": "object",
        "properties": {
            "trade": {"type": "boolean", "description": "Whether to trade this market."},
            "direction": {"type": "string", "enum": ["yes", "no"]},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "rationale": {"type": "string"},
        },
        "required": ["trade", "direction", "confidence", "rationale"],
    },
}


@dataclass
class Decision:
    market_id: str
    trade: bool
    direction: str
    confidence: float
    rationale: str


def build_prompt(market: Market, mispricing_pct: float) -> str:
    return (
        f"Market: {market.question}\n"
        f"Resolution criteria: {market.resolution_criteria}\n"
        f"Current YES price: {market.yes_price}\n"
        f"Price 1h ago: {market.price_1h_ago}\n"
        f"24h volume: {market.volume_24h}\n"
        f"Computed mispricing score: {mispricing_pct:.1f}%\n\n"
        "Decide whether this mispricing represents a genuine trading edge "
        "or just noise. Call record_decision with your answer."
    )


def analyze_market(client, market: Market, mispricing_pct: float) -> Decision:
    response = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=1024,
        tools=[DECISION_TOOL],
        tool_choice={"type": "tool", "name": "record_decision"},
        messages=[{"role": "user", "content": build_prompt(market, mispricing_pct)}],
    )
    tool_use_block = next(b for b in response.content if b.type == "tool_use")
    data = tool_use_block.input
    return Decision(
        market_id=market.market_id,
        trade=data["trade"],
        direction=data["direction"],
        confidence=data["confidence"],
        rationale=data["rationale"],
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_analyst.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add analyst.py tests/test_analyst.py
git commit -m "feat: add Claude-backed market analyst with structured decisions"
```

---

### Task 6: Paper executor — simulated fills and P&L

**Files:**
- Create: `executor_paper.py`
- Test: `tests/test_executor_paper.py`

**Interfaces:**
- Consumes: `scanner.Market` (Task 4), `analyst.Decision` (Task 5), `storage.record_trade_open`/`record_trade_close` (Task 2).
- Produces: `executor_paper.FillResult` (dataclass: `trade_id: int`, `fill_price: float`, `size_usd: float`), `executor_paper.execute_paper_trade(conn, cycle_id: int, market: Market, decision: Decision, size_usd: float, mispricing_pct: float, ts: str) -> FillResult`, `executor_paper.close_paper_trade(conn, trade_id: int, current_price: float, entry_price: float, size_usd: float, ts: str) -> float` (returns realized P&L in USD).

- [ ] **Step 1: Write the failing test**

`tests/test_executor_paper.py`:
```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_executor_paper.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'executor_paper'`

- [ ] **Step 3: Implement `executor_paper.py`**

```python
from dataclasses import dataclass

import storage
from analyst import Decision
from scanner import Market


@dataclass
class FillResult:
    trade_id: int
    fill_price: float
    size_usd: float


def execute_paper_trade(
    conn, cycle_id: int, market: Market, decision: Decision,
    size_usd: float, mispricing_pct: float, ts: str,
) -> FillResult:
    fill_price = market.yes_price if decision.direction == "yes" else (1 - market.yes_price)
    trade_id = storage.record_trade_open(
        conn, cycle_id, market.market_id, market.question, decision.direction,
        fill_price, size_usd, mispricing_pct, decision.confidence, ts,
    )
    return FillResult(trade_id=trade_id, fill_price=fill_price, size_usd=size_usd)


def close_paper_trade(
    conn, trade_id: int, current_price: float, entry_price: float,
    size_usd: float, ts: str,
) -> float:
    shares = size_usd / entry_price
    exit_value = shares * current_price
    pnl_usd = exit_value - size_usd
    storage.record_trade_close(conn, trade_id, current_price, pnl_usd, ts)
    return pnl_usd
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_executor_paper.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add executor_paper.py tests/test_executor_paper.py
git commit -m "feat: add paper executor with simulated fills and P&L"
```

---

### Task 7: Notifier — Telegram alerts

**Files:**
- Create: `notifier.py`
- Test: `tests/test_notifier.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `notifier.send_message(bot_token: str, chat_id: str, text: str, session: requests.Session | None = None) -> None`, `notifier.format_trade_alert(question: str, direction: str, size_usd: float, confidence: float, equity_usd: float, floor_usd: float, ceiling_usd: float) -> str`, `notifier.format_error_alert(error_count: int, last_error: str) -> str`.

- [ ] **Step 1: Write the failing test**

`tests/test_notifier.py`:
```python
import notifier


class FakeResponse:
    def raise_for_status(self):
        pass


class FakeSession:
    def __init__(self):
        self.calls = []

    def post(self, url, data=None, timeout=None):
        self.calls.append((url, data))
        return FakeResponse()


def test_send_message_posts_to_telegram_api():
    session = FakeSession()

    notifier.send_message("tok123", "chat456", "hello", session=session)

    assert len(session.calls) == 1
    url, data = session.calls[0]
    assert url == "https://api.telegram.org/bottok123/sendMessage"
    assert data == {"chat_id": "chat456", "text": "hello"}


def test_format_trade_alert_includes_key_numbers():
    text = notifier.format_trade_alert(
        question="Will X happen?", direction="yes", size_usd=3.0,
        confidence=0.8, equity_usd=52.0, floor_usd=50.0, ceiling_usd=75.0,
    )
    assert "Will X happen?" in text
    assert "YES" in text
    assert "$3.00" in text
    assert "80%" in text
    assert "$52.00" in text


def test_format_error_alert_includes_count_and_message():
    text = notifier.format_error_alert(error_count=3, last_error="timeout")
    assert "3" in text
    assert "timeout" in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_notifier.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'notifier'`

- [ ] **Step 3: Implement `notifier.py`**

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_notifier.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add notifier.py tests/test_notifier.py
git commit -m "feat: add Telegram notifier"
```

---

### Task 8: Main orchestrator

**Files:**
- Create: `main.py`
- Test: `tests/test_main.py`

**Interfaces:**
- Consumes: `config.Config` (Task 1), all of `storage` (Task 2), `risk_guard.should_stop_loss`/`should_reverse_exit`/`size_position`/`apply_ceiling` (Task 3), all of `scanner` (Task 4), `analyst.analyze_market` (Task 5), `executor_paper.execute_paper_trade`/`close_paper_trade` (Task 6), `notifier.send_message`/`format_trade_alert` (Task 7).
- Produces: `main.compute_floor_reached(conn, current_equity_usd: float, floor_usd: float) -> bool`, `main.run_cycle(cfg, conn, claude_client) -> dict` (keys `cycle_id`, `trades_opened`, `equity_usd`, `reserved_usd`), `main.main() -> None` (real entrypoint, checks `STOP` file, loads config, opens `trading.db`, runs one cycle).

Per spec, open positions exit on **either** a price-based stop-loss **or** a confidence reversal — so each open position gets a fresh (cheap, single-market) Claude read every cycle, separate from the shortlist's new-opportunity calls.

**Ruling (from Task 3's review):** `risk_guard.size_position`'s `floor_reached` parameter must be a **sticky latch** — "has equity ever reached floor_usd" — not a live "is current equity right now >= floor_usd" check. A naive live check has two bugs: (1) on the very first cycle ever, equity is seeded to exactly `floor_usd`, so a live check would immediately latch `True` and block all trading forever (headroom = 0); (2) after the floor is genuinely reached once, a later losing streak that drops equity back below `floor_usd` would un-latch it, silently turning the floor guard off exactly when it matters most. `compute_floor_reached` fixes both: on a database with no prior `equity_history` rows (the very first cycle), it returns `False` (the starting stake is naturally at risk, per spec). On every later cycle, it returns `True` if either the historical max equity ever recorded, or this cycle's current equity, is `>= floor_usd` — sticky because the historical `MAX` query only grows, and immediate because it also checks the live value so the guard engages the same cycle equity first reaches the floor, not one cycle late.

- [ ] **Step 1: Write the failing test**

`tests/test_main.py`:
```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_main.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'main'`

- [ ] **Step 3: Implement `main.py`**

```python
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import analyst
import config as config_module
import executor_paper
import notifier
import risk_guard
import scanner
import storage

STOP_FILE = "STOP"


def compute_floor_reached(conn, current_equity_usd: float, floor_usd: float) -> bool:
    """Sticky latch: True once equity has ever reached floor_usd.

    On the very first cycle ever (no equity_history rows yet), returns
    False -- the seed capital is the starting stake, naturally at risk,
    not yet "recovered" principal. On every later cycle, returns True if
    either the historical max equity ever recorded, or the current
    cycle's live equity, is >= floor_usd. This is sticky (a later losing
    streak can't un-latch it, since MAX only grows) and immediate (it
    engages the same cycle equity first reaches the floor, not one cycle
    late).
    """
    row = conn.execute("SELECT COUNT(*) AS n, MAX(equity_usd) AS m FROM equity_history").fetchone()
    if row["n"] == 0:
        return False
    historical_max = row["m"]
    return historical_max >= floor_usd or current_equity_usd >= floor_usd


def run_cycle(cfg, conn, claude_client) -> dict:
    ts = datetime.now(timezone.utc).isoformat()
    markets = scanner.fetch_open_markets()
    markets_by_id = {m.market_id: m for m in markets}

    equity_usd, reserved_usd = storage.get_current_equity(conn)
    if equity_usd == 0.0 and reserved_usd == 0.0:
        equity_usd = cfg.floor_usd  # seed starting bankroll on the very first cycle

    # 1. Check open positions for stop-loss or confidence-reversal exits.
    # Price stop-loss is checked first since it's free (no API call); the
    # analyst is only re-consulted for positions that survive it, to avoid
    # paying for a Claude call on a position we're already closing.
    realized_pnl = 0.0
    for trade in storage.get_open_trades(conn):
        market = markets_by_id.get(trade["market_id"])
        if market is None:
            continue
        current_price = market.yes_price if trade["direction"] == "yes" else (1 - market.yes_price)

        if risk_guard.should_stop_loss(trade["entry_price"], current_price, cfg.stop_loss_pct):
            realized_pnl += executor_paper.close_paper_trade(
                conn, trade["id"], current_price, trade["entry_price"], trade["size_usd"], ts,
            )
            continue

        mispricing_pct = scanner.compute_mispricing_pct(market)
        fresh_decision = analyst.analyze_market(claude_client, market, mispricing_pct)
        if risk_guard.should_reverse_exit(trade["confidence"], fresh_decision.confidence):
            realized_pnl += executor_paper.close_paper_trade(
                conn, trade["id"], current_price, trade["entry_price"], trade["size_usd"], ts,
            )
    equity_usd += realized_pnl

    # 2. Scan for new opportunities
    shortlist = scanner.shortlist_candidates(markets, cfg.mispricing_threshold_pct, cfg.shortlist_size)
    cycle_id = storage.record_cycle(conn, ts, len(markets), json.dumps([m.market_id for m in shortlist]))

    floor_reached = compute_floor_reached(conn, equity_usd, cfg.floor_usd)
    trades_opened = 0
    for market in shortlist:
        mispricing_pct = scanner.compute_mispricing_pct(market)
        decision = analyst.analyze_market(claude_client, market, mispricing_pct)
        if not decision.trade:
            continue
        sizing = risk_guard.size_position(
            equity_usd, decision.confidence, cfg.kelly_cap_pct, cfg.floor_usd, floor_reached,
        )
        if sizing.blocked_reason:
            continue
        executor_paper.execute_paper_trade(
            conn, cycle_id, market, decision, sizing.size_usd, mispricing_pct, ts,
        )
        trades_opened += 1
        notifier.send_message(
            cfg.telegram_bot_token, cfg.telegram_chat_id,
            notifier.format_trade_alert(
                market.question, decision.direction, sizing.size_usd,
                decision.confidence, equity_usd, cfg.floor_usd, cfg.ceiling_usd,
            ),
        )

    # 3. Apply the ceiling sweep and persist equity
    equity_usd, reserved_usd = risk_guard.apply_ceiling(equity_usd, reserved_usd, cfg.ceiling_usd, cfg.floor_usd)
    storage.record_equity(conn, ts, equity_usd, reserved_usd)

    return {
        "cycle_id": cycle_id,
        "trades_opened": trades_opened,
        "equity_usd": equity_usd,
        "reserved_usd": reserved_usd,
    }


def main() -> None:
    if Path(STOP_FILE).exists():
        print("STOP file present, exiting without trading.")
        return

    cfg = config_module.load_config()
    conn = storage.init_db("trading.db")

    import anthropic
    claude_client = anthropic.Anthropic(api_key=cfg.anthropic_api_key)

    try:
        result = run_cycle(cfg, conn, claude_client)
        print(result)
    except Exception as exc:
        notifier.send_message(
            cfg.telegram_bot_token, cfg.telegram_chat_id,
            notifier.format_error_alert(1, str(exc)),
        )
        raise


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_main.py -v`
Expected: PASS

- [ ] **Step 5: Run the full test suite**

Run: `pytest -v`
Expected: All tests across every module PASS

- [ ] **Step 6: Commit**

```bash
git add main.py tests/test_main.py
git commit -m "feat: add main orchestrator wiring the full cycle together"
```

---

### Task 9: Task Scheduler wiring

**Files:**
- Create: `run_cycle.ps1`, `README.md`

**Interfaces:**
- Consumes: `main.py` (Task 8).
- Produces: a scheduled-task-friendly script; no new Python interfaces.

- [ ] **Step 1: Create the wrapper script**

`run_cycle.ps1`:
```powershell
$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot
& "$PSScriptRoot\.venv\Scripts\python.exe" "$PSScriptRoot\main.py" *>> "$PSScriptRoot\cycle.log"
```

- [ ] **Step 2: Create the setup README**

`README.md`:
```markdown
# Polymarket Paper-Trading Agent

## One-time setup

1. `python -m venv .venv`
2. `.venv\Scripts\pip install -r requirements.txt`
3. Copy `config.example.yaml` to `config.yaml` and `.env.example` to `.env`, fill in your Anthropic API key and Telegram bot token/chat ID.
4. Run once by hand to confirm it works: `.venv\Scripts\python main.py`
5. Register the 10-minute schedule (run once, as your own user, from a PowerShell prompt in this folder):

   ```powershell
   $action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$PWD\run_cycle.ps1`""
   $trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes 10) -RepetitionDuration ([TimeSpan]::MaxValue)
   Register-ScheduledTask -TaskName "PolymarketPaperBot" -Action $action -Trigger $trigger -Description "Runs the Polymarket paper-trading cycle every 10 minutes"
   ```

## Stopping it

Drop an empty file named `STOP` in this folder — the next cycle will see it and exit without trading. Delete the file to resume.

To fully remove the schedule: `Unregister-ScheduledTask -TaskName "PolymarketPaperBot" -Confirm:$false`

## After the paper-trading week

Run `python calibrate.py` to see which mispricing thresholds and hold times actually performed well, then adjust `config.yaml` by hand before considering live trading.
```

- [ ] **Step 3: Verify manually**

Run `main.py` by hand once (with a real or dummy `.env`/`config.yaml`) and confirm it either completes a cycle or fails with a clear, expected error (e.g. missing API key) rather than crashing unexpectedly. Create an empty `STOP` file and re-run to confirm it exits immediately with the "STOP file present" message, then delete `STOP`.

- [ ] **Step 4: Commit**

```bash
git add run_cycle.ps1 README.md
git commit -m "docs: add Task Scheduler wiring and setup instructions"
```

---

### Task 10: Calibration report

**Files:**
- Create: `calibrate.py`
- Test: `tests/test_calibrate.py`

**Interfaces:**
- Consumes: `storage.init_db`, `storage.record_cycle`, `storage.record_trade_open`, `storage.record_trade_close` (Task 2).
- Produces: `calibrate.build_report(conn) -> str`.

- [ ] **Step 1: Write the failing test**

`tests/test_calibrate.py`:
```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_calibrate.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'calibrate'`

- [ ] **Step 3: Implement `calibrate.py`**

```python
from collections import defaultdict
from datetime import datetime

import storage

THRESHOLD_BUCKETS = [(0, 5), (5, 8), (8, 15), (15, 1000)]
HOLD_TIME_BUCKETS_HOURS = [(0, 2), (2, 6), (6, 1000)]


def bucket_threshold(pct: float) -> str:
    for lo, hi in THRESHOLD_BUCKETS:
        if lo <= pct < hi:
            return f"{lo}-{hi}%"
    return "unknown"


def bucket_hold_time(hours: float) -> str:
    for lo, hi in HOLD_TIME_BUCKETS_HOURS:
        if lo <= hours < hi:
            return f"{lo}-{hi}h"
    return "unknown"


def hours_between(ts_opened: str, ts_closed: str) -> float:
    opened = datetime.fromisoformat(ts_opened)
    closed = datetime.fromisoformat(ts_closed)
    return (closed - opened).total_seconds() / 3600


def build_report(conn) -> str:
    rows = conn.execute("SELECT * FROM trades WHERE status='closed'").fetchall()

    by_threshold = defaultdict(list)
    by_hold_time = defaultdict(list)
    for row in rows:
        by_threshold[bucket_threshold(row["mispricing_pct"])].append(row["pnl_usd"])
        hold_hours = hours_between(row["ts_opened"], row["ts_closed"])
        by_hold_time[bucket_hold_time(hold_hours)].append(row["pnl_usd"])

    lines = ["=== Mispricing threshold buckets ==="]
    for bucket, pnls in sorted(by_threshold.items()):
        avg = sum(pnls) / len(pnls)
        lines.append(f"{bucket}: {len(pnls)} trades, avg P&L ${avg:.2f}")

    lines.append("")
    lines.append("=== Hold time buckets ===")
    for bucket, pnls in sorted(by_hold_time.items()):
        avg = sum(pnls) / len(pnls)
        lines.append(f"{bucket}: {len(pnls)} trades, avg P&L ${avg:.2f}")

    return "\n".join(lines)


if __name__ == "__main__":
    conn = storage.init_db("trading.db")
    print(build_report(conn))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_calibrate.py -v`
Expected: PASS

- [ ] **Step 5: Run the full test suite one more time**

Run: `pytest -v`
Expected: All tests across every module PASS

- [ ] **Step 6: Commit**

```bash
git add calibrate.py tests/test_calibrate.py
git commit -m "feat: add end-of-week calibration report"
```

---

## Deferred to a follow-up iteration

Per the user's preference to adjust as we go rather than lock everything up front, these spec items are intentionally left out of this first pass and can be added as their own small task once the base loop is running:

- **Daily Telegram summary** (spec asked for trade alerts + one daily digest; this plan wires trade/error alerts only — a daily summary is a small addition to `notifier.py` + a scheduled once-a-day check in `main.py`).
- **Live executor wiring** (`executor_live.py`), Polygon wallet setup, and any real-money flip — explicitly out of scope until the paper week is reviewed, per the spec.
- **Config-level validation that `floor_usd <= ceiling_usd`.** Task 3's review found that `risk_guard.apply_ceiling`'s sweep clamp (added to fix money-fabrication via negative `reserved_usd`) can still overstate tradable equity if `floor_usd > ceiling_usd` — a misconfiguration `config.py` doesn't currently reject. Parked because this plan is paper-mode only (no real money at risk) and the default config is safe; **must be fixed with a `config.py` load-time check before any live-trading task is scoped.**
- Anything from the spec's own "Open items deferred to later phases" section (ceiling-sweep-to-real-wallet automation, dashboard/UI beyond Telegram).
