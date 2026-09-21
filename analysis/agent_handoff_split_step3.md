# Agent Handoff Split — Step 3: Backtest Reporting Extraction

**Date:** 2026-04-14
**Status:** Complete — backtest identical, zero regression

---

## What Was Extracted

### New file: `analysis_helpers/backtest_reporting.py` (412 lines, 9 functions)

| Function | Purpose |
|----------|---------|
| `is_shadow_recommendation()` | Detect heuristic/shadow path recommendations |
| `get_strategy_bucket()` | Normalized strategy key for summary (sport | league | strat) |
| `_extract_score_pair()` | Extract home/away score from backtest match |
| `resolve_actual_market_from_match()` | Determine actual market outcome (home/away/draw/btts/etc.) |
| `update_equity_metrics()` | Track equity, peak, drawdown (abs + %) |
| `update_streaks()` | Track win/loss/push streaks |
| `init_strategy_row()` | Initialize strategy stats dict |
| `update_strategy_stats()` | Full stats update per recommendation |
| `print_strategy_summary()` | Print sorted strategy summary table |

### What these functions cover

**Shadow detection**: Identifies recommendations from heuristic fallback path (shadow_only flag, shadow markers in error strings).

**Strategy bucketing**: Creates normalized keys like `football | SA | DRAW_SA` for grouping results by sport, league, and strategy.

**Backtest settlement**: Resolves actual market outcomes from match results (1X2, BTTS, totals) for win/loss determination.

**Equity/drawdown tracking**: Running equity curve, peak equity, max drawdown (absolute and percentage).

**Streak tracking**: Current and max win/loss streaks, push resets.

**Summary printing**: Sorted by ROI, prints comprehensive per-strategy stats.

### Dependencies

`backtest_reporting.py` imports only:
- `collections.Counter`, `typing` (stdlib)

No external dependencies, no DB, no global state.

### Changes to `agent_handoff_v7.py`

1. Added import: `from analysis_helpers.backtest_reporting import (...)`
2. Added `resolve_actual_market_from_match` to imports (was missed in initial extraction)
3. Removed ~365 lines of inline code
4. Updated 9 call sites of `update_strategy_stats()` to pass `bankroll=args.bankroll` and `detect_league_key_fn=detect_league_key` (previously accessed global state directly)

---

## What Remains in God File

| Block | Lines | Why Not Extracted |
|-------|-------|-------------------|
| `build_rule_recommendation()` | ~240 lines | Depends on `get_conn()`, `resolve_stake_pct_and_meta()`, `get_market_family()` — tightly coupled to engine internals |
| `enrich_with_math()` | ~340 lines | DB calls for adaptive staking (BTTS_YES_CORE), stake mode resolution, bankroll regime |
| `is_league_allowed()` | ~20 lines | Used by multiple sports, trivial size |
| LLM system prompt + `call_llm()` | ~150 lines | Core engine, GLOBAL_ARGS dependency, prompt templates |
| `normalize_response()` | ~15 lines | Tiny, LLM post-processing |
| Main analysis loop | ~2000+ lines | Orchestration, all sports |
| DB helpers (`get_conn`, schema, bankroll) | ~200 lines | Engine-level, not extractable without major refactor |
| Exposure/streak helpers (DB-dependent) | ~100 lines | DB-dependent, not pure |

---

## Backtest BEFORE vs AFTER

### Football backtest (--limit 200, --no-llm)

| Metric | Step 2 (before) | Step 3 (after) | Match? |
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

### Per-strategy comparison

Every strategy bucket has identical metrics:
- **BTTS_YES_CORE**: seen=1, W=1, profit=+742.50, ROI=+99.00%
- **DRAW_SA**: seen=2, W=1/L=1, profit=+1600.00, ROI=+80.00%
- **PD_BTTS_DOUBLE**: seen=1, W=1, profit=+790.00, ROI=+79.00%
- **MLS_BTTS_HOME**: seen=11, W=9/L=2, profit=+3600.00, ROI=+32.73%
- **PD_AWAY_VALUE**: seen=3, W=1/L=1, profit=+300.00, ROI=+15.00%
- **RPL_OVER25_BTTS**: seen=2, W=1/L=1, profit=-180.00, ROI=-9.00%
- **heuristic_shadow (DEL)**: seen=18, W=1/L=3, profit=-1000.00, ROI=-25.00%
- **heuristic_shadow**: seen=132, W=8/L=27, profit=-41895.46, ROI=-60.40%
- **DRAW_BALANCED_LINE_SA**: seen=1, W=0/L=1, profit=-1000.00, ROI=-100.00%
- **SA_AWAY_DRAW**: seen=1, W=0/L=1, profit=-1000.00, ROI=-100.00%

### Hockey backtest (--limit 50, --no-llm)

| Metric | Step 3 |
|--------|--------|
| матчей | 50 |
| pre-flight SKIP | 0 |
| BET | 0 (football) / 1 (hockey) |
| BACKTEST: total | 1 |
| settled | 1 |
| wins | 1 |
| losses | 0 |

Hockey backtest runs successfully — no regression.

---

## Line Count Impact

| File | Before Step 3 | After Step 3 | Change |
|------|--------------|-------------|--------|
| `agent_handoff_v7.py` | ~4357 | 4000 | -357 lines |
| `analysis_helpers/backtest_reporting.py` | 0 | 412 | +412 lines |

Net: +55 lines (import overhead + parameter passing), but god file reduced by 357 lines.

### Cumulative (Steps 1-3)

| File | Original | After 3 Steps | Total Change |
|------|----------|--------------|--------------|
| `agent_handoff_v7.py` | ~5100 | 4000 | -1100 lines |
| `strategies/football_rules.py` | 0 | ~600 | +600 (Step 1) |
| `analysis_helpers/probability_pipeline.py` | 0 | 558 | +558 (Step 2) |
| `analysis_helpers/backtest_reporting.py` | 0 | 412 | +412 (Step 3) |

---

## Regression Status

**NO REGRESSION DETECTED**

- Football backtest output is byte-identical (filtered)
- All metrics match exactly
- Hockey cross-sport test passes
- Import chain works correctly
- Per-strategy stats identical for all 10+ buckets

---

## Design Decisions

### Parameter injection for pure functions

Two parameters were added to `update_strategy_stats()` to avoid coupling to global state:
- `bankroll: float` — replaces direct access to `args.bankroll`
- `detect_league_key_fn` — replaces direct import of `detect_league_key` from hockey module

This keeps the helper pure and testable while the god file supplies the concrete values at call sites.

### `resolve_actual_market_from_match` import

Initially missed from the import list — added in a follow-up fix. This function is called in the backtest settlement path for both hockey and football.

---

## Next Steps (Step 4 Candidates)

Most tightly coupled remaining blocks:

1. **LLM utility block** (`extract_json_object`, `normalize_response`, `simulate_llm_response`, `build_structured_comment`) — ~100 lines total. Mostly pure functions, good extraction candidate.

2. **`enrich_with_math()`** (~340 lines) — has DB calls for adaptive staking, but the core EV/Kelly math is pure. Could split into `math_core()` (pure) + `stake_resolution()` (DB-dependent).

3. **`build_rule_recommendation()`** (~240 lines) — depends on `get_conn()`, `resolve_stake_pct_and_meta()`. Could extract the rule→rec mapping logic if stake resolution is deferred.

4. **DB helpers** (`get_conn`, schema creation, bankroll state, exposure/streak) — ~200 lines. Not extractable without major refactor.
