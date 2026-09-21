# Tennis Settlement Winner Semantics Fix

**Date:** 2026-04-12
**Status:** FIXED

---

## Problem Found

### betz.su does NOT always list winner first

The previous code at `tennis_results_updater.py:163-165` assumed:
```python
# betz.su lists winner first in results
winner = player1
loser = player2
```

**This is FALSE.** betz.su lists players in a fixed order (likely by seed/ranking), and the score determines the actual winner.

**Evidence from real data:**
| betz listing | Score | Actual winner |
|---|---|---|
| Елена Остапенко - Елена-Габрьела Русе | 1:2 (6:4, 4:6, 1:6) | Русе (second player) |
| Тамара Корпач - Анастасия Потапова | 0:2 (2:6, 1:6) | Потапова (second player) |

The old code stored Остапенко as winner when Русе actually won — **wrong settlement for any bet on this match**.

### What was broken

1. **Parser** (`parse_day`): Only iterated `<a>` tags, ignored `<u>` score elements, assumed first player = winner
2. **Table schema**: Had `player1`/`player2`/`winner`/`loser` columns where `winner` was always equal to `player1` (redundant, misleading)
3. **Settlement lookup**: Compared against `player1`/`player2` positions instead of explicit `winner_name`
4. **SQLite LOWER()**: Doesn't handle Cyrillic — all case-insensitive matching with `LOWER()` silently failed for Russian names

---

## Changes Made

### 1. `tennis_results_updater.py` — Parser rewrite

**Before:** Iterated `<a>` tags only, assumed first player = winner, no score parsing.

**After:**
- Iterates `<a>` and `<u>` elements in document order
- Extracts score from `<u>` tag (e.g. "1:2 (6:4, 4:6, 1:6)")
- Parses set score to determine actual winner: `s1 > s2` → player1 won, `s2 > s1` → player2 won
- Skips matches without parseable scores (can't determine winner)
- Stores `winner_name` / `loser_name` (not `player1`/`player2`)

### 2. `tennis_results_updater.py` — Table schema

**Before:** `player1`, `player2`, `winner`, `loser` (winner always = player1)

**After:** `winner_name`, `loser_name` (explicit, no ambiguity)

Migration: Old table dropped and recreated (only 6 rows, all had incorrect winners for matches where first player lost).

### 3. `tennis_results_updater.py` — `lookup_result()` rewrite

- Compares bet pick against explicit `winner_name` column
- Handles surname extraction from both formats: "Мирра Андреева" and "Андреева М."
- Uses `COLLATE NOCASE` instead of `LOWER()` for Cyrillic-aware matching
- Handles partial mappings (only one player has Russian name mapping)

### 4. `tennis_live_pipeline.py` — `_find_result_in_live()` rewrite

- Same improvements as `lookup_result()`
- Detects if input is already Cyrillic (Russian name passed directly)
- Surname-based matching handles format mismatch between mapping table ("Андреева М.") and betz results ("Мирра Андреева")
- Uses `COLLATE NOCASE` for all LIKE comparisons

---

## Safety Test Results

7/7 tests passed on real betz.su data:

| Test | Match | Expected | Result |
|------|-------|----------|--------|
| 1 | Андреева vs Кырстя (Андреева won, only p1 mapped) | p1_won | p1_won |
| 2 | Векич vs Плишкова (Векич won, only p1 mapped) | p1_won | p1_won |
| 3 | Потапова vs Векич (Потапова won, both mapped) | p1_won | p1_won |
| 4 | Векич vs Потапова (Потапова won, both mapped) | p2_won | p2_won |
| 5 | Русе vs Остапенко (neither mapped) | None | None |
| 6 | Остапенко vs Русе (Русе won, Russian names) | p2_won | p2_won |
| 7 | Андреева vs Русе (Андреева won, only p1 mapped) | p1_won | p1_won |

Critical test (#6): Остапенко was listed first in betz.su but lost 1:2. Settlement correctly returns `p2_won` (Русе won).

---

## Answers

1. **Does betz source encode winner as first player?** **NO** — players are listed in fixed order (seed/ranking), score determines winner
2. **Are results now stored with explicit winner_name?** **YES** — `winner_name` / `loser_name` columns, determined from score parsing
3. **Does settlement compare against explicit winner_name?** **YES** — all lookup functions compare bet pick against `winner_name`, not player positions
4. **Any already-written rows need migration/backfill?** **YES** — old table was dropped and recreated. 6 rows were re-fetched from betz.su with correct winner parsing. The critical fix: "Елена Остапенко vs Елена-Габрьела Русе" now correctly shows Русе as winner (was incorrectly Остапенко).
