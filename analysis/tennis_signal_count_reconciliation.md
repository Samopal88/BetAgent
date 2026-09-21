# Tennis Signal Count Reconciliation

**Date:** 2026-04-12

---

## The Numbers

| Metric | Count |
|--------|-------|
| **Total tennis_signals in DB** | 14 |
| **Status = pending** | 14 |
| **Status = open** | 0 (column doesn't exist, uses `pending`) |
| **Created last 24h** | 14 |
| **Created today** | 14 |
| **Result = NULL** | 14 |
| **Result = won/lost** | 0 |
| **Skipped by dedup (last run)** | 14 |
| **Candidates before final filters** | ~36 (125 parsed - 89 no mapping) |
| **Passed final filters (EV/edge)** | 0 (current run) |
| **Persisted signals** | 14 (from earlier run, before dedup was added) |

## Bets table (what notify reads)

| Metric | Count |
|--------|-------|
| **Total pending bets** | 2 (both football) |
| **Pending tennis bets** | **0** |
| **Pending bets last 24h** | 0 |

---

## The Root Cause

**Tennis signals are saved to `tennis_signals` table.**
**Notify reads from `bets` table.**

`tg_bot.py:notify("bets")` queries:
```sql
SELECT ... FROM bets b JOIN matches m ON b.match_id = m.id
WHERE b.result = 'pending' AND b.created_at >= datetime('now', '-24 hours')
```

`bot/notifier.py:notify_new_bets()` queries:
```sql
SELECT ... FROM bets b JOIN matches m ON b.match_id = m.id
WHERE b.result = 'pending' AND b.created_at >= datetime('now', '-24 hours')
```

**Neither query touches `tennis_signals`.** Tennis signals live in a completely separate table and are invisible to the notification system.

---

## Dry-run candidates vs Persisted signals vs New for notify

| Category | Count | Explanation |
|----------|-------|-------------|
| Dry-run candidates (original verification) | 14 | Signals that passed all filters in the first run (before dedup existed) |
| Persisted signals (tennis_signals table) | 14 | Same 14, written to `tennis_signals` |
| New signals for notification (bets table) | 0 | Tennis signals are never written to `bets` |
| New signals for notification (tennis_signals) | 14 | Would be found if notify queried `tennis_signals` |

---

## Why 14 → 0

The original 14 signals were created in the first pipeline run (before dedup was added). Subsequent runs skip them as duplicates. Current run generates 0 new signals because:
- 125 matches parsed
- 89 skipped (no name mapping)
- 22 skipped (no edge/EV)
- 14 skipped (dedup — already in DB)
- 0 passed all filters

---

## Answers

1. **12-14 signals referred to what exactly?**
   Signals saved to `tennis_signals` table in the first pipeline run (before dedup existed). They are NOT in the `bets` table.

2. **How many real OPEN tennis bets exist now?**
   **0** in `bets` table. 14 in `tennis_signals` table (status=pending), but these are not real bets — they're signals that were never converted to `bets` records.

3. **How many new tennis bets in last 24h?**
   **0** — tennis pipeline writes to `tennis_signals`, not `bets`.

4. **Why notify says no new bets?**
   Two reasons:
   - **Primary:** Notify queries `bets` table, tennis signals are in `tennis_signals` table — completely separate. No bridge exists between them.
   - **Secondary:** Even if it queried `tennis_signals`, the 14 signals were created at 04:07 today, and the notify window is `-24 hours`, so they would be found — but the table mismatch is the blocker.
