# Tennis Guardrails Backtest Comparison

**Date:** 2026-04-12
**Status:** COMPLETED

---

## Step 1. Live Universe Check

**123 live tennis matches** across 36 unique leagues currently in Fonbet line:

| Category | Count | Leagues |
|----------|-------|---------|
| ATP main tour | 3 | Монте-Карло, Барселона, Мюнхен |
| WTA main tour | 3 | Линц, Штутгарт, Руан |
| ATP Challenger | 7 | + 4 qualifying |
| ITF | 14 | Men's and women's |
| WTA 125K | 1 | + 1 qualifying |

**Risk:** Pipeline currently accepts Challenger, ITF, and qualifying matches — significantly wider than just ATP/WTA main tour. These lower-tier tournaments have less reliable data and higher variance.

---

## Step 2. Side Bias Check

**100% of 14 live signals are `player1_win`. Zero P2 signals.**

**Root cause:** Hardcoded `"market": "player1_win"` at `tennis_live_pipeline.py:939`. The entire prediction pipeline (features, model output, edge, EV) is built exclusively around player1. There is no logic path that ever evaluates or recommends betting on player2.

The model is trained asymmetrically — features are named from P1's perspective (`player_win_pct_5`, `opponent_win_pct_5`, etc.). `model.predict(x)` returns P1 win probability only.

---

## Step 3. Guardrails Tested

Three configurations tested on 34,974 historical match pairs (17,487 matches × both orderings):

| Config | Description |
|--------|-------------|
| **BASELINE** | P1-only, no guardrails (current behavior) |
| **GUARDRAILS** | P1-only + tour filter (block Challenger/ITF/qualifying) + odds 1.50-3.50 + EV cap 0.60 |
| **STRONG** | P1-only + edge >= 0.04 (was 0.02) + form >= 5 matches + EV >= 0.05 (was 0.03) |

**P2 evaluation was tested in v1** and rejected: betting P2 with `1 - raw_prob` produced 58% of signals but dragged hit rate from 56.7% to 55.1% and ROI from 13.3% to 10.2%. The model is trained from P1 perspective — `1 - raw_prob` is not a reliable P2 estimate.

---

## Step 4. Backtest Results

### BASELINE (P1-only, no guardrails)
| Metric | Value |
|--------|-------|
| Signals | 12,865 |
| Hit rate | 56.7% |
| Avg EV | 0.171 |
| Simulated ROI | 13.3% |
| ATP signals | 6,548 (57% HR) |
| WTA signals | 6,317 (56% HR) |

### GUARDRAILS (P1-only + tour + odds + EV cap)
| Metric | Value | vs Baseline |
|--------|-------|-------------|
| Signals | 12,865 | 0% |
| Hit rate | 56.7% | 0.0% |
| Simulated ROI | 13.3% | 0.0% |

**No change** — historical data is already ATP/WTA main tour, and simulated odds (2.0) always pass the 1.50-3.50 filter. The tour filter and odds filter will have effect in live mode where Challenger/ITF matches exist.

### STRONG (P1-only + edge>=0.04 + form>=5)
| Metric | Value | vs Baseline |
|--------|-------|-------------|
| Signals | 10,408 | **-19%** |
| Hit rate | 57.9% | **+1.3%** |
| Avg EV | 0.192 | **+12%** |
| Simulated ROI | 15.9% | **+2.5%** |
| ATP signals | 5,360 (59% HR) | +2pp |
| WTA signals | 5,048 (57% HR) | +1pp |

---

## Step 5. Stability Evaluation

| Criterion | Result |
|-----------|--------|
| Hit rate improved? | YES (+1.3pp) |
| ROI improved? | YES (+2.5pp) |
| Signal volume adequate? | YES (10,408 — still substantial) |
| P1/P2 bias addressed? | PARTIALLY — keeping P1-only but with stricter thresholds |
| Tour filter needed? | YES for live mode (blocks Challenger/ITF) |

**VERDICT: PASS** — STRONG guardrails improve quality without breaking the strategy.

---

## Step 6. Live Pipeline Changes Applied

### Applied to `tennis_live_pipeline.py`:

1. **Tour filter** (line ~818-822): Blocks Challenger, ITF, WTA 125K, and qualifying tournaments
   ```python
   _BLOCKED_TOUR_KEYWORDS = ["challenger", "челлендж", "itf", "125k", "квалификац", "qualifying"]
   ```

2. **Raised edge threshold** (line ~903): From 0.02 to 0.04
   ```python
   min_edge = 0.04  # was profile.get("min_edge_vs_market", 0.02)
   min_ev = 0.05    # was profile.get("min_ev", 0.03)
   ```

3. **Minimum form requirement** (line ~907): Requires >= 5 matches of history
   ```python
   if n_form < 5:
       skipped_form += 1
       continue
   ```

4. **P1-only approach retained**: No P2 evaluation added. Model asymmetry makes `1 - raw_prob` unreliable.

5. **New skip counters**: `skipped_tour` and `skipped_form` added to pipeline summary output.

---

## Answers

1. **Live universe:** 123 matches, 36 leagues — includes ATP/WTA main tour (6 leagues) + Challenger (11) + ITF (14) + WTA 125K (2) + qualifying (5). Pipeline accepts all of these.

2. **Side bias:** 100% P1 signals (14/0). Caused by hardcoded `"market": "player1_win"` at line 939. Model is trained asymmetrically from P1 perspective.

3. **Guardrails impact:** Tour filter + odds + EV cap had no effect on historical data (already clean). STRONG mode (edge>=0.04, form>=5) improved ROI from 13.3% to 15.9% (+2.5pp) with 19% fewer signals.

4. **P2 betting viable?** No — `1 - raw_prob` produced 58% of signals but dragged ROI from 13.3% to 10.2%. Model asymmetry makes P2 evaluation unreliable.

5. **Recommended changes:** Tour filter (block Challenger/ITF), raise edge to 0.04, require form >= 5. Keep P1-only.
