# Tennis H2H Leakage Fix — Impact Report

## 1. Bug Description

The `build_h2h()` function in `build_tennis_ml_enriched_v3.py` had a critical data leakage bug:

- **Bug**: `h2h_wins[key]` was incremented by 1 for every match regardless of who won
- **Effect**: `w_h2h_wins` = total prior meetings (not actual wins), `l_h2h_wins` = always 0
- **Leakage**: Winner rows always had `h2h_player_wins > 0`, loser rows always had `h2h_player_wins = 0`
- **Before fix**: target=1 mean=0.41, target=0 mean=0.00 (perfect separation)
- **After fix**: target=1 mean=0.24, target=0 mean=0.17 (both non-zero, symmetric)

The model learned: `h2h_player_wins > 0` → predict target=1. This is 100% lookahead bias.

## 2. Fix Applied

```python
# Track actual wins per player in each H2H pair
h2h_p1_wins = {}  # prior wins by alphabetically-first player
# ... assign prior wins correctly based on who was p1 vs p2
# ... update only the actual winner's count after assigning
```

H2H values are now symmetric: for both rows of the same match,
`h2h_player_wins(row1) == h2h_opponent_wins(row2)` and vice versa.

## 3. Model Comparison — Metrics

| Metric | With H2H (fixed) | Without H2H | Delta |
|--------|-----------------|-------------|-------|
| Test LogLoss | 0.6334 | 0.6765 | -0.0431 |
| Test Brier | 0.2194 | 0.2183 | +0.0011 |
| Test Accuracy | 0.6369 | 0.6402 | -0.0033 |
| OOD LogLoss | 0.5747 | 0.5951 | -0.0204 |
| OOD Brier | 0.1955 | 0.1913 | +0.0042 |
| OOD Accuracy | 0.6971 | 0.6992 | -0.0021 |

## 4. Betting Backtest Comparison (Kelly Q, EV>=0.03)

| Metric | With H2H (fixed) | Without H2H | Delta |
|--------|-----------------|-------------|-------|
| Test Bets | 1481 | 1639 | -158 |
| Test ROI | 21.90% | 19.93% | +1.97% |
| Test ROI_BR | 644.43% | 648.22% | -3.79% |
| Test PnL | 644434 | 648216 | -3782 |
| Test Max DD | 31.04% | 27.23% | +3.81% |
| Test Lose Streak | 9 | 11 | -2 |
| Test Win Rate | 43.1% | 44.4% | |

| Metric | With H2H (fixed) | Without H2H | Delta |
|--------|-----------------|-------------|-------|
| OOD Bets | 185 | 208 | -23 |
| OOD ROI | 36.57% | 25.89% | +10.68% |
| OOD ROI_BR | 134.34% | 104.86% | +29.48% |
| OOD PnL | 134344 | 104862 | +29483 |
| OOD Max DD | 16.53% | 13.82% | +2.71% |

## 5. Year-by-Year Backtest Results

### With H2H (fixed)

| Year | Bets | PnL | ROI | Win Rate |
|------|------|-----|-----|----------|
| 2025 | 1481 | 644434 | 21.76% | 43.1% |
| 2026 | 185 | 134344 | 36.31% | 43.8% |

### Without H2H

| Year | Bets | PnL | ROI | Win Rate |
|------|------|-----|-----|----------|
| 2025 | 1639 | 648216 | 19.77% | 44.4% |
| 2026 | 208 | 104862 | 25.21% | 42.8% |

## 6. Feature Importance (With H2H)

| Feature | Gain |
|---------|------|
| rank_pts_diff | 12766.3 |
| rank_diff | 5105.7 |
| opponent_form_diff | 1847.8 |
| surface_diff | 1610.8 |
| serve_diff | 1165.8 |
| player_surface_win_pct | 1030.7 |
| player_days_rest | 1020.5 |
| opponent_surface_win_pct | 994.0 |
| opponent_days_rest | 976.2 |
| player_surface_matches | 851.1 |
| opponent_minutes_avg | 724.3 |
| opponent_surface_matches | 669.5 |
| return_diff | 635.6 |
| player_minutes_14d | 628.1 |
| opponent_surface_bp_saved_pct | 624.6 |

## 7. EV Threshold Grid (Test 2025, Kelly Q)

| EV Threshold | With H2H Bets | With H2H ROI | No H2H Bets | No H2H ROI |
|-------------|--------------|-------------|------------|-----------|
| 0.00 | 1629 | 24.79% | 1756 | 20.95% |
| 0.02 | 1571 | 22.81% | 1686 | 20.64% |
| 0.03 | 1481 | 21.90% | 1639 | 19.93% |
| 0.05 | 1451 | 20.86% | 1539 | 17.61% |

## 8. Verdict

1. **H2H impact on test ROI**: +1.97% (with H2H: 21.90%, without: 19.93%)
3. **Accuracy impact**: -0.0033 (with H2H: 0.6369, without: 0.6402)
4. **H2H feature importance**: 0.7% of total gain
5. **Recommendation**: Keep H2H features (fixed)
