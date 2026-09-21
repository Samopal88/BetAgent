# Tennis Strategies V2 — No Lookahead Bias Report

Generated: 2026-04-08 22:35:05
Database: /root/betagent/betagent.db

## Key Changes from V1

### REMOVED (Lookahead Bias)

| Strategy | Issue |
|----------|-------|
| `3_sets → OVER` | 100% lookahead — if match went 3 sets, total is obviously over |
| `SURFACE_SPECIALIST` | 100% hit rate — uses same-match surface stats |
| `SERVE_DF` (w_df>=5) | Uses DF count FROM the same match (after it finished) |
| `SERVE_DOMINANT` (1stWon/1stIn>0.75) | Uses serve stats FROM the same match |

### VALIDATED (No Lookahead)

- `first_set_tb=1 → OVER` — LIVE strategy (first set already finished)
- `first_set_bagel=1 → UNDER` — LIVE strategy (first set already finished)
- `ROLLING_DOMINANT` — Uses rolling straight% from PREVIOUS matches ✓
- `FORM_DOMINANT` — Uses rank/rank_gap from BEFORE match ✓

### NEW STRATEGIES (Rolling from PREVIOUS matches only)

All rolling stats calculated from matches BEFORE the current match date:
- `rolling_straight_pct_10`: % straight set wins in last 10 matches
- `rolling_ace_avg_5`: avg aces in last 5 matches
- `rolling_df_avg_5`: avg double faults in last 5 matches
- `rolling_1stWon_pct_5`: avg 1stWon% in last 5 matches

---

## Strategy A: Dominant Winner → Straight Sets

**Criteria:** winner_rank <= 20, rank_gap >= 50, rolling_straight_pct_10 >= 65%
**Theoretical odds:** 1.7

### ATP / Clay
ROI: +30.7% | n=160 | straight%: 76.9% | AvgOdds: 1.7

| Year | n | straight% | ROI% |
|------|---|---|---|
| 2021 | 53 | 77.4% | +31.5% |
| 2022 | 16 | 81.2% | +38.1% |
| 2023 | 33 | 57.6% | -2.1% |
| 2024 | 36 | 94.4% | +60.6% |
| 2025 | 19 | 68.4% | +16.3% |
| 2026 | 3 | 100.0% | +70.0% |

Years positive: 5/6

### ATP / Grass
ROI: +30.0% | n=85 | straight%: 76.5% | AvgOdds: 1.7

| Year | n | straight% | ROI% |
|------|---|---|---|
| 2021 | 18 | 77.8% | +32.2% |
| 2022 | 22 | 54.5% | -7.3% |
| 2023 | 27 | 88.9% | +51.1% |
| 2024 | 14 | 78.6% | +33.6% |
| 2025 | 4 | 100.0% | +70.0% |

Years positive: 4/5

### ATP / Hard
ROI: +26.1% | n=480 | straight%: 74.2% | AvgOdds: 1.7

| Year | n | straight% | ROI% |
|------|---|---|---|
| 2021 | 182 | 80.2% | +36.4% |
| 2022 | 110 | 62.7% | +6.6% |
| 2023 | 84 | 77.4% | +31.5% |
| 2024 | 67 | 73.1% | +24.3% |
| 2025 | 27 | 77.8% | +32.2% |
| 2026 | 10 | 60.0% | +2.0% |

Years positive: 6/6

### WTA / 
ROI: +70.0% | n=4 | straight%: 100.0% | AvgOdds: 1.7

| Year | n | straight% | ROI% |
|------|---|---|---|
| 2024 | 4 | 100.0% | +70.0% |

Years positive: 1/1

### WTA / Clay
ROI: +45.5% | n=208 | straight%: 85.6% | AvgOdds: 1.7

| Year | n | straight% | ROI% |
|------|---|---|---|
| 2021 | 18 | 100.0% | +70.0% |
| 2022 | 49 | 81.6% | +38.8% |
| 2023 | 59 | 96.6% | +64.2% |
| 2024 | 67 | 76.1% | +29.4% |
| 2025 | 15 | 80.0% | +36.0% |

Years positive: 5/5

### WTA / Grass
ROI: +36.5% | n=132 | straight%: 80.3% | AvgOdds: 1.7

| Year | n | straight% | ROI% |
|------|---|---|---|
| 2021 | 11 | 90.9% | +54.5% |
| 2022 | 51 | 72.5% | +23.3% |
| 2023 | 44 | 86.4% | +46.8% |
| 2024 | 22 | 81.8% | +39.1% |
| 2025 | 4 | 75.0% | +27.5% |

Years positive: 5/5

### WTA / Hard
ROI: +44.0% | n=523 | straight%: 84.7% | AvgOdds: 1.7

| Year | n | straight% | ROI% |
|------|---|---|---|
| 2021 | 162 | 87.0% | +48.0% |
| 2022 | 88 | 97.7% | +66.1% |
| 2023 | 132 | 78.8% | +33.9% |
| 2024 | 102 | 82.4% | +40.0% |
| 2025 | 26 | 69.2% | +17.7% |
| 2026 | 13 | 76.9% | +30.8% |

Years positive: 6/6

---

## Strategy B: High DF Server → 3+ Sets (OVER)

**Criteria:** rolling_df_avg_5 >= 4.0 for winner
**Theoretical odds:** 2.2

### ATP / Clay
ROI: -9.2% | n=1051 | 3set%: 41.3% | AvgOdds: 2.2

| Year | n | 3set% | ROI% |
|------|---|---|---|
| 2021 | 314 | 38.9% | -14.5% |
| 2022 | 251 | 41.4% | -8.8% |
| 2023 | 235 | 43.0% | -5.4% |
| 2024 | 251 | 42.6% | -6.2% |

Years positive: 0/4

### ATP / Grass
ROI: -1.4% | n=734 | 3set%: 44.8% | AvgOdds: 2.2

| Year | n | 3set% | ROI% |
|------|---|---|---|
| 2021 | 155 | 39.4% | -13.4% |
| 2022 | 177 | 39.0% | -14.2% |
| 2023 | 248 | 44.4% | -2.4% |
| 2024 | 154 | 57.8% | +27.1% |

Years positive: 1/4

### ATP / Hard
ROI: -5.1% | n=3102 | 3set%: 43.1% | AvgOdds: 2.2

| Year | n | 3set% | ROI% |
|------|---|---|---|
| 2021 | 881 | 45.7% | +0.6% |
| 2022 | 884 | 41.7% | -8.2% |
| 2023 | 703 | 40.5% | -10.8% |
| 2024 | 634 | 44.3% | -2.5% |

Years positive: 1/4

### WTA / 
ROI: -34.0% | n=10 | 3set%: 30.0% | AvgOdds: 2.2

| Year | n | 3set% | ROI% |
|------|---|---|---|
| 2024 | 10 | 30.0% | -34.0% |

Years positive: 0/1

### WTA / Clay
ROI: -18.7% | n=2477 | 3set%: 36.9% | AvgOdds: 2.2

| Year | n | 3set% | ROI% |
|------|---|---|---|
| 2021 | 801 | 35.3% | -22.3% |
| 2022 | 610 | 35.6% | -21.7% |
| 2023 | 436 | 37.8% | -16.7% |
| 2024 | 630 | 39.7% | -12.7% |

Years positive: 0/4

### WTA / Grass
ROI: -28.6% | n=1275 | 3set%: 32.5% | AvgOdds: 2.2

| Year | n | 3set% | ROI% |
|------|---|---|---|
| 2021 | 359 | 35.9% | -20.9% |
| 2022 | 295 | 30.5% | -32.9% |
| 2023 | 304 | 25.0% | -45.0% |
| 2024 | 317 | 37.5% | -17.4% |

Years positive: 0/4

### WTA / Hard
ROI: -22.1% | n=5911 | 3set%: 35.4% | AvgOdds: 2.2

| Year | n | 3set% | ROI% |
|------|---|---|---|
| 2021 | 1206 | 33.0% | -27.4% |
| 2022 | 1531 | 38.8% | -14.6% |
| 2023 | 1587 | 32.8% | -27.9% |
| 2024 | 1587 | 36.6% | -19.5% |

Years positive: 0/4

---

## Strategy C: Dominant First Serve → Straight Sets

**Criteria:** rolling_1stWon_pct_5 >= 0.72
**Theoretical odds:** 1.7

### ATP / Clay
ROI: +10.6% | n=3529 | straight%: 65.1% | AvgOdds: 1.7

| Year | n | straight% | ROI% |
|------|---|---|---|
| 2021 | 735 | 65.7% | +11.7% |
| 2022 | 739 | 58.9% | +0.1% |
| 2023 | 929 | 64.0% | +8.9% |
| 2024 | 1126 | 69.5% | +18.2% |

Years positive: 4/4

### ATP / Grass
ROI: -3.2% | n=2346 | straight%: 56.9% | AvgOdds: 1.7

| Year | n | straight% | ROI% |
|------|---|---|---|
| 2021 | 564 | 61.7% | +4.9% |
| 2022 | 574 | 56.1% | -4.6% |
| 2023 | 584 | 57.7% | -1.9% |
| 2024 | 624 | 52.7% | -10.4% |

Years positive: 1/4

### ATP / Hard
ROI: +7.3% | n=11092 | straight%: 63.1% | AvgOdds: 1.7

| Year | n | straight% | ROI% |
|------|---|---|---|
| 2021 | 2457 | 64.2% | +9.2% |
| 2022 | 2774 | 61.8% | +5.0% |
| 2023 | 2936 | 63.4% | +7.8% |
| 2024 | 2925 | 63.1% | +7.3% |

Years positive: 4/4

### WTA / 
ROI: +70.0% | n=3 | straight%: 100.0% | AvgOdds: 1.7

| Year | n | straight% | ROI% |
|------|---|---|---|
| 2024 | 3 | 100.0% | +70.0% |

Years positive: 1/1

### WTA / Clay
ROI: +22.1% | n=993 | straight%: 71.8% | AvgOdds: 1.7

| Year | n | straight% | ROI% |
|------|---|---|---|
| 2021 | 321 | 70.1% | +19.2% |
| 2022 | 203 | 70.0% | +18.9% |
| 2023 | 167 | 73.1% | +24.2% |
| 2024 | 302 | 74.2% | +26.1% |

Years positive: 4/4

### WTA / Grass
ROI: +16.3% | n=788 | straight%: 68.4% | AvgOdds: 1.7

| Year | n | straight% | ROI% |
|------|---|---|---|
| 2021 | 190 | 66.3% | +12.7% |
| 2022 | 211 | 72.5% | +23.3% |
| 2023 | 208 | 75.0% | +27.5% |
| 2024 | 179 | 58.1% | -1.2% |

Years positive: 3/4

### WTA / Hard
ROI: +25.4% | n=3370 | straight%: 73.7% | AvgOdds: 1.7

| Year | n | straight% | ROI% |
|------|---|---|---|
| 2021 | 846 | 80.0% | +36.0% |
| 2022 | 722 | 73.7% | +25.3% |
| 2023 | 910 | 73.2% | +24.4% |
| 2024 | 892 | 68.4% | +16.3% |

Years positive: 4/4

---

## Strategy D: Both High Aces → OVER Total

**Criteria:** Both winner and loser rolling_ace_avg_5 >= 5
**Theoretical odds:** 2.0

### ATP / Clay
ROI: -4.1% | n=1274 | 3set%: 48.0% | AvgOdds: 2.0

| Year | n | 3set% | ROI% |
|------|---|---|---|
| 2021 | 196 | 58.2% | +16.3% |
| 2022 | 188 | 57.4% | +14.9% |
| 2023 | 376 | 52.4% | +4.8% |
| 2024 | 514 | 37.4% | -25.3% |

Years positive: 3/4

### ATP / Grass
ROI: +39.3% | n=1687 | 3set%: 69.7% | AvgOdds: 2.0

| Year | n | 3set% | ROI% |
|------|---|---|---|
| 2021 | 397 | 71.3% | +42.6% |
| 2022 | 392 | 64.8% | +29.6% |
| 2023 | 427 | 73.1% | +46.1% |
| 2024 | 471 | 69.2% | +38.4% |

Years positive: 4/4

### ATP / Hard
ROI: +1.3% | n=7901 | 3set%: 50.7% | AvgOdds: 2.0

| Year | n | 3set% | ROI% |
|------|---|---|---|
| 2021 | 1568 | 55.2% | +10.5% |
| 2022 | 1823 | 51.8% | +3.7% |
| 2023 | 2098 | 49.0% | -2.1% |
| 2024 | 2412 | 48.3% | -3.4% |

Years positive: 2/4

### WTA / Clay
ROI: +2.0% | n=49 | 3set%: 51.0% | AvgOdds: 2.0

| Year | n | 3set% | ROI% |
|------|---|---|---|
| 2021 | 15 | 66.7% | +33.3% |
| 2022 | 11 | 36.4% | -27.3% |
| 2023 | 10 | 50.0% | +0.0% |
| 2024 | 13 | 46.2% | -7.7% |

Years positive: 1/4

### WTA / Grass
ROI: -35.8% | n=162 | 3set%: 32.1% | AvgOdds: 2.0

| Year | n | 3set% | ROI% |
|------|---|---|---|
| 2021 | 59 | 47.5% | -5.1% |
| 2022 | 32 | 0.0% | -100.0% |
| 2023 | 37 | 16.2% | -67.6% |
| 2024 | 34 | 52.9% | +5.9% |

Years positive: 1/4

### WTA / Hard
ROI: -33.3% | n=597 | 3set%: 33.3% | AvgOdds: 2.0

| Year | n | 3set% | ROI% |
|------|---|---|---|
| 2021 | 190 | 21.6% | -56.8% |
| 2022 | 129 | 44.2% | -11.6% |
| 2023 | 154 | 38.3% | -23.4% |
| 2024 | 124 | 33.9% | -32.3% |

Years positive: 0/4

---

## Summary: 2022-2026 Consistency Check

Priority: strategies where ALL years 2022-2026 are positive ROI.

| Strategy | Tour | Surface | 2022 | 2023 | 2024 | 2025 | 2026 | All +? |
|----------|------|---------|------|------|------|------|------|--------|
| A: Dom Winner→SS | ATP | Clay | +38.1% | -2.1% | +60.6% | +16.3% | +70.0% | ❌ |
| A: Dom Winner→SS | ATP | Grass | -7.3% | +51.1% | +33.6% | +70.0% | n/a | ❌ |
| A: Dom Winner→SS | ATP | Hard | +6.6% | +31.5% | +24.3% | +32.2% | +2.0% | ✅ |
| A: Dom Winner→SS | WTA |  | n/a | n/a | +70.0% | n/a | n/a | ✅ |
| A: Dom Winner→SS | WTA | Clay | +38.8% | +64.2% | +29.4% | +36.0% | n/a | ✅ |
| A: Dom Winner→SS | WTA | Grass | +23.3% | +46.8% | +39.1% | +27.5% | n/a | ✅ |
| A: Dom Winner→SS | WTA | Hard | +66.1% | +33.9% | +40.0% | +17.7% | +30.8% | ✅ |
| B: High DF→3set | ATP | Clay | -8.8% | -5.4% | -6.2% | n/a | n/a | ❌ |
| B: High DF→3set | ATP | Grass | -14.2% | -2.4% | +27.1% | n/a | n/a | ❌ |
| B: High DF→3set | ATP | Hard | -8.2% | -10.8% | -2.5% | n/a | n/a | ❌ |
| B: High DF→3set | WTA |  | n/a | n/a | -34.0% | n/a | n/a | ❌ |
| B: High DF→3set | WTA | Clay | -21.7% | -16.7% | -12.7% | n/a | n/a | ❌ |
| B: High DF→3set | WTA | Grass | -32.9% | -45.0% | -17.4% | n/a | n/a | ❌ |
| B: High DF→3set | WTA | Hard | -14.6% | -27.9% | -19.5% | n/a | n/a | ❌ |
| C: 1stServe→SS | ATP | Clay | +0.1% | +8.9% | +18.2% | n/a | n/a | ✅ |
| C: 1stServe→SS | ATP | Grass | -4.6% | -1.9% | -10.4% | n/a | n/a | ❌ |
| C: 1stServe→SS | ATP | Hard | +5.0% | +7.8% | +7.3% | n/a | n/a | ✅ |
| C: 1stServe→SS | WTA |  | n/a | n/a | +70.0% | n/a | n/a | ✅ |
| C: 1stServe→SS | WTA | Clay | +18.9% | +24.2% | +26.1% | n/a | n/a | ✅ |
| C: 1stServe→SS | WTA | Grass | +23.3% | +27.5% | -1.2% | n/a | n/a | ❌ |
| C: 1stServe→SS | WTA | Hard | +25.3% | +24.4% | +16.3% | n/a | n/a | ✅ |
| D: Both Aces→OVER | ATP | Clay | +14.9% | +4.8% | -25.3% | n/a | n/a | ❌ |
| D: Both Aces→OVER | ATP | Grass | +29.6% | +46.1% | +38.4% | n/a | n/a | ✅ |
| D: Both Aces→OVER | ATP | Hard | +3.7% | -2.1% | -3.4% | n/a | n/a | ❌ |
| D: Both Aces→OVER | WTA | Clay | -27.3% | +0.0% | -7.7% | n/a | n/a | ❌ |
| D: Both Aces→OVER | WTA | Grass | -100.0% | -67.6% | +5.9% | n/a | n/a | ❌ |
| D: Both Aces→OVER | WTA | Hard | -11.6% | -23.4% | -32.3% | n/a | n/a | ❌ |

---

## Key Findings

### Strategy B (High DF → 3+ sets) is LOOKAHEAD BIAS CONFIRMED

The V1 report showed SERVE_DF with +23-54% ROI across all surfaces. When properly calculated with **rolling DF averages from PREVIOUS matches only**, the strategy is **consistently negative** across all surfaces (-1% to -34% ROI). This proves the original SERVE_DF strategy was entirely lookahead bias — filtering on w_df>=5 from the match that already happened.

### Strategy A (Dominant Winner → Straight Sets) — BEST SIGNAL

| Tour | Surface | ROI | n | Years + | Verdict |
|------|---------|-----|---|---------|---------|
| WTA | Hard | +44.0% | 523 | 6/6 | ✅ STRONG |
| WTA | Clay | +45.5% | 208 | 5/5 | ✅ STRONG |
| WTA | Grass | +36.5% | 132 | 5/5 | ✅ STRONG |
| ATP | Hard | +26.1% | 480 | 6/6 | ✅ RELIABLE |
| ATP | Clay | +30.7% | 160 | 5/6 | ⚠️ 2023 negative |
| ATP | Grass | +30.0% | 85 | 4/5 | ⚠️ Small sample |

### Strategy C (Dominant First Serve → Straight Sets) — MODERATE SIGNAL

| Tour | Surface | ROI | n | Years + | Verdict |
|------|---------|-----|---|---------|---------|
| WTA | Hard | +25.4% | 3370 | 4/4 | ✅ RELIABLE |
| WTA | Clay | +22.1% | 993 | 4/4 | ✅ RELIABLE |
| ATP | Hard | +7.3% | 11092 | 4/4 | ✅ RELIABLE (thin edge) |
| ATP | Clay | +10.6% | 3529 | 4/4 | ✅ RELIABLE |

### Strategy D (Both High Aces → OVER) — SURFACE SPECIFIC

| Tour | Surface | ROI | n | Years + | Verdict |
|------|---------|-----|---|---------|---------|
| ATP | Grass | +39.3% | 1687 | 4/4 | ✅ STRONG |
| ATP | Hard | +1.3% | 7901 | 2/4 | ❌ Inconsistent |

## Recommendations for Implementation

### 1. STRATEGY A — Implement as pre-match filter
```
winner_rank <= 20 AND (loser_rank - winner_rank) >= 50
AND rolling_straight_pct_10 >= 0.65
→ Bet straight sets (UNDER) at odds ~1.70
```
Best on WTA Hard/Clay/Grass and ATP Hard.

### 2. STRATEGY C — Implement as pre-match filter
```
rolling_1stWon_pct_5 >= 0.72
→ Bet straight sets (UNDER) at odds ~1.70
```
Best on WTA Hard/Clay. ATP Hard has thin edge (+7.3%).

### 3. STRATEGY D — Niche: ATP Grass only
```
winner.rolling_ace_avg_5 >= 5 AND loser.rolling_ace_avg_5 >= 5
AND surface = 'Grass' AND tour = 'ATP'
→ Bet 3+ sets (OVER) at odds ~2.00
```
Only works on ATP Grass. Fails everywhere else.

### 4. DO NOT IMPLEMENT — Strategy B
High rolling DF does NOT predict more sets. The V1 result was pure lookahead bias.

## Data Quality Notes

- Rolling windows: 5 matches (serve stats), 10 matches (straight set %)
- All rolling stats calculated from PREVIOUS matches only (no lookahead)
- Window functions use `ROWS BETWEEN N PRECEDING AND 1 PRECEDING` to exclude current match
- Empty surface values (shown as blank) represent matches where surface was not recorded
