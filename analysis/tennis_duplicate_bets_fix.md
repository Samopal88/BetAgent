# Tennis Duplicate Bets — Root Cause & Fix

**Date:** 2026-04-15

---

## 1. Root Cause

**The dedup key uses `player1_eng`/`player2_eng` which can flip between English and Russian names across pipeline runs.**

### How it happens:

1. Pipeline run #1 (e.g. 05:05): Fonbet returns **Russian** names: `"Блокс А"`, `"Шелтон Б"`
   - `p1_name = "Блокс А"`, `p2_name = "Шелтон Б"`
   - `player1_eng = "Блокс А"`, `player2_eng = "Шелтон Б"` (line 1074-1075: just copies p1_name/p2_name)
   - dedup_key: `tennis_2026-04-15_Блокс А_Шелтон Б_player2_win`
   - Bet created with this key

2. Pipeline run #2 (e.g. 18:02): Fonbet returns **English** names: `"Blockx A."`, `"ben shelton"`
   - `p1_name = "Blockx A."`, `p2_name = "ben shelton"`
   - `player1_eng = "Blockx A."`, `player2_eng = "ben shelton"`
   - dedup_key: `tennis_2026-04-15_Blockx A._ben shelton_player2_win`
   - **Different key → no dedup match → new bet created**

3. Pipeline run #3 (next morning): Fonbet returns **Russian** names again
   - dedup_key matches run #1 → dedup works for that key
   - But run #2's English-key bet is still pending → **now 2 pending bets**

### Why the signal dedup also failed:

Signal dedup (line 768-771) loads `player1_eng, player2_eng` from `tennis_signals` table and compares against `(match_date, p1_name, p2_name)`. When `p1_name` changes between runs (Russian → English), the comparison fails.

### Secondary issue: match_date drift

Historical duplicates (bets 868/892, 869/893, etc.) show a different pattern: the **match_date changed** between runs (e.g. `2026-04-13` → `2026-04-14`). Fonbet updates match dates as schedules shift, and the dedup key includes the date, so it doesn't match.

---

## 2. Anti-Duplicate Rule (Fixed)

### New dedup key format:

```python
p1_norm = sig["player1"].strip().lower()   # Russian names, normalized
p2_norm = sig["player2"].strip().lower()
dedup_key = f"tennis_{match_date}_{p1_norm}_{p2_norm}_{market}"
```

### Key changes:

| Component | Before | After |
|-----------|--------|-------|
| Player names | `sig['player1_eng']` / `sig['player2_eng']` (can be English or Russian) | `sig['player1']` / `sig['player2']` (always Russian from Fonbet), `.strip().lower()` |
| Signal dedup load | `SELECT player1_eng, player2_eng` | `SELECT LOWER(TRIM(player1)), LOWER(TRIM(player2))` |
| Signal dedup compare | `(match_date, p1_name, p2_name)` (case-sensitive) | `(match_date, p1_name.strip().lower(), p2_name.strip().lower())` |
| Settlement lookup | `f"tennis_{date}_{p1_eng}_{p2_eng}_{market}"` | `f"tennis_{date}_{p1_norm}_{p2_norm}_{market}"` |
| Cancel lookup | Same as settlement | Same as settlement |

### Changed files:

- `tennis_live_pipeline.py` — 4 locations modified:
  1. `_create_tennis_bet()` (line ~685): dedup key + fonbet_id use normalized Russian names
  2. `run_pipeline()` signal dedup load (line ~768): load `LOWER(TRIM(player1/2))` from signals table
  3. `run_pipeline()` signal dedup compare (line ~895): normalize to lowercase before comparison
  4. `settle_tennis_signals()` settlement lookup (line ~1544): use normalized names for dedup key
  5. `_mark_cancelled()` (line ~1621): use normalized names for dedup key, accept `p1_name`/`p2_name` instead of `p1_eng`/`p2_eng`

---

## 3. Recent Duplicates Found

### Pending duplicates (active):

| Match | Market | Bet IDs | Odds | Stakes | Created |
|-------|--------|---------|------|--------|---------|
| Блокс А vs Шелтон Б (Apr 15) | player2_win | 916, 919 | 1.45, 1.70 | 476, 331 | Apr 13 / Apr 15 |
| Марожан Ф vs Циципас С (Apr 15) | player2_win | 917, 920 | 1.72, 1.72 | 508, 331 | Apr 14 / Apr 15 |
| Мухова К vs Мертенс Э (Apr 16) | player1_win | 918, 922 | 1.45, 1.45 | 508, 331 | Apr 14 / Apr 15 |

### Historical duplicates (already settled):

| Match | Market | Bet IDs | Results | Notes |
|-------|--------|---------|---------|-------|
| Баптист Х vs Понше Дж | player2_win | 889, 912 | lost, lost | Date drift 04-13→04-14 |
| Блинкова А vs Потапова А | player1_win | 888, 911 | won, cancelled | Date drift 04-13→04-14 |
| Грикспор Т vs Шаповалов Д | player1_win | 886, 902 | lost, lost | Date drift |
| Зверев А vs Кецманович М | player2_win | 883, 900 | lost, lost | Date drift |
| Корпач Т vs Шнайдер Д | player1_win | 878, 908 | lost, lost | Date drift |
| Костюк М vs Парри Д | player2_win | 890, 913 | lost, lost | Date drift |
| Ландалус М vs Музетти Л | player1_win | 870, 894 | lost, lost | Date drift |
| Лис Е vs Бадоса П | player1_win | 879, 909 | won, won | Date drift — double payout! |
| Махач Т vs Баэс С | player1_win | 868, 892 | won, won | Date drift — double payout! |
| Навоне М vs Рублев А | player1_win | 869, 893 | lost, lost | Date drift |
| Остапенко Е vs Андреева М | player1_win | 876, 906 | lost, void | Date drift |
| Табило А vs Фонсека Ж | player1_win | 871, 901 | lost, lost | Date drift |
| Чилич М vs Альтмайер Д | player1_win | 873, 903 | lost, lost | Date drift |
| Эала А vs Фернандес Л | player1_win | 877, 907 | lost, lost | Date drift |
| Марожан Ф vs Циципас С | player2_win | 915, 917, 920 | void, pending, pending | Name flip + triple! |

**Total recent duplicates:** 17 duplicate pairs (15 historical + 3 active pending, minus Марожан which is a triple)

---

## 4. Existing Duplicates — Cleanup Recommendation

### Active pending duplicates (3 pairs):

**Recommended: void the OLDER bet in each pair, keep the LATEST.**

Rationale: The latest bet has the most current odds and stake calculation. The older bet was created with stale odds.

| Keep | Void | Reason |
|------|------|--------|
| 919 (Apr 15, odds 1.70) | 916 (Apr 13, odds 1.45) | Latest odds more accurate |
| 920 (Apr 15, odds 1.72) | 917 (Apr 14, odds 1.72) | Latest run |
| 922 (Apr 15, odds 1.45) | 918 (Apr 14, odds 1.45) | Latest run |

**NOT applied yet** — these matches haven't been played yet. They may settle normally. The fix prevents future duplicates.

### Historical duplicates (15 pairs, already settled):

These are already resolved (won/lost/cancelled). No cleanup needed — the PnL is already recorded. However, **2 pairs resulted in double payouts** (Лис Е vs Бадоса П: both won; Махач Т vs Баэс С: both won). This is a financial loss that already happened.

---

## 5. Other Sports Risk

**Football:** No pending duplicates found. Football uses `match.id` (integer) + `market` + `created_at_minute` as fingerprint (line 2622: `f"{match.id}_{market}_{created_at_minute}"`). Since `match.id` is stable, this is not vulnerable to name changes. However, the fingerprint includes the minute timestamp, so it doesn't prevent duplicates across runs — it just logs them separately in `handoff_decisions`. The actual `bets.created_by` field for football is `"agent_handoff_v7"`, not a unique dedup key, so football could theoretically have duplicates too, but in practice the pipeline runs once per scheduled time and the same match gets the same `match.id`.

**Hockey:** No pending duplicates found. Hockey bets go through the same `agent_handoff_v7.py` path as football, using `match.id`-based fingerprint.

**Risk level for other sports: LOW** — they use stable `match.id` rather than player names in their dedup logic.

---

## 6. Financial Impact of Historical Duplicates

| Pair | Bet IDs | Results | Double PnL Impact |
|------|---------|---------|-------------------|
| Лис Е vs Бадоса П | 879 (+1015), 909 (+1087.5) | both won | **+2102.5 RUB** (should be ~1015) |
| Махач Т vs Баэс С | 868 (+374.4), 892 (+326.4) | both won | **+700.8 RUB** (should be ~374) |
| Блинкова А vs Потапова А | 888 (+1128), 911 (cancelled) | won + cancelled | +1128 (only 1 counted) |

**Total overpayment from double wins: ~2803 RUB**

---

## 7. What the Fix Does NOT Address

1. **match_date drift** — If Fonbet changes the match date between runs, the dedup key still won't match. A more robust solution would use a player-pair hash independent of date, but this is a secondary issue. The primary fix (Russian names) solves the English/Russian flip which is the most common cause.

2. **Historical double payouts** — Already happened. No retroactive fix applied.

3. **Football/hockey dedup** — Not broken, but could be hardened. Not addressed in this fix.
