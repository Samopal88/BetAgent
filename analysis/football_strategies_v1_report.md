# Football Strategies v1 — Full Report

**Generated:** 2026-04-09 11:25:18
**Database:** betagent.db / football_features_ml_v1
**Total matches:** 60,586
**Date range:** 2019–2026
**Hypotheses tested:** 509

## 1. Coverage Summary

| Market | Matches | Coverage % | Evaluable? |
|--------|---------|------------|------------|
| 1X2 | 57,504 | 94.9% | Yes (but not priority) |
| Total O/U | 58,438 | 96.5% | **Yes** |
| BTTS | 34,091 | 56.3% | **Yes** |
| Corners | 13,138 | 21.7% | No (no outcome data) |
| Yellow Cards | 5,245 | 8.7% | No (no outcome data) |

> **NOTE:** Corners and Yellow Cards have odds/lines in the database but NO outcome columns
> (`home_corners`, `away_corners`, `home_yellow_cards`, `away_yellow_cards` are absent).
> These markets will become evaluable once outcome data is added to the pipeline.

## 2. Hypotheses Tested

### A. Base Total O/U
- Low margin total markets (1–8%)
- Total line ranges (0–1.5 to 5.5+)
- Exact total lines (1.5, 2.0, 2.25, 2.5, 2.75, 3.0, 3.25, 3.5, 4.0, 4.5)
- Odds ranges (1.05–6.0)
- 1X2 imbalance + total (home/away favorite at various thresholds)
- Draw-ish matches + total
- Low margin + specific line combos
- Home/away prob ratio + total
- Contrarian: high implied prob -> bet opposite
- Home underdog + total
- Balanced matches + total
- Margin ranges

### B. BTTS
- BTTS odds ranges (1.05–6.0)
- BTTS + total line combos
- BTTS + 1X2 imbalance (home/away favorite)
- BTTS + draw-ish matches
- BTTS + low margin (2–8%)
- BTTS + high/low total line
- BTTS + balanced matches
- Contrarian: high prob_btts_yes -> bet No
- BTTS + prob_btts_yes ranges
- BTTS + home underdog
- BTTS margin ranges

### X. Cross-Market (Total + BTTS)
- Low margin on both total and BTTS simultaneously
- Total line 2.5 + BTTS odds combos
- Total Over + BTTS Yes (both signal goals)
- BTTS No + total under + draw-ish (triple defensive)
- Home strong favorite + total under
- BTTS No + dominant home (clean sheet)
- Total line 2.5/3.0 + margin filters
- BTTS + total line + 1X2 combos
- prob_btts_yes/no + total line combos

## 3. Classification Summary

| Class | Count |
|-------|-------|
| STRONG | 6 |
| WATCHLIST | 2 |
| FRAGILE | 0 |
| REJECT | 501 |

## 4. Top Strategies

### STRONG Strategies

#### 1. BTTS No | odds [4.0, 6.0)

- **Market:** BTTS
- **Sample:** n = 108
- **Hits:** 29
- **Hit Rate:** 26.9%
- **Avg Odds:** 4.517
- **ROI:** 21.3%
- **ROI 2024–2026:** 31.18% (n=17)
- **ROI 2025–2026:** 27.0% (n=10)
- **ROI by year:**
  - 2019: ROI=-100.0%, HR=0.0%, n=2
  - 2020: ROI=37.56%, HR=29.3%, n=41
  - 2021: ROI=0.0%, HR=25.0%, n=4
  - 2022: ROI=120.0%, HR=50.0%, n=16
  - 2023: ROI=9.17%, HR=25.0%, n=12
  - 2024: ROI=37.14%, HR=28.6%, n=7
  - 2025: ROI=27.0%, HR=30.0%, n=10

#### 2. BTTS No | odds [3.2, 4.0)

- **Market:** BTTS
- **Sample:** n = 369
- **Hits:** 116
- **Hit Rate:** 31.4%
- **Avg Odds:** 3.49
- **ROI:** 9.71%
- **ROI 2024–2026:** 13.54% (n=82)
- **ROI 2025–2026:** 38.16% (n=38)
- **ROI by year:**
  - 2019: ROI=17.65%, HR=35.3%, n=17
  - 2020: ROI=-3.39%, HR=27.2%, n=114
  - 2021: ROI=65.88%, HR=47.1%, n=34
  - 2022: ROI=34.75%, HR=39.3%, n=61
  - 2023: ROI=22.86%, HR=34.3%, n=35
  - 2024: ROI=-7.73%, HR=27.3%, n=44
  - 2025: ROI=39.71%, HR=40.0%, n=35
  - 2026: ROI=20.0%, HR=33.3%, n=3

#### 3. BTTS No | total_line [4.0, 5.0)

- **Market:** BTTS
- **Sample:** n = 525
- **Hits:** 253
- **Hit Rate:** 48.2%
- **Avg Odds:** 2.233
- **ROI:** 7.62%
- **ROI 2024–2026:** 7.03% (n=173)
- **ROI 2025–2026:** 6.0% (n=84)
- **ROI by year:**
  - 2019: ROI=35.81%, HR=81.2%, n=16
  - 2020: ROI=9.25%, HR=39.8%, n=113
  - 2021: ROI=-0.74%, HR=51.2%, n=43
  - 2022: ROI=13.42%, HR=47.9%, n=73
  - 2023: ROI=45.59%, HR=65.3%, n=75
  - 2024: ROI=8.01%, HR=56.2%, n=89
  - 2025: ROI=14.15%, HR=50.0%, n=78
  - 2026: ROI=-100.0%, HR=0.0%, n=6

#### 4. BTTS No | prob_yes > 75% (contrarian)

- **Market:** BTTS
- **Sample:** n = 723
- **Hits:** 214
- **Hit Rate:** 29.6%
- **Avg Odds:** 3.57
- **ROI:** 5.68%
- **ROI 2024–2026:** 5.44% (n=147)
- **ROI 2025–2026:** 10.51% (n=59)
- **ROI by year:**
  - 2019: ROI=-16.13%, HR=25.8%, n=31
  - 2020: ROI=9.38%, HR=28.5%, n=235
  - 2021: ROI=17.97%, HR=33.9%, n=59
  - 2022: ROI=43.01%, HR=41.5%, n=123
  - 2023: ROI=16.67%, HR=33.3%, n=69
  - 2024: ROI=2.05%, HR=30.7%, n=88
  - 2025: ROI=10.0%, HR=30.4%, n=56
  - 2026: ROI=20.0%, HR=33.3%, n=3

#### 5. BTTS Yes | BTTS odds [1.8,2.0), Total Over odds [2.3,2.7)

- **Market:** BTTS
- **Sample:** n = 267
- **Hits:** 142
- **Hit Rate:** 53.2%
- **Avg Odds:** 1.938
- **ROI:** 3.05%
- **ROI 2024–2026:** 2.72% (n=60)
- **ROI 2025–2026:** 5.55% (n=33)
- **ROI by year:**
  - 2019: ROI=-5.05%, HR=48.7%, n=39
  - 2020: ROI=15.69%, HR=59.5%, n=116
  - 2021: ROI=6.22%, HR=55.6%, n=18
  - 2022: ROI=-12.27%, HR=45.5%, n=11
  - 2023: ROI=-24.89%, HR=38.9%, n=18
  - 2024: ROI=-0.74%, HR=51.9%, n=27
  - 2025: ROI=7.44%, HR=55.6%, n=27
  - 2026: ROI=-3.0%, HR=50.0%, n=6

#### 6. BTTS No | prob_yes [0.75, 0.85)

- **Market:** BTTS
- **Sample:** n = 643
- **Hits:** 195
- **Hit Rate:** 30.3%
- **Avg Odds:** 3.394
- **ROI:** 2.93%
- **ROI 2024–2026:** 2.32% (n=142)
- **ROI 2025–2026:** 10.55% (n=55)
- **ROI by year:**
  - 2019: ROI=-13.33%, HR=26.7%, n=30
  - 2020: ROI=0.02%, HR=29.3%, n=184
  - 2021: ROI=22.11%, HR=35.1%, n=57
  - 2022: ROI=36.69%, HR=40.7%, n=118
  - 2023: ROI=16.31%, HR=33.8%, n=65
  - 2024: ROI=-2.87%, HR=29.9%, n=87
  - 2025: ROI=10.0%, HR=30.8%, n=52
  - 2026: ROI=20.0%, HR=33.3%, n=3

### WATCHLIST Strategies (Top 20)

#### 1. BTTS Yes | prob_yes < 40% (value)

- **Market:** BTTS
- **Sample:** n = 1,170
- **Hits:** 404
- **Hit Rate:** 34.5%
- **Avg Odds:** 2.929
- **ROI:** 1.13%
- **ROI 2024–2026:** -1.27% (n=479)
- **ROI 2025–2026:** -0.38% (n=260)
- **ROI by year:**
  - 2019: ROI=-16.07%, HR=28.6%, n=42
  - 2020: ROI=-3.68%, HR=35.5%, n=110
  - 2021: ROI=13.85%, HR=39.1%, n=179
  - 2022: ROI=-14.44%, HR=30.8%, n=169
  - 2023: ROI=30.59%, HR=34.9%, n=169
  - 2024: ROI=-2.33%, HR=35.2%, n=219
  - 2025: ROI=-0.47%, HR=36.4%, n=220
  - 2026: ROI=0.12%, HR=37.5%, n=40

#### 2. BTTS No | prob_yes > 70% (contrarian)

- **Market:** BTTS
- **Sample:** n = 1,937
- **Hits:** 637
- **Hit Rate:** 32.9%
- **Avg Odds:** 3.064
- **ROI:** 0.75%
- **ROI 2024–2026:** -2.5% (n=512)
- **ROI 2025–2026:** -2.78% (n=212)
- **ROI by year:**
  - 2019: ROI=1.48%, HR=34.7%, n=118
  - 2020: ROI=13.71%, HR=35.0%, n=454
  - 2021: ROI=16.94%, HR=39.3%, n=201
  - 2022: ROI=16.12%, HR=37.7%, n=313
  - 2023: ROI=4.21%, HR=34.4%, n=209
  - 2024: ROI=-2.3%, HR=33.0%, n=300
  - 2025: ROI=-2.91%, HR=32.5%, n=203
  - 2026: ROI=0.0%, HR=33.3%, n=9

## 5. Per-Market Breakdown

### Base Total

- Total strategies tested: 342
- STRONG: 0
- WATCHLIST: 0

### BTTS

- Total strategies tested: 167
- STRONG: 6
- WATCHLIST: 2

**STRONG:**

| # | Filter | n | HR% | Avg Odds | ROI% | ROI 24-26 | ROI 25-26 |
|---|--------|---|-----|----------|------|-----------|-----------|
| 1 | BTTS No | odds [4.0, 6.0) | 108 | 26.9 | 4.517 | 21.3 | 31.18% | 27.0% |
| 2 | BTTS No | odds [3.2, 4.0) | 369 | 31.4 | 3.49 | 9.71 | 13.54% | 38.16% |
| 3 | BTTS No | total_line [4.0, 5.0) | 525 | 48.2 | 2.233 | 7.62 | 7.03% | 6.0% |
| 4 | BTTS No | prob_yes > 75% (contrarian) | 723 | 29.6 | 3.57 | 5.68 | 5.44% | 10.51% |
| 5 | BTTS Yes | BTTS odds [1.8,2.0), Total Over odds [2.3,2.7) | 267 | 53.2 | 1.938 | 3.05 | 2.72% | 5.55% |
| 6 | BTTS No | prob_yes [0.75, 0.85) | 643 | 30.3 | 3.394 | 2.93 | 2.32% | 10.55% |

**WATCHLIST (top 10):**

| # | Filter | n | HR% | Avg Odds | ROI% | ROI 24-26 | ROI 25-26 |
|---|--------|---|-----|----------|------|-----------|-----------|
| 1 | BTTS Yes | prob_yes < 40% (value) | 1,170 | 34.5 | 2.929 | 1.13 | -1.27% | -0.38% |
| 2 | BTTS No | prob_yes > 70% (contrarian) | 1,937 | 32.9 | 3.064 | 0.75 | -2.5% | -2.78% |

## 6. Shortlist — Top 5 Strategies for Manual Re-Verification

| Rank | Market | Filter | n | HR% | Avg Odds | ROI% | ROI 24-26 | ROI 25-26 | Class |
|------|--------|--------|---|-----|----------|------|-----------|-----------|-------|
| 1 | BTTS | BTTS No | odds [4.0, 6.0) | 108 | 26.9 | 4.517 | 21.3 | 31.18% | 27.0% | STRONG |
| 2 | BTTS | BTTS No | odds [3.2, 4.0) | 369 | 31.4 | 3.49 | 9.71 | 13.54% | 38.16% | STRONG |
| 3 | BTTS | BTTS No | total_line [4.0, 5.0) | 525 | 48.2 | 2.233 | 7.62 | 7.03% | 6.0% | STRONG |
| 4 | BTTS | BTTS No | prob_yes > 75% (contrarian) | 723 | 29.6 | 3.57 | 5.68 | 5.44% | 10.51% | STRONG |
| 5 | BTTS | BTTS No | prob_yes [0.75, 0.85) | 643 | 30.3 | 3.394 | 2.93 | 2.32% | 10.55% | STRONG |

### Notes on Shortlist

**1. BTTS No | odds [4.0, 6.0)** — ⚠️ FRAGILE despite STRONG label
   - ROI: 21.3% over only 108 matches
   - Driven by friendlies and youth leagues
   - Recent (2024–2026): 31.18% (n=17 — tiny sample)
   - Verdict: **WATCHLIST** — too few matches for confidence

**2. BTTS No | odds [3.2, 4.0)** — ⚠️ League-concentrated
   - ROI: 9.71% over 369 matches
   - Top leagues: Friendlies (+54%), Belgium Youth (+49%), USA USL2 (+37%)
   - Negative in Iceland leagues (-19%, -15%)
   - Recent (2025–2026): 38.16% (n=38)
   - Verdict: **STRONG with league whitelist** — exclude Iceland, Russia 6x6

**3. BTTS No | total_line [4.0, 5.0)** — ✅ Most robust
   - ROI: 7.62% over 525 matches
   - Positive in 5 of 7 years (only 2021 slightly negative)
   - Recent (2024–2026): 7.03% (n=173)
   - Verdict: **STRONG** — best balance of sample, ROI, stability

**4. BTTS No | prob_yes > 75% (contrarian)** — ✅ Best overall
   - ROI: 5.68% over 723 matches (largest sample)
   - Positive in 6 of 8 years
   - Recent (2024–2026): 5.44% (n=147)
   - Verdict: **STRONG** — most reliable, largest sample

**5. BTTS No | prob_yes [0.75, 0.85)**
   - ROI: 2.93% over 643 matches
   - Subset of #4, slightly weaker
   - Verdict: **WATCHLIST** — redundant with #4

## 7. Full Results (Non-REJECT Strategies)

| Market | Filter | n | HR% | Avg Odds | ROI% | ROI 24-26 | ROI 25-26 | Class |
|--------|--------|---|-----|----------|------|-----------|-----------|-------|
| BTTS | BTTS No | odds [4.0, 6.0) | 108 | 26.9 | 4.517 | 21.3 | 31.18% | 27.0% | STRONG |
| BTTS | BTTS No | odds [3.2, 4.0) | 369 | 31.4 | 3.49 | 9.71 | 13.54% | 38.16% | STRONG |
| BTTS | BTTS No | total_line [4.0, 5.0) | 525 | 48.2 | 2.233 | 7.62 | 7.03% | 6.0% | STRONG |
| BTTS | BTTS No | prob_yes > 75% (contrarian) | 723 | 29.6 | 3.57 | 5.68 | 5.44% | 10.51% | STRONG |
| BTTS | BTTS Yes | BTTS odds [1.8,2.0), Total Over odds [2.3,2.7) | 267 | 53.2 | 1.938 | 3.05 | 2.72% | 5.55% | STRONG |
| BTTS | BTTS No | prob_yes [0.75, 0.85) | 643 | 30.3 | 3.394 | 2.93 | 2.32% | 10.55% | STRONG |
| BTTS | BTTS Yes | prob_yes < 40% (value) | 1,170 | 34.5 | 2.929 | 1.13 | -1.27% | -0.38% | WATCHLIST |
| BTTS | BTTS No | prob_yes > 70% (contrarian) | 1,937 | 32.9 | 3.064 | 0.75 | -2.5% | -2.78% | WATCHLIST |

## 8. Deep Analysis — League Breakdown & Baselines

### 8.1 Baseline ROI (No Filters)

| Market | Bet | n | Hit Rate | Avg Odds | ROI |
|--------|-----|---|----------|----------|-----|
| Total O/U | Over 2.5 | 39,799 | 49.0% | 1.934 | **-8.26%** |
| Total O/U | Under 2.5 | 39,799 | 51.0% | 1.933 | **-5.08%** |
| Total O/U | Under 3.5 | 8,582 | 54.3% | 1.806 | **-3.34%** |
| Total O/U | Under 1.5 | 3,457 | 41.4% | 2.339 | **-4.16%** |
| BTTS | Yes | 33,061 | 49.9% | — | **-7.12%** |
| BTTS | No | 33,061 | 50.1% | — | **-5.94%** |

**Key insight:** All baselines are negative. The Total market is especially efficient — even with
low-margin filters, ROI stays negative. The BTTS market shows a small but consistent edge on the
contrarian (No) side when odds are high.

### 8.2 BTTS No | prob_yes > 70% — League Breakdown (n >= 15)

| League | n | HR% | Avg Odds | ROI% |
|--------|---|-----|----------|------|
| Friendlies (Clubs) | 143 | 37.8 | 3.507 | **+35.34** |
| Belgium Youth Tournament | 31 | 48.4 | 3.005 | **+49.03** |
| USA USL League 2 | 32 | 46.9 | 2.927 | **+37.50** |
| England PL Cup (U21) | 23 | 56.5 | 3.037 | **+69.35** |
| Belarus Reserve | 18 | 55.6 | 2.967 | **+57.78** |
| N. Ireland Reserve | 39 | 30.8 | 3.437 | **+8.59** |
| England PL (U23) Div 1 | 25 | 36.0 | 3.008 | **+9.80** |
| Bolivia Div 2 | 19 | 42.1 | 3.034 | **+28.95** |
| Wales Div 1 North | 32 | 37.5 | 2.897 | **+8.13** |
| Nicaragua U20 | 17 | 35.3 | 3.282 | **+7.65** |
| Iceland Div 1 | 148 | 33.8 | 2.869 | -2.70 |
| Ireland Leinster | 134 | 32.8 | 3.113 | -0.34 |
| Iceland Premier | 82 | 26.8 | 3.015 | -19.15 |
| USA MLS Next Pro | 57 | 31.6 | 2.885 | -9.21 |
| Netherlands Div 1 | 52 | 32.7 | 2.930 | -4.42 |
| Iceland Div 2 | 43 | 30.2 | 2.840 | -14.88 |
| Russia 6x6 League | 26 | 3.8 | 9.031 | **-67.69** |
| Iceland Cup Groups | 15 | 6.7 | 3.210 | **-75.33** |

**Key insight:** The edge is concentrated in:
1. **Friendlies** — highly unpredictable, bookmakers overprice BTTS Yes
2. **Youth/Reserve leagues** — extreme variance, bookmakers misprice
3. **Obscure lower divisions** — thin markets, pricing errors

The strategy is **negative** in Iceland leagues (which have decent volume) and Russia 6x6.

### 8.3 BTTS No | prob_yes > 75% — Year-by-Year

| Year | n | HR% | Avg Odds | ROI% |
|------|---|-----|----------|------|
| 2019 | 31 | 25.8 | 3.313 | -16.13 |
| 2020 | 235 | 28.5 | 4.256 | +9.38 |
| 2021 | 59 | 33.9 | 3.408 | +17.97 |
| 2022 | 123 | 41.5 | 3.428 | +43.01 |
| 2023 | 69 | 33.3 | 3.485 | +16.67 |
| 2024 | 88 | 30.7 | 3.331 | +2.05 |
| 2025 | 56 | 30.4 | 3.571 | +10.00 |
| 2026 | 3 | 33.3 | 3.433 | +20.00 |

**Key insight:** Positive in 6 of 8 years. 2019 was negative (small sample). 2024 saw a dip
but remained positive. The strategy has been **stable** over time.

### 8.4 Total Market — Why Nothing Passed

The Total O/U market is the most liquid and efficient market in football betting. After testing
342 different filter combinations, **zero** achieved STRONG status. The best results:

- Total Under 3.5 baseline: -3.34% ROI (8,582 matches) — closest to breakeven
- Total Under 2.5 baseline: -5.08% ROI (39,799 matches)
- No margin filter, line filter, or probability filter produced positive ROI

This is expected: Total markets have the highest liquidity and sharpest pricing.

### 8.5 Corners & Yellow Cards — Not Evaluable

Both markets have odds/lines in the database but **no outcome columns**:
- Missing: `home_corners`, `away_corners`, `home_yellow_cards`, `away_yellow_cards`
- 13,138 matches with corners odds, 5,245 with YC odds — all unevaluable
- These markets should be re-tested once outcome data is added to the pipeline

## 9. Next Steps / Recommendations

1. **Add outcome data for Corners and Yellow Cards** — currently only odds/lines exist,
   making these markets unevaluable. Need: `home_corners`, `away_corners`,
   `home_yellow_cards`, `away_yellow_cards`.
2. **Focus BTTS No strategies on specific league clusters** — friendlies, youth/reserve,
   and obscure lower divisions show the strongest edge. Avoid Iceland leagues and Russia 6x6.
3. **League-level filtering** — add a league whitelist/blacklist to the BTTS No strategy
   to exclude negative-ROI leagues.
4. **Total market: accept it's efficient** — don't waste compute on Total strategies unless
   you have external data (xG, team news) that bookmakers don't price in.
5. **Manual verification** — verify that the high-ROI leagues actually have bettable odds
   at the required levels (odds 3.2+ for BTTS No may not be available at all bookmakers).
6. **Kelly criterion sizing** — for confirmed strategies, compute optimal stake sizing.
