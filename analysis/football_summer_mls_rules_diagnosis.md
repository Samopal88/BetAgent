# MLS/SUMMER Strategy Diagnosis — Root Cause Analysis

**Date:** 2026-04-15
**Scope:** `SUMMER_BTTS_HOME` + `MLS_BTTS_HOME` strategies — why zero bets generated

---

## 1. Are the strategies loaded and called?

**YES** — both strategies are active in the live pipeline.

### Loading path:

```
agent_handoff_v7.py:3368
  └── get_pruned_live_rule()  ← strategies/football_rules.py
        ├── MLS_BTTS_HOME (line 329-343)
        └── SUMMER_BTTS_HOME (line 345-359)
```

Both rules are in `_no_calib` set (line 3400), meaning they skip probability calibration and use raw rule output.

### Rule criteria:

| Rule | League | Market | Odds Range | Key Criteria |
|------|--------|--------|-----------|-------------|
| `MLS_BTTS_HOME` | MLS | BTTS Yes | 1.50-1.75 | Home team in whitelist |
| `SUMMER_BTTS_HOME` | DNK/SWE/FIN | BTTS Yes | 1.55-1.85 | Home team in whitelist, month 4-11 |

---

## 2. What matches are available?

| League | Matches Found | BTTS Market Available |
|--------|--------------|----------------------|
| MLS | 15 matches | Yes |
| Sweden (Allsvenskan) | 12 matches | Yes |
| Denmark (Superliga) | 8 matches | Yes |
| Finland (Veikkausliiga) | 7 matches | Yes |
| Norway (Eliteserien) | 0 matches today | — |
| Iceland | 0 matches today | — |

---

## 3. Matches that pass rule criteria

| Match | League | BTTS Odds | Rule | Status |
|-------|--------|-----------|------|--------|
| Атланта Юнайтед vs Нэшвилл | MLS | 1.67 | MLS_BTTS_HOME | PASSES rule |
| Оденсе vs Раннерс | Denmark | 1.58 | SUMMER_BTTS_HOME | PASSES rule |
| Хеккен vs ГАИС | Sweden | 1.60 | SUMMER_BTTS_HOME | PASSES rule |

All three matches have valid BTTS odds within range and home teams in the whitelist.

---

## 4. ROOT CAUSE: Pre-flight check blocks all rule-matched matches

### Code flow after rule match:

```python
# agent_handoff_v7.py ~3544-3596
rule_name, market = get_pruned_live_rule(match, facts)
if rule_name:
    rec = build_recommendation(match, rule_name, market, ...)
    # rec is validated, EV/Kelly computed
    # ... then falls through to:

# Line 3571 — pre-flight check (ALWAYS runs, no early continue)
skip_reason = pre_flight_check(profile, facts, signal_type, has_lineups)
ba_ok = is_backtest_approved(rule_name, match)

if skip_reason and not ba_ok:
    # SKIP — recommendation discarded
    continue
```

**The problem:** Rule-matched matches do NOT have an early `continue` that skips the pre-flight check. They fall through to line 3571 where:

1. `skip_reason = "Pre-flight: нет данных (standings, форма, голы)"` — match_facts table has NULL values for all summer/MLS matches
2. `ba_ok = False` — `SUMMER_BTTS_HOME` and `MLS_BTTS_HOME` are NOT in `is_backtest_approved()`
3. `if skip_reason and not ba_ok:` → **True** → match is skipped

### Why match_facts is NULL:

The enrichment step (`enricher_football.py`) uses football-data.org API which only covers major European leagues (EPL, La Liga, Bundesliga, Serie A, Ligue 1, RPL). MLS and Scandinavian leagues are NOT covered by the enrichment API, so `match_facts` has no rows for these matches.

### Why is_backtest_approved doesn't include them:

`is_backtest_approved()` (analysis_helpers/probability_pipeline.py:184-268) only includes:
- `DRAW_SA`, `AWAY_SA`, `P1_PD`, `PD_AWAY_VALUE`, `DRAW_BL1_FL1`, `AWAY_BL1`

`SUMMER_BTTS_HOME` and `MLS_BTTS_HOME` were never added to this list, so they cannot bypass the pre-flight check.

---

## 5. Secondary Issue: SUMMER_TEAMS missing NOR and IRL

In `strategies/football.py`:

```python
# Line 101-105 — SUMMER_TEAMS dict
SUMMER_TEAMS = {
    "DNK": {"Оденсе", "Раннерс", ...},   # Denmark
    "SWE": {"Хеккен", "ГАИС", ...},       # Sweden
    "FIN": {"ХИК", "КуПС", ...},          # Finland
    # NOR and IRL are MISSING
}
```

But `FOOTBALL_LEAGUE_STAKING` (line 148-153) lists: `DNK, SWE, FIN, NOR, IRL` — inconsistency.

If Norway or Iceland matches existed with BTTS odds in range, `SUMMER_BTTS_HOME` would fail because `detect_football_league_key()` returns `"NOR"` or `"IRL"`, but `SUMMER_TEAMS["NOR"]` doesn't exist → KeyError or empty set.

---

## 6. Pipeline Blockage Map

```
Fonbet odds → rule match → recommendation built → pre-flight check → BLOCKED
                                                    ↑
                                    match_facts = NULL (no enrichment data)
                                    ba_ok = False (not in backtest_approved)
```

---

## 7. Summary Answers

| Question | Answer |
|----------|--------|
| **Strategies loaded?** | YES — both in get_pruned_live_rule() |
| **Rules called in live pipeline?** | YES — agent_handoff_v7.py:3368 |
| **Matches with BTTS market?** | YES — 15 MLS, 27 summer matches |
| **Matches passing rule criteria?** | 1 MLS + 2 summer matches |
| **Exact rejection reason?** | `Pre-flight: нет данных (standings, форма, голы) — PASS без LLM` |
| **Breakage from refactoring?** | NO — the issue is architectural, not a regression. Pre-flight check was designed to block matches without enrichment data, but SUMMER/MLS rules were never granted bypass. |
| **Root cause** | Pre-flight check blocks ALL matches without match_facts data. SUMMER_BTTS_HOME and MLS_BTTS_HOME are NOT in is_backtest_approved(), so they cannot bypass. |

---

## 8. Recommended Fixes (Priority Order)

### P0 — Bypass pre-flight for rule-matched SUMMER/MLS matches

Option A: Add to `is_backtest_approved()`:
```python
# analysis_helpers/probability_pipeline.py ~line 268
APPROVED_RULES = {
    "DRAW_SA", "AWAY_SA", "P1_PD", "PD_AWAY_VALUE",
    "DRAW_BL1_FL1", "AWAY_BL1",
    "SUMMER_BTTS_HOME",  # ADD
    "MLS_BTTS_HOME",      # ADD
}
```

Option B: Skip pre-flight for rule-matched matches in the main loop:
```python
# agent_handoff_v7.py ~3571
if rule_name and rule_name in ("SUMMER_BTTS_HOME", "MLS_BTTS_HOME"):
    # These rules don't need enrichment data — they're purely odds-based
    skip_reason = None
else:
    skip_reason = pre_flight_check(...)
```

**Recommendation: Option A** — cleaner, centralized, consistent with existing pattern.

### P1 — Add NOR and IRL to SUMMER_TEAMS

```python
# strategies/football.py ~line 101-105
SUMMER_TEAMS = {
    "DNK": {...},
    "SWE": {...},
    "FIN": {...},
    "NOR": {"Мольде", "Будё-Глимт", "Русенборг", "Викинг", ...},
    "IRL": {"Шемрок Роверс", "Дерри Сити", "Дандолк", ...},
}
```

### P2 — Enrichment data for MLS/Scandinavian leagues (long-term)

Consider adding a secondary enrichment source (e.g., API-Football) that covers MLS and Scandinavian leagues. Until then, these leagues will rely purely on rule-based analysis without form/standings context.
