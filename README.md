# Kalshi Paper-Trading Agent

Originally built for Polymarket, then switched to [Kalshi](https://kalshi.com) after the
Czech Ministry of Finance added Polymarket to its unauthorized-gambling blocklist and
ISPs started blocking it. Kalshi is CFTC-regulated and available in Czech Republic.

## One-time setup

1. `python -m venv .venv`
2. `.venv\Scripts\pip install -r requirements.txt`
3. Copy `config.example.yaml` to `config.yaml` and `.env.example` to `.env`, fill in your Anthropic API key. Telegram is optional -- leave `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID` blank and the bot prints trade/error alerts to the console (captured in `cycle.log`) instead.
4. Run once by hand to confirm it works: `.venv\Scripts\python main.py`
5. Register the 10-minute schedule (run once, as your own user, from a PowerShell prompt in this folder):

   ```powershell
   $action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$PWD\run_cycle.ps1`""
   $trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes 10) -RepetitionDuration (New-TimeSpan -Days 3650)
   Register-ScheduledTask -TaskName "KalshiPaperBot" -Action $action -Trigger $trigger -Description "Runs the Kalshi paper-trading cycle every 10 minutes"
   ```

No Kalshi account or API key is needed for this paper-trading phase -- market and trade data are pulled from Kalshi's public, unauthenticated endpoints.

## Stopping it

Drop an empty file named `STOP` in this folder — the next cycle will see it and exit without trading. Delete the file to resume.

To fully remove the schedule: `Unregister-ScheduledTask -TaskName "KalshiPaperBot" -Confirm:$false`

## After the paper-trading week

Run `python calibrate.py` to see which mispricing thresholds and hold times actually performed well, then adjust `config.yaml` by hand before considering live trading.

## Known limitations of this paper-trading phase

- No live X/Twitter sentiment feed (Claude doesn't have that access) — the mispricing signal comes from Kalshi's own real trade prints instead: [scanner.py](scanner.py) treats a ticker's earliest trade price in the last hour as the "before" price and compares it to the current price. Kalshi's `previous_price_dollars` field looked like the obvious source for this but is empty even on actively-traded markets, so this was built from `GET /markets/trades` instead.
- The scanner only considers tickers that actually traded in the last hour (`GET /markets/trades`), not Kalshi's full open-markets catalog -- a raw page of `/markets` is overwhelmingly inactive/combo markets with no price signal at all.
- **Worth watching in calibration:** the current top mispricing candidates tend to be very short-dated markets (e.g. "price up in next 15 mins?"). Those swing hard right before expiry as a matter of course, which isn't the same thing as genuine mispricing -- the hold-time buckets in `calibrate.py`'s report should reveal if these are actually losers. A minimum time-to-resolution filter in the scanner is an easy follow-up if so.
- No daily Telegram summary yet — only trade and error alerts, and only if Telegram is configured at all (otherwise they print to the console/`cycle.log`). A daily digest is a small follow-up.
- `config.py` does not yet validate that `floor_usd <= ceiling_usd`. The defaults are safe; this must be added before any live-money phase.
- Live trading (`executor_live.py`) is entirely out of scope until the paper week's results are reviewed. Kalshi's real trading endpoints require an account, KYC, and API key auth (RSA-signed requests) -- none of that is needed or used in this paper-trading phase.
