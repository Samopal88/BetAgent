# Tennis Results Updater — Implementation Report

**Date:** 2026-04-12
**Status:** IMPLEMENTED

---

## 1. Source Chosen

**betz.su** (`https://betz.su/res/result.php?date=DD.MM.YYYY&sport=Теннис`)

Why betz.su:
- Updated daily (results appear same day as match completion)
- Russian player names match Fonbet API format (same transliteration conventions)
- No API key required — simple HTTP GET with standard headers
- HTML structure is stable: `<div id="cc">` for league headers, `<a>` tags for match pairs
- Already used in project for other sports data

Alternative considered: tennis-data.co.uk (CSV, English names, updated with 1-2 day lag, requires mapping).

---

## 2. Table for Live Results

**`tennis_live_results`** — new table in `betagent.db`

| Column | Type | Notes |
|--------|------|-------|
| id | INTEGER PK | Auto-increment |
| tour | TEXT | ATP / WTA |
| level | TEXT | 250 / 500 / 1000 |
| tournament | TEXT | Tournament name (e.g. "ATP Монте-Карло") |
| surface | TEXT | clay / grass / hard / indoor / unknown |
| match_date | TEXT | YYYY-MM-DD |
| player1 | TEXT | Winner (Russian name, Fonbet format) |
| player2 | TEXT | Loser (Russian name, Fonbet format) |
| winner | TEXT | Same as player1 |
| loser | TEXT | Same as player2 |
| sets_winner | INTEGER | e.g. 2 |
| sets_loser | INTEGER | e.g. 1 |
| score_detail | TEXT | e.g. "(6:2, 4:6, 7:5)" |
| source | TEXT | "betz_su" |
| fetched_at | TEXT | datetime('now') |

Unique constraint: `(match_date, player1, player2, tour)` — prevents duplicate inserts.

Indexes on `match_date` and `(player1, player2)` for fast settlement lookup.

---

## 3. Update Frequency

**Every pipeline run** — 4 times daily (morning 08:00, afternoon 14:00, evening 21:00, night 23:30).

Each run fetches the last 3 days (`--days 3`) to catch any missed results or late updates. Dedup is handled by the UNIQUE constraint + upsert logic in `save_results()`.

This ensures:
- Morning run catches overnight results
- Afternoon run catches morning completions
- Evening run catches afternoon results before peak notification window
- Night run catches late-night completions

---

## 4. How Settlement Works Now

**Priority chain** in `settle_tennis_signals()` (`tennis_live_pipeline.py`):

1. **Live source** (`tennis_live_results`):
   - Loads English→Russian name mapping from `tennis_player_mapping` table
   - Reverses it to English→Russian for lookup
   - Queries `tennis_live_results` using Russian player names
   - Falls back to English name + last-name substring match if Russian names don't match
   - Returns "p1_won" or "p2_won"

2. **Backtest fallback** (`backtest_tennis_players`):
   - Only used if live source returns no result
   - Uses English names directly (historical CSV data)
   - Same substring fallback

3. **Result recording**:
   - Updates `tennis_signals` table with `result` field ("won"/"lost")
   - Records `settled_at` timestamp and `settle_source` ("live" or "backtest")

```
Signal (English names) → reverse map → Russian names → tennis_live_results lookup
                                                          ↓ (not found)
                                              backtest_tennis_players lookup
```

---

## 5. Pipeline Integration

**`run_pipeline.py`** — tennis tasks wired into all 4 runners:

```
task_tennis_results()   ← fetches betz.su results (--days 3)
task_tennis_settle()    ← settles pending signals using live + fallback
task_bet_tennis()       ← generates new tennis signals
```

Order in each runner (after analysis, before notifications):
1. `task_tennis_results()` — refresh results first
2. `task_tennis_settle()` — settle using fresh results
3. `task_notify_tennis("bets")` — notify about new bets
4. `task_notify_tennis("results")` — notify about settled results (evening only)

Removed duplicate `task_tennis_settle()` calls that existed before analysis in `run_evening` and `run_night` — settlement now happens only once per runner, after results are refreshed.

---

## Files Modified

| File | Change |
|------|--------|
| `tennis_results_updater.py` | **Created** — betz.su scraper, `tennis_live_results` table, `lookup_result()` helper |
| `tennis_live_pipeline.py` | **Modified** — `_load_eng_to_rus_map()`, `_find_result_in_live()`, `_find_result_in_backtest()`, rewritten `settle_tennis_signals()` |
| `run_pipeline.py` | **Modified** — added `task_tennis_results()`, wired into all 4 runners, removed duplicate settle calls |

---

## Answers to Required Questions

1. **Source chosen?** betz.su — daily-updated, Russian names matching Fonbet format
2. **Table for live results?** `tennis_live_results` with UNIQUE constraint on (match_date, player1, player2, tour)
3. **Update frequency?** Every pipeline run (4x daily), fetching last 3 days with dedup
4. **How settlement works now?** Live source first (tennis_live_results with Russian name mapping) → backtest fallback (backtest_tennis_players with English names) → unsettled if neither found
5. **Integrated into pipeline?** Yes — `task_tennis_results()` → `task_tennis_settle()` → `task_bet_tennis()` in all 4 runners, before notifications
