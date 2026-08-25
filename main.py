import json
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
