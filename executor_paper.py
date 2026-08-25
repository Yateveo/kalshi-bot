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
