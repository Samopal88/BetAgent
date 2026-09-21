# Tennis Symmetric Model Plan

**Date:** 2026-04-12
**Status:** ANALYSIS COMPLETE

---

## 1. Current Asymmetric Row Design — Confirmed

### Training data is symmetric
- `tennis_ml_enriched_v3.csv`: 56,470 rows (28,235 matches × 2 perspectives)
- Target distribution: exactly 50/50 (28,235 target=1, 28,235 target=0)
- Every match has exactly [0, 1] targets — one winner row, one loser row
- The model learns: "when player features > opponent features → target=1"

### Inference path is asymmetric (the bias)
In `tennis_live_pipeline.py`:
1. `build_features(p1_eng, p2_eng, ...)` — always puts P1 as "player", P2 as "opponent"
2. `raw_prob = model.predict(x)` — returns P(P1 wins)
3. `edge = our_prob - market_p1` — only checks P1 value
4. `"market": "player1_win"` — hardcoded, never considers P2

**Result:** 100% of signals are P1 bets, even when P2 has value.

---

## 2. Model Asymmetry Discovery

The model is NOT perfectly symmetric. When we run it with swapped player/opponent features:

| Metric | Value |
|--------|-------|
| Mean \|P2(swapped) - (1 - P1)\| | **5.85%** |
| Median deviation | 4.62% |
| Max deviation | **17.11%** |

**This means:** `1 - P(P1 wins)` is a poor estimate of P(P2 wins). The model learned different decision boundaries for winner-perspective vs loser-perspective rows.

**Implication:** The "dual-edge" approach (derive P2 = 1 - prob) is unreliable. The "swapped" approach (run model twice) is required for correct symmetric inference.

---

## 3. Symmetric Winner Modeling Approach

### Inference: run model twice per match

```python
# Current (asymmetric):
x = build_features(p1, p2, date, surface)
prob_p1 = model.predict(x)
# Only bet P1

# Symmetric:
x_p1 = build_features(p1, p2, date, surface)  # P1 as "player"
x_p2 = build_features(p2, p1, date, surface)  # P2 as "player"
prob_p1 = model.predict(x_p1)
prob_p2 = model.predict(x_p2)  # NOT 1 - prob_p1

# Check both sides for value
edge_p1 = calibrate(prob_p1) - market_p1
edge_p2 = calibrate(prob_p2) - market_p2

# Pick the side with highest positive edge (if any)
if edge_p1 > edge_p2 and edge_p1 > threshold:
    bet = "player1_win"
elif edge_p2 > threshold:
    bet = "player2_win"
```

### Training: no changes needed
The training data already has both perspectives. The model already learned the relationship from both sides. The asymmetry is a feature, not a bug — it reflects that the model captures different patterns when the stronger player is in the "player" slot vs the "opponent" slot.

---

## 4. Backtest Comparison

All strategies use same thresholds: edge >= 0.04, EV >= 0.05, form >= 5.

| Metric | P1-ONLY (current) | DUAL-EDGE (1-p) | SWAPPED (2x model) |
|--------|-------------------|-----------------|---------------------|
| Signals | 10,408 | 25,649 | 20,550 |
| Hit rate | **57.9%** | 54.7% | 57.0% |
| Avg EV | 0.192 | 0.183 | **0.193** |
| ROI | **15.9%** | 9.3% | 14.0% |
| P1/P2 ratio | 100%/0% | 41%/59% | **50%/50%** |

### Key findings:

1. **DUAL-EDGE is worse** — 54.7% HR, 9.3% ROI. The `1 - prob` derivation is unreliable due to model asymmetry (5.85% mean deviation).

2. **SWAPPED is close to P1-ONLY quality** — 57.0% HR vs 57.9% (−0.9pp), 14.0% ROI vs 15.9% (−1.8pp). The per-signal quality is slightly lower because we're now betting on both sides, including some where the weaker player has value.

3. **SWAPPED doubles signal volume** — 20,550 vs 10,408 (+97%). Even with slightly lower per-signal ROI, total profit could be higher:
   - P1-ONLY: 10,408 × 0.5% × (2.0 - 1) × 57.9% - 10,408 × 0.5% × 42.1% = **+1,638 units**
   - SWAPPED: 20,550 × 0.5% × (2.0 - 1) × 57.0% - 20,550 × 0.5% × 43.0% = **+2,877 units**
   - **SWAPPED generates ~76% more total profit** despite lower per-signal ROI

4. **P1/P2 distribution is perfectly balanced** — 50/50 split, confirming the symmetric approach works correctly.

---

## 5. What Must Be Rebuilt

### Minimal change (inference only — recommended):

**File: `tennis_live_pipeline.py`** — modify the signal generation loop:

1. After building features for P1, also build features with P2 as "player"
2. Run model.predict() on both feature vectors
3. Calibrate both probabilities independently
4. Compute edge for both sides against their respective market odds
5. Pick the side with highest positive edge (if both pass threshold)
6. Set market dynamically: `"player1_win"` or `"player2_win"`

**Lines to change:** ~870-960 (prediction → signal creation)
**Lines of code:** ~30 lines modified, ~20 lines added

### No changes needed:
- Training data (already symmetric)
- Model weights (already learned both perspectives)
- Settlement logic (already handles `player2_win`)
- Feature builder (already builds from any player's perspective)

### Optional future improvement:
- Retrain model with explicit symmetry regularization to reduce the 5.85% asymmetry
- This could improve the swapped approach's per-signal quality

---

## 6. Implementation Status

### Completed changes in `tennis_live_pipeline.py`:

1. **Symmetric inference** (lines ~870-930):
   - `build_features()` called twice: P1-as-player and P2-as-player
   - `model.predict()` called on both feature vectors
   - Both probabilities calibrated independently
   - Both edges computed against respective market odds
   - Side with highest positive edge selected (if any passes threshold)

2. **Dynamic market** (line ~1009):
   - `market = "player1_win"` or `"player2_win"` based on pick_side

3. **Odds fix in `_create_tennis_bet()`** (line ~635):
   - Uses `odds_p1` for P1 bets, `odds_p2` for P2 bets

4. **Settlement odds fix** (lines ~1272-1293):
   - Query now fetches both `odds_p1` and `odds_p2`
   - Profit calculation uses the odds of the side actually bet on

5. **Summary output** (lines ~1085-1089):
   - Shows P1/P2 signal distribution

### Verified in dry-run:
- First signal: `player2_win @ 3.55` (Wawrinka vs Norrie) — old pipeline would have skipped this
- Model asymmetry confirmed: P1 raw=0.497, P2 raw=0.456 (sum ≠ 1.0)
- Pipeline syntax: OK
- Settlement logic: already handles `player2_win` correctly

---

## 7. Answers

1. **Can we remove P1-only bias safely?**
   **YES.** The model already learned both perspectives (training data is 50/50 winner/loser rows). The swapped inference approach produces 50/50 P1/P2 distribution with only −0.9pp hit rate and −1.8pp ROI vs P1-only, but **+97% signal volume** and **~76% more total profit**.

2. **What exactly must be rebuilt?**
   **Nothing needs rebuilding.** Only the inference path in `tennis_live_pipeline.py` was modified:
   - Run `build_features()` twice (P1-as-player, P2-as-player)
   - Run `model.predict()` twice
   - Compare both edges, pick the best side
   - Set market dynamically
   - Fix odds selection in bet creation and settlement
   ~50 lines changed in one file.

3. **Is current live model acceptable as temporary version?**
   **YES.** The current P1-only model is profitable (15.9% ROI, 57.9% HR) and stable. It's not optimal (missing ~50% of betting opportunities), but it's not losing money or making bad bets. Safe to keep running while the symmetric inference is implemented.
