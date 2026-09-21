# Agent Handoff Split — Step 4: LLM Utility Functions Extraction

**Date:** 2026-04-14
**Status:** Complete — backtest identical, zero regression

---

## What Was Extracted

### New file: `analysis_helpers/llm_utils.py` (98 lines, 3 functions)

| Function | Purpose |
|----------|---------|
| `extract_json_object(text)` | Parse JSON from LLM response (handles markdown code blocks, raw JSON) |
| `normalize_response(rec)` | Normalize LLM response fields (market labels, type coercion) |
| `build_structured_comment(rec, payload)` | Build structured comment dict for bet records |

### Dependencies

`llm_utils.py` imports only:
- `json`, `re`, `typing` (stdlib)

No external dependencies, no DB, no global state.

### Changes to `agent_handoff_v7.py`

1. Added import: `from analysis_helpers.llm_utils import (...)`
2. Removed ~68 lines of inline code (extract_json_object, normalize_response, build_structured_comment)
3. No signature changes needed — all functions were already self-contained

---

## Backtest BEFORE vs AFTER

### Football backtest (--limit 200, --no-llm)

| Metric | Step 3 (before) | Step 4 (after) | Match? |
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

Per-strategy: all 10+ buckets identical (BTTS_YES_CORE, DRAW_SA, PD_BTTS_DOUBLE, MLS_BTTS_HOME, PD_AWAY_VALUE, RPL_OVER25_BTTS, heuristic_shadow x2, DRAW_BALANCED_LINE_SA, SA_AWAY_DRAW).

### Hockey backtest (--limit 50, --no-llm)

| Metric | Step 4 |
|--------|--------|
| матчей | 50 |
| BET | 1 (hockey) |
| BACKTEST: total | 1 |
| wins | 1 |
| losses | 0 |

---

## Line Count Impact

| File | Before Step 4 | After Step 4 | Change |
|------|--------------|-------------|--------|
| `agent_handoff_v7.py` | 4000 | 3932 | -68 lines |
| `analysis_helpers/llm_utils.py` | 0 | 98 | +98 lines |

### Cumulative (Steps 1-4)

| File | Original | After 4 Steps | Total Change |
|------|----------|--------------|--------------|
| `agent_handoff_v7.py` | ~5100 | 3932 | -1168 lines |
| `strategies/football_rules.py` | 0 | ~600 | +600 (Step 1) |
| `analysis_helpers/probability_pipeline.py` | 0 | 558 | +558 (Step 2) |
| `analysis_helpers/backtest_reporting.py` | 0 | 412 | +412 (Step 3) |
| `analysis_helpers/llm_utils.py` | 0 | 98 | +98 (Step 4) |

---

## Regression Status

**NO REGRESSION DETECTED**

- Football backtest: all metrics identical
- Hockey backtest: passes
- Per-strategy stats: identical for all buckets

---

## Next Steps (Step 5 Candidates)

Remaining tightly coupled blocks:

1. **`enrich_with_math()`** (~340 lines) — has DB calls for adaptive staking, but the core EV/Kelly math is pure. Could split into `math_core()` (pure) + `stake_resolution()` (DB-dependent).

2. **`build_rule_recommendation()`** (~240 lines) — depends on `get_conn()`, `resolve_stake_pct_and_meta()`. Could extract the rule→rec mapping logic if stake resolution is deferred.

3. **DB helpers** (`get_conn`, schema creation, bankroll state, exposure/streak) — ~200 lines. Not extractable without major refactor.
