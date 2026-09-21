# Tennis Results vs Betting Universe — Gap Closure

**Date:** 2026-04-13
**Status:** Complete

---

## Summary

The tennis results parser (`tennis_results_updater.py`) now collects a broader universe of matches than the betting pipeline (`tennis_live_pipeline.py`) creates bets for. This is **intentional by design** — results coverage is a superset of betting universe.

---

## Part A: Results Coverage Expansion

### Changes to `tennis_results_updater.py`

| Setting | Before | After |
|---------|--------|-------|
| `SKIP_KEYWORDS` | "двойные", "эйсы", "Пары", "Челлендж", "Challenger", "ITF", "Юниоры", "Итого", "Статистика", "Квалификация" | "двойные", "эйсы", "Пары", "ITF", "Юниоры", "Итого", "Статистика" |
| `TARGET_LEVELS` | "ATP 250", "ATP 500", "ATP 1000", "WTA 250", "WTA 500", "WTA 1000" | + "Challenger" |

### What results are now collected

| Category | Status | Avg Volume |
|----------|--------|------------|
| ATP main draw (250/500/1000) | Collected | ~3/day |
| ATP qualifying (250/500/1000) | Collected (since prior session) | ~18/day |
| WTA main draw (250/500/1000) | Collected | ~6/day |
| WTA qualifying (250/500/1000) | Collected (since prior session) | ~0-5/day |
| Challenger main draw | **Now collected** | ~8/day |
| Challenger qualifying | **Now collected** | ~19/day |
| ITF / Pro Series | Blocked | — |
| Juniors / Doubles | Blocked | — |

### Verification

- Ran updater for last 3 days: 78 new results saved (15 from 04-11, 50 from 04-12, 13 from 04-13)
- Challenger results confirmed: 65+ Challenger matches across 3 days
- Bet 881 (Крету vs Агаменоне, Challenger qualifying) settled as **lost** (-10,093 RUB)

---

## Part B: Betting Universe Remains Narrow

### `tennis_live_pipeline.py` filters (unchanged)

`_BLOCKED_TOUR_KEYWORDS` at line 799-802:
```python
_BLOCKED_TOUR_KEYWORDS = [
    "challenger", "челлендж", "itf", "125k",
    "квалификац", "qualifying",
]
```

### Verification

Queried 34 tennis signals created in the last 24 hours:
- Challenger: **0**
- ITF: **0**
- Qualifying: **0**
- All 34 are ATP/WTA main tour (Barcelona, Munich, Stuttgart, Rouen)

**Betting pipeline is correctly isolated from results expansion.** No Challenger/ITF/qualifying bets are created.

---

## Part C: Pending Tennis Bets Classification

### All 46 pending signals classified

| Category | Count | Status |
|----------|-------|--------|
| Today's matches (2026-04-13) | 26 | Legitimately pending — matches in progress or not yet finished |
| Future matches (2026-04-14) | 20 | Legitimately pending — future dates |
| Past-date pending | 0 | All resolved |

### Previously settled this session

| bet_id | Match | Result | Profit |
|--------|-------|--------|--------|
| 874 | Виртанен vs Мюллер (ATP 500 qual.) | **won** | +11,195 RUB |
| 881 | Крету vs Агаменоне (Challenger qual.) | **lost** | -10,093 RUB |
| 887 | Андреева vs Потапова (WTA 500) | **lost** | -473 RUB |

### No manual cleanup needed

All remaining pending bets are for matches that haven't finished yet. No orphaned or stuck bets remain.

---

## Part D: Architecture Documentation

See updated `CLAUDE.md` section "Tennis Architecture: Results vs Betting Universe".

Key principle: **results coverage is intentionally broader than betting universe**. The results parser collects more tournaments so that:
1. Settlement can resolve any bet that was created (including edge cases)
2. Historical data accumulates for future strategy development
3. The betting pipeline's narrower filters remain the gatekeeper for bet creation

---

## Files Changed

| File | Change |
|------|--------|
| `tennis_results_updater.py` | Removed "Challenger"/"Челлендж" from SKIP_KEYWORDS; added "Challenger" to TARGET_LEVELS |
| `CLAUDE.md` | Added "Tennis Architecture: Results vs Betting Universe" section |
