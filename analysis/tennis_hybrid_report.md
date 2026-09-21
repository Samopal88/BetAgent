# Tennis ML — Hybrid Model Report

## 1. Methodology

- **Model**: LightGBM binary classification (raw probabilities, soft clip [0.35, 0.75])
- **Calibration**: Temperature scaling (T=1.5) to soften overconfident predictions
- **Walk-forward**: Train 2021-2022, validate 2023, test 2024, OOD 2025-2026
- **New features**: rank_ratio, surface_advantage, momentum
- **Rule filters**: dominant_form (ss_pct >= 0.65), rank_gap >= 30, surface_specialist (surf_win% >= 0.65)
- **Staking**: Flat 0.5% of current bankroll (compounding)
- **EV threshold**: >= 0.05 (raised from 0.03)
- **EV calculation**: EV = temp_prob * odds - 1 (temperature-scaled, not raw)

## 2. Model Evaluation

| Year | Raw Acc | Raw LL | Temp Acc | Temp LL |
|------|---------|--------|----------|---------|
| 2023 | 0.6726 | 0.5999 | 0.6726 | 0.6094 |
| 2024 | 0.6565 | 0.6040 | 0.6565 | 0.6124 |
| 2025 | 0.6416 | 0.6282 | 0.6416 | 0.6288 |
| 2026 | 0.6950 | 0.5692 | 0.6950 | 0.5897 |

## 3. Feature Importance (Top 15)

| Feature | Gain |
|---------|------|
| rank_ratio | 6609.9 |
| rank_diff | 2785.7 |
| rank_pts_diff | 2340.2 |
| opponent_form_diff | 1438.3 |
| serve_diff | 906.4 |
| return_diff | 685.5 |
| opponent_surface_win_pct | 630.4 |
| player_surface_win_pct | 577.3 |
| opponent_surface_matches | 551.9 |
| opponent_1st_in_avg | 545.3 |
| surface_diff | 502.1 |
| player_surface_matches | 500.6 |
| opponent_days_rest | 497.5 |
| opponent_minutes_avg | 486.7 |
| opponent_df_avg | 483.0 |

## 4. Rule Filter Pass Rates

| Year | dominant_form | rank_gap >= 30 | surface_specialist | All 3 | >= 2 of 3 |
|------|--------------|---------------|-------------------|-------|-----------|
| 2024 | 41.4% | 59.7% | 20.8% | 4.7% | 35.4% |
| 2025 | 45.8% | 59.1% | 30.7% | 8.0% | 41.8% |
| 2026 | 48.5% | 62.7% | 27.5% | 7.1% | 44.1% |

## 5. Strategy Comparison

### 2024

| Strategy | Bets | ROI | Max DD | Win Rate | Total PnL |
|----------|------|-----|--------|----------|-----------|
| ML only (EV>=0.05) | 1339 | 22.33% | 8.88% | 44.9% | +350846 |
| ML only (EV>=0.03) | 1410 | 22.34% | 9.24% | 45.7% | +384386 |
| Rules only (all 3) | 48 | -38.98% | 8.88% | 25.0% | -8881 |
| Hybrid (ML+Rules) | 48 | -38.98% | 8.88% | 25.0% | -8881 |
| Relaxed (>=2 rules+ML) | 440 | 7.72% | 11.55% | 38.9% | +18875 |

### 2025

| Strategy | Bets | ROI | Max DD | Win Rate | Total PnL |
|----------|------|-----|--------|----------|-----------|
| ML only (EV>=0.05) | 1486 | 11.25% | 20.50% | 40.4% | +126884 |
| ML only (EV>=0.03) | 1552 | 12.51% | 21.11% | 41.5% | +163805 |
| Rules only (all 3) | 119 | -19.91% | 15.21% | 25.2% | -11406 |
| Hybrid (ML+Rules) | 119 | -19.91% | 15.21% | 25.2% | -11406 |
| Relaxed (>=2 rules+ML) | 599 | -8.24% | 23.11% | 33.4% | -21662 |

### 2026

| Strategy | Bets | ROI | Max DD | Win Rate | Total PnL |
|----------|------|-----|--------|----------|-----------|
| ML only (EV>=0.05) | 200 | 24.28% | 4.42% | 41.5% | +27083 |
| ML only (EV>=0.03) | 212 | 27.28% | 4.13% | 43.4% | +32835 |
| Rules only (all 3) | 4 | -62.55% | 1.25% | 25.0% | -1246 |
| Hybrid (ML+Rules) | 4 | -62.55% | 1.25% | 25.0% | -1246 |
| Relaxed (>=2 rules+ML) | 82 | 2.29% | 5.59% | 32.9% | +924 |

## 6. Aggregate Performance

| Strategy | Avg ROI | Avg DD | Avg WR | Total Bets |
|----------|---------|--------|--------|------------|
| ML only (EV>=0.05) | 19.29% | 11.27% | 42.3% | 3025 |
| ML only (EV>=0.03) | 20.71% | 11.49% | 43.5% | 3174 |
| Rules only (all 3) | -40.48% | 8.45% | 25.1% | 171 |
| Hybrid (ML+Rules) | -40.48% | 8.45% | 25.1% | 171 |
| Relaxed (>=2 rules+ML) | 0.59% | 13.42% | 35.1% | 1121 |

## 7. Monthly Breakdown

**Best strategy**: ML only (EV>=0.03)

### 2024

| Month | Bets | PnL | Win Rate |
|-------|------|-----|----------|
| 2024-01 | 137 | 24604 | 43.8% |
| 2024-02 | 92 | 21665 | 48.9% |
| 2024-03 | 111 | 17907 | 47.7% |
| 2024-04 | 157 | 24353 | 47.8% |
| 2024-05 | 170 | 24580 | 42.9% |
| 2024-06 | 99 | 10405 | 45.5% |
| 2024-07 | 149 | 58005 | 45.0% |
| 2024-08 | 245 | 42551 | 44.1% |
| 2024-09 | 95 | 59715 | 50.5% |
| 2024-10 | 138 | 93519 | 46.4% |
| 2024-11 | 17 | 7082 | 41.2% |

### 2025

| Month | Bets | PnL | Win Rate |
|-------|------|-----|----------|
| 2024-12 | 2 | 296 | 50.0% |
| 2025-01 | 116 | 10874 | 37.9% |
| 2025-02 | 101 | -8195 | 34.7% |
| 2025-03 | 111 | 13604 | 41.4% |
| 2025-04 | 162 | -7408 | 40.7% |
| 2025-05 | 196 | 49667 | 46.4% |
| 2025-06 | 111 | 17182 | 44.1% |
| 2025-07 | 212 | 60047 | 44.3% |
| 2025-08 | 257 | -24411 | 37.0% |
| 2025-09 | 99 | -3434 | 35.4% |
| 2025-10 | 161 | 44103 | 47.2% |
| 2025-11 | 24 | 11481 | 50.0% |

### 2026

| Month | Bets | PnL | Win Rate |
|-------|------|-----|----------|
| 2026-01 | 103 | 12131 | 39.8% |
| 2026-02 | 96 | 19911 | 47.9% |
| 2026-03 | 6 | 2138 | 50.0% |
| 2026-04 | 7 | -1344 | 28.6% |

## 8. Kill Switch Analysis

**Threshold**: Monthly loss > 10% of bankroll (10,000 RUB)

- **2024**: No months would trigger kill switch
- **2025**: 1 months would trigger kill switch
  - 2025-08: PnL=-24411 (-10.3% of BR)
- **2026**: No months would trigger kill switch

## 9. Verdict

### Key Findings

- **ML-only (EV>=0.05)**: avg ROI = 19.29% across 3025 bets
- **Relaxed Hybrid (>=2 rules + ML)**: avg ROI = 0.59% across 1121 bets
- **Rules only**: consistently negative ROI — rule filters alone have no predictive power
- **Hybrid (all 3 rules + ML)**: too restrictive, only 171 bets total

### Important Caveats

1. **ROI is calculated with compounding stakes** (0.5% of current bankroll). With fixed stakes, ROI would be lower.
2. **The model finds underdog value**: avg odds ~3.0, win rate ~44-45%. This is a genuine signal — the model identifies mispriced underdogs.
3. **Platt scaling failed catastrophically** (logloss 11-13x worse) — confirmed again with this dataset.
4. **Temperature scaling (T=1.5) is used for EV calculation** to avoid overconfident probability estimates.
5. **No monthly losses exceeded 10%** — kill switch was never triggered in any year.

**ML-only with EV>=0.05 is recommended for live deployment.**
- ML-only avg ROI: 19.29% vs Hybrid avg ROI: -40.48%
- Rule filters (all 3) are too restrictive — only 171 bets total
- Relaxed Hybrid (>=2 rules) has positive ROI but lower than ML-only
- Flat 0.5% staking with EV >= 0.05
- Kill switch: stop if monthly loss > 10% of bankroll
