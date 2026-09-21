# Client Bot Tennis Notification Cleanup

**Date:** 2026-04-15
**Status:** FIXED

---

## 1. Problem

After the previous fix, `run_full()` called both:
1. `task_notify_client("bets")` — general "Новые сигналы" (includes ALL sports from `bets` table)
2. `task_notify_tennis("bets")` — separate "Теннисные сигналы" block

This caused subscribers to receive **two messages** for the same tennis bets:
- Message 1: "Новые сигналы — N шт." with tennis entries included
- Message 2: "Теннисные сигналы — N шт." with the same tennis entries

---

## 2. Root Cause

`notify_new_bets()` in `bot/notifier.py` queries:
```sql
SELECT ... FROM bets b JOIN matches m ON b.match_id = m.id
WHERE b.result = 'pending' AND b.created_at >= datetime('now', '-24 hours')
```

This returns **ALL pending bets** regardless of sport (football, hockey, tennis). Tennis bets are already in the general flow. The separate `notify_tennis_signals()` path was redundant for the "new bets" use case.

---

## 3. Changes Applied

### File: `run_pipeline.py`

Removed `notify_tennis_bets` task from all automatic runners:

| Runner | Before | After |
|--------|--------|-------|
| `run_morning()` | `notify_client` + `notify_tennis_bets` | `notify_client` only |
| `run_afternoon()` | `notify_client` + `notify_tennis_bets` | `notify_client` only |
| `run_evening()` | `notify_client_bets` + `notify_tennis_bets` + `notify_tennis_results` | `notify_client_bets` + `notify_tennis_results` |
| `run_night()` | `notify_client` + `notify_tennis_bets` | `notify_client` only |
| `run_full()` | `notify_client` + `notify_tennis_bets` | `notify_client` only |

### What was kept:

- `task_notify_tennis()` function — **still exists**, available for manual use
- `notify_tennis_results` in `run_evening()` — **kept** (this is settled results, not new bets — different flow)
- `notify_tennis_signals()` in `bot/notifier.py` — **unchanged** (manual `--tennis` flag still works)

---

## 4. Verification

### Tennis bets in general flow

| Check | Result |
|-------|--------|
| `notify_new_bets()` query includes tennis? | YES — no sport filter, queries all `bets` |
| `fmt_new_signal()` handles tennis? | YES — tennis icon, market mapping |
| Tennis bets returned by query? | YES — all 6 pending bets are tennis |
| Dedup works for tennis bets? | YES — per-user key `bet_{id}_u{user_id}` |

### No duplicate tennis messages

| Check | Result |
|-------|--------|
| `notify_tennis_bets` in `run_full()`? | REMOVED |
| `notify_tennis_bets` in `run_morning()`? | REMOVED |
| `notify_tennis_bets` in `run_afternoon()`? | REMOVED |
| `notify_tennis_bets` in `run_night()`? | REMOVED |
| `notify_tennis_bets` in `run_evening()`? | REMOVED (results kept) |

### Admin/channel paths unaffected

| Check | Result |
|-------|--------|
| `task_notify_unified()` | UNCHANGED (admin + channel) |
| `task_notify_tennis("results")` in evening | KEPT (settled results, separate flow) |
| `task_notify("report")` in evening | UNCHANGED |

---

## 5. Answers

| Question | Answer |
|----------|--------|
| **Separate tennis client auto-notification removed?** | **YES** — removed from all 5 runners |
| **Tennis still included in general client flow?** | **YES** — `notify_new_bets()` queries all sports from `bets` table |
| **Duplicate/confusing second tennis message gone?** | **YES** — only one message per pipeline run |
| **Any legacy tennis notify path still remains?** | **YES** — `task_notify_tennis()` function exists for manual use (`--tennis` flag), and `notify_tennis_results` remains in evening runner for settled results |
