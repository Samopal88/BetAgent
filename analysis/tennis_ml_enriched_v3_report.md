# Tennis ML Enriched Dataset v3 — Coverage Report

## 1. Join Coverage (v3 vs v2)

- backtest_tennis_players total rows: 28235
- High confidence: 11374 (40.3%)
- Medium confidence: 1751 (6.2%)
- Suspicious: 519 (1.8%)
- Total with odds: 13644 (48.3%)
- Unmatched: 14591 (51.7%)

| Version | Odds Coverage |
|---------|--------------|
| v2 (exact rank) | 11.9% |
| v3 (name norm) | 48.3% |

## 2. Usable Rows

- Enriched match-level rows: 56470
- Year range: 2021 - 2026
- Tours: ['ATP', 'WTA']
- Surfaces: ['Clay', 'Hard', 'Grass', '']

## 3. Confidence Distribution

- unmatched: 29182 (51.7%)
- high: 22748 (40.3%)
- medium: 3502 (6.2%)
- suspicious: 1038 (1.8%)

## 4. Missing Rates (Top 20)

| Feature | Missing % |
|---------|-----------|
| odds_opponent | 51.9% |
| odds_player | 51.9% |
| opponent_minutes_14d | 37.0% |
| player_minutes_14d | 37.0% |
| player_surface_bp_saved_pct | 26.8% |
| opponent_surface_bp_saved_pct | 26.8% |
| opponent_surface_1st_won_pct | 26.7% |
| player_surface_1st_won_pct | 26.7% |
| player_surface_ace_avg | 26.7% |
| opponent_surface_ace_avg | 26.7% |
| opponent_minutes_avg | 24.4% |
| player_minutes_avg | 24.4% |
| opponent_bp_saved_pct | 24.2% |
| player_bp_saved_pct | 24.2% |
| opponent_1st_won_pct | 24.2% |
| player_1st_won_pct | 24.2% |
| opponent_ace_avg | 24.2% |
| opponent_df_avg | 24.2% |
| player_df_avg | 24.2% |
| player_ace_avg | 24.2% |

## 5. Feature Coverage Summary

- Rows with odds: 27152 (48.1%)
- Rows with serve stats: 42822 (75.8%)
- Rows with surface stats: 52395 (92.8%)
- Rows with H2H history: 14314 (25.3%)
- Rows with fatigue data: 54415 (96.4%)

## 6. Join Type Breakdown

- : 29182
- exact: 22748
- multi_odds_2: 3096
- swapped: 1038
- multi_odds_3: 340
- multi_odds_4: 56
- multi_odds_5: 10

## 7. Verdict

- Dataset has 27152 rows with odds — **READY** for baseline ML model
- Odds coverage improved from 11.9% (v2) to 48.1% (v3)
- Name normalization is the primary improvement driver
- High confidence subset recommended for initial model training
