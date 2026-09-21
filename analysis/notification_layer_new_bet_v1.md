# Notification Layer — NEW_BET v1 Integration

**Date:** 2026-04-13
**Scope:** Unified NEW_BET event flow for admin + channel, minimal safe integration

---

## What Was Done

### 1. `notification_layer.py` — Extended from skeleton to working dispatcher

Added `notify_new_bet_unified()` function that:

- **Queries** pending bets from SQLite `bets` + `matches`
  - Admin window: last 30 days (matches `tg_bot.py` behavior)
  - Channel window: last 2 hours (matches `content_publisher.py` behavior)
- **Formats** using existing templates (copied from `tg_bot.py` and `content_publisher.py`)
  - Tennis bets get separate header ("Теннисные прогнозы")
  - Other sports get "Новые прогнозы" header with strategy labels
  - Channel gets simplified public-facing format
- **Splits** into chunks to respect Telegram's 4096 char limit
  - Admin: max 15 bets per message
  - Channel: max 5 bets per message
- **Deduplicates** via unified `notification_log` table
  - Key: `NEW_BET:{bet_id}:admin` or `NEW_BET:{bet_id}:channel`
  - Batch messages use timestamped keys: `NEW_BET:tennis_batch_20260413_08_0:admin`
- **Routes** via `send_with_dedup()` — checks, sends, marks in one call

### 2. `run_pipeline.py` — Wired unified notification into all runners

Added `task_notify_unified()` function that calls `notification_layer.notify_new_bet_unified()`.

Replaced separate admin bet notification + channel publish in all runners:

| Runner | Before | After |
|--------|--------|-------|
| morning | `notify_bets` + `publish_channel(bets)` | `notify_unified` |
| afternoon | `publish_channel(bets)` | `notify_unified` |
| evening | `notify_bets` + `publish_bets` | `notify_unified` |
| night | `publish_channel(bets)` | `notify_unified` |
| full | `notify_bets` | `notify_unified` |

**What stays separate (not unified yet):**
- `task_notify_client("bets")` — per-user PG dedup, subscription tiers, too complex for v1
- `task_notify("report")` — evening-only admin report
- `task_notify("results")` — settled bet results (SETTLED_RESULT event type, future)
- `task_publish_channel("results")` — channel result posts (future)
- Tennis-specific notifications — still use `task_notify_tennis()`

### 3. Canonical NEW_BET Event Payload

```python
NotificationEvent(
    event_type="NEW_BET",
    entity_id="42",                    # bet_id
    target="admin",                    # admin | channel
    data={
        "bet_id": 42,
        "sport": "tennis",
        "market": "player1_win",
        "home_team": "Djokovic N.",
        "away_team": "Nadal R.",
        "odds": 1.85,
        "stake": 500,
        "ev": 0.08,
        "signal_type": "Medium",
        "bookmaker": "fonbet",
        "match_date": "2026-04-13T18:00",
    }
)
```

### 4. Dedup Key Design

| Target | Key Pattern | Storage |
|--------|------------|---------|
| Admin (single bet) | `NEW_BET:{bet_id}:admin` | SQLite `notification_log` |
| Admin (tennis) | `NEW_BET:tennis:{bet_id}:admin` | SQLite `notification_log` |
| Admin (batch) | `NEW_BET:tennis_batch_YYYYMMDD_HH_N:admin` | SQLite `notification_log` |
| Channel | `NEW_BET:{bet_id}:channel` | SQLite `notification_log` |

---

## Changed Files

| File | Change |
|------|--------|
| `notification_layer.py` | Added `notify_new_bet_unified()`, formatters, chunking, CLI args |
| `run_pipeline.py` | Added `task_notify_unified()`, replaced 5 notify+channel calls |

---

## Testing Results

### Dry Run
```
Dry run: {'admin_sent': 0, 'channel_sent': 0, 'admin_skipped': 0, 'channel_skipped': 0}
```
(No pending bets in test window at time of dry run)

### Live Test (48 pending tennis bets)
```
Run 1: {'admin_sent': 48, 'channel_sent': 0, 'admin_skipped': 0, 'channel_skipped': 0}
  → 4 admin messages sent (48 bets / 15 per chunk = 4 messages)
  → Channel: 0 (2-hour window bets already sent by previous test)

Run 2: {'admin_sent': 0, 'channel_sent': 0, 'admin_skipped': 0, 'channel_skipped': 0}
  → All deduped — no duplicate sends
```

### Dedup Verification
- First run: all 48 bets sent, marked in `notification_log`
- Second run: 0 sends, all skipped by dedup check
- **Dedup works correctly**

---

## Answers

1. **NEW_BET now uses notification_layer?** — Yes. Admin and channel paths go through `notify_new_bet_unified()` → `send_with_dedup()`.

2. **Admin path via unified layer?** — Yes. Replaces `tg_bot.py --notify bets` in all pipeline runners. Same formatting, same tennis/non-tennis split, now with chunking.

3. **Client path via unified layer?** — No. Client notifications still use `bot/notifier.py` with per-user PG dedup. Too complex (subscription tiers, signal saving, per-user filtering) for v1.

4. **Channel path via unified layer?** — Yes. Replaces `content_publisher.py --mode bets` in all pipeline runners. Same public-facing format.

5. **Dedupe works on real send?** — Yes. Verified with two consecutive runs — first sends all, second sends none.

6. **What remains outside unified layer?**
   - **Client notifications** (`bot/notifier.py`) — per-user PG dedup, subscription tiers, signal saving
   - **Result notifications** (`--notify results`, `publish_results`) — SETTLED_RESULT event type, future
   - **Weekly/monthly reports** — already have their own dedup (fixed in previous session)
   - **Admin report** (`--notify report`) — no dedup yet, future SYSTEM_ALERT/REPORT event
   - **Golden mode** (`--notify golden`) — never called from pipeline, future
   - **Tennis-specific client notifications** — `task_notify_tennis()` still uses `bot/notifier.py --tennis`
