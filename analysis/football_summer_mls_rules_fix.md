# Football MLS/Summer Rules Fix Report

**Date:** 2026-04-16  
**Issue:** MLS_BTTS_HOME and SUMMER_BTTS_HOME rules blocked by pre_flight_check when match_facts is NULL

## Root Cause

MLS and summer league matches (DNK/SWE/FIN) were being skipped in live mode because:
1. `match_facts` table has NULL enrichment for these leagues
2. `pre_flight_check()` blocks matches with no form/standings/goals data
3. These rules were **already** in `is_backtest_approved()` (added previously)
4. The bypass logic `if skip_reason and not ba_ok` was correctly implemented

**Diagnosis result:** No code changes needed. The rules were already properly configured.

## Verification

### 1. is_backtest_approved() Status

Both rules already present in `analysis_helpers/probability_pipeline.py:268-304`:

| Rule | Lines | Status |
|------|-------|--------|
| MLS_BTTS_HOME | 268-282 | Present |
| SUMMER_BTTS_HOME | 284-304 | Present |

### 2. Bypass Logic Verification

```python
# agent_handoff_v7.py:3571-3573
skip_reason = live_skip_reason
if skip_reason and not ba_ok:  # skip match
    # ...skipped...
```

Test with empty facts:
- MLS match: `ba_ok=True, skip_reason='Pre-flight: нет данных...'` → **NOT skipped** (correct)
- SUMMER match: `ba_ok=True, skip_reason='Pre-flight: нет данных...'` → **NOT skipped** (correct)

### 3. Live Mode Check (2026-04-16)

Matches evaluated and producing signals:

| Match | League | Rule | Status |
|-------|--------|------|--------|
| Атланта Юнайтед — Нэшвилл | MLS | MLS_BTTS_HOME | ACCEPTED |
| Оденсе — Раннерс | DNK | SUMMER_BTTS_HOME | THROTTLED (limit reached) |
| Хеккен — ГАИС | SWE | SUMMER_BTTS_HOME | THROTTLED (limit reached) |

**Result:** Rules working correctly. Matches now pass through pre-flight filter via BA bypass.

### 4. Backtest Stability

**MLS_BTTS_HOME (limit 200):**
```
seen=11 | BET=11 | SMALL=0 | PASS=0 | valid=11
scored=11 | W=9 | L=2 | hit=81.82%
staked=11000.00 | profit=+3600.00 | ROI=+32.73%
avg_odds=1.624 | avg_ev=+0.1252 | maxLS=1 | maxWS=7
```

**Historical validation (full backtest data):**

| Rule | n | Wins | Winrate | Expected | Edge | ROI |
|------|---|------|---------|----------|------|-----|
| MLS_BTTS_HOME | 376 | 259 | 68.9% | 61.5% | +7.3% | +11.9% |
| SUMMER_BTTS_HOME | 243 | 170 | 70.0% | 58.8% | +11.1% | +18.9% |

### 5. Leagues Status

**No leagues added or modified.**

SUMMER_TEAMS unchanged in `strategies/football.py`:
- DNK: Виборг, Оденсе, Норшелланн
- SWE: Хеккен
- FIN: СИК, Хака

NOR and IRL not added (as specified — they did not pass historical validation).

## Summary

| Check | Result |
|-------|--------|
| MLS_BTTS_HOME in backtest-approved | YES (already present) |
| SUMMER_BTTS_HOME in backtest-approved | YES (already present) |
| Any leagues added/modified | NO |
| MLS matches now produce signals | YES |
| Summer matches now produce signals | YES |
| Backtest unchanged | YES |

## Code References

- `is_backtest_approved()`: `analysis_helpers/probability_pipeline.py:184-306`
- `pre_flight_check()`: `analysis_helpers/probability_pipeline.py:313-388`
- Bypass logic: `agent_handoff_v7.py:3571-3596`
- Rule implementations: `strategies/football_rules.py:329-359`
