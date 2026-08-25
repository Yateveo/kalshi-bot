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
