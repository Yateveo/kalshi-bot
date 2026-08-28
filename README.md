# Polymarket Paper-Trading Agent

## One-time setup

1. `python -m venv .venv`
2. `.venv\Scripts\pip install -r requirements.txt`
3. Copy `config.example.yaml` to `config.yaml` and `.env.example` to `.env`, fill in your Anthropic API key. Telegram is optional -- leave `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID` blank and the bot prints trade/error alerts to the console (captured in `cycle.log`) instead.
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

## Known limitations of this paper-trading phase

- No live X/Twitter sentiment feed (Claude doesn't have that access) — mispricing signal comes from Polymarket's own price/volume momentum instead.
- No daily Telegram summary yet — only trade and error alerts, and only if Telegram is configured at all (otherwise they print to the console/`cycle.log`). A daily digest is a small follow-up.
- `config.py` does not yet validate that `floor_usd <= ceiling_usd`. The defaults are safe; this must be added before any live-money phase.
- Live trading (`executor_live.py`) is entirely out of scope until the paper week's results are reviewed.
