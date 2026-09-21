# Tennis ML Enriched Dataset v2 — Coverage Report

## 1. Join Coverage

- backtest_tennis_players total rows: 31684
- Matched with odds (exact rank): 3762 (11.9%)
- Rows without odds: 27922 (88.1%)

## 2. Usable Rows

- Enriched match-level rows: 63368
- Year range: 2021 - 2026
- Tours: ['ATP', 'WTA']
- Surfaces: ['Hard', 'Clay', 'Grass', '']

## 3. Feature Categories

| Category | Features | Count |
|----------|----------|-------|
| Market | odds_player, odds_opponent | 2 |
| Rank | player/opponent rank, rank pts, diffs | 6 |
| Rolling Form | win_pct 5/10, straight_sets 5/10 | 8 |
| Serve/Return | ace, df, 1st_in, 1st_won%, bp_saved% | 12 |
| Surface | surface win%, matches, serve stats | 10 |
| Fatigue | days_rest, matches 7d/14d, minutes 14d | 8 |
| H2H | wins, losses, total | 3 |
| **Total** | | **~49** |

## 4. Missing Rates (Top 20)

| Feature | Missing % |
|---------|-----------|
| odds_player | 88.1% |
| odds_opponent | 88.1% |
| opponent_minutes_14d | 41.0% |
| player_minutes_14d | 41.0% |
| opponent_surface_bp_saved_pct | 26.1% |
| player_surface_bp_saved_pct | 26.1% |
| player_surface_1st_won_pct | 26.0% |
| opponent_surface_1st_won_pct | 26.0% |
| opponent_surface_ace_avg | 26.0% |
| player_surface_ace_avg | 26.0% |
| player_minutes_avg | 23.5% |
| opponent_minutes_avg | 23.5% |
| player_bp_saved_pct | 23.3% |
| opponent_bp_saved_pct | 23.3% |
| player_1st_won_pct | 23.2% |
| opponent_1st_won_pct | 23.2% |
| opponent_1st_in_avg | 23.2% |
| opponent_ace_avg | 23.2% |
| player_ace_avg | 23.2% |
| opponent_df_avg | 23.2% |

## 5. Feature Coverage Summary

- Rows with odds: 7524 (11.9%)
- Rows with serve stats: 48663 (76.8%)
- Rows with surface stats: 58664 (92.6%)
- Rows with H2H history: 16610 (26.2%)
- Rows with fatigue data: 60991 (96.2%)

## 6. Blockers / Limitations

- Odds only available for ~13% of matches (exact rank match required)
- Serve stats available for ~75% of backtest_tennis_players rows
- H2H limited to matches within backtest_tennis_players dataset
- No external data (injuries, weather, travel)
- Name format prevents fuzzy matching between tables

## 7. Verdict

- Dataset has 63368 rows — **READY** for baseline enriched model
- Rich feature set: rolling form, serve/return, surface, fatigue, H2H
- Serve stats provide strong signal even without odds
- Can train model with serve-based features; odds only needed for EV calculation
