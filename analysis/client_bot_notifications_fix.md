# Client Bot Notifications — Fix Report

**Date:** 2026-04-15
**Status:** FIXED + VERIFIED

---

## 1. Change Applied

### File: `run_pipeline.py`

**Location:** `run_full()` function, line 759-762

**Before:**
```python
run_task("archive_snapshot", lambda: task_archive_snapshot(), summary=summary)
run_task("notify_unified", lambda: task_notify_unified(), summary=summary)

summary.ended_at = ...
```

**After:**
```python
run_task("archive_snapshot", lambda: task_archive_snapshot(), summary=summary)
run_task("notify_unified", lambda: task_notify_unified(), summary=summary)
run_task("notify_client", lambda: task_notify_client("bets"), summary=summary)
run_task("notify_tennis_bets", lambda: task_notify_tennis("bets"), summary=summary)

summary.ended_at = ...
```

### What this does:

- `task_notify_client("bets")` → runs `bot/notifier.py --mode bets` → sends new bet notifications to all subscribers via client bot
- `task_notify_tennis("bets")` → runs `bot/notifier.py --mode bets --tennis` → sends tennis signal notifications to all subscribers

### Alignment with other runners:

| Runner | notify_client("bets") | notify_tennis("bets") |
|--------|----------------------|----------------------|
| `run_morning()` | YES | YES |
| `run_afternoon()` | YES | YES |
| `run_evening()` | YES (bets+results) | YES (bets+results) |
| `run_night()` | YES | YES |
| **`run_full()`** | **NOW YES** | **NOW YES** |

---

## 2. Duplicate Send Risk — NONE

Deduplication is handled at the `bot/notifier.py` level via PostgreSQL `client_notifications` table:

- **Bet notifications**: per-user key `bet_{bet_id}_u{user_id}` with `ON CONFLICT DO NOTHING`
- **Tennis notifications**: per-user key `tennis_{mode}_{signal_id}_u{user_id}` with `ON CONFLICT DO NOTHING`

Each user can only be notified once per bet/signal. Running the notification task multiple times is safe — subsequent runs find all bets already marked as notified and skip them.

---

## 3. Verification Results

### Bet notifications (notify_new_bets)

| Metric | Value |
|--------|-------|
| Pending bets found (last 24h) | 6 (bets 919-924, all tennis) |
| Active subscribers | 29 |
| Successfully notified | 21/29 |
| Failed (blocked bot / invalid ID) | 8/29 (users 17, 19, 24-29 + test user 123456789) |
| Notifications created in PG | 126 rows in `client_notifications` |
| **Dedup test (2nd run)** | **0 notifications sent** — confirmed working |

### Tennis notifications (notify_tennis_signals)

| Metric | Value |
|--------|-------|
| Tennis signals found (last 24h) | 8 |
| Successfully notified | 21/29 |
| Failed | 8/29 (same users — blocked bot) |

### Users who never received notifications (before fix)

10 users (ids 17, 19, 24-29) had zero entries in `client_notifications`. After this fix, they will receive notifications on the next pipeline run. 8 of them have blocked the bot or have invalid telegram_id, so those will continue to fail until they unblock.

---

## 4. No Other Changes

- `bot/notifier.py` — unchanged
- `task_notify_client()` — unchanged (already existed, just wasn't called from `run_full`)
- `task_notify_tennis()` — unchanged (already existed, just wasn't called from `run_full`)
- `notification_layer.py` — unchanged (admin/channel path, separate from client path)
- No changes to dedup logic, message formatting, or subscriber queries

---

## 5. Answers

| Question | Answer |
|----------|--------|
| **Fixed in run_full()?** | **YES** — 2 lines added: `notify_client` + `notify_tennis_bets` |
| **Client bot now receives new bets?** | **YES** — verified: 21/29 users notified, 126 PG rows created |
| **Tennis client notifications included?** | **YES** — verified: 21/29 users notified |
| **Duplicate send risk introduced?** | **NO** — per-user dedup via `client_notifications` table confirmed working (2nd run = 0 sends) |
