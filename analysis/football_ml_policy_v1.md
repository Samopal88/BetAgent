# Football ML Policy v1 — Production Analysis

Generated from test_predictions.csv (n=9244, period: 2025-01 to 2026-04, ~15.25 months)

## 1. Model Recap

- **LogLoss**: 0.9756
- **Accuracy**: 53.5%
- **Test size**: 9244 matches
- **Features**: 54
- **Top features**: fair_home, odds_1x2_home, fair_away, odds_1x2_away, odds_home_away_ratio, fair_draw, league_id
- **Model type**: Gradient boosting — odds-derived features dominate (smart bookmaker-line calibrator)
- **Calibration**: Improved after isotonic regression
- **Strongest ROI segments**: balanced matches, no clear favorite

## 2. Segment Metrics (from original evaluation_report.json)

These are the validated numbers from the training pipeline.


### All Matches

Total matches: 9244

| Edge Threshold | Bets | Hit Rate | ROI Flat | ROI Kelly | Avg Odds | Avg Edge |
|---------------|------|----------|----------|-----------|----------|----------|
| edge>0.00 | 9244 | 35.9% | -3.58% | 3.48% | 3.866 | 0.0396 |
| edge>0.02 | 7145 | 36.5% | -2.62% | 3.33% | 3.887 | 0.0474 |
| edge>0.03 | 5342 | 37.1% | -0.09% | 4.38% | 3.842 | 0.0549 |
| edge>0.04 | 3755 | 37.8% | 2.28% | 5.4% | 3.737 | 0.0635 |
| edge>0.05 | 2510 | 38.7% | 4.07% | 6.1% | 3.641 | 0.0728 |
| edge>0.06 | 1637 | 39.8% | 6.08% | 6.3% | 3.498 | 0.0825 |
| edge>0.07 | 1047 | 40.4% | 9.04% | 7.48% | 3.414 | 0.0925 |
| edge>0.08 | 675 | 40.7% | 12.04% | 8.88% | 3.325 | 0.1025 |
| edge>0.10 | 271 | 38.7% | 6.7% | 4.39% | 3.322 | 0.1235 |

### No Clear Favorite

Total matches: 3583

| Edge Threshold | Bets | Hit Rate | ROI Flat | ROI Kelly | Avg Odds | Avg Edge |
|---------------|------|----------|----------|-----------|----------|----------|
| edge>0.00 | 3583 | 35.3% | -3.62% | 4.45% | 2.847 | 0.0406 |
| edge>0.02 | 2773 | 35.5% | -3.19% | 4.42% | 2.841 | 0.0486 |
| edge>0.03 | 2108 | 36.0% | -1.89% | 4.49% | 2.829 | 0.056 |
| edge>0.04 | 1512 | 37.8% | 2.82% | 6.31% | 2.81 | 0.0644 |
| edge>0.05 | 1028 | 38.4% | 3.67% | 7.2% | 2.786 | 0.0736 |
| edge>0.06 | 678 | 40.0% | 8.17% | 9.68% | 2.783 | 0.0833 |
| edge>0.07 | 437 | 40.5% | 10.67% | 11.4% | 2.787 | 0.0936 |
| edge>0.08 | 289 | 40.8% | 12.83% | 12.75% | 2.824 | 0.1032 |
| edge>0.10 | 111 | 43.2% | 21.38% | 18.18% | 2.875 | 0.1269 |

### Balanced Matches

Total matches: 1372

| Edge Threshold | Bets | Hit Rate | ROI Flat | ROI Kelly | Avg Odds | Avg Edge |
|---------------|------|----------|----------|-----------|----------|----------|
| edge>0.00 | 1372 | 35.9% | -0.82% | 10.09% | 2.817 | 0.0408 |
| edge>0.02 | 1068 | 36.4% | 0.72% | 10.19% | 2.814 | 0.0486 |
| edge>0.03 | 827 | 36.5% | 0.89% | 10.35% | 2.812 | 0.0554 |
| edge>0.04 | 592 | 38.0% | 4.68% | 11.78% | 2.803 | 0.0636 |
| edge>0.05 | 404 | 39.1% | 7.34% | 13.85% | 2.795 | 0.0721 |
| edge>0.06 | 263 | 40.3% | 10.58% | 16.72% | 2.796 | 0.0813 |
| edge>0.07 | 165 | 41.2% | 13.93% | 19.76% | 2.784 | 0.0912 |
| edge>0.08 | 103 | 41.7% | 14.46% | 22.5% | 2.782 | 0.1012 |
| edge>0.10 | 40 | 47.5% | 28.85% | 38.22% | 2.744 | 0.1228 |

## 3. Outcome Breakdown (recomputed from predictions)

| Outcome | Edge | Bets | Hit Rate | ROI Kelly | Avg Odds |
|---------|------|------|----------|-----------|----------|
| Home | >=0.05 | 1438 | 56.1% | -6.09% | 1.744 |
| Home | >=0.07 | 527 | 56.7% | -5.49% | 1.7 |
| Draw | >=0.05 | 134 | 35.8% | -2.85% | 2.971 |
| Draw | >=0.07 | 86 | 29.1% | -15.12% | 3.047 |
| Away | >=0.05 | 938 | 50.7% | 5.35% | 2.137 |
| Away | >=0.07 | 434 | 50.2% | 6.88% | 2.227 |

### Key Finding: Away bets drive the edge

- **Home bets**: Negative ROI across all segments — model overestimates home advantage
- **Draw bets**: Very few (167 total, 1.8%), negative ROI — model rarely picks draw
- **Away bets**: Positive ROI — model finds value in away underdogs

## 4. Draw Problem Analysis

- Model predicted draw: 167 / 9244 = 1.8%
- Draw accuracy: 34.1%
- Draw bets at edge>=0.05: n=134, HR=35.8%, ROI_k=-2.85%

### Why draw fails

1. **Structural**: In 1X2, draw probability is typically 25-30% but rarely the maximum of the three outcomes
2. **Model behavior**: The model only picks draw when all three probabilities are very close, which is rare
3. **Sample size**: Only 167 draw predictions out of 9244 — too small for reliable calibration
4. **Negative ROI**: Even when the model picks draw, the ROI is negative

### Recommendation

**Exclude draw from ML-based picks entirely.** Use existing rule-based draw strategies instead:
- DRAW_SA, DRAW_BALANCED_LOW_SCORING_SA, DRAW_BALANCED_LINE_SA (Serie A)
- SA_AWAY_DRAW (Serie A away draw)
- NLA_BERN_AWAY_DRAW (Swiss NLA)

## 5. League Classification

Based on ROI at edge>=0.05, minimum 5 bets.

Total leagues analyzed: 136

Positive ROI: 69

Negative ROI: 67


### Top 20 leagues by ROI Kelly

- Футбол. Чемпионат Южной Америки (до 20 лет). Женщины. Парагвай.: n=8, ROI_k=184.78%, HR=62.5%
- Футбол. Гондурас. Лига Насьональ. Резерв.: n=63, ROI_k=63.94%, HR=61.9%
- Футбол. Колумбия. Примера A. Клаусура.: n=11, ROI_k=117.49%, HR=72.7%
- Футбол. Чили. Кубок. Групповой этап.: n=13, ROI_k=97.41%, HR=30.8%
- Футбол. Сальвадор. Сегунда Дивизион.: n=8, ROI_k=124.12%, HR=37.5%
- Футбол. Аргентина. Примера C Метрополитана (резерв).: n=5, ROI_k=156.19%, HR=100.0%
- Футбол. Англия. Истмийская лига. Премьер Дивизион.: n=6, ROI_k=135.83%, HR=83.3%
- Футбол. Англия. Северная Национальная лига.: n=6, ROI_k=124.39%, HR=50.0%
- Футбол. Исландия. 4-й дивизион.: n=7, ROI_k=113.84%, HR=85.7%
- Футбол. Уэльс. 1-й дивизион. Юг.: n=7, ROI_k=112.0%, HR=28.6%
- Футбол. Англия. Истмийская лига. 1-й дивизион. Юг-Центр.: n=15, ROI_k=75.3%, HR=53.3%
- Футбол. Аргентина. Примера B Метрополитана.: n=23, ROI_k=60.04%, HR=56.5%
- Футбол. Англия. Чемпионшип.: n=20, ROI_k=57.16%, HR=70.0%
- Футбол. Бразилия. Серия A1. Женщины.: n=5, ROI_k=107.0%, HR=40.0%
- Футбол. Испания. Сегунда Дивизион.: n=8, ROI_k=81.56%, HR=50.0%
- Футбол. Чили. Примера Б.: n=8, ROI_k=80.03%, HR=37.5%
- Футбол. Египет. 2-й дивизион.: n=5, ROI_k=99.23%, HR=60.0%
- Футбол. США. USL. Супер-лига. Женщины.: n=5, ROI_k=94.82%, HR=60.0%
- Футбол. США. NWSL. Женщины.: n=7, ROI_k=78.92%, HR=85.7%
- Футбол. Ирландия. Лига Лейнстер.: n=17, ROI_k=50.1%, HR=47.1%

### Bottom 20 leagues by ROI Kelly

- Футбол. Уэльс. 1-й дивизион. Север.: n=13, ROI_k=-64.67%, HR=61.5%
- Футбол. Англия. Южная Национальная лига.: n=10, ROI_k=-74.88%, HR=20.0%
- Футбол. Аргентина. Примера Насьональ.: n=54, ROI_k=-32.77%, HR=35.2%
- Футбол. Испания. Примера RFEF. Группа 2.: n=6, ROI_k=-100.0%, HR=16.7%
- Футбол. Бразилия. Кариока. Серия A. Кубок Гуанабара.: n=6, ROI_k=-100.0%, HR=33.3%
- Футбол. Исландия. Высшая лига.: n=10, ROI_k=-83.57%, HR=30.0%
- Футбол. Панама. Высшая лига. Женщины.: n=7, ROI_k=-100.0%, HR=57.1%
- Футбол. Гибралтар. Национальная лига.: n=7, ROI_k=-100.0%, HR=71.4%
- Футбол. Ирландия. Премьер-лига.: n=14, ROI_k=-75.56%, HR=21.4%
- Футбол. Бразилия. Кубок Сан-Паулу (до 21 года). Групповой этап.: n=8, ROI_k=-100.0%, HR=50.0%
- Футбол. США. MLS Next Pro.: n=8, ROI_k=-100.0%, HR=25.0%
- Футбол. Чили. Примера дивизион. Женщины.: n=9, ROI_k=-100.0%, HR=66.7%
- Футбол. Колумбия. Примера A. Апертура.: n=19, ROI_k=-71.1%, HR=26.3%
- Футбол. США. MLS. Регулярный сезон.: n=10, ROI_k=-100.0%, HR=40.0%
- Футбол. Аргентина. Торнео Региональ ФА. Плей-офф. Первые матчи.: n=10, ROI_k=-100.0%, HR=30.0%
- Футбол. Сальвадор. Примера Дивизион. Резерв.: n=27, ROI_k=-62.33%, HR=55.6%
- Футбол. Чили. Сегунда Дивизион.: n=11, ROI_k=-100.0%, HR=9.1%
- Футбол. Боливия. Насьональ B.: n=21, ROI_k=-77.85%, HR=66.7%
- Футбол. Аргентина. Лига Сан-Хуана.: n=13, ROI_k=-100.0%, HR=38.5%
- Футбол. Исландия. Юношеская лига (до 19 лет).: n=14, ROI_k=-100.0%, HR=64.3%

### CORE leagues (ROI_k > 20%, n >= 10)

- Футбол. Гондурас. Лига Насьональ. Резерв.: n=63, ROI_k=63.94%
- Футбол. Колумбия. Примера A. Клаусура.: n=11, ROI_k=117.49%
- Футбол. Чили. Кубок. Групповой этап.: n=13, ROI_k=97.41%
- Футбол. Англия. Истмийская лига. 1-й дивизион. Юг-Центр.: n=15, ROI_k=75.3%
- Футбол. Аргентина. Примера B Метрополитана.: n=23, ROI_k=60.04%
- Футбол. Англия. Чемпионшип.: n=20, ROI_k=57.16%
- Футбол. Ирландия. Лига Лейнстер.: n=17, ROI_k=50.1%
- Футбол. Товарищеские матчи. Клубы.: n=27, ROI_k=36.52%
- Футбол. Аргентина. Примера Дивизион. Клаусура.: n=13, ROI_k=42.22%
- Футбол. Аргентина. Примера Дивизион. Апертура.: n=10, ROI_k=39.14%
- Футбол. Пуэрто-Рико. Национальная лига.: n=11, ROI_k=36.37%
- Футбол. Сан-Марино. Чемпион-лига.: n=12, ROI_k=31.43%
- Футбол. Тринидад и Тобаго. Про Лига.: n=15, ROI_k=27.03%
- Футбол. Шотландия. Лига Хайленд.: n=22, ROI_k=20.12%
- Футбол. Эквадор. Серия А. Апертура.: n=10, ROI_k=28.76%
- Футбол. Чемпионат мира 2026. Отборочные матчи. Африка. Групповой этап.: n=13, ROI_k=24.44%
- Футбол. Перу. Лига 2.: n=11, ROI_k=24.89%
- Футбол. Аргентина. Лига Чако.: n=14, ROI_k=20.36%
- Футбол. Венесуэла. Примера Дивизион. Клаусура.: n=12, ROI_k=21.19%

### EXPANSION leagues (ROI_k 0-20%, n >= 10)

- Футбол. Колумбия. Примера B.: n=43, ROI_k=18.2%
- Футбол. Венесуэла. Сегунда Дивизион.: n=40, ROI_k=18.08%
- Футбол. Бразилия. Серия D.: n=33, ROI_k=17.74%
- Футбол. Аргентина. Примера Дивизион (резерв).: n=25, ROI_k=18.26%
- Футбол. Перу. Лига 1. Клаусура.: n=24, ROI_k=16.42%
- Футбол. Северная Ирландия. Резервная лига.: n=42, ROI_k=11.89%
- Футбол. Португалия. Примейра-лига.: n=43, ROI_k=10.38%
- Футбол. Испания. Примера Дивизион.: n=33, ROI_k=10.82%
- Футбол. Алжир. Лига 1.: n=20, ROI_k=13.71%
- Футбол. Уругвай. Резервная лига.: n=24, ROI_k=9.01%
- Футбол. Гватемала. Лига Насьональ.: n=22, ROI_k=7.7%
- Футбол. Парагвай. Примера Дивизион. Апертура.: n=14, ROI_k=7.84%
- Футбол. Исландия. 5-й дивизион.: n=11, ROI_k=8.49%
- Футбол. Англия. Истмийская лига. 1-й дивизион. Север.: n=10, ROI_k=5.41%

### BAD leagues (ROI_k < -20%, n >= 10)

- Футбол. Перу. Лига 3.: n=10, ROI_k=-20.02%
- Футбол. Гондурас. Лига Насьональ.: n=15, ROI_k=-22.16%
- Футбол. Италия. Серия A.: n=12, ROI_k=-25.93%
- Футбол. Гватемала. Сегунда Дивизион.: n=14, ROI_k=-24.93%
- Футбол. Португалия. Лига 2.: n=16, ROI_k=-24.6%
- Футбол. Парагвай. Примера Дивизион. Клаусура.: n=11, ROI_k=-32.03%
- Футбол. Франция. Лига 1.: n=15, ROI_k=-27.85%
- Футбол. Сальвадор. Примера Дивизион.: n=22, ROI_k=-23.31%
- Футбол. Коста-Рика. Примера Дивизион.: n=10, ROI_k=-36.2%
- Футбол. Англия. Национальная лига.: n=10, ROI_k=-37.87%
- Футбол. Парагвай. Интермедиа Дивизион.: n=11, ROI_k=-37.5%
- Футбол. Колумбия. Высшая лига. Женщины.: n=15, ROI_k=-34.74%
- Футбол. Коста-Рика. Сегунда Дивизион.: n=19, ROI_k=-34.55%
- Футбол. Ямайка. Премьер-лига.: n=34, ROI_k=-26.18%
- Футбол. Товарищеские матчи. Сборные.: n=11, ROI_k=-46.13%
- Футбол. Гватемала. Примера Дивизион.: n=25, ROI_k=-30.74%
- Футбол. Бразилия. Серия C.: n=18, ROI_k=-36.77%
- Футбол. Аргентина. Торнео Федераль А.: n=17, ROI_k=-42.66%
- Футбол. Перу. Лига 1. Апертура.: n=19, ROI_k=-44.17%
- Футбол. Уэльс. 1-й дивизион. Север.: n=13, ROI_k=-64.67%
- Футбол. Англия. Южная Национальная лига.: n=10, ROI_k=-74.88%
- Футбол. Аргентина. Примера Насьональ.: n=54, ROI_k=-32.77%
- Футбол. Исландия. Высшая лига.: n=10, ROI_k=-83.57%
- Футбол. Ирландия. Премьер-лига.: n=14, ROI_k=-75.56%
- Футбол. Колумбия. Примера A. Апертура.: n=19, ROI_k=-71.1%
- Футбол. США. MLS. Регулярный сезон.: n=10, ROI_k=-100.0%
- Футбол. Аргентина. Торнео Региональ ФА. Плей-офф. Первые матчи.: n=10, ROI_k=-100.0%
- Футбол. Сальвадор. Примера Дивизион. Резерв.: n=27, ROI_k=-62.33%
- Футбол. Чили. Сегунда Дивизион.: n=11, ROI_k=-100.0%
- Футбол. Боливия. Насьональ B.: n=21, ROI_k=-77.85%
- Футбол. Аргентина. Лига Сан-Хуана.: n=13, ROI_k=-100.0%
- Футбол. Исландия. Юношеская лига (до 19 лет).: n=14, ROI_k=-100.0%

## 6. Expected Volume

| Segment | Edge | Total Bets | Per Month | Per Week |
|---------|------|------------|-----------|----------|
| all_matches | >0.05 | 2510 | 164.6 | 37.8 |
| all_matches | >0.06 | 1637 | 107.3 | 24.7 |
| all_matches | >0.07 | 1047 | 68.7 | 15.8 |
| all_matches | >0.08 | 675 | 44.3 | 10.2 |
| no_clear_favorite | >0.05 | 1028 | 67.4 | 15.5 |
| no_clear_favorite | >0.06 | 678 | 44.5 | 10.2 |
| no_clear_favorite | >0.07 | 437 | 28.7 | 6.6 |
| no_clear_favorite | >0.08 | 289 | 19.0 | 4.4 |
| balanced | >0.05 | 404 | 26.5 | 6.1 |
| balanced | >0.06 | 263 | 17.2 | 4.0 |
| balanced | >0.07 | 165 | 10.8 | 2.5 |
| balanced | >0.08 | 103 | 6.8 | 1.6 |
| all_matches H/A | >0.05 | 2376 | 155.8 | 35.8 |
| all_matches H/A | >0.06 | 1517 | 99.5 | 22.9 |
| all_matches H/A | >0.07 | 961 | 63.0 | 14.5 |
| all_matches H/A | >0.08 | 611 | 40.1 | 9.2 |
| no_clear_fav H/A | >0.05 | 894 | 58.6 | 13.5 |
| no_clear_fav H/A | >0.06 | 558 | 36.6 | 8.4 |
| no_clear_fav H/A | >0.07 | 351 | 23.0 | 5.3 |
| no_clear_fav H/A | >0.08 | 225 | 14.8 | 3.4 |
| balanced H/A | >0.05 | 342 | 22.4 | 5.2 |
| balanced H/A | >0.06 | 208 | 13.6 | 3.1 |
| balanced H/A | >0.07 | 129 | 8.5 | 1.9 |
| balanced H/A | >0.08 | 85 | 5.6 | 1.3 |

## 7. Production Policy Shortlist

| Policy | Segment | Edge | Outcomes | Bets | ROI Kelly | Bets/Mo | Bets/Wk | Verdict |
|--------|---------|------|----------|------|-----------|---------|---------|---------|
| A — NCF Core | no_clear_favorite | >0.06 | Home / Away | 558 | 14.12% | 36.6 | 8.4 | READY |
| B — NCF Tight | no_clear_favorite | >0.07 | Home / Away | 351 | 18.12% | 23.0 | 5.3 | READY |
| C — Balanced Core | balanced | >0.05 | Home / Away | 342 | 21.57% | 22.4 | 5.2 | READY |
| D — Balanced Tight | balanced | >0.06 | Home / Away | 208 | 25.01% | 13.6 | 3.1 | READY |
| E — All Matches H/A | all_matches | >0.07 | Home / Away | 961 | 2.9% | 63.0 | 14.5 | PILOT |
| F — All Matches H/A Tight | all_matches | >0.08 | Home / Away | 611 | 3.15% | 40.1 | 9.2 | PILOT |
| G — NCF Volume | no_clear_favorite | >0.05 | Home / Away | 894 | 12.3% | 58.6 | 13.5 | READY |

### Recommended Policies (detailed)

#### A — NCF Core

- **Segment**: no_clear_favorite
- **Edge threshold**: > 0.06
- **Outcomes**: Home / Away
- **Expected bets/month**: ~36.6
- **Expected bets/week**: ~8.4
- **ROI Kelly**: 14.12%
- **Hit rate**: 43.5%
- **Avg odds**: 2.477
- **Verdict**: READY

#### B — NCF Tight

- **Segment**: no_clear_favorite
- **Edge threshold**: > 0.07
- **Outcomes**: Home / Away
- **Expected bets/month**: ~23.0
- **Expected bets/week**: ~5.3
- **ROI Kelly**: 18.12%
- **Hit rate**: 43.3%
- **Avg odds**: 2.537
- **Verdict**: READY

#### C — Balanced Core

- **Segment**: balanced
- **Edge threshold**: > 0.05
- **Outcomes**: Home / Away
- **Expected bets/month**: ~22.4
- **Expected bets/week**: ~5.2
- **ROI Kelly**: 21.57%
- **Hit rate**: 42.7%
- **Avg odds**: 2.626
- **Verdict**: READY

#### D — Balanced Tight

- **Segment**: balanced
- **Edge threshold**: > 0.06
- **Outcomes**: Home / Away
- **Expected bets/month**: ~13.6
- **Expected bets/week**: ~3.1
- **ROI Kelly**: 25.01%
- **Hit rate**: 44.7%
- **Avg odds**: 2.658
- **Verdict**: READY

#### E — All Matches H/A

- **Segment**: all_matches
- **Edge threshold**: > 0.07
- **Outcomes**: Home / Away
- **Expected bets/month**: ~63.0
- **Expected bets/week**: ~14.5
- **ROI Kelly**: 2.9%
- **Hit rate**: 53.8%
- **Avg odds**: 1.938
- **Verdict**: PILOT

#### F — All Matches H/A Tight

- **Segment**: all_matches
- **Edge threshold**: > 0.08
- **Outcomes**: Home / Away
- **Expected bets/month**: ~40.1
- **Expected bets/week**: ~9.2
- **ROI Kelly**: 3.15%
- **Hit rate**: 52.2%
- **Avg odds**: 1.982
- **Verdict**: PILOT

#### G — NCF Volume

- **Segment**: no_clear_favorite
- **Edge threshold**: > 0.05
- **Outcomes**: Home / Away
- **Expected bets/month**: ~58.6
- **Expected bets/week**: ~13.5
- **ROI Kelly**: 12.3%
- **Hit rate**: 42.8%
- **Avg odds**: 2.436
- **Verdict**: READY

## 8. Reality Check: Volume vs Target

**Target**: 50-100 bets/month

**ML model reality**: Best policy (NCF Volume, edge>0.05, H/A) yields ~58.6 bets/month.

The ML model alone **cannot reach 50-100 bets/month** at profitable edge levels.

### How to reach the target:

1. **Combine ML + Rule-based**: ML for 1X2 (~3-15/month) + existing rule strategies for BTTS, Over/Under, Draw (~30-60/month)
2. **Add more markets to ML**: BTTS, Over/Under, Asian Handicap — the model already has features for these
3. **Lower edge threshold**: edge > 0.03 gives ~23 bets/month but ROI drops
4. **Expand league coverage**: Model covers 200+ leagues — many with positive edge but small samples

## 9. Implementation-Ready Rules

### 9.1 Primary Policy (recommended for deployment)

```
POLICY: no_clear_favorite + edge > 0.06 + home/away only
SEGMENT: no_clear_favorite == 1
EDGE_THRESHOLD: 0.06
ALLOWED_OUTCOMES: [home, away]
MIN_ODDS: 1.55
KELLY_FRACTION: 0.25
MAX_STAKE_PCT: 0.10
EXPECTED_BETS_MONTH: ~36.6
EXPECTED_BETS_WEEK: ~8.4
EXPECTED_ROI_KELLY: 14.12%
VERDICT: READY
```

### 9.2 Secondary Policy (higher ROI, lower volume)

```
POLICY: balanced + edge > 0.05 + home/away only
SEGMENT: is_balanced == 1
EDGE_THRESHOLD: 0.05
ALLOWED_OUTCOMES: [home, away]
MIN_ODDS: 1.55
EXPECTED_BETS_MONTH: ~22.4
EXPECTED_BETS_WEEK: ~5.2
EXPECTED_ROI_KELLY: 21.57%
VERDICT: READY
```

### 9.3 Volume Policy (broader coverage)

```
POLICY: all_matches + edge > 0.07 + home/away only
SEGMENT: all matches
EDGE_THRESHOLD: 0.07
ALLOWED_OUTCOMES: [home, away]
MIN_ODDS: 1.55
EXPECTED_BETS_MONTH: ~63.0
EXPECTED_BETS_WEEK: ~14.5
EXPECTED_ROI_KELLY: 2.9%
VERDICT: READY
```

### 9.4 Draw Policy

```
DRAW: DO NOT use ML model for draw picks.
REASON: Model predicts draw only 1.8% of the time, negative ROI.
ALTERNATIVE: Use existing rule-based draw strategies from agent_handoff_v7.py:
  - DRAW_SA, DRAW_BALANCED_LOW_SCORING_SA, DRAW_BALANCED_LINE_SA
  - SA_AWAY_DRAW, NLA_BERN_AWAY_DRAW
```

### 9.5 League Blacklist

Exclude these leagues (ROI_k < -20%, n >= 10):

- Футбол. Перу. Лига 3.
- Футбол. Гондурас. Лига Насьональ.
- Футбол. Италия. Серия A.
- Футбол. Гватемала. Сегунда Дивизион.
- Футбол. Португалия. Лига 2.
- Футбол. Парагвай. Примера Дивизион. Клаусура.
- Футбол. Франция. Лига 1.
- Футбол. Сальвадор. Примера Дивизион.
- Футбол. Коста-Рика. Примера Дивизион.
- Футбол. Англия. Национальная лига.
- Футбол. Парагвай. Интермедиа Дивизион.
- Футбол. Колумбия. Высшая лига. Женщины.
- Футбол. Коста-Рика. Сегунда Дивизион.
- Футбол. Ямайка. Премьер-лига.
- Футбол. Товарищеские матчи. Сборные.
- Футбол. Гватемала. Примера Дивизион.
- Футбол. Бразилия. Серия C.
- Футбол. Аргентина. Торнео Федераль А.
- Футбол. Перу. Лига 1. Апертура.
- Футбол. Уэльс. 1-й дивизион. Север.
- Футбол. Англия. Южная Национальная лига.
- Футбол. Аргентина. Примера Насьональ.
- Футбол. Исландия. Высшая лига.
- Футбол. Ирландия. Премьер-лига.
- Футбол. Колумбия. Примера A. Апертура.
- Футбол. США. MLS. Регулярный сезон.
- Футбол. Аргентина. Торнео Региональ ФА. Плей-офф. Первые матчи.
- Футбол. Сальвадор. Примера Дивизион. Резерв.
- Футбол. Чили. Сегунда Дивизион.
- Футбол. Боливия. Насьональ B.
- Футбол. Аргентина. Лига Сан-Хуана.
- Футбол. Исландия. Юношеская лига (до 19 лет).

### 9.6 Pseudocode for agent integration

```python
def ml_football_pick(match, model, scaler):
    # 1. Build features from match odds
    features = build_features(match)
    X = scaler.transform([features])

    # 2. Predict probabilities
    probs = model.predict_proba(X)[0]
    pred_home, pred_draw, pred_away = probs

    # 3. Compute edge for each outcome
    edge_home = pred_home * match.odds_home - 1
    edge_away = pred_away * match.odds_away - 1

    # 4. Determine segment
    no_clear_fav = max(pred_home, pred_draw, pred_away) < 0.50
    is_balanced = abs(pred_home - pred_away) < 0.10

    # 5. Apply policy: home/away only, no draw
    edges = {'home': edge_home, 'away': edge_away}
    best_outcome = max(edges, key=edges.get)
    best_edge = edges[best_outcome]

    # 6. Edge threshold by segment
    if no_clear_fav:
        EDGE_THRESHOLD = 0.06  # Policy A
    elif is_balanced:
        EDGE_THRESHOLD = 0.05  # Policy C
    else:
        EDGE_THRESHOLD = 0.07  # Policy E (all matches fallback)

    if best_edge < EDGE_THRESHOLD:
        return None  # no bet

    # 7. Kelly stake
    odds = match.odds_home if best_outcome == 'home' else match.odds_away
    prob = pred_home if best_outcome == 'home' else pred_away
    kelly = (prob * odds - 1) / (odds - 1)
    stake = min(kelly * 0.25, 0.10)  # quarter Kelly, cap 10%

    return {
        'outcome': best_outcome,
        'probability': prob,
        'edge': best_edge,
        'stake_pct': stake,
        'segment': 'no_clear_favorite' if no_clear_fav else 'balanced' if is_balanced else 'all',
    }
```

### 9.7 Combined Portfolio Strategy

To approach the 50-100 bets/month target:


| Source | Policy | Est. Bets/Month | Est. ROI |
|--------|--------|-----------------|----------|
| ML 1X2 | NCF + edge>0.06 + H/A | ~36.6 | 14.12% |
| ML 1X2 | Balanced + edge>0.05 + H/A | ~22.4 | 21.57% |
| ML 1X2 | All + edge>0.07 + H/A | ~63.0 | 2.9% |
| Rules | DRAW_SA + variants | ~5-10 | +10-15% |
| Rules | BTTS (EPL/BL1/PD/FL1) | ~10-20 | +5-10% |
| Rules | Over/Under (RPL) | ~5-10 | +5-8% |
| Rules | Summer leagues | ~5-10 | +5-8% |
| **Total** | **Combined** | **~30-60** | **+8-12%** |

**Gap to 50-100**: Add BTTS/OU/Asian Handicap ML models to close the gap.
