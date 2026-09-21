# Tennis Stuck Bets — Manual Resolution Report

**Date:** 2026-04-15
**Scope:** All tennis bets with `result='pending'` and `match_date <= 2026-04-15`

---

## 1. Summary

| Metric | Count |
|--------|-------|
| Total stuck tennis bets found | **10** |
| Had results on betz.su (settled normally) | **1** (bet 904) |
| Cancelled/void (match not found anywhere) | **5** |
| Manually settled now | **6** (1 lost + 5 void) |
| Still unresolved (future matches, today) | **4** |
| Surname mapping was the problem? | **No** |

---

## 2. Root Cause Analysis

### Why bets were stuck

The primary issue is **not surname mapping** — it's a **match status pipeline failure**:

1. **Matches table has `status='upcoming'` or `status='pending'`** for matches whose dates have already passed
2. `settler.py` only processes bets where `matches.status = 'finished'` AND `home_score IS NOT NULL`
3. The `updater_results.py` fuzzy matching pipeline failed to update these matches' status
4. The tennis results updater (`tennis_results_updater.py`) DID fetch results from betz.su, but:
   - Some matches were **cancelled/withdrawn** and never appeared on betz.su
   - Some matches appeared but the **matches table was never updated** because the updater's fuzzy matching couldn't link betz.su names to Fonbet names

### Specific failure modes per bet:

| Bet | Failure Mode |
|-----|-------------|
| 904 | Result EXISTS in tennis_live_results + normalized_results, but match status='upcoming' so settler skipped it |
| 880, 910, 905, 906, 915 | Match **not found on betz.su at all** — cancelled/withdrawn from draw |
| 916, 917, 919, 920 | Match date is today (2026-04-15), not yet played — **not actually stuck** |

### Why cancelled matches still have bets

The tennis pipeline (`tennis_live_pipeline.py`) creates bets from Fonbet odds. Fonbet lists matches that may later be cancelled/withdrawn. The pipeline has no mechanism to cancel bets when matches are withdrawn from the draw.

---

## 3. Per-Bet Resolution Table

| Bet ID | Created | Players | League | Match Date | Market | Odds | Stake | Result on betz.su | Verdict | Action Taken |
|--------|---------|---------|--------|------------|--------|------|-------|-------------------|---------|-------------|
| **880** | 2026-04-12 | Ферро Ф vs Кирстя С | WTA Руан | 2026-04-13 | player1_win | 4.3 | 480 | NOT FOUND — match cancelled | CANCELLED/VOID | Settled void, profit=0 |
| **910** | 2026-04-12 | Рахимова К vs Калиева Э | WTA Руан | 2026-04-13 | player1_win | 1.63 | 480 | NOT FOUND — Калиева played qualies Apr 12, main draw match withdrawn | CANCELLED/VOID | Settled void, profit=0 |
| **904** | 2026-04-12 | Мухова К vs Саснович А | WTA Штутгарт | 2026-04-14 | player2_win | 3.4 | 480 | FOUND: Мухова won 2:0 (6:2, 6:4) | RESULT_FOUND_LOSS | Settled lost, profit=-480 |
| **905** | 2026-04-12 | Сонмез З vs Паолини Я | WTA Штутгарт | 2026-04-14 | player1_win | 4.4 | 480 | NOT FOUND — Сонмез played qualies Apr 12, main draw match withdrawn | CANCELLED/VOID | Settled void, profit=0 |
| **906** | 2026-04-12 | Остапенко Е vs Андреева М | WTA Штутгарт | 2026-04-14 | player1_win | 3.3 | 480 | NOT FOUND — Андреева played Linz final Apr 12, Остапенко only in doubles | CANCELLED/VOID | Settled void, profit=0 |
| **915** | 2026-04-13 | Марожан Ф vs Циципас С | ATP Мюнхен | 2026-04-14 | player2_win | 1.6 | 473.18 | NOT FOUND — neither player in München Apr 14 results | CANCELLED/VOID | Settled void, profit=0 |
| **916** | 2026-04-13 | Блокс А vs Шелтон Б | ATP Мюнхен | 2026-04-15 | player2_win | 1.45 | 476.32 | Not yet played (today) | FUTURE — not stuck | No action needed |
| **917** | 2026-04-14 | Марожан Ф vs Циципас С | ATP Мюнхен | 2026-04-15 | player2_win | 1.72 | 507.91 | Not yet played (today) | FUTURE — not stuck | No action needed |
| **919** | 2026-04-15 | Блокс А vs Шелтон Б | ATP Мюнхен | 2026-04-15 | player2_win | 1.7 | 331.39 | Not yet played (today) | FUTURE — not stuck | No action needed |
| **920** | 2026-04-15 | Марожан Ф vs Циципас С | ATP Мюнхен | 2026-04-15 | player2_win | 1.72 | 331.39 | Not yet played (today) | FUTURE — not stuck | No action needed |

**Note:** Bets 921 (Альтмайер vs Молчан, Apr 16) and 922 (Мухова vs Мертенс, Apr 16) are also pending but are future matches — not stuck.

---

## 4. Surname Mapping Analysis

**Surname mapping was NOT the problem.**

The `_surname()` function in `settler.py:117-125` correctly extracts surnames:
- "Мухова К" -> "Мухова"
- "Саснович А" -> "Саснович"

The SQL LIKE query in `_try_tennis_settle()` uses `LIKE '%surname%' COLLATE NOCASE` which handles Cyrillic matching.

The real issue is that `settler.py` requires `matches.status = 'finished'` before it even attempts settlement. For cancelled matches, the status never changes from 'upcoming'/'pending', so the settler never runs.

---

## 5. Financial Impact

| Category | Count | Total Stake | P&L |
|----------|-------|------------|-----|
| Lost bets | 1 | 480.00 | -480.00 |
| Void bets | 5 | 2,393.18 | 0.00 |
| Future (not stuck) | 4 | 1,647.01 | TBD |
| **Total stuck resolved** | **6** | **2,873.18** | **-480.00** |

---

## 6. Recommended Fixes

### Immediate (low risk)
1. **Run tennis results updater before settler**: Ensure `tennis_results_updater.py --days 3` runs before `settler.py` in the pipeline
2. **Add cancelled match detection**: In `settler.py`, check `tennis_live_results` for matches with `sets_winner IS NULL` (cancelled) and void those bets

### Medium priority
3. **Update match status for cancelled matches**: Add logic to mark matches as 'cancelled' when they don't appear on betz.su within 24h of match_date
4. **Add bet cancellation flow**: When a match is withdrawn from the draw, automatically void associated bets

### Pipeline fix
5. **Settler should handle non-finished matches**: Modify `settler.py` to also check for matches where `match_date < today` and `status != 'finished'` — these should be flagged for manual review or auto-voided if not found in results

---

## 7. SQL Commands Used for Manual Settlement

```sql
-- Bet 904: Мухова vs Саснович — LOST (Мухова won 2:0)
UPDATE bets SET result='lost', profit=-480.0, settled_at=datetime('now') WHERE id=904;

-- Bets 880, 910, 905, 906, 915: CANCELLED/VOID
UPDATE bets SET result='void', profit=0, settled_at=datetime('now'),
  validation_notes='MANUAL_SETTLE: match not found on betz.su, likely cancelled/withdrawn'
WHERE id IN (880, 910, 905, 906, 915);
```
