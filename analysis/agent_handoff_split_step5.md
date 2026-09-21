# Agent Handoff Split — Step 5: Match Utility Functions Extraction

**Date:** 2026-04-14
**Status:** Complete — backtest identical, zero regression

---

## What Was Extracted

### New file: `analysis_helpers/match_utils.py` (95 lines, 7 functions)

| Function | Purpose |
|----------|---------|
| `ba_rule_to_market(rule)` | Map backtest-approved rule name to market (draw/away/home) |
| `_ba_tag(match)` | Display tag for BA-approved matches in log output |
| `_rule_tag(rec)` | Display tag for rule-driven/hockey/shadow recommendations |
| `get_market_family(market)` | Classify market into family (1X2, TOTALS, BTTS, HANDICAP) |
| `is_placeholder_match(home, away)` | Detect placeholder team names (Хозяева/Гости) |
| `safe_prob(odds)` | Convert odds to implied probability, safely |
| `_coerce_float(val)` | Safe float coercion, None on failure |

### Dependencies

`match_utils.py` imports only:
- `typing` (stdlib)

No external dependencies, no DB, no global state.

### Changes to `agent_handoff_v7.py`

1. Added import: `from analysis_helpers.match_utils import (...)`
2. Removed ~55 lines of inline code (7 small pure functions)
3. No signature changes, no behavior changes

---

## Backtest BEFORE vs AFTER

### Football backtest (--limit 200, --no-llm)

| Metric | Step 4 (before) | Step 5 (after) | Match? |
|--------|-----------------|----------------|--------|
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

### Hockey backtest (--limit 50, --no-llm)

| Metric | Step 5 |
|--------|--------|
| матчей | 50 |
| pre-flight SKIP | 0 |
| BET | 1 (hockey) |
| BACKTEST: total | 1 |
| wins | 1 |
| losses | 0 |

---

## Line Count Impact

| File | Before Step 5 | After Step 5 | Change |
|------|--------------|-------------|--------|
| `agent_handoff_v7.py` | 3932 | 3877 | -55 lines |
| `analysis_helpers/match_utils.py` | 0 | 95 | +95 lines |

### Cumulative (Steps 1-5)

| File | Original | After 5 Steps | Total Change |
|------|----------|--------------|--------------|
| `agent_handoff_v7.py` | ~5100 | 3877 | -1223 lines |
| `strategies/football_rules.py` | 0 | ~600 | +600 (Step 1) |
| `analysis_helpers/probability_pipeline.py` | 0 | 558 | +558 (Step 2) |
| `analysis_helpers/backtest_reporting.py` | 0 | 412 | +412 (Step 3) |
| `analysis_helpers/llm_utils.py` | 0 | 98 | +98 (Step 4) |
| `analysis_helpers/match_utils.py` | 0 | 95 | +95 (Step 5) |

---

## Regression Status

**NO REGRESSION DETECTED**

- Football backtest: all metrics identical
- Hockey backtest: passes
- Per-strategy stats: identical for all buckets

---

## What Remains Tightly Coupled

| Block | Lines | Why Not Extracted |
|-------|-------|-------------------|
| `build_rule_recommendation()` | ~240 lines | DB calls (`get_conn()`, `resolve_stake_pct_and_meta()`) |
| `enrich_with_math()` | ~340 lines | DB calls for adaptive staking, stake mode resolution |
| `call_llm()` / `simulate_llm_response()` | ~200 lines | GLOBAL_ARGS, env vars, HTTP, prompt templates |
| `enforce_validator_gate()` | ~70 lines | GLOBAL_ARGS (dry_run mode) |
| `save_handoff_decision()` / `save_recommendation()` | ~200 lines | DB writes, JSON serialization |
| `print_result()` / `print_backtest_summary()` | ~100 lines | Console output, formatting |
| Main analysis loop (`main()`) | ~800+ lines | Orchestration, all sports |
| DB helpers (`get_conn`, schema, bankroll) | ~200 lines | Engine-level infrastructure |
| `ALLOWED_LEAGUES` constant + `is_league_allowed()` | ~60 lines | Used by main loop, trivial size |

---

## Next Steps (Step 6 Candidates)

Remaining extraction candidates (in order of safety):

1. **`ALLOWED_LEAGUES` + `is_league_allowed()`** (~60 lines) — pure config + function, but used by main loop
2. **`print_backtest_summary()`** (~40 lines) — pure formatting, but depends on backtest_results list
3. **`enforce_validator_gate()`** (~70 lines) — depends on GLOBAL_ARGS for dry_run mode

No further extraction without explicit confirmation.
