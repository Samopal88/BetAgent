# BETAGENT — Project Context

## Quick Start

```bash
python agent_handoff_v7.py --dry-run --sport hockey --limit 11
python agent_handoff_v7.py --dry-run --sport football --limit 10 --no-llm
python3 backtest_llm.py --league SA --season 2024 --limit 50
```

---

## Architecture Overview

BETAGENT is a multi-sport betting decision engine (football, hockey, tennis, MMA, esports) that finds positive-EV bets. It combines rule-driven strategies with LLM-based analysis, validates every recommendation through a gatekeeper, and manages bankroll via Kelly quarter-staking.

Two operational modes:
- **Live mode** (`agent_handoff_v7.py`): Parses current odds from Fonbet API, enriches with external data, applies rule filters, calls LLM for analysis, validates and places bets
- **Backtest mode**: Runs historical data through rules or LLM without placing real bets

---

## Project Structure

| File | Purpose |
|------|---------|
| `agent_handoff_v7.py` (~3877 lines) | Core decision engine — orchestration, LLM calls, EV/Kelly, stake resolution, DB helpers |
| `validator.py` (153 lines) | Recommendation validation gate — EV/Kelly recompute, signal classification, odds zones, exposure limits |
| `parser_v2.py` | Fonbet API odds parser |
| `strategies/football_rules.py` (~600 lines) | Football rule-driven strategies — `get_pruned_live_rule()`, league detection, form calc |
| `strategies/football.py` | Football league detection functions and league-to-staking-mode mappings |
| `strategies/hockey.py` | Hockey strategy processing with league-aware dispatch (NHL draw_tight, Czech home_favorite, KHL intersection) |
| `hockey_backtest_fast_v2.py` | Fast rule-based hockey backtest with 6+ strategy functions and ensemble logic |
| `backtest.py` | Rule-based football backtest (no LLM) |
| `backtest_llm.py` | LLM-based football backtest with dynamic historical form/table building |
| `enricher_football.py` | Football data enrichment (form, standings, H2H via football-data.org) |
| `injuries_fetcher.py` | Injury data fetcher |
| `fetch_team_history.py` | Historical team data fetcher |
| `settler.py` | Bet settlement engine (dual-path: normalized primary, raw fallback) |
| `result_normalization.py` | Result normalization layer — canonical winner/score from raw sources |
| `pipeline_stability.py` | Pipeline hardening — task wrapper, fail-fast, run summaries, sanity checks |
| `pipeline_alerting.py` | Failure alerting — Telegram alerts for critical pipeline task failures |
| `clv_tracker.py` | Closing Line Value tracking |
| `tg_bot.py` | Telegram bot for notifications |
| `web_panel.py` | Flask dashboard |
| `run_pipeline.py` | Scheduled pipeline orchestrator (4 daily runs: 08:00, 14:00, 21:00, 23:30) with stability layer |
| `updater_results.py` | Result fetching + match status updates (fuzzy matching, transitional — writes to `matches`, not `normalized_results`) |
| `backtest_downloader.py` | Historical data downloader |
| `sport_profiles.json` | Per-sport calibration profiles (probability caps, penalties, preflight rules) |
| `analysis_helpers/probability_pipeline.py` (558 lines) | Pure: sport profiles, calibration engine, pre-flight checks, backtest approval, facts normalization |
| `analysis_helpers/backtest_reporting.py` (412 lines) | Pure: shadow detection, strategy bucketing, equity/streak metrics, settlement, summary printing |
| `analysis_helpers/llm_utils.py` (98 lines) | Pure: JSON extraction, response normalization, structured comment building |
| `analysis_helpers/match_utils.py` (95 lines) | Pure: BA rule mapping, display tags, market family, placeholder detection, safe prob, float coercion |
| `db/init.sql` | PostgreSQL schema for SaaS API layer |
| `AGENT_RULES.md` | BETAGENT v2.2 betting rules documentation |

---

## Decomposition Progress (agent_handoff_v7.py)

**Original:** ~5100 lines → **Current:** ~3877 lines (−1223 lines extracted across 5 steps)

### Extracted Modules (Steps 1-5)

| Step | Module | Lines | Functions | Status |
|------|--------|-------|-----------|--------|
| 1 | `strategies/football_rules.py` | ~600 | `get_pruned_live_rule()`, form helpers, league detection | Complete |
| 2 | `analysis_helpers/probability_pipeline.py` | 558 | `calibrate_probability()`, `pre_flight_check()`, `is_backtest_approved()`, profiles | Complete |
| 3 | `analysis_helpers/backtest_reporting.py` | 412 | `update_strategy_stats()`, `print_strategy_summary()`, equity/streak metrics | Complete |
| 4 | `analysis_helpers/llm_utils.py` | 98 | `extract_json_object()`, `normalize_response()`, `build_structured_comment()` | Complete |
| 5 | `analysis_helpers/match_utils.py` | 95 | `ba_rule_to_market()`, `get_market_family()`, `_ba_tag()`, `_rule_tag()`, `safe_prob()`, `_coerce_float()`, `is_placeholder_match()` | Complete |

### What Remains in agent_handoff_v7.py (not yet extractable)

| Block | ~Lines | Why Tightly Coupled |
|-------|--------|---------------------|
| `build_rule_recommendation()` | ~240 | DB calls (`get_conn()`, `resolve_stake_pct_and_meta()`) |
| `enrich_with_math()` | ~340 | DB calls for adaptive staking, stake mode resolution |
| `call_llm()` / `simulate_llm_response()` | ~200 | GLOBAL_ARGS, env vars, HTTP, prompt templates |
| `enforce_validator_gate()` | ~70 | GLOBAL_ARGS (dry_run mode) |
| `save_handoff_decision()` / `save_recommendation()` | ~200 | DB writes, JSON serialization |
| `print_result()` / `print_backtest_summary()` | ~100 | Console output, formatting |
| Main analysis loop (`main()`) | ~800+ | Orchestration, all sports |
| DB helpers (`get_conn`, schema, bankroll, exposure) | ~200 | Engine-level infrastructure |
| `ALLOWED_LEAGUES` + `is_league_allowed()` | ~60 | Used by main loop, trivial size |

### Extraction Rules

- One small extraction at a time
- Mandatory backtest BEFORE/AFTER comparison (football --limit 200 --no-llm + hockey --limit 50 --no-llm)
- No behavior changes allowed — identical output required
- No refactoring of orchestration, LLM call path, or DB-heavy logic without explicit approval

---

## Database Schema

### Local SQLite (`betagent.db`)

The engine uses SQLite with these key tables:

**`backtest_matches`** — Historical match results used for backtesting and form building.
- Columns: `id`, `home_team`, `away_team`, `league`, `season`, `match_date`, `home_score`, `away_score`, `result` (H/D/A), `odds_home`, `odds_draw`, `odds_away`, `home_scored_avg`, `away_scored_avg`, etc.

**`match_facts`** — Enriched match context at analysis time.
- Columns: `match_id`, `form_last_5_home`, `form_last_5_away`, `h2h_summary`, `home_position`, `away_position`, `home_goals_scored_avg`, `home_goals_allowed_avg`, `away_goals_scored_avg`, `away_goals_allowed_avg`, `notes`, etc.
- Loaded via `_load_match_facts()` at `agent_handoff_v7.py:2418`

**`bets`** — Placed bet records.
- Track match_id, market, odds, stake, status (pending/won/lost).

**`signals`** — Published betting signals (also in PostgreSQL SaaS schema).
- Columns: `id`, `sport`, `league`, `home_team`, `away_team`, `match_date`, `market`, `odds`, `bookmaker`, `confidence`, `ev_range`, `result`.
- Used as the public-facing signal storage; the `handoff_decisions` table stores internal LLM outputs.

**`normalized_results`** — Canonical normalized match results (added 2026-04-13).
- Columns: `id`, `source`, `source_match_id`, `sport`, `league`, `match_date`, `participant_1`, `participant_2`, `winner_name`, `loser_name`, `winner_side`, `score_p1`, `score_p2`, `score_detail`, `status`, `is_overtime`, `raw_data`, `parsed_at`, `normalized_at`, `confidence`.
- Unique key: `(source, source_match_id, sport)`. Indexes on `(sport, match_date)`, `(winner_name)`, `(participant_1, participant_2)`, `(status)`, `(source)`.
- Populated by `result_normalization.py` from `results_raw` (football/hockey) and `tennis_live_results` (tennis).
- Settlement reads from this table first (dual-path: normalized primary, raw fallback).
- `winner_side` is explicit: `participant_1`, `participant_2`, or `draw`. For hockey OT matches, regulation-time score is preserved as a draw.

**`results_raw`** — Raw match results from 7+ parsers (transitional — settlement should prefer `normalized_results`).
- Columns: `id`, `league`, `match_date`, `kickoff`, `home_team`, `away_team`, `home_score`, `away_score`, `is_finished`, `source`, `updated_at`, `is_overtime`.
- Still used by `updater_results.py` for fuzzy matching and by enrichment scripts.
- Settlement falls back to this table when `normalized_results` doesn't have the match.

**`tennis_live_results`** — Tennis match results from betz.su (transitional — settlement should prefer `normalized_results`).
- Columns: `id`, `tour`, `level`, `tournament`, `surface`, `match_date`, `winner_name`, `loser_name`, `sets_winner`, `sets_loser`, `score_detail`, `source`, `fetched_at`.
- Still used by `tennis_live_pipeline.py` for tennis signal settlement.

### PostgreSQL SaaS (`db/init.sql`)

Multi-tenant API layer: `users`, `subscriptions`, `payments`, `signals`, `user_signal_views` (anti-leak watermarking), `audit_log`.

---

## Pipeline Stability Layer (`pipeline_stability.py`)

Added 2026-04-13. Minimal hardening layer for `run_pipeline.py` — additive, no strategy/ML changes.

### Components

| Component | Purpose |
|-----------|---------|
| `TaskResult` | Dataclass: name, started_at, ended_at, duration_sec, success, error, metadata |
| `RunSummary` | Collects per-task results, aggregates counters, saves JSON + text to `run_summaries/` |
| `run_task(name, fn, summary)` | Wraps any callable with timing, exception handling, auto-adds to summary |
| `check_parse_sanity(sport, db)` | Verifies parsed matches exist, odds in range, no stale pending |
| `check_enrich_sanity(sport, db)` | Verifies enrichment produced data today |

### Fail-Fast Behavior

```
parse ──┬── enrich_football ── bet_football
        │
        └── enrich_hockey ── bet_hockey

bet_tennis (independent — runs even if parse fails)
settle (independent — runs even if parse fails)
notify/archive (non-critical — always runs)
```

| Failure | Action |
|---------|--------|
| `parse` fails | Skip `enrich_football`, `enrich_hockey`, `bet_football`, `bet_hockey` |
| `enrich_football` fails | Skip `bet_football`. Hockey and tennis still run |
| `enrich_hockey` fails | Skip `bet_hockey`. Football and tennis still run |
| `settle` fails | Log warning, continue |
| `notify` fails | Log warning, continue |
| `bot/notifier.py` missing | Log warning, skip (dead code detection) |

### Run Summaries

Each pipeline run saves JSON + text to `run_summaries/` directory:
- JSON: `run_summaries/morning_20260413_080000.json` — full structured data
- Text: logged to `pipeline.log` — human-readable summary with per-task status, duration, counters

### Failure Alerting (`pipeline_alerting.py`)

Added 2026-04-14. Sends a single Telegram alert to admin chat when critical pipeline tasks fail.

| Feature | Detail |
|---------|--------|
| Critical tasks | `parse`, `enrich_football`, `enrich_hockey`, `bet_football`, `bet_hockey`, `bet_tennis`, `settle`, `normalize` |
| Warning tasks | `archive_snapshot`, `tennis_*`, `notify_*` — don't trigger alerts unless fail_fast is active |
| Deduplication | One alert per run (all failures in one message) |
| Safety | `try/except` wrapper — alerting failures never crash the pipeline |
| No spam | Clean runs produce zero alerts |
| Delivery | Direct Telegram Bot API POST, independent of `tg_bot.py` notify flow |

Called automatically after `summary.save()` in every runner (`morning`, `afternoon`, `evening`, `night`, `full`).

---

## Result Normalization Layer (`result_normalization.py`)

Added 2026-04-13. Canonical normalized result entity so settlement doesn't depend on raw source quirks.

### Flow

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
      normalized_results (~1048 rows)
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
```

### Per-Sport Normalization Rules

| Sport | Source | Key Normalization |
|-------|--------|-------------------|
| **Football** | `results_raw` | Derive winner from score. Normalize team names. Confidence = 1.0. |
| **Hockey** | `results_raw` | Same + capture `is_overtime`. OT matches: regulation score = draw. Source-dependent confidence: `betz.su`=1.0, `sports.ru`=0.9, others=0.85. |
| **Tennis** | `tennis_live_results` | Already has explicit winner_name/loser_name. Maps to canonical format. |

### Name Normalization

- `normalize_team_name()`: strips trailing parentheticals, expands hockey abbreviations (CGY→Калгари, MTL→Монреаль, etc.)
- `extract_surname()`: handles "First Surname" and "Surname Initial" formats for tennis

### Lookup API

- `lookup_normalized_result(conn, sport, p1, p2, date)` — exact match first, then fuzzy fallback within normalized data
- `result_for_market_normalized(market, winner_side, score_p1, score_p2, is_overtime, sport)` — determines bet result using normalized semantics

---

## Settlement Architecture (Dual-Path)

`settler.py` uses a two-path approach:

1. **PATH 1 (primary)**: Try `normalized_results` via `lookup_normalized_result()`. If confidence >= 0.8, use normalized winner/score.
2. **PATH 2 (fallback)**: Existing raw `results_raw` logic with fuzzy matching — unchanged, still works.

### Hockey OT/SO Semantics

Critical fix: for hockey OT matches, `normalized_results` stores:
- `score_p1` = `score_p2` (regulation-time draw, e.g., 1:1)
- `is_overtime` = 1
- `winner_side` = "draw"

When settling a draw market bet on an OT match, `result_for_market_normalized()` returns "won" because regulation time was a draw. The raw fallback handles this separately by rewriting OT draws to 1:1.

### Tennis Settlement

`tennis_live_pipeline.py` has its own settlement (`settle_tennis_signals()`) that:
1. Looks up in `tennis_live_results` by surname substring match
2. Falls back to `backtest_tennis_players`
3. Compares bet pick against explicit `winner_name` — not player positions

This is NOT yet dual-path with normalized_results (planned next step).

### Tennis Architecture: Results vs Betting Universe

**Results coverage and betting universe are intentionally different scopes.** The results parser collects more tournaments than the betting pipeline creates bets for.

| Component | Scope | Filter Mechanism |
|-----------|-------|-----------------|
| `tennis_results_updater.py` | ATP/WTA 250-1000 (main + qual) + Challenger (main + qual) | `SKIP_KEYWORDS` blocks ITF, juniors, doubles; `TARGET_LEVELS` allows main tour + Challenger |
| `tennis_live_pipeline.py` | ATP/WTA 250-1000 only (main + qual) | `_BLOCKED_TOUR_KEYWORDS` blocks Challenger, ITF, qualifying |

**Why this design:**
1. Settlement can resolve any bet that was created, including edge cases
2. Historical data accumulates for future strategy development
3. The betting pipeline's narrower filters remain the sole gatekeeper for bet creation
4. Extra results in `tennis_live_results` that no bet references are harmless — they just sit unused

**Current filter state (2026-04-13):**

Results parser (`tennis_results_updater.py`):
```python
TARGET_LEVELS = ["ATP 250", "ATP 500", "ATP 1000", "WTA 250", "WTA 500", "WTA 1000", "Challenger"]
SKIP_KEYWORDS = ["двойные", "эйсы", "Пары", "ITF", "Юниоры", "Итого", "Статистика"]
```

Betting pipeline (`tennis_live_pipeline.py:799-802`):
```python
_BLOCKED_TOUR_KEYWORDS = ["challenger", "челлендж", "itf", "125k", "квалификац", "qualifying"]
```

**Volume impact:** Challenger adds ~8 main draw + ~19 qualifying matches/day average, but these results are never used for settlement since no Challenger bets are created. Main tour qualifying adds ~18 matches/day and IS used for settlement (resolved bet 874: +11,195 RUB).

---

## Pipeline Orchestration (`run_pipeline.py`)

### Daily Runners

| Runner | Time | Key Steps |
|--------|------|-----------|
| `run_morning()` | 08:00 | normalize → settle → parse → enrich → bet (all sports) → archive → tennis → notify |
| `run_afternoon()` | 14:00 | parse → enrich → bet (football) → archive → tennis → notify |
| `run_evening()` | 21:00 | normalize → settle → parse → enrich → bet (all sports) → archive → tennis → notify |
| `run_night()` | 23:30 | parse → bet (tennis only) → archive → tennis → notify |

### Pipeline Steps

| Step | Function | Purpose |
|------|----------|---------|
| `task_normalize_results()` | NEW | Run result normalization for football, hockey, tennis (last 3 days) |
| `task_settle()` | Modified | Settle bets — now calls normalize first, then parses results, then runs updater |
| `task_parse()` | Unchanged | Parse odds from Fonbet API |
| `task_enrich_football()` | Unchanged | Enrich football matches with form, standings, injuries |
| `task_enrich_hockey()` | Unchanged | Enrich hockey matches with stats |
| `task_bet_football()` | Unchanged | Run football analysis, create signals/bets |
| `task_bet_hockey()` | Unchanged | Run hockey analysis, create signals/bets |
| `task_bet_tennis()` | Unchanged | Run tennis pipeline |
| `task_tennis_results()` | Unchanged | Fetch tennis results from betz.su |
| `task_tennis_settle()` | Unchanged | Settle tennis signals |
| `task_archive_snapshot()` | Unchanged | Archive historical data |
| `task_notify()` | Unchanged | Send notifications |

---

## Transitional / Deprecated Logic

These components still exist but should be phased out or updated in future work:

| Component | Status | Issue | Next Step |
|-----------|--------|-------|-----------|
| `updater_results.py` fuzzy matching | Transitional | Writes to `matches` table, not `normalized_results` | Wire to upsert to `normalized_results` after fuzzy match |
| `settler.py` raw fallback | Transitional | Still uses 4-char substring fuzzy matching | Reduce as `normalized_results` coverage grows |
| `tennis_live_pipeline.py` surname matching | Transitional | `LIKE '%surname%' COLLATE NOCASE` | Switch to dual-path with `normalized_results` |
| `results_raw` as settlement source | Transitional | 7+ parsers, inconsistent formats | `normalized_results` should become primary |
| `bot/notifier.py` | Live | Client subscriber notifications — `notify_tennis_signals()` wired to pipeline (2026-04-14) | No action needed |

---

## Strategies

### Football Rule-Driven Strategies (`agent_handoff_v7.py:440-731`, `get_pruned_live_rule`)

Each rule checks league, odds range, table position, form, and goal averages:

| Rule | League | Market | Key Criteria |
|------|--------|--------|--------------|
| `DRAW_SA` | Serie A | Draw | Table diff ≤ 5, form gap ≤ 3, both avg goals ≤ 1.55, both conceded ≤ 1.75 |
| `DRAW_BALANCED_LOW_SCORING_SA` | Serie A | Draw | Odds 3.0-3.6, table diff ≤ 6, low scoring both teams |
| `DRAW_BALANCED_LINE_SA` | Serie A | Draw | Odds close together (gap ≤ 0.95), both ≥ 2.0, table diff ≤ 5 |
| `SA_AWAY_DRAW` | Serie A | Draw | Specific away teams + draw odds in bimodal zone + under_2.5 ≤ 2.0 |
| `AWAY_SA_STRICT_PLUS` | Serie A | Away | Away team better in table (gap ≥ -4), form ahead by ≥ 4pts |
| `BTTS_YES_CORE` | EPL/BL1 | BTTS Yes | Both score ≥ 1.0, both concede ≥ 0.8 in last 5 |
| `RPL_OVER25_BTTS` | RPL | Over 2.5 | Over2.5 = 1.8-2.1 AND BTTS = 1.8-2.1 (doubly confirmed) |
| `PD_BTTS_DOUBLE` | La Liga | BTTS Yes | Over2.5 = 1.6-1.9 AND BTTS = 1.75-1.95 |
| `FL1_BTTS_DOUBLE` | Ligue 1 | BTTS Yes | Over2.5 = 1.6-1.9 AND BTTS = 2.0-2.1 |
| `NLA_BERN_AWAY_DRAW` | Swiss NLA | Draw | Bern playing away, draw odds 4.0-5.2 |
| `MLS_BTTS_HOME` | MLS | BTTS Yes | Specific attacking home teams, BTTS odds 1.50-1.75 |
| `SUMMER_BTTS_HOME` | DK/SWE/FIN | BTTS Yes | Specific teams, BTTS odds 1.55-1.85 |

DISABLED rules: `DRAW_BL1`, `AWAY_SA`, `DRAW_BALANCED_LINE_BL1` (negative ROI).

### Hockey Strategies (`hockey_backtest_fast_v2.py`)

| Strategy | Logic |
|----------|-------|
| `underdog_live` | Favors underdog based on PPG diff, form5, expected goal diff, attack gaps |
| `defensive_wall` | Values low GA_10, low expected total, tight match, defensive balance |
| `favorite_pressure` | Favors favorite based on strength metrics |
| `draw_tight` | Close teams on all metrics |
| `nhl_draw_tight` | NHL draw when odds 3.5-5.0, abs(ppg)<0.2, abs(form5)<0.5 |
| `czech_home_favorite` | Czech home win when odds 1.6-2.0, strength diff PPG>0.5 |

**KHL matches** use intersection of `underdog_live` AND `defensive_wall`. Other leagues use single-strategy paths.

**`combined_pick()`** — Combines `favorite_pressure` + `favorite_bounceback` in fp_or_fb, fp_and_fb, fp_or_fb_priority_fb modes.
**`ensemble_pick()`** — Combines underdog + defensive_wall in strict_intersection, relaxed_odds, relaxed_edge modes.

### EV/Kelly Requirements

All bets: `EV = probability * odds - 1 >= 0.03`. Min edge: 0.025 for football, 0.03 for hockey. Kelly quarter-fraction with confidence caps (see `validator.py:25-38`).

---

## How Backtest Mode Works vs Live Mode

### Backtest Mode
1. **Rule-based** (`backtest.py`, `hockey_backtest_fast_v2.py`): Applies mathematical criteria to historical data. No LLM. Fast.
2. **LLM-based** (`backtest_llm.py`): Calls OpenRouter LLM API for each historical match. Dynamically builds form, table, H2H as they existed at each match date (avoids look-ahead bias via `before_date` filtering in `build_form()`, `build_table()`). Applies `math_filter()` with probability cap 0.57, min edge 0.025.

**Key backtest flow**: `fetch_backtest_matches()` → build features → filter → bet simulation with Kelly × 0.25 → equity tracking in `backtest_equity` table.

### Live Mode
1. Parse current odds from Fonbet via `parser_v2.py`
2. Enrich with form, standings, injuries
3. **Football**: Run rule-driven analysis first (`get_pruned_live_rule()`). If match passes rules, still call LLM in **shadow mode** (`shadow_only=True`) for data collection — rule path is primary.
4. **Hockey**: Entirely rule-based via `hockey_backtest_fast_v2` functions. No LLM needed.
5. All recommendations go through `validator.validate_recommendation()` before being placed or sent to Telegram.
6. Shadow mode results stored in `handoff_decisions` table for later analysis.

**CLI flags**: `--dry-run` (don't place bets), `--no-llm` (skip LLM calls), `--backtest` (use historical data), `--pure-ba` (backtest-approved rules only).

---

## Form Calculation Logic

### Live Mode (enricher)
Form data comes from `enricher_football.py` via football-data.org API:
- `form_last_5_home` / `form_last_5_away` — arrays of W/D/L results
- `home_form_details` / `away_form_details` — arrays with goals_for/goals_against per match
- `home_goals_scored_avg`, `away_goals_scored_avg` — season averages
- In `get_pruned_live_rule()`: `calc_form_stats()` computes form_scored and form_conceded from form_details, falling back to season averages

### Backtest Mode (dynamic reconstruction)
In `backtest_llm.py:33-107`:
```python
def build_form(matches, team, before_date, n=5):
    # Filters to matches before the target date only
    # Avoids look-ahead bias by rebuilding form per match
```
Similar for `build_goals()`, `build_table()`, `build_h2h()`.

### Form Penalties in Calibration (`calibrate_probability()` in `analysis_helpers/probability_pipeline.py`)

Applied after LLM returns probability:
1. **Cap by lineup status**: Without lineups → cap at profile's `no_lineup_cap` (football: 0.57, hockey: 0.58). With lineups → `lineup_cap` (0.72 / 0.70). BTTS gets +0.03 softer cap.
2. **League adjustment**: Multiply by `league_confidence` factor (e.g., Serie A ×1.15, RPL ×1.00, Ligue 1 ×0.92).
3. **No H2H penalty**: Subtract `no_h2h_penalty` (-0.01 football, -0.02 hockey)
4. **Short form penalty**: If min(home_form, away_form) < 3 → subtract 0.02/0.03. If < 5 → subtract 0.01.
5. **Lineup/injury penalties**: Additional subtractions based on signal type (Weak/Medium) and missing data.
6. **Floor**: Apply `probability_floor` (football: 0.36, hockey: 0.38).

---

## How LLM Calls Are Made

**Function**: `call_llm()` in `agent_handoff_v7.py` (line ~2516)

**API**: OpenRouter (`https://openrouter.ai/api/v1/chat/completions`)
**Env vars**: `LLM_API_URL`, `LLM_API_KEY`, `LLM_MODEL` (default: `anthropic/claude-haiku-4-5`)

```python
body = {
    "model": LLM_MODEL,
    "temperature": 0.1,
    "response_format": {"type": "json_object"},
    "messages": [
        {"role": "system", "content": SYSTEM_PROMPT},  # lines 1031-1117
        {"role": "user", "content": USER_PROMPT_TEMPLATE.format(payload)},
    ],
}
```

**Retry logic**: 3 attempts with 15s delay on 500/502/503, 10s on timeout/connection errors.

**System prompt** (lines 1031-1117): Contains full BETAGENT v2.2 rules — draw logic, lineup/injury handling, team quality checks, stop conditions.

**Response format**: JSON with `market`, `our_probability`, `confidence`, `signal_type`, `decision`, `market_error`, `confirmed_facts`, `lineup_data_available`.

**Post-processing**: `normalize_response()` cleans up fields, maps market names.

---

## Validation Pipeline (`validator.py:64-153`)

Every recommendation must pass:
1. `market != "pass"` and `decision != "PASS"`
2. EV >= 0.03 (recomputed: `EV = our_p * odds - 1`)
3. Kelly > 0 (recomputed: `Kelly = (p*o - 1) / (o - 1)`)
4. Odds >= 1.50 (zone 1.50-1.54 requires Strong signal + EV > 5%)
5. Total exposure < 50% (`open_exposure_pct + stake_pct <= 0.50`)
6. Loss streak halving: 3+ losses in 72h same sport → stake / 2
7. `market_error` field required
8. `confirmed_facts` required
9. Strong signal requires `lineup_data_available = True`
10. Confidence cap checked

Signal classification (`classify_signal()`):
- `Pass` if confirmed_facts <= 0
- `Strong` if lineups available + confirmed_facts >= 2
- `Medium` if confirmed_facts >= 1
- Otherwise `Weak`

**Stake calculation**: `min(kelly_quarter, confidence_cap, 10%)`. Confidence caps range from 0 (confidence 1) to 0.10 (confidence 10).

---

## Common Patterns for Adding Filters

### Adding a new football rule strategy
Edit `get_pruned_live_rule()` in `agent_handoff_v7.py:440-731`. Pattern:
```python
# Rule name
if (is_LEAGUE() and match.odds_market is not None and
        MIN <= float(match.odds_market) <= MAX):
    td = table_diff()
    if td is not None and td <= TABLE_DIFF:
        if _has_home_form and _has_away_form:
            if home_form_condition and away_form_condition:
                return "RULE_NAME", "market"
```

### Adding a new hockey strategy
Add function in `hockey_backtest_fast_v2.py` following `underdog_live()` / `defensive_wall()` pattern. Integrate via `combined_pick()`, `ensemble_pick()`, or league dispatch in `strategies/hockey.py`.

### Adding sport profile parameters
Edit `sport_profiles.json` profile section. Key fields: `no_lineup_cap`, `lineup_cap`, `probability_floor`, `min_edge_vs_market`, `min_ev`, penalties, `preflight_rules`, `league_confidence`.

### Adding validation gates
Edit `validate_recommendation()` in `validator.py`. Add checks before the `notes.append("VALID")` line.

### Adding pre-LLM filters
Edit `preflight_rules` in `sport_profiles.json` or add logic in `pre_flight_check()` in `analysis_helpers/probability_pipeline.py`. Current rules: require_any_data, min_form_for_llm, block_if_no_h2h_and_short_form, require_injuries_for_medium_without_lineups, require_table_for_medium_without_lineups.

### Adding a new sport
1. Add profile to `sport_profiles.json`
2. Add strategy functions or league detection
3. Ensure `get_profile(sport)` loads correctly
4. Wire up in main() analysis flow

---

## Key Constants

- **Bankroll**: Configurable, default 100,000 RUB
- **Kelly fraction**: 0.25 (quarter Kelly)
- **Max stake**: 10% of bankroll
- **Minimum odds**: 1.50 (absolute), 1.55 for most strategies
- **Minimum EV**: 0.03 (3%)
- **Max exposure**: 50% of bankroll
