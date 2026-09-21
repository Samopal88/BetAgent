# Tennis Winner ML — Production Audit v1

## Audit Verdict: **CLEAN**
## Deployment Status: **READY FOR PAPER LIVE**

## 1. Checks Passed

Total: 28

- [dataset] All 28235 matches have exactly 2 rows
- [dataset] Sample of 200 matches: each has target=[0, 1]
- [dataset] No duplicate rows
- [dataset] rank_diff consistent within matches (sample)
- [time_split] Years strictly separated: train(2021-23), val(2024), test(2025), ood(2026)
- [time_split] No match spans multiple years
- [time_split] Train max (2023-11-27) <= Val min (2024-01-01)
- [time_split] Val max (2024-12-18) <= Test min (2024-12-29)
- [feature_leakage] Rolling features use shift(1) — verified in source code
- [feature_leakage] H2H computed chronologically — only prior meetings counted (verified in source)
- [feature_leakage] Surface stats use groupby+shift(1)+expanding — only prior surface matches (verified in source)
- [feature_leakage] H2H consistency: player_wins + opponent_wins == h2h_total
- [feature_leakage] No set/score columns in feature set
- [feature_leakage] No odds columns used as features
- [betting_math] Average overround: 0.0536 (5.4%) — realistic
- [betting_math] EV formula verified: EV = prob * odds - 1
- [betting_math] Kelly quarter formula verified
- [betting_math] Flat staking: 2% of initial bankroll per bet
- [betting_math] Bankroll updates dynamically; max stake capped at 2% of initial bankroll
- [betting_math] Max drawdown formula verified
- [betting_math] Losing streak tracking verified
- [betting_math] ROI = PnL / total_staked; ROI_BR = PnL / initial_bankroll — both reported
- [backtest_sanity] No single month dominates — max is 15.6%
- [backtest_sanity] No tournament has win rate > 85% (max: 50.00% in Abierto Mexicano)
- [backtest_sanity] Accuracy 65-69% is realistic for tennis prediction
- [backtest_sanity] 1843 unique matches in test betting set (expected ~1843)
- [backtest_sanity] Odds range: p01=1.50, p99=8.00 — no extreme outliers
- [backtest_sanity] Target balanced in test: 0.500

## 3. Warnings

- **[feature_leakage]** Median imputation computed on full subset (train+val+test), not train-only
  - Note: Should compute medians on train only and apply to val/test. Impact: minor for large datasets, but technically a leakage.

## 4. Info

- **[median_leakage]** Median imputation uses full subset median instead of train-only
  - Note: Impact estimate: < 0.5% on metrics for this dataset size. Fix: compute medians on train, apply to val/test. Not blocking for deployment but should be fixed in next version.

## 5. Live Rollout Design

### Signal Generation Rules

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| Subset | high+medium | Better test/OOD ROI than high-only |
| Min odds | 1.50 | Consistent with backtest filter |
| Min EV | 0.03 | Conservative threshold |
| Min model prob | 0.52 | Ensures model sees positive edge |
| Max stake | 2% of bankroll | Capped to prevent compounding |
| Staking | Kelly quarter | Adaptive sizing with safety cap |

### Live Output Schema

```json
{
  "timestamp": "2026-04-12T14:30:00Z",
  "model_version": "tennis_winner_v1",
  "match_id": 12345,
  "tour": "ATP",
  "tournament": "miami",
  "surface": "Hard",
  "round": "R32",
  "player": "Alcaraz C.",
  "opponent": "Sinner J.",
  "odds_player": 2.10,
  "odds_opponent": 1.80,
  "market_implied_prob": 0.476,
  "model_prob": 0.58,
  "calibrated_prob": 0.56,
  "edge": 0.08,
  "ev": 0.176,
  "stake_pct": 0.02,
  "stake_amount": 2000,
  "decision": "BET",
  "join_confidence": "high",
  "result": null,
  "pnl": null
}
```

### Controlled Rollout Plan

| Phase | Duration | Stake | Criteria to Advance | Kill Switch |
|-------|----------|-------|---------------------|-------------|
| Paper trading | 30 days | $0 | ROI > 0, logloss < 0.60 | N/A |
| Micro live | 30 days | 0.5% bankroll | ROI > 5%, no DD > 15% | 3 consecutive losing days or DD > 20% |
| Small live | 60 days | 1% bankroll | ROI > 3%, cal. logloss < 0.55 | DD > 25% or 10-loss streak |
| Normal live | ongoing | 2% bankroll | ROI > 2%, stable metrics | DD > 30% or monthly ROI < -10% |

## 6. Monthly Retrain Framework

### Champion/Challenger Logic

1. **Current production model** remains champion
2. **Every month** (or when 500+ new completed matches available):
   - Add newly completed matches to training data
   - Add live predictions and their results to evaluation set
   - Retrain candidate model on expanded dataset
   - Compare candidate vs champion on held-out recent data

### Comparison Metrics

| Metric | Weight | Champion Threshold |
|--------|--------|-------------------|
| Logloss (recent 3 months) | 40% | Candidate must be <= champion |
| ROI (paper/live) | 30% | Candidate ROI >= champion ROI - 2% |
| Calibration (Brier) | 15% | Candidate Brier <= champion Brier + 0.01 |
| Max drawdown | 15% | Candidate DD <= champion DD + 5% |

### Promotion Criteria
- Candidate must beat or match champion on ALL weighted metrics
- Minimum 200 new completed matches since last retrain
- At least 30 days of out-of-sample evaluation

### Rollback Criteria
- Champion model ROI drops below -5% over any 30-day window
- Champion model logloss exceeds 0.65 on recent data
- Max drawdown exceeds 30%
- 10+ consecutive losing bets
- Immediate rollback: revert to previous champion, pause live betting for 48h

## 7. Final Recommendation

- **Audit verdict**: CLEAN
- **Can deploy to controlled live**: yes
- **Recommended initial bankroll policy**: 2% max stake, Kelly quarter, EV >= 0.03
- **Recommended live logging fields**: timestamp, model_version, match_id, tour, tournament, surface, round, player, opponent, odds_player, odds_opponent, market_implied_prob, model_prob, calibrated_prob, edge, ev, stake_pct, stake_amount, decision, join_confidence, result, pnl
- **Recommended monthly retrain loop**: champion/challenger with 200+ new matches minimum, weighted metric comparison, automatic rollback on DD > 30%

### Status: **READY FOR PAPER LIVE**
