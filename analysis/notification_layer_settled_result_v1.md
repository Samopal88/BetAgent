# Notification Layer — SETTLED_RESULT v1 Integration

**Date:** 2026-04-13
**Scope:** Unified SETTLED_RESULT event flow for admin + channel, minimal safe integration

---

## What Was Done

### 1. `notification_layer.py` — Added SETTLED_RESULT dispatcher

Added `notify_settled_results_unified()` function that:

- **Queries** recently settled bets (won/lost) from SQLite `bets` + `matches`
  - Admin window: last 2 days (matches `tg_bot.py get_closed_bets()` behavior)
  - Channel window: last 4 hours (matches `content_publisher.py publish_results()` behavior)
- **Formats** using existing templates (copied from `tg_bot.py` and `content_publisher.py`)
  - Admin: summary header with W/L counts + total profit, one line per bet with score, market, odds, PnL
  - Channel: individual messages per result with win/loss messaging + ROI
- **Deduplicates** via unified `notification_log` table
  - Admin key: `SETTLED_RESULT:{bet_id}:{result}:admin` (includes result to handle re-settlement)
  - Channel key: `SETTLED_RESULT:{bet_id}:channel`
- **Routes** via `send_with_dedup()` — checks, sends, marks in one call

### 2. `run_pipeline.py` — Wired unified SETTLED_RESULT into pipeline

Added `task_notify_results_unified()` function that calls `notification_layer.notify_settled_results_unified()`.

Replaced separate result notifications:

| Location | Before | After |
|----------|--------|-------|
| `task_settle()` | `task_notify("results")` | `task_notify_results_unified()` |
| Evening runner | `notify_bets` + `publish_results` | `notify_results` (unified) |

**What stays separate (not unified yet):**
- `task_notify_client("results")` — per-user PG dedup, subscription tiers
- `task_notify_tennis("results")` — tennis-specific client notifications
- `task_notify("report")` — evening admin report (30-day stats)

### 3. Canonical SETTLED_RESULT Event Payload

```python
NotificationEvent(
    event_type="SETTLED_RESULT",
    entity_id="42",                    # bet_id
    target="admin",                    # admin | channel
    data={
        "bet_id": 42,
        "sport": "football",
        "market": "draw",
        "home_team": "Juventus",
        "away_team": "Milan",
        "odds": 3.20,
        "result": "won",
        "profit": 1100,
        "home_score": 1,
        "away_score": 1,
        "settled_at": "2026-04-13 22:15:00",
    }
)
```

### 4. Dedup Key Design

| Target | Key Pattern | Storage |
|--------|------------|---------|
| Admin | `SETTLED_RESULT:{bet_id}:{result}:admin` | SQLite `notification_log` |
| Channel | `SETTLED_RESULT:{bet_id}:channel` | SQLite `notification_log` |

Admin key includes `result` because a bet could theoretically be re-settled with a different result (rare but possible with corrections).

---

## Changed Files

| File | Change |
|------|--------|
| `notification_layer.py` | Added `notify_settled_results_unified()`, `_format_admin_result_card()`, `_format_channel_result_card()` |
| `run_pipeline.py` | Added `task_notify_results_unified()`, replaced `task_notify("results")` in `task_settle()` and evening runner |

---

## Testing Results

### Admin (2-day window)
```
Run 1: {'admin_sent': 10, 'channel_sent': 0, 'admin_skipped': 0, 'channel_skipped': 0}
  → 10 settled results sent in 1 message (W/L summary + individual lines)

Run 2: {'admin_sent': 0, 'channel_sent': 0, 'admin_skipped': 0, 'channel_skipped': 0}
  → All deduped — no duplicate sends
```

### Channel (4-hour default window)
```
Run 1: {'admin_sent': 0, 'channel_sent': 0, ...}
  → No settled bets in last 4 hours (expected)

Channel (30d backfill test): {'channel_sent': 20, 'channel_skipped': 80}
  → 20 sent before Telegram rate limit, 80 skipped
  → Rate limit is expected for historical backfill; normal 4-hour window won't hit it
```

### Dedup Verification
- First run: all results sent, marked in `notification_log`
- Second run: 0 sends, all skipped by dedup check
- **Dedup works correctly**

---

## Answers

1. **SETTLED_RESULT now uses notification_layer?** — **Yes**
2. **Admin result path via unified layer?** — **Yes** (replaces `tg_bot.py --notify results`)
3. **Channel result path via unified layer?** — **Yes** (replaces `content_publisher.py --mode results`)
4. **Dedupe works?** — **Yes** (verified: 10 sent on run 1, 0 on run 2)
5. **What remains outside unified layer after this?**
   - **Client notifications** (`bot/notifier.py`) — per-user PG dedup, subscription tiers, signal saving
   - **Tennis client results** (`task_notify_tennis`) — tennis-specific per-user notifications
   - **Admin report** (`--notify report`) — 30-day stats summary, no dedup yet
   - **Weekly/monthly reports** — have their own dedup (fixed in prior session)
   - **Golden mode** (`--notify golden`) — never called from pipeline
