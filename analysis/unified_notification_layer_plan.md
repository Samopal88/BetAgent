# Unified Notification Layer — Plan

**Date:** 2026-04-13
**Scope:** Design unified notification architecture, identify bugs, propose minimal safe first step

---

## Current State: 5 Notification Endpoints, 3 Bots, 4 Dedup Systems

### Endpoint Map

| # | File | Bot Token | Destination | Modes | Dedup | Status |
|---|------|-----------|-------------|-------|-------|--------|
| 1 | `tg_bot.py` (638 lines) | `TELEGRAM_BOT_TOKEN` | Admin chat (`TELEGRAM_CHAT_ID`) | bets, results, golden, report, test | SQLite `tg_notifications` (global) | WORKING |
| 2 | `bot/notifier.py` (553 lines) | `CLIENT_BOT_TOKEN` | Individual subscribers (PG `users.telegram_id`) | bets, results (with `--tennis` flag) | PG `client_notifications` (per-user) | WORKING (fragile) |
| 3 | `bot/client_bot.py` (1023 lines) | `CLIENT_BOT_TOKEN` | Interactive subscriber bot | N/A (interactive) | N/A | WORKING (has dead code) |
| 4 | `content_publisher.py` (279 lines) | `CHANNEL_BOT_TOKEN` | Telegram channel (`CHANNEL_ID`) | bets, results, weekly, monthly | SQLite `channel_sent_log` (global) | WORKING (has bug) |
| 5 | `bot/weekly_notify.py` (104 lines) | `CLIENT_BOT_TOKEN` | Active subscribers (PG query) | weekly only | NONE | WORKING (no dedup) |

### Pipeline Call Schedule

| Runner | Admin (`tg_bot.py`) | Client (`notifier.py`) | Tennis (`notifier.py --tennis`) | Channel (`content_publisher.py`) |
|--------|---------------------|------------------------|--------------------------------|----------------------------------|
| morning 08:00 | `notify(bets)` | `notify_client(bets)` | — | `publish(bets)` |
| afternoon 14:00 | — | `notify_client(bets)` | — | `publish(bets)` |
| evening 21:00 | `notify(bets)` + `notify(report)` | `notify_client(bets)` + `notify_client(results)` | `notify_tennis(results)` | `publish(bets)` + `publish(results)` |
| night 23:30 | — | `notify_client(bets)` | — | `publish(bets)` |

### Crontab Additions

| Schedule | Command | Destination |
|----------|---------|-------------|
| Sun 20:00 | `content_publisher.py --mode weekly` | Public channel |
| 1st 10:00 | `content_publisher.py --mode monthly` | Public channel |
| Sun 12:00 | `bot/weekly_notify.py` | Individual subscribers |

---

## Problems Found

### P1 — Bugs (broken functionality)

| # | File | Issue | Impact |
|---|------|-------|--------|
| 1 | `content_publisher.py:210` | `publish_weekly()` references `conn2` before walrus assignment — `NameError` | Weekly channel posts missing "accumulated live ROI" line |
| 2 | `bot/weekly_notify.py` | No deduplication — if cron fires twice, subscribers get duplicate weekly messages | Spam risk |
| 3 | `bot/notifier.py:481` | If `bets.settled_at` column missing, `notify_results()` silently skips | Client result notifications silently fail |

### P2 — Data Inconsistency

| # | Issue | Detail |
|---|-------|--------|
| 4 | Three different stats sources | `tg_bot.py` reads SQLite `bets`, `weekly_notify.py` reads PG `signals`, `content_publisher.py` reads SQLite `bets` — same "weekly stats" concept, different numbers |
| 5 | Tennis double-sending | `notify_new_bets()` includes tennis bets; `notify_tennis_signals()` also sends tennis bets. Different dedup keys, so same signal can go twice |
| 6 | `report` mode no dedup | `tg_bot.py --notify report` always sends — if evening pipeline runs twice, admin gets duplicate reports |

### P3 — Architecture Gaps

| # | Issue | Detail |
|---|-------|--------|
| 7 | `golden` never called from pipeline | `tg_bot.py` supports `--notify golden` but `task_notify()` doesn't expose it |
| 8 | `client_bot.py` auto-fires notifier on startup | Every restart re-sends all un-notified bets — intentional but risky |
| 9 | `client_bot.py` dead code | Email verification handler duplicated (lines 796-823 and 826-853), unreachable code path |
| 10 | No unified event types | Each endpoint defines its own message format, no canonical event model |

---

## Source of Truth Analysis

| Notification Type | Current Source | Should Be |
|-------------------|---------------|-----------|
| New bet alerts (admin) | SQLite `bets` WHERE `result='pending'` AND `created_at >= 30d` | SQLite `bets` (correct) |
| New bet alerts (client) | SQLite `bets` WHERE `result='pending'` AND `created_at >= 24h` | SQLite `bets` (correct) |
| New bet alerts (channel) | SQLite `bets` WHERE `result='pending'` AND `created_at >= 2h` | SQLite `bets` (correct) |
| Settled result alerts (admin) | SQLite `bets` WHERE `result IN ('won','lost')` AND `settled_at >= 2d` | SQLite `bets` (correct) |
| Settled result alerts (client) | SQLite `bets` WHERE `settled_at >= 24h` | SQLite `bets` (correct) |
| Weekly report (channel) | SQLite `bets` last 7 days | SQLite `bets` (correct) |
| Weekly report (subscribers) | PG `signals` last 7 days | Should match channel source (SQLite `bets`) |
| Monthly report (channel) | SQLite `bets` last 30 days | SQLite `bets` (correct) |

**Verdict:** The data sources are mostly correct. The inconsistency is that `bot/weekly_notify.py` reads PG `signals` while `content_publisher.py` reads SQLite `bets` — they report different numbers for the same "weekly stats" concept.

---

## Proposed Unified Notification Architecture

### Layer Model

```
┌─────────────────────────────────────────────────────────┐
│                    EVENT SOURCE LAYER                    │
│  Queries SQLite bets / signals / normalized_results      │
│  Produces canonical NotificationEvent objects            │
└──────────────────────┬──────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────┐
│                    FORMATTER LAYER                       │
│  Renders event → text per target (admin/client/channel)  │
│  Each target has its own template                        │
└──────────────────────┬──────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────┐
│                    ROUTER LAYER                          │
│  Routes event to appropriate targets based on:           │
│  - event type (NEW_BET, SETTLED, REPORT, ALERT)          │
│  - sport (tennis has separate path)                      │
│  - target config (admin, client, channel)                │
└──────────────────────┬──────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────┐
│                    DEDUP / SENT-STATE                    │
│  Unified dedup check before send:                        │
│  - key = "{event_type}:{entity_id}:{target}"             │
│  - Storage: SQLite notification_log (unified table)      │
│  - Per-user dedup for client: PG client_notifications    │
└──────────────────────┬──────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────┐
│                    SEND LAYER                            │
│  Thin adapters per bot:                                  │
│  - send_admin(text) → TELEGRAM_BOT_TOKEN → chat_id       │
│  - send_client(text, user_id) → CLIENT_BOT_TOKEN         │
│  - send_channel(text) → CHANNEL_BOT_TOKEN → CHANNEL_ID   │
└─────────────────────────────────────────────────────────┘
```

### Canonical Event Types

| Type | Trigger | Data Required | Targets |
|------|---------|---------------|---------|
| `NEW_BET` | New pending bet created | bet_id, sport, teams, market, odds, stake, ev, strategy | admin, client, channel |
| `SETTLED_RESULT` | Bet settled (won/lost) | bet_id, sport, teams, market, result, profit, odds | admin, client, channel |
| `WEEKLY_REPORT` | Sunday scheduled run | wins, losses, winrate, roi, bank_change | channel, subscribers |
| `MONTHLY_REPORT` | 1st of month scheduled run | Same as weekly + monthly trend | channel |
| `SYSTEM_ALERT` | Pipeline failure, stale bets | alert_type, message, severity | admin only |

### Dedup Key Design

| Event Type | Key Pattern | Storage |
|------------|-------------|---------|
| `NEW_BET` | `new_bet:{bet_id}:{target}` | SQLite `notification_log` |
| `SETTLED_RESULT` | `settled:{bet_id}:{result}:{target}` | SQLite `notification_log` |
| `WEEKLY_REPORT` | `weekly:{year}:{week}:{target}` | SQLite `notification_log` |
| `MONTHLY_REPORT` | `monthly:{year}:{month}:{target}` | SQLite `notification_log` |
| `SYSTEM_ALERT` | `alert:{type}:{date}` | SQLite `notification_log` |

For per-user client notifications, keep existing PG `client_notifications` table with key `bet_{id}_u{user_id}`.

### Unified Table Proposal

```sql
CREATE TABLE IF NOT EXISTS notification_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL,       -- NEW_BET, SETTLED_RESULT, WEEKLY_REPORT, etc.
    entity_id TEXT NOT NULL,        -- bet_id, weekly_2026_15, etc.
    target TEXT NOT NULL,           -- admin, client, channel
    notify_key TEXT NOT NULL,       -- full dedup key
    sent_at TEXT DEFAULT (datetime('now')),
    UNIQUE(event_type, entity_id, target)
);
```

This replaces the three separate dedup tables (`tg_notifications`, `channel_sent_log`, and could coexist with PG `client_notifications`).

---

## What NOT to Change (Yet)

- `bot/client_bot.py` — interactive bot, works fine aside from dead code
- `tg_bot.py` interactive mode (`/start`, `/bets`, `/stats`) — working
- Message templates — current formats are good, just need centralization
- Pipeline call schedule — the timing is correct
- Per-user PG dedup for client notifications — works, keep it

---

## Minimal Safe First Step (This Session)

### Step 1: Fix the weekly report bug in `content_publisher.py`

The `conn2` walrus operator bug on line 210 is a clear, isolated fix:
- Move `conn2 := get_conn()` before the query that uses it
- This is a one-line fix with zero risk

### Step 2: Add dedup to `bot/weekly_notify.py`

Add a simple SQLite-based dedup check using the same pattern as `content_publisher.py`:
- Key: `weekly_sub_{year}_{week}`
- Check before sending, mark after

### Step 3: Create `notification_layer.py` skeleton

A minimal module with:
- `NotificationEvent` dataclass
- `send_admin()`, `send_client()`, `send_channel()` thin wrappers
- `was_sent()`, `mark_sent()` using unified `notification_log` table
- No refactoring of existing code yet — just the infrastructure

### Step 4: Document the architecture

Save this plan. Future work can incrementally migrate each endpoint.

---

## Future Migration Path (Not Now)

1. **Migrate `tg_bot.py` notify modes** → use `notification_layer.py` for dedup and send
2. **Migrate `content_publisher.py`** → use unified dedup table, fix weekly/monthly to use same data source
3. **Migrate `bot/notifier.py`** → use unified event types, fix tennis double-sending
4. **Add `SYSTEM_ALERT`** → pipeline failure alerts, stale bet alerts
5. **Unify weekly stats** → single query, two targets (channel + subscribers)
6. **Add `golden` to pipeline** → call `task_notify("golden")` in morning runner

---

## Answers

1. **biggest current notification problem =** Three different data sources for the same stats concept (SQLite `bets` vs PG `signals`), plus the `content_publisher.py` weekly report bug (`NameError` on `conn2`), plus no dedup in `bot/weekly_notify.py`.

2. **canonical notification source should be =** SQLite `bets` table for all bet-related notifications (admin, client, channel). PG `signals` is for the SaaS API layer, not for notifications. The `notification_log` table should be the unified dedup store.

3. **what dead path should be removed first?** — The duplicated email verification handler in `bot/client_bot.py` (lines 796-823 and 826-853). Also the unreachable code path at line 796. Not critical but cleanable.

4. **what minimal safe refactor should be done now?** — Fix the `content_publisher.py:210` walrus operator bug (one-line fix), add dedup to `bot/weekly_notify.py` (simple check/mark), create `notification_layer.py` skeleton with unified dedup table.

5. **unified layer partially implemented?** — No. Not yet. This plan defines the architecture; the first implementation step is the bug fix + skeleton module.
