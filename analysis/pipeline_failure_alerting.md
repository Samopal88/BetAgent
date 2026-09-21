# Pipeline Failure Alerting

**Date:** 2026-04-14
**Status:** Complete

---

## What Was Added

### New file: `pipeline_alerting.py` (~160 lines)

| Function | Purpose |
|----------|---------|
| `_classify_task(name)` | Classify task as CRITICAL or WARNING severity |
| `_build_alert_text(summary)` | Build formatted Telegram message from RunSummary, returns None if no alertable failures |
| `_send_telegram(text)` | Direct Telegram Bot API POST to admin chat |
| `send_pipeline_alert(summary)` | Public API — fire-and-forget alert dispatcher |

### Changes to `run_pipeline.py`

1. Added import: `from pipeline_alerting import send_pipeline_alert`
2. Added `send_pipeline_alert(summary)` call after `summary.save()` in all 5 runners:
   - `run_morning()`
   - `run_afternoon()`
   - `run_evening()`
   - `run_night()`
   - `run_full()`

---

## Alert Logic

### When an alert IS sent

1. At least one task failed (`not t.success`)
2. AND either:
   - A CRITICAL task failed (parse, enrich, bet, settle, normalize), OR
   - `fail_fast_triggered` is True

### When an alert is NOT sent

- All tasks succeeded — no alert on clean runs
- Only non-critical tasks failed (archive, notify, tennis_results) AND fail_fast was NOT triggered — these are logged but don't warrant Telegram spam

### Severity classification

| Severity | Tasks |
|----------|-------|
| CRITICAL | `parse`, `enrich_football`, `enrich_hockey`, `bet_football`, `bet_hockey`, `bet_tennis`, `settle`, `normalize` |
| WARNING | `archive_snapshot`, `tennis_results`, `tennis_settle`, `notify_*`, `parse_football_stats` |

### Alert message format

```
🔴 CRITICAL Pipeline Failure
Runner: morning
Time: 2026-04-14 08:00:15
Mode: LIVE

Failed tasks:
  🔴 parse (12.3s)
     TimeoutExpired: Command timed out after 1200s

Skipped (5):
  ⏭ enrich_football
  ⏭ enrich_hockey
  ⏭ bet_football
  ⏭ bet_hockey
  ⏭ bet_tennis

FAIL-FAST: Parse failed — skipping enrich and analysis

Tasks: 1/6 ok, 1 failed, 5 skipped
```

---

## Safety Guarantees

| Requirement | How it's met |
|-------------|-------------|
| Never crash pipeline | `send_pipeline_alert()` wraps everything in try/except, logs errors |
| No spam on success | Returns early if `_build_alert_text()` returns None |
| One alert per run | All failures collected into single message, not per-task |
| Deduplication | Telegram dedup is inherent — one POST per run |
| No dependency on betting logic | Pure alerting module, only imports `RunSummary` type |
| No global state | Stateless functions, reads env vars at import time |

---

## Delivery Path

```
run_pipeline.py runner
    └── summary.save()
    └── send_pipeline_alert(summary)
            ├── _build_alert_text(summary) → formatted string or None
            └── _send_telegram(text) → requests.post to Telegram Bot API
```

Uses direct `requests.post` to Telegram Bot API (`/sendMessage` endpoint), not the `tg_bot.py` notify flow. This avoids coupling to the bot's notification dedup tables and keeps the alerting path minimal and independent.

Falls back gracefully if `TELEGRAM_BOT_TOKEN` or `TELEGRAM_CHAT_ID` are not set.

---

## Dependencies

`pipeline_alerting.py` imports:
- `logging`, `os`, `time`, `datetime`, `pathlib`, `typing` (stdlib)
- `requests` (for Telegram delivery — already a project dependency via tg_bot.py)

No DB, no global state, no coupling to betting/model/rule logic.
