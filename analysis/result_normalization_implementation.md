# Result Normalization Layer & Settlement Hardening

**Date:** 2026-04-13
**Scope:** Canonical normalized result entity, dual-path settlement, reduced fuzzy matching

---

## Problem Statement

Settlement is one of the most dangerous areas in BetAgent:
- Financial truth (bankroll, ROI, reports, ML retraining) depends on correct result resolution
- 7+ different parsers write to `results_raw` in different formats
- Hockey OT/SO semantics: regulation-time score vs final score
- Team name formats vary: "Монреаль" vs "Монреаль Канадиенс" vs "CGY"
- Tennis has explicit `winner_name`, team sports derive winner from score comparison
- Settlement uses fragile fuzzy matching (`LIKE '%substr%'`, 4-char overlap)
- No confidence tracking — a fuzzy match is treated the same as an exact match

---

## What Was Done

### 1. New File: `result_normalization.py`

Canonical normalized result layer with:

#### Schema: `normalized_results` table

| Column | Type | Purpose |
|--------|------|---------|
| `id` | INTEGER PK | Auto-increment |
| `source` | TEXT | Source: `results_raw`, `tennis_live_results`, `fonbet_api` |
| `source_match_id` | TEXT | Composite key from source for dedup |
| `sport` | TEXT | `football`, `hockey`, `tennis` |
| `league` | TEXT | League key |
| `match_date` | TEXT | YYYY-MM-DD |
| `participant_1` | TEXT | Home team or player1 (normalized name) |
| `participant_2` | TEXT | Away team or player2 (normalized name) |
| `winner_name` | TEXT | Canonical name of winner |
| `loser_name` | TEXT | Canonical name of loser |
| `winner_side` | TEXT | `participant_1`, `participant_2`, or `draw` |
| `score_p1` | INTEGER | Score of participant_1 (regulation time for hockey) |
| `score_p2` | INTEGER | Score of participant_2 (regulation time for hockey) |
| `score_detail` | TEXT | Sport-specific: sets for tennis, "OT" for hockey |
| `status` | TEXT | `completed`, `postponed`, `cancelled`, `void`, `unknown` |
| `is_overtime` | INTEGER | Hockey: went to OT/SO |
| `raw_data` | TEXT | JSON blob of original raw fields for audit |
| `parsed_at` | TEXT | When source parsed this result |
| `normalized_at` | TEXT | When we normalized it |
| `confidence` | REAL | 1.0 = exact, 0.5-0.9 = fuzzy, <0.5 = uncertain |

Unique constraint: `(source, source_match_id, sport)` — prevents duplicates.

#### Per-sport normalization rules

| Sport | Raw Source | Key Normalization |
|-------|-----------|-------------------|
| **Football** | `results_raw` | Derive winner from `home_score` vs `away_score`. Normalize team names (strip parentheticals). Confidence = 1.0. |
| **Hockey** | `results_raw` | Same as football + capture `is_overtime` flag. For OT matches, regulation-time score is a draw — this is the critical semantic fix. Source-dependent confidence: `betz.su`=1.0, `sports.ru`=0.9, others=0.85. |
| **Tennis** | `tennis_live_results` | Already has explicit `winner_name`/`loser_name`. Maps to canonical format. Confidence = 1.0. |

#### Name normalization

- `normalize_team_name()`: strips trailing parentheticals, expands hockey abbreviations (CGY→Калгари, MTL→Монреаль, etc.), normalizes whitespace
- `extract_surname()`: handles both "First Surname" and "Surname Initial" formats for tennis

#### Lookup API

- `lookup_normalized_result(conn, sport, p1, p2, date)`: exact match first, then fuzzy fallback with confidence tracking
- `result_for_market_normalized(market, winner_side, score_p1, score_p2, is_overtime, sport)`: determines bet result using normalized semantics

#### Ingestion

- `ingest_from_results_raw(conn, sport, days)`: reads results_raw, normalizes, upserts by unique key
- `ingest_from_tennis_live_results(conn, days)`: reads tennis_live_results, normalizes, upserts
- Upsert logic: only updates if new source has higher confidence

### 2. Modified File: `settler.py`

Dual-path settlement:

1. **PATH 1 (primary)**: Try `normalized_results` via `lookup_normalized_result()`. If confidence >= 0.8, use normalized winner/score.
2. **PATH 2 (fallback)**: Existing raw `results_raw` logic with fuzzy matching — unchanged, still works.

Output now shows which path was used:
```
SETTLED [normalized(results_raw,conf=1.0)]: Team A vs Team B | home -> won | profit=50.0
SETTLED [raw]: Team C vs Team D | away -> lost | profit=-100.0
```

### 3. Modified File: `run_pipeline.py`

- Added `task_normalize_results()`: runs normalization for football, hockey, tennis (last 3 days)
- Called in `task_settle()` before parsing results
- Added to morning and evening runners before settle step

---

## Current State

### Normalized Results Inventory

```
football: 519 records (confidence 1.0: 321, 0.8-0.89: 198)
hockey:   523 records (confidence 1.0: 523)
tennis:     6 records (confidence 1.0: 6)
TOTAL:   1048 records
```

### Confidence Distribution

| Confidence | Count | Meaning |
|------------|-------|---------|
| 1.0 (exact) | 850 | Team names matched exactly after normalization |
| 0.8-0.89 | 198 | Football records from non-primary sources (sports.ru, liveresult) |

### Source Distribution

| Source | Sport | Count |
|--------|-------|-------|
| `results_raw` | hockey | 523 |
| `results_raw` | football | 519 |
| `tennis_live_results` | tennis | 6 |

---

## What Fuzzy Matching Remains

### In `settler.py` (fallback path)

The raw fallback still uses:
- 4-character substring overlap: `LIKE '%substr(4chars)%'`
- First-word prefix matching for hockey
- This is only used when normalized layer doesn't have the match

### In `updater_results.py` (result fetching)

Still uses full fuzzy matching pipeline:
1. Exact match by home/away/date
2. Normalized exact match (date +/-1)
3. Short-vs-full name matching via `team_names_match()`
4. Reversed team order support
5. Aggressive mode for stale matches (date +/-2, no league filter)

This is **not** changed — `updater_results.py` writes to `matches` table, not to settlement. The normalization layer reads from `results_raw` which is populated by parsers, not by updater.

### In `tennis_live_pipeline.py` (tennis settlement)

Still uses surname-based `LIKE '%surname%' COLLATE NOCASE` matching against `tennis_live_results`. This is the existing flow and is not changed. The normalization layer provides a canonical view but tennis settlement already has explicit `winner_name` semantics.

### In `_try_normalized_settle()` (new function in settler.py)

Has a fuzzy fallback: first-word substring match if exact match fails. But only within `normalized_results`, not against raw sources.

---

## What Should Be Switched Next

### Priority 1: Wire `updater_results.py` to write to normalized_results

Currently `updater_results.py` writes to `matches` table. After it finds a result via its fuzzy matching, it should also upsert to `normalized_results`. This would:
- Capture results that were found via fuzzy matching (currently lost to normalization)
- Build up the normalized table over time from operational data

### Priority 2: Add Fonbet API as a normalized source

`updater_results.py` already fetches from Fonbet API (`fetch_fonbet_results()`). Add a `normalize_fonbet_result()` function and ingest path. Fonbet is the original odds source — results from it would have high confidence.

### Priority 3: Tennis settlement dual-path

Update `tennis_live_pipeline.py`'s `settle_tennis_signals()` to try `lookup_normalized_result()` first, then fall back to `_find_result_in_live()`. Tennis already has clean semantics (explicit winner_name), so this is low-risk.

### Priority 4: Add indexes for settlement performance

```sql
CREATE INDEX IF NOT EXISTS idx_nr_settle_lookup
    ON normalized_results(sport, match_date, participant_1, participant_2);
```

### Priority 5: Add a settlement audit log

When settlement uses the normalized path, log the `raw_data` JSON for audit trail. This allows post-hoc verification that the normalized result matches what the raw source said.

---

## What Was NOT Changed

- `updater_results.py` — fuzzy matching logic unchanged (still works, still needed)
- `tennis_live_pipeline.py` — tennis settlement unchanged (already has winner semantics)
- `tennis_results_updater.py` — result fetching unchanged
- All 7 result parsers — unchanged
- `fix_sync_results.py` — PostgreSQL sync unchanged
- `settler_watchdog.py` — stale bet monitoring unchanged
- `result_for_market()` — original function preserved for fallback path

---

## Architecture After This Change

```
Raw Sources (7 parsers)          Tennis Results (betz.su)
        │                                │
        ▼                                ▼
  results_raw (3115 rows)     tennis_live_results (6 rows)
        │                                │
        └────────┬───────────────────────┘
                 ▼
      result_normalization.py
      (ingest + normalize)
                 │
                 ▼
      normalized_results (1048 rows)
      ┌─────────────────────────────┐
      │ winner_name (canonical)     │
      │ winner_side (explicit)      │
      │ score_p1/score_p2           │
      │ is_overtime (hockey)        │
      │ confidence (quality)        │
      │ raw_data (audit trail)      │
      └─────────────────────────────┘
                 │
                 ▼
      settler.py (dual-path)
      ┌─────────────────────────────┐
      │ PATH 1: normalized_results  │ ← primary
      │ PATH 2: results_raw         │ ← fallback
      └─────────────────────────────┘
                 │
                 ▼
      bets.result (won/lost)
      accuracy_log
```

---

## Answers

1. **normalized results table created?** — Yes. `normalized_results` with 20 columns, unique constraint, 5 indexes.

2. **which sports covered first?** — All three: football (519), hockey (523), tennis (6). Total: 1048 records.

3. **can settlement use normalized layer now?** — Yes, partially. `settler.py` has dual-path: tries normalized first (confidence >= 0.8), falls back to raw. Currently ~50% of settleable matches should be in normalized layer (last 30 days). As pipeline runs daily, coverage increases.

4. **what fuzzy matching remains?** — `updater_results.py` (full fuzzy pipeline unchanged), `tennis_live_pipeline.py` (surname LIKE matching), settler fallback path (4-char substring). The normalized layer itself has a soft fuzzy fallback (first-word substring) but only within its own data.

5. **what should be switched next?** — (a) Wire `updater_results.py` to upsert to `normalized_results` after fuzzy matching, (b) Add Fonbet API as normalized source, (c) Tennis settlement dual-path, (d) Settlement audit log with raw_data JSON.
