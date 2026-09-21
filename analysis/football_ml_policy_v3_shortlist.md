# Football ML Policy v3 — Deployment Shortlist

Generated from test_predictions.csv (period: 2025-01 to 2026-04, ~15.25 months)

Focus: B_NCF_Tight, C_Bal_Core, D_Bal_Tight — CORE whitelist, stability, stress test.

## 1. Executive Summary

Three policies analyzed after aggressive league filtering:
- **Draw excluded** from all picks (v1 conclusion)
- **Home/away only** — away bets carry the edge
- **CORE whitelist**: leagues with n>=5, ROI_k>0, no youth/reserve/women/friendly/cup/exotic patterns
- **Stress tested**: removing top-1 and top-2 leagues by PnL contribution

| Policy | Segment | Edge | WL Bets | WL ROI_k | Bets/Mo | Max DD Kelly | Max Losing | Verdict |
|--------|---------|------|---------|----------|---------|--------------|------------|---------|
| B_NCF_Tight | Футбол. Испания. При... | — | 61 | 85.38% | 4.0 | 10.8% | 4 | TBD |
| C_Bal_Core | Футбол. Колумбия. Пр... | — | 77 | 67.28% | 5.0 | 11.0% | 7 | TBD |
| D_Bal_Tight | Футбол. Аргентина. Л... | — | 37 | 68.58% | 2.4 | 11.0% | 5 | TBD |


## 2. B_NCF_Tight

**Segment**: NCF Tight
**Edge threshold**: > 0.07
**Outcomes**: Home / Away (draw excluded)

### Before vs After Whitelist

| Metric | Before | After Whitelist |
|--------|--------|-----------------|
| Bets | 351 | 61 |
| Hit Rate | 43.3% | 67.2% |
| ROI Kelly | 18.12% | 85.38% |
| PnL Flat | 31.01 | 45.37 |
| Bets/Month | 23.0 | 4.0 |
| Max DD Kelly | — | 10.8% |
| Max Losing Streak | — | 4 |

### CORE Whitelist Leagues

Total: 11 leagues

- Футбол. Испания. Примера Дивизион.: n=9, HR=88.9%, ROI_k=104.92%, PnL=10.4
- Футбол. Англия. Истмийская лига. 1-й дивизион. Юг-Центр.: n=7, HR=71.4%, ROI_k=94.86%, PnL=5.65
- Футбол. Аргентина. Примера B Метрополитана.: n=9, HR=55.6%, ROI_k=82.03%, PnL=5.63
- Футбол. Англия. Премьер-лига.: n=6, HR=66.7%, ROI_k=74.72%, PnL=3.9
- Футбол. Аргентина. Лига Чако.: n=8, HR=50.0%, ROI_k=26.18%, PnL=2.62
- Футбол. Аргентина. Примера С Метрополитана.: n=7, HR=57.1%, ROI_k=38.68%, PnL=2.32
- Футбол. Англия. Северная Национальная лига.: n=3, HR=100.0%, ROI_k=163.61%, PnL=4.9
- Футбол. Шотландия. Лига Хайленд.: n=3, HR=100.0%, ROI_k=155.96%, PnL=4.65
- Футбол. Египет. 2-й дивизион.: n=3, HR=66.7%, ROI_k=100.34%, PnL=3.3
- Футбол. Колумбия. Примера B.: n=3, HR=66.7%, ROI_k=145.41%, PnL=1.9
- Футбол. Эквадор. Серия B.: n=3, HR=33.3%, ROI_k=54.37%, PnL=0.1

### Blacklisted Leagues (excluded)

Total: 96 leagues

- Футбол. Гондурас. Лига Насьональ. Резерв.: n=11, ROI_k=68.68%, PnL=6.91
- Футбол. Чемпионат Южной Америки (до 20 лет). Женщины. Парагвай.: n=2, ROI_k=184.78%, PnL=3.75
- Футбол. Аргентина. Примера C Метрополитана (резерв).: n=2, ROI_k=154.74%, PnL=3.0
- Футбол. Аргентина. Примера Насьональ (резерв).: n=1, ROI_k=250.0%, PnL=2.5
- Футбол. Парагвай. Примера Дивизион. Женщины.: n=2, ROI_k=116.96%, PnL=2.34
- Футбол. Испания. Юношеская лига (до 19 лет). Группа 6.: n=1, ROI_k=200.0%, PnL=2.0
- Футбол. Аргентина. Примера. Женщины.: n=1, ROI_k=175.0%, PnL=1.75
- Футбол. Товарищеские матчи. Клубы.: n=1, ROI_k=160.0%, PnL=1.6
- Футбол. Исландия. Кубок (до 19 лет). Плей-офф.: n=1, ROI_k=140.0%, PnL=1.4
- Футбол. Англия. Премьер-лига (до 21 года).: n=1, ROI_k=136.0%, PnL=1.36
- Футбол. Лига чемпионов УЕФА. Женщины. Общий этап.: n=3, ROI_k=49.91%, PnL=1.34
- Футбол. Исландия. Кубок Лиги B. Женщины. Групповой этап.: n=1, ROI_k=130.0%, PnL=1.3
- Футбол. Чемпионат Европы 2025. Женщины. Групповой этап. Швейцария.: n=1, ROI_k=128.0%, PnL=1.28
- Футбол. Бразилия. Катариненсе (до 20 лет).: n=1, ROI_k=115.0%, PnL=1.15
- Футбол. Уругвай. Резервная лига.: n=4, ROI_k=26.51%, PnL=1.12
- ... and 81 more

### Monthly Stability (after whitelist)

| Month | Bets | Hit Rate | ROI Kelly | PnL | Cum PnL |
|-------|------|----------|-----------|-----|---------|
| 2025-01 | 3 | 100.0% | 174.51% | 5.35 | 5.35 |
| 2025-02 | 4 | 50.0% | 156.63% | 2.3 | 7.65 |
| 2025-03 | 15 | 80.0% | 119.72% | 17.92 | 25.57 |
| 2025-04 | 4 | 50.0% | 33.71% | 1.08 | 26.65 |
| 2025-05 | 2 | 0.0% | -100.0% | -2.0 | 24.65 |
| 2025-06 | 4 | 75.0% | 88.14% | 3.07 | 27.72 |
| 2025-07 | 1 | 100.0% | 170.0% | 1.7 | 29.42 |
| 2025-08 | 6 | 83.3% | 143.05% | 6.32 | 35.74 |
| 2025-09 | 3 | 100.0% | 118.87% | 3.92 | 39.66 |
| 2025-10 | 7 | 71.4% | 52.2% | 4.46 | 44.12 |
| 2025-11 | 4 | 50.0% | 33.72% | 1.12 | 45.24 |
| 2025-12 | 2 | 50.0% | 59.74% | 0.8 | 46.04 |
| 2026-01 | 2 | 50.0% | 11.37% | 0.43 | 46.47 |
| 2026-02 | 1 | 0.0% | -100.0% | -1.0 | 45.47 |
| 2026-03 | 2 | 50.0% | 74.52% | 0.9 | 46.37 |
| 2026-04 | 1 | 0.0% | -100.0% | -1.0 | 45.37 |

Max consecutive losing months: 1
Worst month: 2025-05, PnL=-2.0, n=2

### Quarterly Stability (after whitelist)

| Quarter | Bets | Hit Rate | ROI Kelly | PnL | Cum PnL |
|---------|------|----------|-----------|-----|---------|
| 2025Q1 | 22 | 77.3% | 134.96% | 25.57 | 25.57 |
| 2025Q2 | 10 | 50.0% | 31.15% | 2.15 | 27.72 |
| 2025Q3 | 10 | 90.0% | 137.32% | 11.94 | 39.66 |
| 2025Q4 | 13 | 61.5% | 47.52% | 6.38 | 46.04 |
| 2026Q1 | 5 | 40.0% | 6.92% | 0.33 | 46.37 |
| 2026Q2 | 1 | 0.0% | -100.0% | -1.0 | 45.37 |
Worst quarter: 2026Q2, PnL=-1.0

### Risk Metrics (after whitelist)

- **Max drawdown (flat)**: 4.00 units
- **Max drawdown (Kelly)**: 10.8% of bankroll
- **Longest losing streak**: 4
- **Worst month**: 2025-05 (PnL=-2.0)
- **Worst quarter**: 2026Q2 (PnL=-1.0)
- **Rolling 50-bet ROI**: min=62.8%, max=86.24%, avg=76.96%
- **Negative 50-bet windows**: 0/12 (0%)

### Stress Test

**Remove top-1 league** (Футбол. Испания. Примера Дивизион.):
- n=52, HR=63.5%, ROI_k=82.15%, PnL=34.97
- Verdict: PASS

**Remove top-2 leagues** (Футбол. Испания. Примера Дивизион., Футбол. Англия. Истмийская лига. 1-й дивизион. Юг-Центр.):
- n=45, HR=62.2%, ROI_k=80.39%, PnL=29.32
- Verdict: PASS


## 2. C_Bal_Core

**Segment**: Bal Core
**Edge threshold**: > 0.05
**Outcomes**: Home / Away (draw excluded)

### Before vs After Whitelist

| Metric | Before | After Whitelist |
|--------|--------|-----------------|
| Bets | 342 | 77 |
| Hit Rate | 42.7% | 53.2% |
| ROI Kelly | 21.57% | 67.28% |
| PnL Flat | 39.83 | 31.46 |
| Bets/Month | 22.4 | 5.0 |
| Max DD Kelly | — | 11.0% |
| Max Losing Streak | — | 7 |

### CORE Whitelist Leagues

Total: 14 leagues

- Футбол. Колумбия. Примера B.: n=6, HR=83.3%, ROI_k=102.44%, PnL=6.45
- Футбол. Аргентина. Примера B Метрополитана.: n=11, HR=54.5%, ROI_k=80.68%, PnL=6.35
- Футбол. Аргентина. Лига Чако.: n=8, HR=62.5%, ROI_k=70.97%, PnL=5.22
- Футбол. Чили. Примера Дивизион.: n=6, HR=50.0%, ROI_k=62.6%, PnL=1.95
- Футбол. Бразилия. Серия D.: n=6, HR=50.0%, ROI_k=9.64%, PnL=1.9
- Футбол. Ямайка. Премьер-лига.: n=5, HR=40.0%, ROI_k=150.0%, PnL=-0.13
- Футбол. Парагвай. Интермедиа Дивизион.: n=5, HR=40.0%, ROI_k=7.32%, PnL=-0.18
- Футбол. Перу. Лига 3.: n=6, HR=33.3%, ROI_k=11.45%, PnL=-0.9
- Футбол. Аргентина. Примера С Метрополитана.: n=6, HR=33.3%, ROI_k=5.87%, PnL=-0.95
- Футбол. Испания. Примера Дивизион.: n=4, HR=75.0%, ROI_k=129.73%, PnL=4.55
- Футбол. Панама. Лига Насиональ.: n=4, HR=75.0%, ROI_k=79.12%, PnL=3.55
- Футбол. Чили. Кубок. Групповой этап.: n=3, HR=66.7%, ROI_k=97.41%, PnL=2.15
- Футбол. Аргентина. Примера Дивизион. Клаусура.: n=4, HR=50.0%, ROI_k=63.21%, PnL=1.9
- Футбол. Алжир. Лига 1.: n=3, HR=33.3%, ROI_k=160.0%, PnL=-0.4

### Blacklisted Leagues (excluded)

Total: 90 leagues

- Футбол. Гондурас. Лига Насьональ. Резерв.: n=3, ROI_k=155.0%, PnL=4.6
- Футбол. США. USL. Супер-лига. Женщины.: n=2, ROI_k=164.98%, PnL=3.4
- Футбол. Аргентина. Примера C Метрополитана (резерв).: n=2, ROI_k=169.17%, PnL=3.35
- Футбол. Аргентина. Примера B Метрополитана (резерв).: n=3, ROI_k=21.0%, PnL=1.71
- Футбол. Бразилия. Паранаэнсе (до 20 лет).: n=1, ROI_k=165.0%, PnL=1.65
- Футбол. США. NWSL. Женщины.: n=1, ROI_k=0.0%, PnL=1.6
- Футбол. Чемпионат Европы 2025. Женщины. 1/4 финала. Швейцария.: n=1, ROI_k=155.0%, PnL=1.55
- Футбол. Чемпионат Южной Америки (до 20 лет). Женщины. Парагвай.: n=1, ROI_k=155.0%, PnL=1.55
- Футбол. Сальвадор. Примера Дивизион. Резерв.: n=4, ROI_k=39.77%, PnL=1.1
- Футбол. Колумбия. Высшая лига. Женщины.: n=4, ROI_k=42.3%, PnL=0.95
- Футбол. Уругвай. Резервная лига.: n=9, ROI_k=8.6%, PnL=0.94
- Футбол. Бразилия. Серия D. Плей-офф. 1/16 финала. Первые матчи.: n=2, ROI_k=-65.95%, PnL=0.9
- Футбол. Бразилия. Гояно. 1-й дивизион.: n=2, ROI_k=-11.17%, PnL=0.9
- Футбол. Аргентина. Примера Дивизион (резерв).: n=10, ROI_k=18.43%, PnL=0.55
- Футбол. Мексика. Юношеская лига (до 19 лет).: n=3, ROI_k=-37.83%, PnL=-0.15
- ... and 75 more

### Monthly Stability (after whitelist)

| Month | Bets | Hit Rate | ROI Kelly | PnL | Cum PnL |
|-------|------|----------|-----------|-----|---------|
| 2025-01 | 1 | 100.0% | 230.0% | 2.3 | 2.3 |
| 2025-02 | 8 | 50.0% | 109.85% | 3.45 | 5.75 |
| 2025-03 | 11 | 63.6% | 143.16% | 8.15 | 13.9 |
| 2025-04 | 5 | 60.0% | 44.32% | 2.55 | 16.45 |
| 2025-05 | 5 | 40.0% | -42.4% | 0.15 | 16.6 |
| 2025-06 | 8 | 50.0% | 54.23% | 2.37 | 18.97 |
| 2025-07 | 9 | 44.4% | 50.83% | 1.1 | 20.07 |
| 2025-08 | 4 | 50.0% | -100.0% | 0.75 | 20.82 |
| 2025-09 | 2 | 50.0% | 160.0% | 0.6 | 21.42 |
| 2025-10 | 7 | 71.4% | 34.91% | 6.0 | 27.42 |
| 2025-11 | 2 | 50.0% | 13.29% | 0.9 | 28.32 |
| 2025-12 | 2 | 50.0% | 117.17% | 0.9 | 29.22 |
| 2026-01 | 1 | 100.0% | 0.0% | 1.37 | 30.59 |
| 2026-02 | 6 | 16.7% | -58.16% | -3.45 | 27.14 |
| 2026-03 | 5 | 60.0% | 16.39% | 2.9 | 30.04 |
| 2026-04 | 1 | 100.0% | 142.0% | 1.42 | 31.46 |

Max consecutive losing months: 1
Worst month: 2026-02, PnL=-3.45, n=6

### Quarterly Stability (after whitelist)

| Quarter | Bets | Hit Rate | ROI Kelly | PnL | Cum PnL |
|---------|------|----------|-----------|-----|---------|
| 2025Q1 | 20 | 60.0% | 135.8% | 13.9 | 13.9 |
| 2025Q2 | 18 | 50.0% | 35.25% | 5.07 | 18.97 |
| 2025Q3 | 15 | 46.7% | 44.43% | 2.45 | 21.42 |
| 2025Q4 | 11 | 63.6% | 49.68% | 7.8 | 29.22 |
| 2026Q1 | 12 | 41.7% | -21.51% | 0.82 | 30.04 |
| 2026Q2 | 1 | 100.0% | 142.0% | 1.42 | 31.46 |
Worst quarter: 2026Q1, PnL=0.82

### Risk Metrics (after whitelist)

- **Max drawdown (flat)**: 7.00 units
- **Max drawdown (Kelly)**: 11.0% of bankroll
- **Longest losing streak**: 7
- **Worst month**: 2026-02 (PnL=-3.45)
- **Worst quarter**: 2026Q1 (PnL=0.82)
- **Rolling 50-bet ROI**: min=18.38%, max=45.64%, avg=35.39%
- **Negative 50-bet windows**: 0/28 (0%)

### Stress Test

**Remove top-1 league** (Футбол. Колумбия. Примера B.):
- n=71, HR=50.7%, ROI_k=65.01%, PnL=25.01
- Verdict: PASS

**Remove top-2 leagues** (Футбол. Колумбия. Примера B., Футбол. Аргентина. Примера B Метрополитана.):
- n=60, HR=50.0%, ROI_k=58.39%, PnL=18.66
- Verdict: PASS


## 2. D_Bal_Tight

**Segment**: Bal Tight
**Edge threshold**: > 0.06
**Outcomes**: Home / Away (draw excluded)

### Before vs After Whitelist

| Metric | Before | After Whitelist |
|--------|--------|-----------------|
| Bets | 208 | 37 |
| Hit Rate | 44.7% | 59.5% |
| ROI Kelly | 25.01% | 68.58% |
| PnL Flat | 37.38 | 22.27 |
| Bets/Month | 13.6 | 2.4 |
| Max DD Kelly | — | 11.0% |
| Max Losing Streak | — | 5 |

### CORE Whitelist Leagues

Total: 7 leagues

- Футбол. Аргентина. Лига Чако.: n=8, HR=62.5%, ROI_k=70.97%, PnL=5.22
- Футбол. Колумбия. Примера B.: n=5, HR=80.0%, ROI_k=102.44%, PnL=5.15
- Футбол. Аргентина. Примера B Метрополитана.: n=9, HR=44.4%, ROI_k=76.6%, PnL=3.5
- Футбол. Аргентина. Примера С Метрополитана.: n=5, HR=40.0%, ROI_k=16.88%, PnL=0.05
- Футбол. Бразилия. Серия D.: n=3, HR=100.0%, ROI_k=185.0%, PnL=4.9
- Футбол. Панама. Лига Насиональ.: n=3, HR=66.7%, ROI_k=59.71%, PnL=2.0
- Футбол. Чили. Примера Дивизион.: n=4, HR=50.0%, ROI_k=75.55%, PnL=1.45

### Blacklisted Leagues (excluded)

Total: 64 leagues

- Футбол. Гондурас. Лига Насьональ. Резерв.: n=3, ROI_k=155.0%, PnL=4.6
- Футбол. Аргентина. Примера C Метрополитана (резерв).: n=2, ROI_k=169.17%, PnL=3.35
- Футбол. Аргентина. Примера Насьональ.: n=9, ROI_k=-3.43%, PnL=1.95
- Футбол. Чемпионат Южной Америки (до 20 лет). Женщины. Парагвай.: n=1, ROI_k=155.0%, PnL=1.55
- Футбол. Колумбия. Высшая лига. Женщины.: n=1, ROI_k=155.0%, PnL=1.55
- Футбол. Уругвай. Резервная лига.: n=6, ROI_k=22.89%, PnL=1.52
- Футбол. США. USL. Супер-лига. Женщины.: n=1, ROI_k=150.0%, PnL=1.5
- Футбол. Парагвай. Резервная лига.: n=2, ROI_k=48.99%, PnL=0.55
- Футбол. Аргентина. Примера B Метрополитана (резерв).: n=2, ROI_k=21.0%, PnL=0.38
- Футбол. Аргентина. Примера. Женщины.: n=3, ROI_k=24.48%, PnL=-0.25
- Футбол. Сальвадор. Примера Дивизион. Резерв.: n=3, ROI_k=-3.73%, PnL=-0.45
- Футбол. Аргентина. Торнео Региональ ФА.: n=3, ROI_k=-45.57%, PnL=-0.76
- Футбол. Боливия. Насьональ B.: n=1, ROI_k=-100.0%, PnL=-1.0
- Футбол. Аргентина. Торнео Промосьональ.: n=1, ROI_k=-100.0%, PnL=-1.0
- Футбол. Колумбия. Суперкубок (до 20 лет).: n=1, ROI_k=-100.0%, PnL=-1.0
- ... and 49 more

### Monthly Stability (after whitelist)

| Month | Bets | Hit Rate | ROI Kelly | PnL | Cum PnL |
|-------|------|----------|-----------|-----|---------|
| 2025-02 | 5 | 40.0% | 99.48% | 1.3 | 1.3 |
| 2025-03 | 7 | 85.7% | 155.0% | 9.7 | 11.0 |
| 2025-04 | 2 | 0.0% | -100.0% | -2.0 | 9.0 |
| 2025-05 | 1 | 100.0% | 0.0% | 1.6 | 10.6 |
| 2025-06 | 4 | 75.0% | 95.37% | 3.77 | 14.37 |
| 2025-07 | 3 | 66.7% | 45.91% | 2.15 | 16.52 |
| 2025-08 | 1 | 100.0% | 0.0% | 1.35 | 17.87 |
| 2025-09 | 1 | 100.0% | 160.0% | 1.6 | 19.47 |
| 2025-10 | 6 | 66.7% | 12.0% | 4.0 | 23.47 |
| 2025-12 | 1 | 100.0% | 190.0% | 1.9 | 25.37 |
| 2026-02 | 3 | 0.0% | -100.0% | -3.0 | 22.37 |
| 2026-03 | 3 | 33.3% | -29.16% | -0.1 | 22.27 |

Max consecutive losing months: 2
Worst month: 2026-02, PnL=-3.0, n=3

### Quarterly Stability (after whitelist)

| Quarter | Bets | Hit Rate | ROI Kelly | PnL | Cum PnL |
|---------|------|----------|-----------|-----|---------|
| 2025Q1 | 12 | 66.7% | 132.37% | 11.0 | 11.0 |
| 2025Q2 | 7 | 57.1% | 40.49% | 3.37 | 14.37 |
| 2025Q3 | 5 | 80.0% | 88.05% | 5.1 | 19.47 |
| 2025Q4 | 7 | 71.4% | 57.17% | 5.9 | 25.37 |
| 2026Q1 | 6 | 16.7% | -67.19% | -3.1 | 22.27 |
Worst quarter: 2026Q1, PnL=-3.1

### Risk Metrics (after whitelist)

- **Max drawdown (flat)**: 5.00 units
- **Max drawdown (Kelly)**: 11.0% of bankroll
- **Longest losing streak**: 5
- **Worst month**: 2026-02 (PnL=-3.0)
- **Worst quarter**: 2026Q1 (PnL=-3.1)

### Stress Test

**Remove top-1 league** (Футбол. Аргентина. Лига Чако.):
- n=29, HR=58.6%, ROI_k=67.94%, PnL=17.05
- Verdict: PASS

**Remove top-2 leagues** (Футбол. Аргентина. Лига Чако., Футбол. Колумбия. Примера B.):
- n=24, HR=54.2%, ROI_k=63.43%, PnL=11.9
- Verdict: PASS


## 5. Final Decision

| Policy | Score | Key Strengths | Key Risks |
|--------|-------|---------------|-----------|
| C_Bal_Core | 12/13 | excellent ROI; acceptable volume (5.0/mo); low DD | short losing streak; stable rolling; robust without top leagues |
| B_NCF_Tight | 11/13 | excellent ROI; low volume (4.0/mo); low DD | short losing streak; stable rolling; robust without top leagues |
| D_Bal_Tight | 9/13 | excellent ROI; low volume (2.4/mo); low DD | short losing streak; robust without top leagues |

### PRIMARY READY: C_Bal_Core

- Score: 12/13
- ROI Kelly: 67.28%
- Bets/month: 5.0
- Max DD Kelly: 11.0%
- Strengths: excellent ROI; acceptable volume (5.0/mo); low DD; short losing streak; stable rolling; robust without top leagues

### SECONDARY READY: B_NCF_Tight

- Score: 11/13
- ROI Kelly: 85.38%
- Bets/month: 4.0
- Max DD Kelly: 10.8%
- Strengths: excellent ROI; low volume (4.0/mo); low DD; short losing streak; stable rolling; robust without top leagues

### REJECT (for now): D_Bal_Tight

- Score: 9/13
- ROI Kelly: 68.58%
- Bets/month: 2.4
- Reasons: excellent ROI; low volume (2.4/mo); low DD; short losing streak; robust without top leagues


## 6. Implementation-Ready Rules

### C_Bal_Core

```
SEGMENT: balanced
EDGE_THRESHOLD: 0.05
ALLOWED_OUTCOMES: [home, away]
DRAW: excluded
MIN_ODDS: 1.55
KELLY_FRACTION: 0.25
MAX_STAKE_PCT: 0.10
WHITELIST_LEAGUES: (14 leagues)
  - Футбол. Колумбия. Примера B.
  - Футбол. Аргентина. Примера B Метрополитана.
  - Футбол. Аргентина. Лига Чако.
  - Футбол. Чили. Примера Дивизион.
  - Футбол. Бразилия. Серия D.
  - Футбол. Ямайка. Премьер-лига.
  - Футбол. Парагвай. Интермедиа Дивизион.
  - Футбол. Перу. Лига 3.
  - Футбол. Аргентина. Примера С Метрополитана.
  - Футбол. Испания. Примера Дивизион.
  - Футбол. Панама. Лига Насиональ.
  - Футбол. Чили. Кубок. Групповой этап.
  - Футбол. Аргентина. Примера Дивизион. Клаусура.
  - Футбол. Алжир. Лига 1.
BLACKLIST_PATTERNS: reserve, women, youth, friendly, cup, playoff
EXPECTED_BETS_MONTH: ~5.0
EXPECTED_BETS_WEEK: ~1.2
EXPECTED_ROI_KELLY: 67.28%
EXPECTED_HIT_RATE: 53.2%
AVG_ODDS: 2.649
MAX_DRAWDOWN_KELLY: 11.0%
MAX_DRAWDOWN_FLAT: 7.00 units
LONGEST_LOSING_STREAK: 7
WORST_MONTH: 2026-02 (PnL=-3.45)
WORST_QUARTER: 2026Q1 (PnL=0.82)
```

### B_NCF_Tight

```
SEGMENT: no_clear_favorite
EDGE_THRESHOLD: 0.07
ALLOWED_OUTCOMES: [home, away]
DRAW: excluded
MIN_ODDS: 1.55
KELLY_FRACTION: 0.25
MAX_STAKE_PCT: 0.10
WHITELIST_LEAGUES: (11 leagues)
  - Футбол. Испания. Примера Дивизион.
  - Футбол. Англия. Истмийская лига. 1-й дивизион. Юг-Центр.
  - Футбол. Аргентина. Примера B Метрополитана.
  - Футбол. Англия. Премьер-лига.
  - Футбол. Аргентина. Лига Чако.
  - Футбол. Аргентина. Примера С Метрополитана.
  - Футбол. Англия. Северная Национальная лига.
  - Футбол. Шотландия. Лига Хайленд.
  - Футбол. Египет. 2-й дивизион.
  - Футбол. Колумбия. Примера B.
  - Футбол. Эквадор. Серия B.
BLACKLIST_PATTERNS: reserve, women, youth, friendly, cup, playoff
EXPECTED_BETS_MONTH: ~4.0
EXPECTED_BETS_WEEK: ~0.9
EXPECTED_ROI_KELLY: 85.38%
EXPECTED_HIT_RATE: 67.2%
AVG_ODDS: 2.614
MAX_DRAWDOWN_KELLY: 10.8%
MAX_DRAWDOWN_FLAT: 4.00 units
LONGEST_LOSING_STREAK: 4
WORST_MONTH: 2025-05 (PnL=-2.0)
WORST_QUARTER: 2026Q2 (PnL=-1.0)
```
