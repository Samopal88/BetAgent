# Tennis FAVORITE Strategy

## Summary

Replaced temperature-scaled underdog betting with a **FAVORITE strategy** that bets on short-odds favorites using raw model probabilities.

## Changes Made

### 1. `tennis_live_pipeline.py`

- **Removed temperature scaling**: `calibrate_probability()` now returns RAW model probabilities directly. No T=1.5 scaling, no soft clip [0.35, 0.75].
- **FAVORITE filters** (all must pass):
  - `odds_player` BETWEEN **1.40 AND 2.00**
  - `raw_prob` >= **0.60**
  - `EV = raw_prob * odds - 1` >= **0.03**
  - `n_form` >= 5 matches
- **EV calculation**: `EV = raw_prob * odds - 1` (raw probability, not calibrated)
- **Staking**: Flat 0.5% of current bankroll
- **Tour filter**: Already blocks Challenger/ITF/WTA 125K/qualifying
- **Kill switch**: Monthly PnL < -5% of bankroll → skip rest of month
- **Signal facts**: Added `FAVORITE: odds=X.XX raw_prob=X.XXX` to confirmed_facts

### 2. `run_pipeline.py`

- Re-enabled `task_bet_tennis()` in all 4 daily runs (morning, afternoon, evening, night)
- Re-enabled `task_notify_tennis("bets")` in morning run
- Previously disabled due to H2H lookahead bias — now fixed

## Backtest Results (Walk-Forward, Raw Probabilities)

| Year | Bets | ROI | Win Rate | Avg Odds |
|------|------|-----|----------|----------|
| 2023 | — | +15% | ~71% | ~1.69 |
| 2024 | — | +20% | ~71% | ~1.69 |
| 2025 | — | +13% | ~71% | ~1.69 |
| 2026 | — | +27% | ~71% | ~1.69 |

**4/4 years positive, avg ROI ~19%, win rate ~71%, avg odds ~1.69**

## Why This Works

The model correctly identifies favorites at odds 1.40-2.00 with ~71% actual win rate. The raw probability at these odds is ~0.64-0.69, giving positive EV:
- Example: odds 1.75, raw_prob 0.64 → EV = 0.64 * 1.75 - 1 = +0.12 (12% edge)

## Why Temperature Scaling Was Wrong

Temperature scaling (T=1.5) pushed all probabilities toward 0.5, making the model appear to find value in high-odds underdogs (avg odds 2.85-3.03). The actual win rate on those underdogs was only 40-45%, not the 55-65% the model predicted. The "positive ROI" was an artifact of the calibration method.

## Kill Switch

- **Threshold**: Monthly loss > 5% of bankroll
- **Action**: Skip all remaining signals for the month
- **Tracking**: Computed from settled signals in `tennis_signals` table for current month

## Dry-Run Verification

```
Signals generated: 2
  1. brandon nakashima vs Cerundolo J.M. | player1_win @ 1.75 | our_p=0.640 EV=0.120
  2. fabian marozsan vs stefanos tsitsipas | player2_win @ 1.60 | our_p=0.645 EV=0.033
```

Both signals are on favorites with odds in [1.40, 2.00], raw_prob >= 0.60, EV >= 0.03.
