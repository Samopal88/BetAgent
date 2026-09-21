# Tennis Winner ML — Baseline v1 Report

## high_only

### Metrics

| Split | LogLoss | Brier | Accuracy | N |
|-------|---------|-------|----------|---|
| val | 0.3442 | 0.1193 | 0.8034 | 4588 |
| test | 0.5932 | 0.2024 | 0.6627 | 5598 |
| ood | 0.5098 | 0.1502 | 0.7601 | 446 |

### Top 15 Features (Gain)

| Feature | Importance |
|---------|-----------|
| h2h_player_wins | 16804.1 |
| h2h_opponent_wins | 13648.0 |
| rank_diff | 6679.8 |
| rank_pts_diff | 5427.6 |
| h2h_total | 3527.4 |
| h2h_edge | 2932.3 |
| opponent_form_diff | 971.9 |
| serve_diff | 958.3 |
| player_surface_matches | 828.4 |
| player_surface_win_pct | 771.3 |
| opponent_surface_matches | 739.5 |
| player_surface_bp_saved_pct | 725.7 |
| opponent_surface_win_pct | 710.5 |
| return_diff | 707.4 |
| surface_diff | 694.0 |

### Betting Backtest — Test (2025)

| Method | EV Thresh | Bets | ROI | ROI_BR | PnL | Max DD | Lose Streak |
|--------|-----------|------|-----|--------|-----|--------|-------------|
| flat_ev0.0 | | 1450 | 37.65% | 1091.28% | 1091285 | 11.29% | 9 |
| flat_ev0.02 | | 1414 | 37.10% | 1048.15% | 1048145 | 13.42% | 8 |
| flat_ev0.03 | | 1394 | 37.00% | 1030.82% | 1030819 | 14.19% | 7 |
| flat_ev0.05 | | 1321 | 37.29% | 982.46% | 982460 | 18.59% | 7 |
| kelly_quarter_ev0.0 | | 1450 | 36.69% | 1053.26% | 1053262 | 13.51% | 9 |
| kelly_quarter_ev0.02 | | 1414 | 36.19% | 1016.46% | 1016457 | 15.21% | 8 |
| kelly_quarter_ev0.03 | | 1394 | 36.13% | 1000.84% | 1000839 | 17.41% | 7 |
| kelly_quarter_ev0.05 | | 1321 | 36.48% | 960.21% | 960206 | 19.57% | 7 |

### Betting Backtest — OOD (2026)

| Method | EV Thresh | Bets | ROI | ROI_BR | PnL | Max DD | Lose Streak |
|--------|-----------|------|-----|--------|-----|--------|-------------|
| flat_ev0.0 | | 105 | 62.91% | 132.07% | 132074 | 5.71% | 3 |
| flat_ev0.02 | | 103 | 64.60% | 133.05% | 133049 | 6.73% | 4 |
| flat_ev0.03 | | 101 | 65.78% | 132.85% | 132849 | 6.73% | 4 |
| flat_ev0.05 | | 98 | 65.44% | 128.21% | 128209 | 6.08% | 4 |
| kelly_quarter_ev0.0 | | 105 | 60.45% | 122.34% | 122340 | 5.31% | 3 |
| kelly_quarter_ev0.02 | | 103 | 61.03% | 122.46% | 122465 | 6.53% | 4 |
| kelly_quarter_ev0.03 | | 101 | 61.55% | 122.25% | 122249 | 6.53% | 4 |
| kelly_quarter_ev0.05 | | 98 | 61.75% | 120.00% | 120004 | 6.03% | 4 |

### Monthly Breakdown — Test (Kelly Q, EV>=0.03)

| Month | Bets | PnL | Win Rate |
|-------|------|-----|----------|
| 2024-12 | 2 | 1200 | 50.0% |
| 2025-01 | 108 | 69437 | 42.6% |
| 2025-02 | 91 | 13081 | 40.7% |
| 2025-03 | 104 | 73454 | 51.0% |
| 2025-04 | 139 | 51060 | 46.0% |
| 2025-05 | 187 | 239147 | 56.7% |
| 2025-06 | 92 | 71880 | 53.3% |
| 2025-07 | 187 | 135520 | 49.7% |
| 2025-08 | 230 | 147580 | 50.0% |
| 2025-09 | 86 | 13000 | 44.2% |
| 2025-10 | 145 | 152480 | 62.8% |
| 2025-11 | 23 | 33000 | 65.2% |

## high_medium

### Metrics

| Split | LogLoss | Brier | Accuracy | N |
|-------|---------|-------|----------|---|
| val | 0.3106 | 0.1076 | 0.8243 | 5258 |
| test | 0.5401 | 0.1857 | 0.6874 | 6404 |
| ood | 0.4187 | 0.1428 | 0.7801 | 964 |

### Top 15 Features (Gain)

| Feature | Importance |
|---------|-----------|
| h2h_player_wins | 20506.1 |
| h2h_opponent_wins | 18415.3 |
| rank_diff | 7392.3 |
| h2h_edge | 6552.4 |
| rank_pts_diff | 5842.6 |
| h2h_total | 3083.7 |
| serve_diff | 1020.5 |
| player_surface_win_pct | 973.4 |
| opponent_form_diff | 920.9 |
| player_surface_matches | 878.2 |
| opponent_surface_matches | 771.6 |
| surface_diff | 742.1 |
| opponent_surface_win_pct | 698.4 |
| player_1st_in_avg | 684.3 |
| player_surface_bp_saved_pct | 632.9 |

### Betting Backtest — Test (2025)

| Method | EV Thresh | Bets | ROI | ROI_BR | PnL | Max DD | Lose Streak |
|--------|-----------|------|-----|--------|-----|--------|-------------|
| flat_ev0.0 | | 1576 | 40.85% | 1286.96% | 1286962 | 12.55% | 7 |
| flat_ev0.02 | | 1527 | 39.37% | 1201.69% | 1201694 | 12.72% | 8 |
| flat_ev0.03 | | 1486 | 40.31% | 1196.97% | 1196971 | 14.34% | 7 |
| flat_ev0.05 | | 1411 | 42.65% | 1202.90% | 1202900 | 12.60% | 9 |
| kelly_quarter_ev0.0 | | 1576 | 40.24% | 1246.72% | 1246723 | 12.48% | 7 |
| kelly_quarter_ev0.02 | | 1527 | 38.81% | 1172.36% | 1172364 | 13.93% | 8 |
| kelly_quarter_ev0.03 | | 1486 | 39.45% | 1167.36% | 1167357 | 17.03% | 7 |
| kelly_quarter_ev0.05 | | 1411 | 41.77% | 1174.65% | 1174652 | 12.94% | 9 |

### Betting Backtest — OOD (2026)

| Method | EV Thresh | Bets | ROI | ROI_BR | PnL | Max DD | Lose Streak |
|--------|-----------|------|-----|--------|-----|--------|-------------|
| flat_ev0.0 | | 221 | 67.29% | 297.24% | 297236 | 8.13% | 4 |
| flat_ev0.02 | | 216 | 65.72% | 283.89% | 283889 | 6.72% | 4 |
| flat_ev0.03 | | 215 | 65.47% | 281.49% | 281489 | 6.72% | 4 |
| flat_ev0.05 | | 206 | 67.15% | 276.63% | 276632 | 7.79% | 5 |
| kelly_quarter_ev0.0 | | 221 | 63.60% | 276.02% | 276021 | 7.34% | 4 |
| kelly_quarter_ev0.02 | | 216 | 62.19% | 265.53% | 265533 | 6.16% | 4 |
| kelly_quarter_ev0.03 | | 215 | 61.93% | 263.70% | 263697 | 6.16% | 4 |
| kelly_quarter_ev0.05 | | 206 | 63.31% | 259.02% | 259024 | 7.79% | 5 |

### Monthly Breakdown — Test (Kelly Q, EV>=0.03)

| Month | Bets | PnL | Win Rate |
|-------|------|-----|----------|
| 2024-12 | 2 | 1200 | 50.0% |
| 2025-01 | 107 | 57431 | 39.3% |
| 2025-02 | 92 | 3197 | 40.2% |
| 2025-03 | 108 | 63769 | 48.1% |
| 2025-04 | 150 | 63940 | 48.7% |
| 2025-05 | 195 | 271600 | 55.4% |
| 2025-06 | 98 | 100980 | 56.1% |
| 2025-07 | 197 | 149120 | 49.7% |
| 2025-08 | 247 | 179220 | 52.2% |
| 2025-09 | 93 | 44860 | 48.4% |
| 2025-10 | 171 | 194400 | 63.2% |
| 2025-11 | 26 | 37640 | 69.2% |

## Verdict

1. **Better subset**: high_medium (test ROI: 36.13% vs 39.45%, OOD ROI: 61.55% vs 61.93%)
2. **Standalone tennis ML viable**: yes — best test ROI=39.45%, best OOD ROI=61.93%
3. **Worth moving to theory+ML intersection**: maybe — test positive but OOD needs confirmation
