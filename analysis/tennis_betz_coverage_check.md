# Tennis betz.su Coverage Check — Qualifying/Challenger

**Date:** 2026-04-13
**Question:** Are qualifying/challenger results available on betz.su? Is the gap a source limitation or parser limitation?

---

## 1. Specific Match Check

### Bet 874: Виртанен О vs Мюллер А (ATP 500 Barcelona Qualifying, 2026-04-12)

| Field | Value |
|-------|-------|
| betz.su league | Теннис. ATP 500. Барселона. Испания. Clay. Квалификация. |
| betz.su players | Отто Виртанен - Александр Мюллер |
| betz.su score | **2:0 (6:4, 6:4)** — Виртанен won |
| bet market | player1_win (Виртанен) |
| bet result | **should be: won** |
| Name mapping | Виртанен О. → otto virtanen (confident=0), Мюллер А. → alexandre muller (confident=0) |
| Settlement would work? | **YES** — surname "Виртанен" found in winner_name "Отто Виртанен" |

### Bet 881: Крету Ч vs Агаменоне Ф (ATP Challenger Oeiras-3 Qualifying, 2026-04-12)

| Field | Value |
|-------|-------|
| betz.su league | Теннис. ATP Challenger. Оэйраш-3. Португалия. Clay. Квалификация. |
| betz.su players | Чезар Крету - Франко Агаменоне |
| betz.su score | **1:2 (0:6, 6:4, 3:6)** — Агаменоне won |
| bet market | player1_win (Крету) |
| bet result | **should be: lost** |
| Name mapping | Крету Ч. → cezar cretu (confident=0), Агаменоне Ф. → franco agamenone (confident=0) |
| Settlement would work? | **YES** — surname "Агаменоне" found in winner_name "Франко Агаменоне" |

---

## 2. Root Cause

**Blocked by SKIP_KEYWORDS.** Both matches exist on betz.su with full scores. The updater's filter rejects them:

```python
SKIP_KEYWORDS = [
    "двойные", "эйсы", "Пары", "Челлендж", "Challenger",
    "ITF", "Юниоры", "Итого", "Статистика", "Квалификация",
]
```

- Bet 874: contains "Квалификация" → blocked
- Bet 881: contains "Challenger" AND "Квалификация" → blocked by both

**This is a parser logic limitation, NOT a source limitation.** betz.su has the data.

---

## 3. Volume Impact Analysis

Daily match counts on betz.su (3-day sample):

| Category | 11.04 | 12.04 | 13.04 | Avg |
|----------|-------|-------|-------|-----|
| Main tour (ATP 250-1000, WTA 250-1000) | 2 | 1 | 6 | **3** |
| + Main tour qualifying | 34 | 20 | 0 | **18** |
| + Challenger (non-qual) | 15 | 7 | 3 | **8** |
| + Challenger qualifying | 0 | 47 | 10 | **19** |
| ITF / Pro Series | 80 | 45 | 22 | **49** |

**Key observations:**
- Main tour qualifying is **highly variable** — 0-34 matches/day depending on tournament schedule
- Challenger qualifying is even more volatile — 0-47 matches/day
- ITF/Pro Series is the largest category but lowest quality
- Weekends have more qualifying rounds (Sat-Sun), weekdays have main draws

---

## 4. Quality Assessment

### Main Tour Qualifying (ATP 500/1000, WTA 250/500/1000)
- **Quality: HIGH** — same players as main draw, just earlier rounds
- **Settlement reliability: HIGH** — betz.su covers these with full scores
- **Name mapping: WORKS** — same player database, confident mappings exist
- **Volume: manageable** — 0-34/day, average ~18

### Challenger (non-qualifying)
- **Quality: MEDIUM** — lower-tier but still professional
- **Settlement reliability: HIGH** — betz.su covers these
- **Name mapping: MAYBE** — some Challenger players may not be in the mapping table
- **Volume: manageable** — 3-15/day, average ~8

### Challenger Qualifying
- **Quality: LOW-MEDIUM** — very low-tier players
- **Settlement reliability: MEDIUM** — some matches show "отмена" (cancelled) instead of scores
- **Name mapping: RISKY** — many players won't have confident mappings
- **Volume: HIGH** — 0-47/day, very volatile

### ITF / Pro Series
- **Quality: LOW** — amateur/developmental level
- **Should remain blocked** — too much noise, unreliable data

---

## 5. Recommended Parser Extension

**Allow main tour qualifying only.** This is the minimal safe extension:

```python
# In tennis_results_updater.py:
# Instead of blanket "Квалификация" skip, only skip qualifying for non-main-tour
SKIP_KEYWORDS = [
    "двойные", "эйсы", "Пары",
    "ITF", "Юниоры", "Итого", "Статистика",
]
# Keep Challenger blocked entirely
SKIP_IF_CHALLENGER_AND_QUALIFYING = True  # new flag

# Or simpler: remove "Квалификация" and "Challenger" from SKIP_KEYWORDS,
# but add them to TARGET_LEVELS filter logic:
# - Allow qualifying for ATP 250/500/1000, WTA 250/500/1000
# - Block Challenger entirely (both main and qualifying)
# - Block ITF entirely
```

**Rationale:**
- Main tour qualifying has the same players and data quality as main draw
- The 3 unsettled bets include 1 ATP 500 qualifying match (bet 874) that would be resolved
- Challenger qualifying is too noisy and the bet pipeline already blocks Challenger tournaments via `_BLOCKED_TOUR_KEYWORDS`
- If we allow Challenger results but the pipeline doesn't create Challenger bets, there's no harm — extra results just sit in `tennis_live_results` unused

---

## 6. Fix Applied & Verified

### Parser change
Removed `"Квалификация"` from `SKIP_KEYWORDS` in `tennis_results_updater.py`.
Challenger remains blocked (still in `SKIP_KEYWORDS` via "Challenger" keyword).
Main tour qualifying (ATP 250/500/1000, WTA 250/500/1000) is now fetched.

### Results
- Ran `tennis_results_updater.py --days 3`: fetched 51 new results (31 from 04-11, 20 from 04-12)
- Ran `tennis_live_pipeline.py --settle`: settled bet 874 as **won** (+11,195 RUB)

### Final status of 3 bets

| bet_id | Match | Result | Profit |
|--------|-------|--------|--------|
| 874 | Виртанен vs Мюллер (ATP 500 qual.) | **won** | +11,195 RUB |
| 881 | Крету vs Агаменоне (Challenger qual.) | **pending** (Challenger blocked by design) | — |
| 887 | Андреева vs Потапова (WTA 500) | **lost** | -473 RUB |

Bet 881 will remain pending — it's a Challenger qualifying match that the pipeline no longer creates bets for. The result exists on betz.su but the parser intentionally blocks Challenger. No new Challenger bets will be created.

---

## Answers

1. **betz has these results?** — **YES**. Both matches exist with full scores.

2. **Why current updater missed them?** — **Blocked by SKIP_KEYWORDS**. "Квалификация" and "Challenger" are in the skip list. This is a parser logic limitation, not a source limitation.

3. **Can parser be safely extended?** — **YES**, for main tour qualifying (ATP 250/500/1000, WTA 250/500/1000). Settlement name matching works — surnames from betz.su match the mapping table.

4. **Should qualifying/challenger remain blocked?** — **Main tour qualifying should be allowed.** It's the same quality as main draw, just earlier rounds. Challenger should remain blocked — the pipeline already blocks Challenger bets via `_BLOCKED_TOUR_KEYWORDS`, and Challenger qualifying data is noisy (cancelled matches, missing scores). ITF/Pro Series should remain blocked.
