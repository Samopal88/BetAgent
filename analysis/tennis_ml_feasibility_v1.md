# Tennis ML Feasibility — Blueprint & Market Screening

**Date:** 2026-04-11
**Scope:** Sandbox analysis only. No production changes.

---

## 1. Tennis Data Inventory

### 1.1 Database Tables

| Table | Rows | Source | Date Range |
|-------|------|--------|------------|
| `backtest_tennis_matches` | 26,686 | Fonbet API (Betz parser) | 2021-01 to 2026-04 |
| `backtest_tennis_players` | 28,235 | Jeff Sackmann tennis data | 2021-01 to 2026-04 |
| `tennis_data_odds` | 15,245 | tennis-data.co.uk (Pinnacle/Bet365) | 2021-2026 |
| `tennis_name_lookup` | 2,390 | Russian→English name mapping | N/A |
| `tennis_player_mapping` | 950 | Player mapping with confidence | N/A |
| `tennis_player_mapping_review` | 536 | Fuzzy matches needing review | N/A |

### 1.2 `backtest_tennis_matches` — Primary Dataset

**Schema:**
```
tour, level, tournament, surface, match_date,
player1, player2,
sets_winner, sets_loser, score_detail, tiebreak,
odds_p1, odds_p2,                    -- match winner
odds_total_over, odds_total_under, total_line,  -- total games
odds_handicap_p1, odds_handicap_p2, handicap_line,  -- handicap
winner (1=player1, 2=player2)
```

**Volume by year:**

| Year | Matches |
|------|---------|
| 2021 | 4,969 |
| 2022 | 5,311 |
| 2023 | 5,074 |
| 2024 | 5,144 |
| 2025 | 4,501 |
| 2026 | 1,687 |
| **Total** | **26,686** |

**Volume by tour / surface:**

| Tour | Surface | Matches |
|------|---------|---------|
| ATP | Hard | 2,853 |
| ATP | Clay | 1,959 |
| ATP | (empty) | 3,134 |
| WTA | Hard | 3,985 |
| WTA | Clay | 1,768 |
| WTA | (empty) | 4,566 |
| WTA | 1000 Hard | 2,015 |
| WTA | 1000 Clay | 654 |
| WTA | 1000 (empty) | 2,481 |

**Note:** ~44% of matches have empty surface field. Hard and Clay are well-represented; Grass is essentially missing from this table (only in `backtest_tennis_players`).

### 1.3 `backtest_tennis_players` — Player Stats

**Schema:**
```
tour, year, tourney_name, surface, tourney_level, tourney_date, round,
winner_name, winner_rank, winner_rank_pts,
loser_name, loser_rank, loser_rank_pts,
score, best_of, minutes,
w_ace, w_df, w_1stIn, w_1stWon, w_2ndWon, w_bpSaved, w_bpFaced,
l_ace, l_df, l_1stIn, l_1stWon, l_2ndWon, l_bpSaved, l_bpFaced,
sets_winner, sets_loser, straight_sets
```

**Feature coverage:**

| Feature | Populated | % of 28,235 |
|---------|-----------|-------------|
| Rankings | 28,145 | 99.7% |
| Serve stats (aces, 1stIn, etc.) | 21,375 | 75.7% |
| Match duration | 20,549 | 72.8% |

**Surface coverage:** Hard 17,134 | Clay 7,982 | Grass 3,009 | Empty 110

**Tournament levels:** Grand Slam 6,256 | Masters 1000 2,403 | ATP250/WTA250 1,775 | ATP500/WTA500 1,163 | Others 16,638

### 1.4 `tennis_data_odds` — Secondary Odds Source

15,245 matches from tennis-data.co.uk with Pinnacle + Bet365 odds.
Has: tour, year, tournament, surface, round, best_of, rankings, scores, b365/pinnacle odds.
Does NOT have: serve stats, total games lines, handicap lines.

### 1.5 Name Mapping

- `tennis_name_lookup`: 2,390 entries mapping Russian names → English canonical names
- `tennis_player_mapping`: 950 entries, avg confidence 89.3%
- `tennis_player_mapping_review`: 536 entries needing manual review

**Quality concern:** ~22% of mapped players need review. Russian name variants (full name, initials, abbreviated) create ambiguity.

---

## 2. Market Availability Assessment

### 2.1 Match Winner (Moneyline)

| Metric | Value |
|--------|-------|
| Matches with odds_p1 AND odds_p2 | 26,004 (97.4%) |
| Odds range p1 | 1.01 — 60.0 (avg 2.15) |
| Odds range p2 | 1.01 — 30.0 (avg 2.72) |
| Unique players | ~4,485 |
| Years | 2021-2026 (5+ years) |
| Target clarity | Binary: winner=1 or winner=2 |

**Verdict: EXCELLENT coverage. Best candidate.**

### 2.2 Total Games (Over/Under)

| Metric | Value |
|--------|-------|
| Matches with total odds | 25,104 (94.1%) |
| Matches with total_line | 25,104 (94.1%) |
| Most common lines | 21.5 (8,535), 22.5 (5,706), 20.5 (4,652) |
| Line range | 16.5 — 24.5 |
| Target clarity | Binary: total games > or < line |

**Verdict: GOOD coverage. Second-best candidate.**

### 2.3 Handicap (Games Spread)

| Metric | Value |
|--------|-------|
| Matches with handicap odds | 9,792 (36.7%) |
| Matches with handicap_line | 9,792 (36.7%) |
| Most common lines | -1.5 (2,842), -4.5 (1,033), -3.5 (1,013) |
| Line range | -6.5 to 0.0 |

**Verdict: POOR coverage. Only 37% of matches have handicap data. Not viable for ML without significant data gaps.**

### 2.4 Set Betting / Exact Score

| Outcome | Count | % |
|---------|-------|---|
| 2-0 (p1 wins) | 8,979 | 33.6% |
| 2-1 (p1 wins) | 4,368 | 16.4% |
| 0-2 (p2 wins) | 6,993 | 26.2% |
| 1-2 (p2 wins) | 4,096 | 15.4% |
| Other | 2,250 | 8.4% |

**Verdict: Data exists (sets_winner/sets_loser), but no dedicated odds for set betting markets. Would need to derive implied odds from match winner odds. 4-class classification problem is harder than binary.**

### 2.5 Tiebreak (Yes/No)

| Outcome | Count | % |
|---------|-------|---|
| No tiebreak | 18,436 | 69.1% |
| Tiebreak | 8,250 | 30.9% |

**Verdict: Data exists but no dedicated tiebreak odds. Could be modeled as a side market.**

---

## 3. ML Feasibility by Market

### 3.1 Match Winner — FEASIBLE

**Why it works:**
- 26,004 labeled samples (binary classification)
- 5+ years of temporal data
- Rich feature space available via join with `backtest_tennis_players`
- Clear target variable
- Well-studied problem with known predictive signals

**Feature engineering potential:**
- Rolling form (last 5/10/20 matches) — needs to be computed from `backtest_tennis_players`
- Head-to-head history — needs to be computed from `backtest_tennis_players`
- Surface-specific performance — surface is available
- Ranking differential — available
- Serve dominance metrics — available for 76% of matches
- Tournament level context — available

**Estimated model capacity:** With 26K samples and ~20-30 engineered features, a gradient boosting model (LightGBM/XGBoost) should be trainable with proper time-based splits.

### 3.2 Total Games Over/Under — FEASIBLE (secondary)

**Why it works:**
- 25,104 labeled samples
- Same feature space as match winner
- Binary classification (over vs under)

**Challenges:**
- Total line varies per match (16.5-24.5), so model needs to predict expected total games, not just binary
- Would need to predict expected total, then compare to line
- Less studied than match winner

### 3.3 Handicap — NOT FEASIBLE (insufficient data)

Only 36.7% coverage. Too many gaps for reliable ML training.

### 3.4 Set Betting — POSSIBLE (advanced)

4-class classification with 26K samples. Doable but harder. No dedicated odds to compare against — would need to derive from match winner odds.

### 3.5 Exact Score — NOT FEASIBLE

Too many classes, too few samples per class.

---

## 4. Recommended MVP Market: Match Winner

**Match Winner (moneyline) is the clear MVP candidate.**

Reasons:
1. **Maximum data:** 26,004 samples vs 9,792 for handicap
2. **Binary target:** Simplest ML problem
3. **Direct odds comparison:** Can compute EV = model_prob * odds - 1
4. **Proven signals:** Existing rule-based strategies (tennis_strategies_v2) show +20-45% ROI on specific segments, proving the data has predictive signal
5. **Clear deployment path:** Model outputs probability → compare to market odds → bet if EV > threshold

---

## 5. Proposed Dataset Design

### 5.1 Row Definition

One row = one player's perspective in one match.

This means each match produces TWO rows (one for player1, one for player2), which is standard for tennis ML.

```
match_id, tour, level, surface, match_date, tournament,
player_name, opponent_name,
is_home_player (1=player1, 0=player2),

# Market
odds_for_player,           # odds_p1 if is_home=1, else odds_p2
target_win,                # 1 if this player won, 0 otherwise

# Pre-match features (all computable BEFORE the match)
player_rank, opponent_rank, rank_diff,
player_rank_pts, opponent_rank_pts,

# Rolling form (computed from PREVIOUS matches only)
player_rolling_win_pct_5, player_rolling_win_pct_10,
player_rolling_ace_avg_5, player_rolling_df_avg_5,
player_rolling_1stWon_pct_5, player_rolling_2ndWon_pct_5,
player_rolling_bp_saved_pct_5,
player_rolling_straight_pct_10,
player_matches_played_ytd,

# Opponent rolling form
opponent_rolling_win_pct_5, opponent_rolling_ace_avg_5,
opponent_rolling_df_avg_5, opponent_rolling_1stWon_pct_5,

# Surface-specific form
player_surface_win_pct_20, opponent_surface_win_pct_20,

# H2H
h2h_wins, h2h_losses, h2h_surface_wins, h2h_surface_losses,

# Context
tournament_level_numeric,  # 250/500/1000/GrandSlam
best_of,                   # 3 or 5
days_since_last_match,
is_grand_slam,
```

### 5.2 Target

Binary: `target_win = 1` if the player won the match, `0` otherwise.

### 5.3 Time Split

```
Train:  2021-01 to 2023-12  (~15,000 matches → ~30,000 rows)
Val:    2024-01 to 2024-12  (~5,100 matches → ~10,200 rows)
Test:   2025-01 to 2025-12  (~4,500 matches → ~9,000 rows)
OOD:    2026-01 to present  (~1,700 matches → ~3,400 rows)
```

**CRITICAL:** No shuffling. Strict temporal split to prevent lookahead bias. Rolling features must only use matches BEFORE the current match date.

### 5.4 Feature Computation Strategy

Rolling features must be computed incrementally:
```python
for each match in date order:
    compute rolling stats from all PREVIOUS matches for both players
    append row to dataset
    (do NOT include current match in rolling stats)
```

This is the same pattern used in `tennis_strategies_v2.py` which already implements `rolling_straight_pct_10`, `rolling_ace_avg_5`, etc.

---

## 6. Proposed Training / Backtest / Forward-Test Pipeline

### 6.1 Phase 1: Data Engineering

```
tennis_ml_feasibility_v1.py (this file) — data survey
tennis_ml_dataset.py — feature engineering pipeline
  - Join backtest_tennis_matches + backtest_tennis_players
  - Compute rolling features with no lookahead
  - Compute H2H features
  - Output: tennis_ml_dataset.parquet
```

### 6.2 Phase 2: Model Training

```
tennis_ml_train.py
  - Load tennis_ml_dataset.parquet
  - Time-based train/val/test split
  - Model: LightGBM (gradient boosting)
  - Objective: binary cross-entropy
  - Calibrate probabilities (isotonic regression on val set)
  - Evaluate: log-loss, Brier score, calibration curve
  - Output: tennis_model.pkl, calibration.pkl
```

### 6.3 Phase 3: Backtest Simulation

```
tennis_ml_backtest.py
  - Load model + calibration
  - For each match in test set (2025):
    - Generate features (no lookahead)
    - Predict probability
    - Compare to market odds: EV = p * odds - 1
    - If EV > threshold (e.g., 0.03): place bet
    - Kelly quarter-staking
    - Track equity curve
  - Output: backtest metrics (ROI, hit rate, drawdown, Sharpe)
```

### 6.4 Phase 4: Forward Test (Paper Trading)

```
tennis_ml_live.py
  - Wire into agent_handoff_v7.py --sport tennis
  - Fetch live odds from Fonbet API
  - Fetch player data (rankings, recent results)
  - Compute features in real-time
  - Predict and compare EV
  - Log predictions without placing bets
  - Compare against actual results over 1-2 months
```

### 6.5 Model Architecture

```
LightGBM Classifier
  - n_estimators: 500-1000
  - max_depth: 6-8
  - learning_rate: 0.01-0.05
  - feature_fraction: 0.7
  - Early stopping on val set (50 rounds)

Probability Calibration:
  - Isotonic regression on validation set
  - Prevents overconfident predictions

Feature importance analysis:
  - SHAP values for interpretability
  - Identify which features drive predictions
```

---

## 7. Key Risks & Data Gaps

### 7.1 Critical Risks

| Risk | Severity | Mitigation |
|------|----------|------------|
| **Surface missing for 44% of matches** | HIGH | Use `backtest_tennis_players` surface (better coverage) or infer from tournament name |
| **Name mapping quality** | HIGH | 536 entries need review; wrong mapping corrupts rolling features |
| **Serve stats only 76% coverage** | MEDIUM | Use as optional features; model handles missing values |
| **No injury/retirement data** | MEDIUM | Tennis has ~5-8% retirement rate; model may misprice these |
| **No rest days / schedule data** | MEDIUM | Can be approximated from match_date gaps in player history |
| **Small sample per player** | MEDIUM | ~4,485 unique players; many appear only a few times |
| **Odds from single bookmaker** | LOW | Fonbet API; could add Pinnacle from tennis_data_odds for comparison |

### 7.2 Data Gaps vs Ideal Tennis ML Dataset

| Missing Feature | Impact | Workaround |
|-----------------|--------|------------|
| In-play / live odds | Cannot model live betting | Out of scope for MVP |
| Point-by-point data | Cannot model momentum | Out of scope |
| Weather / indoor | Surface conditions matter | Infer from tournament/venue |
| Player fatigue / travel | Affects performance | Approximate from schedule density |
| Injury reports | Major price mover | Not available; accept as noise |
| Serve speed / ace placement | Advanced serve metrics | Not available |

### 7.3 Market Efficiency Concern

Tennis is one of the most efficiently priced betting markets. The ATP/WTA match winner market has high liquidity and sharp odds. Beating it consistently requires:
- Very accurate probability estimates
- Finding mispriced edges in less liquid tournaments (Challenger, lower-level WTA)
- Surface-specific modeling advantages

---

## 8. Recommendation

### WORTH PURSUING — with caveats

**Yes, tennis ML is feasible** based on current data, but:

1. **Start with Match Winner only.** It has the most data (26K samples), cleanest target, and proven predictive signals from existing rule-based strategies.

2. **Focus on WTA first.** The existing `tennis_strategies_v2` analysis shows WTA strategies have higher and more consistent ROI (+25-45%) than ATP (+20-30%). WTA markets are likely less efficient.

3. **Surface-specific models.** Build separate models for Hard and Clay. Grass has too little data. Handle missing surface by inferring from tournament.

4. **Name mapping must be fixed first.** The 536 entries in `tennis_player_mapping_review` need resolution before rolling features can be trusted.

5. **Expected timeline for MVP:**
   - Week 1: Fix name mapping, build feature engineering pipeline
   - Week 2: Train baseline model, evaluate on 2024 validation
   - Week 3: Backtest on 2025, tune thresholds
   - Week 4: Paper trading setup, forward test

6. **Success criteria for MVP:**
   - Test set log-loss < 0.60 (baseline: market implied ~0.65)
   - Backtest ROI > 5% flat staking on 2025 data
   - At least 100 bets in test period
   - Max drawdown < 25%

### NOT recommended at this stage:
- Total games ML (secondary priority, after match winner proven)
- Handicap ML (insufficient data)
- Set betting / exact score (too complex for MVP)
- Live / in-play modeling (no in-play data available)
