# Tennis ML MVP — Single-Source Baseline Report

## Setup

- **Source**: `tennis_data_odds` table only (betagent.db)
- **No Betz, no mapping files, no multi-source joins**
- **Target**: match winner (binary classification)
- **Model**: LightGBM + logistic calibration
- **Split**: train=2021-2023, val=2024, test=2025, OOD=2026

## Data Summary

- Train (2021-2023): 16124 rows
- Val (2024): 6144 rows
- Test (2025): 6310 rows
- OOD (2026): 1838 rows

## Model Performance

| Split | Accuracy | LogLoss | Brier |
|-------|----------|---------|-------|
| Train (2021-2023) | 0.7096 | 0.5578 | 0.1890 |
| Val (2024) | 0.6838 | 0.5776 | 0.1978 |
| Test (2025) | 0.6751 | 0.5977 | 0.2061 |
| OOD (2026) | 0.7285 | 0.5444 | 0.1827 |

## Calibration Check (Test Set)

| Bin | Count | Avg Pred | Avg Actual |
|-----|-------|----------|------------|
| (0.1, 0.187] | 631 | 0.141 | 0.138 |
| (0.187, 0.281] | 631 | 0.237 | 0.285 |
| (0.281, 0.347] | 631 | 0.311 | 0.328 |
| (0.347, 0.428] | 631 | 0.393 | 0.409 |
| (0.428, 0.496] | 631 | 0.460 | 0.468 |
| (0.496, 0.573] | 631 | 0.535 | 0.521 |
| (0.573, 0.664] | 631 | 0.615 | 0.594 |
| (0.664, 0.717] | 632 | 0.694 | 0.674 |
| (0.717, 0.809] | 631 | 0.760 | 0.734 |
| (0.809, 0.9] | 630 | 0.861 | 0.849 |

## Feature Importance (Top 15)

| Feature | Importance |
|---------|------------|
| odds_opponent | 11558.0 |
| odds_player | 10894.5 |
| imp_opponent | 3612.0 |
| imp_player | 2852.9 |
| fair_player | 2221.6 |
| log_opponent_rank | 1457.4 |
| log_player_rank | 1323.0 |
| rank_diff | 1159.6 |
| tournament_freq | 661.1 |
| fair_opponent | 550.1 |
| overround | 412.0 |
| opponent_rank_inv | 341.8 |
| player_rank_inv | 275.2 |
| round_code | 188.3 |
| odds_ratio | 136.9 |

## Betting Backtest — Test Set (2025)

| EV Thresh | Stake | Bets | Hit Rate | ROI | PnL | MaxDD | Avg Odds |
|-----------|-------|------|----------|-----|-----|-------|----------|
| 0.00 | flat | 1421 | 0.432 | -0.0848 | -120.46 | -127.90 | 3.995 |
| 0.00 | kelly_quarter | 1421 | 0.432 | -0.0821 | -1.86 | -1.95 | 3.995 |
| 0.01 | flat | 1196 | 0.406 | -0.1054 | -126.09 | -132.08 | 4.342 |
| 0.01 | kelly_quarter | 1196 | 0.406 | -0.0939 | -1.92 | -1.99 | 4.342 |
| 0.02 | flat | 998 | 0.379 | -0.1274 | -127.19 | -133.68 | 4.766 |
| 0.02 | kelly_quarter | 998 | 0.379 | -0.1051 | -1.93 | -2.01 | 4.766 |
| 0.03 | flat | 849 | 0.350 | -0.1454 | -123.43 | -132.45 | 5.230 |
| 0.03 | kelly_quarter | 849 | 0.350 | -0.1135 | -1.89 | -1.97 | 5.230 |
| 0.04 | flat | 747 | 0.325 | -0.1777 | -132.73 | -139.65 | 5.629 |
| 0.04 | kelly_quarter | 747 | 0.325 | -0.1255 | -1.91 | -1.99 | 5.629 |
| 0.05 | flat | 637 | 0.320 | -0.1579 | -100.61 | -108.06 | 6.135 |
| 0.05 | kelly_quarter | 637 | 0.320 | -0.1118 | -1.52 | -1.59 | 6.135 |
| 0.07 | flat | 484 | 0.279 | -0.1937 | -93.73 | -95.07 | 7.230 |
| 0.07 | kelly_quarter | 484 | 0.279 | -0.1339 | -1.47 | -1.48 | 7.230 |
| 0.10 | flat | 343 | 0.233 | -0.2008 | -68.87 | -72.28 | 9.031 |
| 0.10 | kelly_quarter | 343 | 0.233 | -0.1311 | -0.99 | -1.05 | 9.031 |

## Betting Backtest — OOD (2026)

| EV Thresh | Stake | Bets | Hit Rate | ROI | PnL | MaxDD | Avg Odds |
|-----------|-------|------|----------|-----|-----|-------|----------|
| 0.00 | flat | 386 | 0.394 | -0.1082 | -41.75 | -83.37 | 5.675 |
| 0.00 | kelly_quarter | 386 | 0.394 | -0.1011 | -0.63 | -1.06 | 5.675 |
| 0.01 | flat | 317 | 0.356 | -0.1118 | -35.44 | -77.28 | 6.436 |
| 0.01 | kelly_quarter | 317 | 0.356 | -0.1023 | -0.56 | -1.00 | 6.436 |
| 0.02 | flat | 268 | 0.325 | -0.1328 | -35.58 | -73.84 | 7.132 |
| 0.02 | kelly_quarter | 268 | 0.325 | -0.1128 | -0.56 | -0.96 | 7.132 |
| 0.03 | flat | 230 | 0.296 | -0.1260 | -28.97 | -64.55 | 7.963 |
| 0.03 | kelly_quarter | 230 | 0.296 | -0.1145 | -0.52 | -0.87 | 7.963 |
| 0.04 | flat | 206 | 0.291 | -0.0878 | -18.08 | -58.41 | 8.646 |
| 0.04 | kelly_quarter | 206 | 0.291 | -0.0925 | -0.39 | -0.81 | 8.646 |
| 0.05 | flat | 181 | 0.276 | -0.0766 | -13.87 | -53.16 | 9.492 |
| 0.05 | kelly_quarter | 181 | 0.276 | -0.0716 | -0.27 | -0.72 | 9.492 |
| 0.07 | flat | 148 | 0.243 | -0.1090 | -16.13 | -47.71 | 10.967 |
| 0.07 | kelly_quarter | 148 | 0.243 | -0.0840 | -0.26 | -0.62 | 10.967 |
| 0.10 | flat | 113 | 0.177 | -0.2624 | -29.65 | -53.21 | 13.274 |
| 0.10 | kelly_quarter | 113 | 0.177 | -0.1747 | -0.40 | -0.73 | 13.274 |

## Conclusion

- **Test accuracy**: 0.6751
- **Best test ROI** (EV-filtered): -0.0821
- **Best OOD ROI**: -0.0716

### Verdict: NOT VIABLE (single-source only)

Single-source tennis ML does not produce positive ROI.
The bookmaker odds already fully incorporate rank and surface information.
A competitive model would need richer features: serve/return stats, fatigue, weather, H2H.
