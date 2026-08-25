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
