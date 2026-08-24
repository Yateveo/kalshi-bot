# Polymarket Paper-Trading Agent — Design Spec

Date: 2026-08-25
Status: Approved for implementation planning

## Purpose

Build a personal, self-hosted trading agent for Polymarket prediction
markets, inspired by a viral demo of an autonomous "Grok Bot." The
agent scans open markets, uses Claude to reason about mispricings, and
sizes bets conservatively. It starts in **paper mode** (simulated
fills, no real money) for a one-week trial, then a human reviews a
calibration report and decides whether/how to flip it to live trading.

Claude (the assistant) never holds funds, wallet keys, or executes
real trades on the user's behalf. The user hosts and runs this project
themselves, on their own machine, with their own API keys and (later)
their own Polymarket wallet.

## Success criteria

- Runs unattended on a 10-minute schedule via Windows Task Scheduler.
- Produces a full audit trail (every cycle, every decision, every
  trade) in a local database.
- Never allows equity to fall below the configured floor once it's
  been reached; sweeps profit above the configured ceiling into a
  non-tradable reserve.
- After ~1 week of paper trading, produces a plain-language
  calibration report the user can act on manually.
- Live trading is a separate, later phase — this spec covers paper
  mode end-to-end; the live executor is stubbed but not wired to a
  real wallet yet.

## Non-goals

- No live X/Twitter sentiment feed (Claude doesn't have Grok's native
  access to it). Mispricing signal is derived from Polymarket's own
  price/volume behavior instead.
- No automated self-tuning of thresholds. Calibration after the paper
  week is a report for the human to review, not code that rewrites
  its own rules.
- No cloud hosting in this phase — runs on the user's own machine.
- No UI/dashboard — Telegram messages are the interface.

## Architecture

One 10-minute cycle, orchestrated by `main.py`:

1. **Scanner** — pulls open markets from Polymarket's public
   read-only API (Gamma/CLOB market data endpoints; no wallet or
   auth required for this). Computes a cheap statistical mispricing
   score per market from price/volume momentum vs. a naive fair-value
   estimate. Produces a shortlist of the top ~5–10 candidates whose
   mispricing exceeds a configurable threshold (default 8%).

2. **Analyst** — sends the shortlist to Claude (via the user's own
   Anthropic API key) with each market's question, resolution
   criteria, current odds, and recent price history. Claude returns a
   structured decision per market: trade/no-trade, direction,
   confidence (0–1), and a short rationale, via a strict JSON/tool-use
   schema (no free-text parsing of the trading decision itself).

3. **Risk Guard** — pure code, no LLM involved, and the most
   heavily-tested part of the system:
   - Position size = Kelly fraction from Claude's stated confidence,
     **hard-capped at 6% of current bankroll** regardless of what
     Kelly math suggests.
   - **Floor rule**: once equity has reached the floor (default $50,
     i.e. the original principal), no trade may be sized in a way
     that could bring equity below the floor. Below-floor bankroll
     shrinks position sizes toward zero rather than blocking outright
     at the very start (before the floor has ever been reached, the
     original $50 is naturally at risk — that's the starting stake).
   - **Ceiling rule**: whenever equity is at or above the ceiling
     (default $75), the amount above the floor is swept into a
     separate non-tradable "reserved" balance. Only the floor amount
     stays in the active trading balance.
   - **Stop-loss**: open positions are re-checked each cycle; if a
     position's current implied value has dropped beyond a
     configurable stop-loss threshold (default 25%), or Claude's
     re-evaluated confidence has reversed, the guard closes it.
   - All thresholds (Kelly cap %, floor, ceiling, stop-loss %,
     mispricing threshold %) live in one config file, tunable without
     touching code.

4. **Executor** — a common interface with two implementations:
   - `executor_paper`: simulates a fill at the current best bid/ask
     from the order book, updates simulated balance, logs the trade.
     This is what runs during the one-week trial. No wallet needed.
   - `executor_live`: places a real signed order via Polymarket's CLOB
     client. Not wired up or exercised in this phase — stubbed only,
     and only usable once the user has generated and funded their own
     Polygon wallet and reviewed the paper results.

5. **Storage** — local SQLite database logging every cycle (markets
   scanned, shortlist, decisions, trades, equity over time) for a full
   audit trail and for the calibration report to query.

6. **Notifier** — Telegram bot (user's own bot token) sends a message
   on every trade and on repeated errors, plus one daily summary.
   Not every no-op cycle, to avoid spam.

7. **Calibrate** — an offline script run after the trial week. Groups
   logged trades by mispricing-threshold bucket and hold-time bucket,
   reports which buckets actually made/lost money, and suggests
   parameter changes. Output is a plain report; the user edits the
   config file by hand if they agree.

## Error handling & safety

- API failures (Polymarket or Anthropic) are logged and the cycle is
  skipped — never a crash loop. Repeated failures (e.g. 3 in a row)
  trigger a Telegram alert.
- A `STOP` file in the project root, checked first thing by `main.py`,
  causes an immediate clean exit with no trading — a manual kill
  switch that doesn't require touching Task Scheduler.
- Missed scheduler runs (e.g. laptop asleep) are safe to resume from —
  all state (equity, open positions) is read from SQLite, not memory.

## Configuration & secrets

`config.yaml` — all tunable thresholds (mispricing %, Kelly cap %,
floor $, ceiling $, stop-loss %, shortlist size).

`.env` (git-ignored) — `ANTHROPIC_API_KEY`, `TELEGRAM_BOT_TOKEN`,
`TELEGRAM_CHAT_ID`. A `POLYGON_WALLET_KEY` placeholder is documented
but not required until the live phase, and is never sent to Claude or
committed anywhere.

## Testing strategy

- TDD on `risk_guard` first: Kelly math, floor/ceiling boundary
  conditions (including the exact-equals cases), stop-loss triggers.
  This is the code that actually protects the user's money, so it
  gets the most rigorous coverage.
- `scanner`/`analyst` tested against recorded fixture market data
  (sample JSON snapshots), not live API calls, so tests are fast and
  deterministic.
- `executor_paper` tested for correct simulated fill and P&L
  bookkeeping.
- One end-to-end dry-run cycle test over fixtures before the code is
  ever pointed at the real Polymarket API.

## Open items deferred to later phases

- Live executor wiring and wallet setup (only after paper week review).
- Whether the reserved/ceiling balance should later be swept to an
  actual separate wallet automatically, or just tracked and withdrawn
  manually.
- Any dashboard/web UI beyond Telegram (explicitly out of scope now).
