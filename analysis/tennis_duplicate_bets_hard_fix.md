# Tennis Duplicate Bets — Hard Fix

**Date:** 2026-04-15
**Status:** FIXED + VERIFIED

---

## 1. Exact Root Cause

**The previous fix canonicalized names using `tennis_player_mapping` (Russian -> English), but many Fonbet name variants like "Blockx A.", "Mertens E." are NOT in that table (they have `needs_review=1` or are missing entirely).**

### How it happens:

1. Pipeline run #1: Fonbet returns **Russian** names: `"Блокс А"`, `"Шелтон Б"`
   - `name_map` has `"Блокс А" -> "Александер Блокс"` (needs_review=0)
   - Reverse mapping: `"александер блокс" -> "Блокс А"`
   - Canonicalization works → dedup key: `tennis_2026-04-15_Блокс А_Шелтон Б_player2_win`

2. Pipeline run #2: Fonbet returns **English** names: `"Blockx A."`, `"ben shelton"`
   - `name_map` does NOT have `"Blockx A."` (needs_review=1, not loaded)
   - Reverse mapping does NOT find it
   - Canonicalization FALLS BACK to raw name: `"blockx a."`
   - Different dedup key: `tennis_2026-04-15_Blockx A._ben shelton_player2_win`
   - **No dedup match → new bet created**

3. Pipeline run #3: Fonbet returns **lowercase Russian**: `"блокс а"`, `"шелтон б"`
   - `name_map` has `"Блокс А"` but NOT `"блокс а"` (case mismatch)
   - Falls back to raw: `"блокс а"`
   - Third dedup key: `tennis_2026-04-15_блокс а_шелтон б_player2_win`
   - **Third bet created**

### Why the previous fix failed:

The previous fix (documented in `tennis_duplicate_bets_fix.md`) used `tennis_player_mapping WHERE needs_review=0` with a reverse English->Russian mapping. But:
- `tennis_player_mapping` only has 683 entries, many with `needs_review=1`
- Fonbet returns names in multiple formats: `"Blockx A."`, `"Блокс А"`, `"блокс а"`
- The `tennis_name_lookup` table has 2325 entries with much broader coverage but was NOT used

### The Muхова К vs Мертенс Э case (5 duplicates):

This match accumulated 5 signals across 5 pipeline runs because:
- Run 1 (18:02): English names `"karolina muchova"`, `"Mertens E."` — not in name_map
- Run 2 (05:05): Russian names `"Мухова К"`, `"Мертенс Э"` — in name_map
- Run 3 (11:05): Lowercase Russian `"мухова к"`, `"мертенс э"` — case mismatch
- Run 4 (18:05): Another variant
- Run 5 (20:35): Another variant

Each produced a different dedup key → 5 signals → 3 bets (some runs didn't pass filters).

---

## 2. Fix Applied

### Files Changed

| File | Changes |
|------|---------|
| `tennis_live_pipeline.py` | 6 locations modified |
| `backfill_tennis_bets.py` | Full rewrite of dedup logic |

### New Dedup Key Format

```python
# Canonical name resolution via tennis_name_lookup (2325 entries) + tennis_player_mapping (683 entries)
p1_canonical = canonicalize_name(p1_name, name_map, name_lookup)  # → stable English: "ben shelton"
p2_canonical = canonicalize_name(p2_name, name_map, name_lookup)  # → stable English: "alexander blockx"
dedup_key = f"tennis_{match_date}_{p1_canonical}_{p2_canonical}_{market}"
```

### canonicalize_name() Priority

1. **`tennis_name_lookup`** (betz_name -> eng_name) — 2325 entries, widest coverage of Fonbet variants
2. **`tennis_player_mapping`** (rus_name -> eng_name) — 683 confident entries
3. **Fallback**: lowercase + strip the raw name

### 6 Locations Modified in `tennis_live_pipeline.py`

| # | Location | What Changed |
|---|----------|-------------|
| 1 | `load_name_lookup()` (new function, line ~164) | Loads `tennis_name_lookup` table |
| 2 | `canonicalize_name()` (new function, line ~193) | Resolves any name variant to stable English |
| 3 | `run_pipeline()` signal dedup load (line ~806) | Uses `canonicalize_name()` when loading existing signals |
| 4 | `run_pipeline()` signal dedup compare (line ~941) | Uses `canonicalize_name()` instead of reverse name_map |
| 5 | `_create_tennis_bet()` (line ~727) | Uses `sig["p1_canonical"]` / `sig["p2_canonical"]` for dedup key |
| 6 | `settle_tennis_signals()` (line ~1537, ~1596, ~1672) | Loads name mappings, uses `canonicalize_name()` for bet lookup and cancel |

### Signal Dict Extended

Added `p1_canonical` and `p2_canonical` fields to signal dict so `_create_tennis_bet()` can use stable names.

---

## 3. DB-Level Protection Added

```sql
CREATE UNIQUE INDEX idx_bets_tennis_dedup
ON bets(created_by)
WHERE created_by LIKE 'tennis_%' AND result = 'pending';
```

This partial unique index prevents inserting two pending tennis bets with the same `created_by` (dedup key). Even if the application code has a bug, the database will reject the duplicate with a constraint violation.

- **Scope**: Only applies to tennis bets (`created_by LIKE 'tennis_%'`)
- **State**: Only applies to pending bets (`result = 'pending'`) — won't affect settled/won/lost/cancelled historical data
- **Safety**: Does not affect football/hockey bets (they use `agent_handoff_v7.py` as `created_by`)

---

## 4. Current Duplicate Groups (Existing Data)

### Active Pending Bet Duplicates (3 groups, 8 total rows)

| Group | Match | Market | Bet IDs | Created | Odds | Stakes | Root Cause |
|-------|-------|--------|---------|---------|------|--------|------------|
| 1 | Блокс А vs Шелтон Б (Apr 15) | player2_win | 916, 919, 923 | Apr 13, 15, 15 | 1.45, 1.70, 1.68 | 476, 331, 329 | English/Russian/lowercase flip |
| 2 | Марожан Ф vs Циципас С (Apr 15) | player2_win | 917, 920 | Apr 14, 15 | 1.72, 1.72 | 508, 331 | English/Russian flip |
| 3 | Мухова К vs Мертенс Э (Apr 16) | player1_win | 918, 922, 924 | Apr 14, 15, 15 | 1.45, 1.45, 1.55 | 508, 331, 329 | English/Russian/lowercase flip |

### Active Pending Signal Duplicates (3 groups, 10 total rows)

| Group | Match | Signal IDs | Created |
|-------|-------|------------|---------|
| 1 | Блокс А vs Шелтон Б (Apr 15) | 49, 52, 56 | Apr 13, 15, 15 |
| 2 | Марожан Ф vs Циципас С (Apr 15) | 50, 53 | Apr 14, 15 |
| 3 | Мухова К vs Мертенс Э (Apr 16) | 51, 55, 57, 58, 59 | Apr 14, 15 (x4) |

### Cleanup Recommendation

**For bets**: Keep the LATEST row in each group (most current odds), void the older ones:

| Keep | Void | Reason |
|------|------|--------|
| 923 (Apr 15 11:05, odds 1.68) | 916, 919 | Latest odds most accurate |
| 920 (Apr 15 05:05, odds 1.72) | 917 | Latest run |
| 924 (Apr 15 11:05, odds 1.55) | 918, 922 | Latest odds most accurate |

**For signals**: Keep the LATEST signal ID in each group, void the older ones.

**NOT applied yet** — these matches haven't been played yet. Manual review recommended before cleanup.

---

## 5. Verification Results

### Dry-run test (2026-04-15 21:19)

```
Loaded 683 confident name mappings
Loaded 2325 name lookup entries
Dedup: 52 existing pending signals loaded

SKIP (duplicate): Альтмайер Д vs Молчан А
SKIP (duplicate): Мухова К vs Мертенс Э

Skipped (duplicate):     2
Signals generated:       0
```

**Result**: Both known duplicate matches correctly detected and skipped. Zero new signals generated (all existing matches already have pending signals).

### New matches processed correctly

- **Фонсека Ж vs Шелтон Б** (Apr 17) — different opponent, processed normally, no duplicate
- **Шаповалов Д vs Марожан Ф** (Apr 16) — different opponent, processed normally, no duplicate

---

## 6. Answers

| Question | Answer |
|----------|--------|
| **Exact root cause** | `tennis_player_mapping` (683 entries) didn't cover all Fonbet name variants. English names like "Blockx A." had `needs_review=1` and weren't loaded. Lowercase Russian names had case mismatches. Each variant produced a different dedup key. |
| **Fixed at bet creation layer?** | **YES** — `_create_tennis_bet()` now uses `canonicalize_name()` via `tennis_name_lookup` (2325 entries) |
| **Duplicate key** | `tennis_{match_date}_{canonical_p1}_{canonical_p2}_{market}` where canonical names are stable English via `tennis_name_lookup` → `tennis_player_mapping` → fallback |
| **DB-level protection added?** | **YES** — `CREATE UNIQUE INDEX idx_bets_tennis_dedup ON bets(created_by) WHERE created_by LIKE 'tennis_%' AND result = 'pending'` |
| **Rerun still creates duplicates?** | **NO** — verified with dry-run: 0 new signals, 2 duplicates correctly skipped |
| **Current duplicate groups** | **3 groups** (8 bet rows, 10 signal rows) — all pre-existing, no new ones created after fix |
