# Agent Handoff Split — Step 1: Football Rules Extraction

**Date:** 2026-04-13
**Status:** Complete — backtest identical, zero regression

---

## What Was Extracted

### New file: `strategies/football_rules.py` (2 functions, ~330 lines)

| Function | Lines (original) | Purpose |
|----------|-----------------|---------|
| `_get_sa_backtest_home_form_pts()` | 430-447 | SA_AWAY_DRAW backtest form lookup |
| `get_pruned_live_rule()` | 450-762 | Pruned portfolio rule engine — 15 rules |

### What `get_pruned_live_rule` covers

All 15 football rules in their original order:
1. DRAW_SA
2. DRAW_BL1 (disabled)
3. AWAY_SA (disabled)
4. DRAW_BALANCED_LOW_SCORING_SA
5. DRAW_BALANCED_LINE_SA
6. DRAW_BALANCED_LINE_BL1 (disabled)
7. AWAY_SA_STRICT_PLUS
8. SA_AWAY_DRAW
9. BTTS_YES_CORE
10. RPL_OVER25_BTTS
11. PD_BTTS_DOUBLE
12. PD_AWAY_VALUE
13. FL1_BTTS_DOUBLE
14. NLA_BERN_AWAY_DRAW
15. MLS_BTTS_HOME
16. SUMMER_BTTS_HOME
17. ECU_BTTS_NO

### Dependencies

`football_rules.py` imports only from `strategies.football`:
- `normalize_rule_league_name`
- `detect_football_league_key`
- `SA_AWAY_TEAMS`
- `SUMMER_TEAMS`

No new dependencies introduced.

### Changes to `agent_handoff_v7.py`

1. Added import: `from strategies.football_rules import get_pruned_live_rule`
2. Removed ~335 lines of inline code (lines 430-762)
3. `build_rule_recommendation()` remains in `agent_handoff_v7.py` (tightly coupled)

---

## What Remains in God File

| Block | Lines | Why Not Extracted |
|-------|-------|-------------------|
| `build_rule_recommendation()` | ~240 lines | Depends on `get_conn()`, `resolve_stake_pct_and_meta()`, `get_market_family()`, `_wins()` — tightly coupled to engine internals |
| `_wins()` | 3 lines | Tiny, used by `build_rule_recommendation` |
| `is_league_allowed()` | ~20 lines | Used by multiple sports, not football-only |
| LLM system prompt | ~90 lines | Core engine, not strategy logic |
| `calibrate_probability()` | ~100 lines | Cross-sport, depends on sport_profiles.json |
| `call_llm()` | ~50 lines | Core engine |
| `enrich_with_math()` | ~80 lines | Cross-sport math filter |
| Main analysis loop | ~2000+ lines | Orchestration, all sports |

---

## Dependency Blockers

| Function | Blocks Extraction Of | Reason |
|----------|---------------------|--------|
| `get_conn()` | `build_rule_recommendation()` | SQLite connection, engine-level |
| `resolve_stake_pct_and_meta()` | `build_rule_recommendation()` | Depends on `bankroll_state`, `match`, `rec` — engine state |
| `get_market_family()` | `build_rule_recommendation()` | Cross-sport market mapping |
| `_wins()` | `build_rule_recommendation()` | Tiny helper, not worth separate file |
| `calibrate_probability()` | Full rule→rec pipeline | Cross-sport, depends on sport_profiles.json |
| `enrich_with_math()` | Full rule→rec pipeline | Cross-sport math filter |

---

## Backtest BEFORE vs AFTER

```
Metric              BEFORE    AFTER     Diff
─────────────────────────────────────────────
Matches analyzed    10        10        0
Bets placed         3         3         0
Hit rate            33.3%     33.3%     0
Staked              6,000     6,000     0
Profit              -4,370    -4,370    0
ROI                 -72.83%   -72.83%   0
Bank end            95,630    95,630    0
MaxLS               1         1         0
MaxWS               1         1         0
─────────────────────────────────────────────
Rule: MLS_BTTS_HOME  BET=1, W=1, +630    IDENTICAL
Rule: heuristic_shadow (RPL)  BET=1, L=1  IDENTICAL
Rule: heuristic_shadow (MLS)  BET=1, L=1  IDENTICAL
```

**`diff` output: empty — byte-identical backtest results.**

---

## Answers

1. **football rules extracted?** — **Yes** — `get_pruned_live_rule` + `_get_sa_backtest_home_form_pts` moved to `strategies/football_rules.py`
2. **backtest identical?** — **Yes** — zero diff, byte-identical output
3. **differences detected?** — **No**
4. **what still tightly coupled?** — `build_rule_recommendation()` (depends on `get_conn`, `resolve_stake_pct_and_meta`, `get_market_family`), calibration pipeline, LLM calls, main orchestration loop
5. **safe to continue step 2?** — **Yes** — extraction pattern proven safe
