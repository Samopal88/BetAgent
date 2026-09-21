# Agent Handoff Split — Step 2: Calibration & Preflight Extraction

**Date:** 2026-04-14
**Status:** Complete — backtest identical, zero regression

---

## What Was Extracted

### New file: `analysis_helpers/probability_pipeline.py` (558 lines, 11 functions)

| Function | Lines (original) | Purpose |
|----------|-----------------|---------|
| `get_profile()` | 252-253 | Sport profile dict lookup |
| `DEFAULT_PROFILE` | 224-248 | Default calibration parameters |
| `SPORT_PROFILES` | 216-222 | Loaded sport profiles from JSON |
| `_wins()` | 256-257 | Count wins in form list |
| `_draws()` | 259-260 | Count draws in form list |
| `_norm_form_list()` | 352-370 | Normalize form data to list |
| `_pick_first_nonempty()` | 372-378 | Pick first non-empty value from dict keys |
| `normalize_known_facts_for_rules()` | 380-420 | Normalize facts dict with alias resolution |
| `merge_known_facts()` | 422-443 | Merge two facts dicts with priority |
| `is_backtest_approved()` | 262-348 | Backtest-approved shortlist rules (6 rules) |
| `pre_flight_check()` | 2410-2470 | Pre-LLM filter based on sport_profiles.json |
| `calibrate_probability()` | 2492-2693 | Unified probability calibration engine |

### What these functions cover

**Profile loading**: `SPORT_PROFILES` from `sport_profiles.json`, `DEFAULT_PROFILE` fallback, `get_profile()` lookup.

**Form helpers**: `_wins`, `_draws`, `_norm_form_list`, `_pick_first_nonempty` — pure utilities for form data normalization.

**Facts normalization**: `normalize_known_facts_for_rules` resolves field aliases (e.g., `home_form` → `form_last_5_home`), `merge_known_facts` combines two facts dicts.

**Backtest approval**: 6 conservative shortlist rules (DRAW_SA, AWAY_SA, P1_PD, PD_AWAY_VALUE, DRAW_BL1_FL1, AWAY_BL1) — bypass pre-flight but don't auto-create bets.

**Pre-flight check**: 6 rules from `sport_profiles.json` → `preflight_rules` — blocks LLM calls when data is insufficient.

**Calibration engine**: 6-step probability calibration:
1. Cap by lineup status (Weak/Medium, BTTS vs 1X2)
2. League confidence adjustment
3. H2H penalty
4. Short form penalty
5. Lineup/injury penalties (two-level: BTTS reduced, 1X2 standard)
6. Floor + underdog protection

### Dependencies

`probability_pipeline.py` imports only:
- `json`, `os`, `pathlib`, `typing` (stdlib)
- `sport_profiles.json` (config file, same path resolution)

No new external dependencies introduced.

### Changes to `agent_handoff_v7.py`

1. Added import: `from analysis_helpers.probability_pipeline import (...)`
2. Removed ~480 lines of inline code (SPORT_PROFILES loading, DEFAULT_PROFILE, 11 functions)
3. `build_rule_recommendation()` remains in `agent_handoff_v7.py` (tightly coupled to DB)
4. `enrich_with_math()` remains in `agent_handoff_v7.py` (DB calls, stake resolution)

---

## What Remains in God File

| Block | Lines | Why Not Extracted |
|-------|-------|-------------------|
| `build_rule_recommendation()` | ~240 lines | Depends on `get_conn()`, `resolve_stake_pct_and_meta()`, `get_market_family()`, `_wins()` — tightly coupled to engine internals |
| `enrich_with_math()` | ~340 lines | Calls `get_conn()`, `resolve_stake_pct_and_meta()`, DB queries for adaptive staking, bankroll regime |
| `is_league_allowed()` | ~20 lines | Used by multiple sports, trivial size |
| LLM system prompt + `call_llm()` | ~150 lines | Core engine, not pure helper |
| `normalize_response()` | ~15 lines | Tiny, LLM post-processing |
| Main analysis loop | ~2000+ lines | Orchestration, all sports |
| DB helpers (`get_conn`, schema, bankroll) | ~200 lines | Engine-level, not extractable without major refactor |
| Exposure/streak/strategy helpers | ~100 lines | DB-dependent |

---

## Dependency Blockers

| Function | Blocks Extraction Of | Reason |
|----------|---------------------|--------|
| `get_conn()` | `build_rule_recommendation()`, `enrich_with_math()` | SQLite connection, engine-level |
| `resolve_stake_pct_and_meta()` | `enrich_with_math()` | Depends on `bankroll_state`, `match`, `rec` — engine state |
| `get_market_family()` | `build_rule_recommendation()` | Cross-sport market mapping, used by exposure checks |
| `GLOBAL_ARGS` | `enrich_with_math()` | Global state for bankroll, backtest flag |
| `enrich_with_math()` | Full rule→rec pipeline | Has DB calls for adaptive staking (BTTS_YES_CORE), stake mode resolution |

---

## Backtest BEFORE vs AFTER

### Football backtest (--limit 200, --no-llm)

| Metric | BEFORE | AFTER | Match? |
|--------|--------|-------|--------|
| матчей | 200 | 200 | YES |
| pre-flight SKIP | 29 | 29 | YES |
| LLM вызовов | 0 | 0 | YES |
| BET | 21 | 21 | YES |
| РЕШЕНИЯ: всего | 202 | 202 | YES |
| BET (total) | 60 | 60 | YES |
| PASS | 142 | 142 | YES |
| valid | 60 | 60 | YES |
| invalid | 142 | 142 | YES |
| BACKTEST: total | 60 | 60 | YES |
| settled | 39 | 39 | YES |
| wins | 17 | 17 | YES |
| losses | 22 | 22 | YES |
| no_result | 21 | 21 | YES |
| Адаптивный стейкинг | 0.75% | 0.75% | YES |
| Drawdown | 10.2% | 10.2% | YES |

### Per-strategy comparison

Full line-by-line diff of filtered backtest output: **ZERO DIFFERENCES**

Every strategy bucket (DRAW_SA, PD_AWAY_VALUE, RPL_OVER25_BTTS, BTTS_YES_CORE, heuristic_shadow, etc.) has identical:
- seen / BET / PASS / valid / invalid counts
- W / L / hit rate
- staked / profit / ROI
- avg_odds / avg_ev / maxDD / maxLS / maxWS

### Hockey backtest (--limit 50, --no-llm)

| Metric | AFTER |
|--------|-------|
| матчей | 50 |
| pre-flight SKIP | 0 |
| BET | 0 |
| BACKTEST: total | 1 |
| settled | 1 |
| wins | 1 |
| losses | 0 |

Hockey backtest runs successfully — no regression.

---

## Line Count Impact

| File | Before Step 2 | After Step 2 | Change |
|------|--------------|-------------|--------|
| `agent_handoff_v7.py` | ~4770 | 4357 | -413 lines |
| `analysis_helpers/probability_pipeline.py` | 0 | 558 | +558 lines |

Net: +145 lines (import overhead + module structure), but god file reduced by 413 lines.

---

## Regression Status

**NO REGRESSION DETECTED**

- Backtest output is byte-identical (filtered)
- All metrics match exactly
- Hockey cross-sport test passes
- Import chain works correctly

---

## Next Steps (Step 3 Candidates)

Most tightly coupled remaining blocks:

1. **`enrich_with_math()`** (~340 lines) — has DB calls for adaptive staking, but the core EV/Kelly math is pure. Could split into `math_core()` (pure) + `stake_resolution()` (DB-dependent).

2. **`build_rule_recommendation()`** (~240 lines) — depends on `get_conn()`, `resolve_stake_pct_and_meta()`. Could extract the rule→rec mapping logic if stake resolution is deferred.

3. **LLM block** (`call_llm`, `extract_json_object`, `normalize_response`, `simulate_llm_response`) — ~200 lines total. Mostly pure except `call_llm` which uses `GLOBAL_ARGS`.

4. **DB helpers** (`get_conn`, schema creation, bankroll state, exposure/streak) — ~200 lines. Not extractable without major refactor.
