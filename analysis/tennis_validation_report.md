# Tennis ML — Out-of-Time Validation Report

## Executive Summary

**The model has real predictive signal but is not profitable enough for live deployment.** Walk-forward validation shows mixed results: 3 of 4 years positive with flat 1% staking, but 2025 was significantly negative (-4.81%). The original 21.90% ROI was inflated by isotonic calibration overfitting to the validation year.

## 1. Critical Methodological Issue: Isotonic Calibration Overfitting

The original H2H analysis used isotonic regression calibrated on a single year (2024) and applied to 2025. This worked because 2024 and 2025 had similar feature distributions. However, when properly tested out-of-time:

- **Calibrating on 2022 alone (4,364 rows)**: isotonic regression produces only **8 mapping points**, collapsing most predictions to exactly 0.0 or 1.0
- **Result**: OOD logloss jumps from 0.67 (raw) to 9.49 (calibrated) — a 14x increase
- **Effect on betting**: calibrated probabilities become extreme (0.0 or 1.0), creating false high-EV signals that lose money

**The 21.90% ROI from the H2H analysis was an artifact of calibration overfitting**, not genuine model edge. Raw predictions (no calibration) give a more honest picture.

## 2. Dataset Overview

| Year | Rows | High | Medium |
|------|------|------|--------|
| 2021 | 4392 | 3944 | 448 |
| 2022 | 4364 | 3926 | 438 |
| 2023 | 4868 | 4246 | 622 |
| 2024 | 5258 | 4588 | 670 |
| 2025 | 6404 | 5598 | 806 |
| 2026 | 964 | 446 | 518 |

## 3. Walk-Forward Validation (Raw Predictions, No Calibration)

**This is the most realistic simulation — train on all prior years, test each year independently.**

| Year | Train Years | Accuracy | LogLoss | Flat 1% Bets | Flat ROI | Flat DD | Flat WR |
|------|------------|----------|---------|-------------|----------|---------|---------|
| 2023 | 2021-2022 | 0.6526 | 0.6727 | 1231 | +7.91% | 27.20% | 46.0% |
| 2024 | 2021-2023 | 0.6552 | 0.6462 | 1392 | +3.22% | 38.31% | 44.7% |
| 2025 | 2021-2024 | 0.6323 | 0.6645 | 1255 | -4.81% | 73.06% | 38.5% |
| 2026 | 2021-2025 | 0.7095 | 0.5584 | 210 | +29.50% | 9.50% | 44.3% |

**Averages**: 3/4 years positive, mean ROI = +8.95%, mean DD = 37.02%

### Kelly Quarter Staking (same walk-forward)

| Year | Kelly Bets | Kelly ROI | Kelly DD | Kelly WR | Final Bankroll |
|------|-----------|-----------|----------|----------|---------------|
| 2023 | 1231 | +4.39% | 99.9% | 46.0% | 205,826 |
| 2024 | 1392 | -3.68% | 99.9% | 44.7% | 281 |
| 2025 | 1255 | -4.14% | 99.9% | 38.5% | 0 |
| 2026 | 210 | +22.55% | 45.3% | 44.3% | 188,727 |

**Kelly is catastrophically dangerous** for this model. Even in years with modest negative ROI, Kelly Q wipes out the bankroll because the edge is too small and variance too high.

## 4. Train 2021-2023, Test 2024-2026 (Fixed Training Set)

| Year | Accuracy | LogLoss | Flat 1% Bets | Flat ROI | Flat DD | Flat WR |
|------|----------|---------|-------------|----------|---------|---------|
| 2024 | 0.6552 | 0.6462 | 1392 | +3.22% | 38.31% | 44.7% |
| 2025 | 0.6210 | 0.6870 | 1460 | -1.97% | 54.44% | 41.6% |
| 2026 | 0.6680 | 0.6049 | 218 | +0.27% | 21.97% | 39.9% |

With a fixed training set, 2026 barely breaks even, confirming the model degrades over time without retraining.

## 5. Monthly Breakdown (Walk-Forward, Flat 1%)

### 2023 (ROI: +7.91%)

| Month | Bets | PnL | Win Rate |
|-------|------|-----|----------|
| 2023-01 | 98 | +13,790 | 45.9% |
| 2023-02 | 74 | +11,684 | 50.0% |
| 2023-03 | 81 | -20,941 | 33.3% |
| 2023-04 | 152 | +13,761 | 49.3% |
| 2023-05 | 161 | -9,440 | 43.5% |
| 2023-06 | 82 | -6,700 | 42.7% |
| 2023-07 | 154 | +23,849 | 48.1% |
| 2023-08 | 167 | -6,724 | 43.1% |
| 2023-09 | 78 | +47,453 | 59.0% |
| 2023-10 | 168 | +22,682 | 46.4% |
| 2023-11 | 16 | +7,912 | 43.8% |

### 2024 (ROI: +3.22%)

| Month | Bets | PnL | Win Rate |
|-------|------|-----|----------|
| 2024-01 | 135 | +1,277 | 42.2% |
| 2024-02 | 86 | -689 | 43.0% |
| 2024-03 | 105 | -10,189 | 41.0% |
| 2024-04 | 147 | -5,597 | 43.5% |
| 2024-05 | 185 | +767 | 45.4% |
| 2024-06 | 104 | +11,878 | 51.0% |
| 2024-07 | 154 | +23,077 | 45.5% |
| 2024-08 | 231 | +2,554 | 43.3% |
| 2024-09 | 101 | +17,294 | 50.5% |
| 2024-10 | 127 | -2,141 | 43.3% |
| 2024-11 | 17 | +6,572 | 47.1% |

### 2025 (ROI: -4.81%)

| Month | Bets | PnL | Win Rate |
|-------|------|-----|----------|
| 2025-01 | 95 | +9,621 | 36.8% |
| 2025-02 | 86 | -32,860 | 29.1% |
| 2025-03 | 92 | -9,350 | 39.1% |
| 2025-04 | 131 | -9,350 | 39.7% |
| 2025-05 | 152 | +24,875 | 46.7% |
| 2025-06 | 89 | -2,197 | 39.3% |
| 2025-07 | 168 | -1,055 | 36.9% |
| 2025-08 | 205 | -37,160 | 32.7% |
| 2025-09 | 89 | -4,688 | 38.2% |
| 2025-10 | 129 | +59 | 45.0% |
| 2025-11 | 17 | +1,143 | 41.2% |

### 2026 (ROI: +29.50%, small sample)

| Month | Bets | PnL | Win Rate |
|-------|------|-----|----------|
| 2026-01 | 104 | +29,497 | 41.3% |
| 2026-02 | 93 | +31,672 | 48.4% |
| 2026-03 | 6 | +8,088 | 66.7% |
| 2026-04 | 7 | -7,307 | 14.3% |

## 6. Key Findings

### 6.1 Model Has Real Signal
- Accuracy consistently 63-71% across all years (above 50% baseline)
- LogLoss 0.56-0.67 (informative but not sharp)
- 3 of 4 walk-forward years positive with flat staking

### 6.2 Edge Is Marginal and Unstable
- Average flat ROI: +8.95% (driven heavily by 2026's small-sample +29.50%)
- 2025 was -4.81% with a 73% max drawdown
- Win rate never exceeds 46% — the edge comes from odds mispricing, not pick accuracy
- Monthly variance is extreme: single months can swing -37k to +47k

### 6.3 Kelly Staking Is Unsuitable
- Kelly Q destroys bankroll in negative ROI years (99%+ DD)
- The model's edge (~3-8% ROI) is too small for Kelly's aggressive sizing
- Flat 1% staking is significantly safer but still has 27-73% drawdowns

### 6.4 Isotonic Calibration Is Dangerous
- With only 8-58 mapping points, isotonic regression overfits to the calibration year
- OOD logloss increases 14x when calibration year differs from test year
- **Recommendation**: Use raw LightGBM predictions or Platt scaling (logistic regression) instead

## 7. Comparison With Original H2H Analysis

| Metric | Original (calibrated) | Walk-forward (raw) |
|--------|----------------------|-------------------|
| 2025 ROI | +21.90% | -4.81% |
| 2026 ROI | +36.57% | +29.50% |
| Method | Calibrated on 2024 | Raw predictions |
| Valid? | No — calibration overfit | Yes — honest OOD |

The 2025 ROI of 21.90% was inflated because isotonic calibration on 2024 created a mapping that happened to work well for 2025's feature distribution. The honest walk-forward ROI for 2025 is -4.81%.

## 8. Verdict

**NOT recommended for live deployment in current form.**

Reasons:
1. **Inconsistent year-to-year performance**: 2025 lost -4.81% with 73% drawdown
2. **Kelly staking destroys bankroll**: 99%+ DD in 2 of 4 years
3. **Calibration methodology is broken**: isotonic regression on single-year data overfits catastrophically
4. **Win rate below 46%**: edge is thin and relies on odds mispricing that may not persist
5. **2026 is small sample**: only 210 bets, +29.50% may be luck

## 9. What Would Need to Improve

1. **Replace isotonic calibration** with Platt scaling (logistic regression) or use raw predictions with a higher EV threshold
2. **Add more features**: serve/return stats from ATP/WTA, surface-specific form, tournament tier
3. **Increase EV threshold**: from 0.03 to 0.05+ to reduce bet volume but increase quality
4. **Use flat staking only**: Kelly is mathematically inappropriate for this edge size
5. **Add a kill switch**: stop betting after 3 consecutive losing months or 25% drawdown
6. **Retrain frequently**: model degrades — 2026 with fixed 2021-2023 training barely broke even (+0.27%)
