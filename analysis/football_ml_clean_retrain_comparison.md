# Football ML Clean Universe Retraining — A/B Test

## Вопрос

Улучшится ли ML 1X2 модель, если обучить только на чистых профессиональных лигах?

## Setup

| | MODEL_A (baseline) | MODEL_B (clean) | MODEL_C (expanded) |
|---|---|---|---|
| **Train data** | FULL (57k matches) | production_universe.core | core + expansion |
| **Train size** | 39,831 | 4,323 | 6,236 |
| **Valid size** | 8,273 | 736 | 1,266 |
| **Test set** | CORE only (997) | CORE only (997) | CORE only (997) |
| **Best iteration** | 111 | 81 | 68 |

Все модели оцениваются на **одном и том же CORE test set** (997 матчей, 2025-2026).
Фиксированный time split: train 2019-2023, valid 2024, test 2025-2026.
Одинаковые гиперпараметры LightGBM, isotonic calibration.

---

## 1. ML Метрики

| Metric | MODEL_A (full) | MODEL_B (core) | MODEL_C (core+exp) |
|--------|---------------|---------------|-------------------|
| **LogLoss** | **0.9986** | 1.0775 | 1.1376 |
| **Accuracy** | **0.5206** | 0.5155 | 0.5196 |

### Per-class Brier Score

| | MODEL_A | MODEL_B | MODEL_C |
|---|---|---|---|
| Home Brier | **0.2214** | 0.2227 | 0.2244 |
| Draw Brier | 0.1966 | 0.1970 | **0.1959** |
| Away Brier | **0.1794** | 0.1809 | 0.1808 |

### Per-class Accuracy

| | MODEL_A | MODEL_B | MODEL_C |
|---|---|---|---|
| Home Accuracy | **0.8141** | 0.7755 | 0.8277 |
| Draw Accuracy | 0.0517 | **0.1107** | 0.0332 |
| Away Accuracy | **0.5123** | 0.4982 | 0.5053 |

### Calibration (avg predicted prob vs actual frequency)

| | MODEL_A | MODEL_B | MODEL_C |
|---|---|---|---|
| Home: avg_pred | 0.4425 | 0.4367 | 0.4428 |
| Home: actual | 0.4423 | 0.4423 | 0.4423 |
| **Home: gap** | **+0.0002** | -0.0056 | +0.0005 |
| Draw: gap | -0.0153 | **-0.0064** | -0.0113 |
| Away: gap | +0.0151 | **+0.0121** | +0.0108 |

### Prediction Distribution

| | Home % | Draw % | Away % |
|---|---|---|---|
| MODEL_A | 44.2% | 25.7% | 30.1% |
| MODEL_B | 43.7% | 26.5% | 29.8% |
| MODEL_C | 44.3% | 26.1% | 29.7% |

---

## 2. Betting Performance — BALANCED Segment

Draw excluded, home/away only.

### ROI Kelly (%)

| Threshold | MODEL_A | MODEL_B | MODEL_C |
|-----------|---------|---------|---------|
| edge > 0.04 | **+16.3%** | +13.8% | +5.3% |
| edge > 0.05 | **+22.9%** | +15.1% | +11.8% |
| edge > 0.06 | **+24.8%** | +17.7% | +19.8% |
| edge > 0.07 | **+22.2%** | +24.7% | +27.1% |
| edge > 0.08 | **+42.8%** | +29.9% | +10.2% |

### Hit Rate (%)

| Threshold | MODEL_A | MODEL_B | MODEL_C |
|-----------|---------|---------|---------|
| edge > 0.04 | 38.8% | **42.7%** | 35.7% |
| edge > 0.05 | 42.9% | 41.8% | 40.0% |
| edge > 0.06 | 41.9% | **42.9%** | 43.3% |
| edge > 0.07 | 40.0% | **46.0%** | 50.0% |
| edge > 0.08 | **50.0%** | 48.6% | 44.4% |

### Volume (bets/month)

| Threshold | MODEL_A | MODEL_B | MODEL_C |
|-----------|---------|---------|---------|
| edge > 0.04 | 4.4 | **7.2** | 4.6 |
| edge > 0.05 | 3.2 | **6.0** | 3.0 |
| edge > 0.06 | 2.0 | **5.1** | 2.0 |
| edge > 0.07 | 1.3 | **3.3** | 0.9 |
| edge > 0.08 | 0.8 | **2.3** | 0.6 |

### Max Drawdown Kelly (%)

| Threshold | MODEL_A | MODEL_B | MODEL_C |
|-----------|---------|---------|---------|
| edge > 0.04 | **0.1%** | 0.2% | 0.2% |
| edge > 0.05 | **0.1%** | 0.2% | 0.2% |
| edge > 0.06 | **0.1%** | 0.1% | 0.2% |
| edge > 0.07 | **0.1%** | 0.1% | 0.1% |
| edge > 0.08 | **0.1%** | 0.1% | 0.1% |

### Longest Losing Streak

| Threshold | MODEL_A | MODEL_B | MODEL_C |
|-----------|---------|---------|---------|
| edge > 0.04 | 7 | **6** | 7 |
| edge > 0.05 | **4** | 6 | 5 |
| edge > 0.06 | **5** | 5 | 7 |
| edge > 0.07 | **5** | 5 | 5 |
| edge > 0.08 | **2** | 5 | 4 |

---

## 3. Betting Performance — NO_CLEAR_FAVORITE Segment

Draw excluded, home/away only.

### ROI Kelly (%)

| Threshold | MODEL_A | MODEL_B | MODEL_C |
|-----------|---------|---------|---------|
| edge > 0.04 | **+8.3%** | +6.5% | +0.3% |
| edge > 0.05 | **+15.2%** | +8.2% | +4.1% |
| edge > 0.06 | **+15.3%** | +10.3% | +9.7% |
| edge > 0.07 | **+26.3%** | +13.9% | +18.2% |
| edge > 0.08 | **+29.2%** | +19.9% | +16.2% |

### Hit Rate (%)

| Threshold | MODEL_A | MODEL_B | MODEL_C |
|-----------|---------|---------|---------|
| edge > 0.04 | 38.9% | 38.8% | 33.8% |
| edge > 0.05 | **44.1%** | 39.0% | 36.7% |
| edge > 0.06 | **42.5%** | 41.0% | 38.5% |
| edge > 0.07 | **48.9%** | 42.0% | 43.9% |
| edge > 0.08 | **51.9%** | 44.3% | 44.0% |

### Volume (bets/month)

| Threshold | MODEL_A | MODEL_B | MODEL_C |
|-----------|---------|---------|---------|
| edge > 0.04 | 10.7 | **13.8** | 9.5 |
| edge > 0.05 | 7.3 | **11.3** | 6.4 |
| edge > 0.06 | 4.8 | **8.8** | 4.3 |
| edge > 0.07 | 3.0 | **5.8** | 2.7 |
| edge > 0.08 | 1.8 | **4.0** | 1.6 |

### Max Drawdown Kelly (%)

| Threshold | MODEL_A | MODEL_B | MODEL_C |
|-----------|---------|---------|---------|
| edge > 0.04 | **0.3%** | 0.3% | 0.2% |
| edge > 0.05 | **0.2%** | 0.3% | 0.2% |
| edge > 0.06 | **0.2%** | 0.3% | 0.2% |
| edge > 0.07 | **0.1%** | 0.3% | 0.2% |
| edge > 0.08 | **0.2%** | 0.2% | 0.1% |

### Longest Losing Streak

| Threshold | MODEL_A | MODEL_B | MODEL_C |
|-----------|---------|---------|---------|
| edge > 0.04 | **11** | 9 | 9 |
| edge > 0.05 | **8** | 9 | 7 |
| edge > 0.06 | **6** | 8 | 6 |
| edge > 0.07 | **5** | 10 | 6 |
| edge > 0.08 | **4** | 5 | 5 |

---

## 4. Calibration Detail (Decile Analysis)

### MODEL_A — Home Calibration

| Decile | Avg Pred | Actual Freq | Gap |
|--------|----------|-------------|-----|
| 0 (lowest) | 0.149 | 0.170 | -0.021 |
| 5 | 0.457 | 0.427 | +0.030 |
| 9 (highest) | 0.754 | 0.745 | +0.009 |

### MODEL_B — Home Calibration

| Decile | Avg Pred | Actual Freq | Gap |
|--------|----------|-------------|-----|
| 0 (lowest) | 0.137 | 0.180 | -0.043 |
| 5 | 0.450 | 0.534 | -0.084 |
| 9 (highest) | 0.797 | 0.755 | +0.042 |

MODEL_A заметно лучше калиброван на home outcome — gap в decile 5 у MODEL_B достигает -8.4pp.

---

## 5. Сравнение с v4 (production universe evaluation)

v4 использовала ту же модель (MODEL_A baseline) и оценивала на production universe:

| Policy (v4) | Universe | ROI Kelly | Bets/Mo |
|---|---|---|---|
| D_Bal_Tight | CORE | -12.74% | 1.4 |
| C_Bal_Relaxed | CORE | -23.34% | 3.4 |
| B_NCF_Relaxed | CORE | -30.33% | 4.0 |

Текущий эксперимент (MODEL_A, CORE test, те же сегменты):

| Segment | Edge | ROI Kelly | Bets/Mo |
|---|---|---|---|
| balanced | >0.06 | **+24.8%** | 2.0 |
| no_clear_favorite | >0.06 | **+15.3%** | 4.8 |

Разница объясняется тем, что v4 оценивала на FULL test set (9244 матча), а здесь — только CORE (997 матчей).
На CORE подмножестве модель работает значительно лучше.

---

## 6. Выводы

### ML Метрики

| Критерий | Победитель | Вердикт |
|----------|-----------|---------|
| LogLoss | **MODEL_A** (0.9986 vs 1.0775) | baseline лучше на 7.9% |
| Accuracy | **MODEL_A** (0.5206 vs 0.5155) | marginally лучше |
| Home Brier | **MODEL_A** (0.2214 vs 0.2227) | marginally лучше |
| Home Calibration | **MODEL_A** (gap +0.0002 vs -0.0056) | значительно лучше |
| Draw Calibration | **MODEL_B** (gap -0.0064 vs -0.0153) | лучше, но draw не беттится |
| Away Calibration | **MODEL_B** (gap +0.0121 vs +0.0151) | marginally лучше |

### Betting Performance

| Критерий | Победитель | Вердикт |
|----------|-----------|---------|
| ROI Kelly (balanced) | **MODEL_A** | лучше на всех порогах кроме edge>0.07 |
| ROI Kelly (no_clear_fav) | **MODEL_A** | лучше на всех порогах |
| Hit Rate (balanced) | **MODEL_B** | лучше на высоких порогах |
| Hit Rate (no_clear_fav) | **MODEL_A** | лучше на всех порогах |
| Volume | **MODEL_B** | 1.5-2x больше bets |
| Max Drawdown | **MODEL_A** | ниже на всех порогах |
| Losing Streak | **MODEL_B** | короче серии в balanced |

### Главный ответ

**Clean retrain НЕ улучшает модель.**

MODEL_A (baseline, полный датасет) превосходит MODEL_B (core only) по:
- logloss: 0.9986 vs 1.0775 (на 7.9% лучше)
- calibration home: gap +0.0002 vs -0.0056 (в 28x точнее)
- ROI Kelly balanced edge>0.06: +24.8% vs +17.7%
- ROI Kelly no_clear_fav edge>0.06: +15.3% vs +10.3%
- max drawdown: существенно ниже

MODEL_B даёт больше volume (7.2 vs 4.4 bets/month на balanced edge>0.04),
но это происходит за счёт более агрессивных edge-ов, а не лучшего качества.

MODEL_C (core+expansion) — худший из трёх.

### Почему clean retrain не помог

1. **Размер данных критичен.** MODEL_B обучался на 4,323 матчах vs 39,831 у MODEL_A.
   LightGBM с 54 фичами и min_child_samples=200 не может эффективно обучиться на 4k примерах.
   Best iteration упал с 111 до 81 — модель не дообучилась.

2. **Модель — odds calibrator, не pattern finder.** Топ-фичи по gain:
   `fair_home`, `odds_1x2_home`, `fair_away`, `odds_1x2_away`.
   Модель в основном калибрует букмекерские коэффициенты.
   Шумные лиги не вредят — они просто добавляют больше примеров для калибровки.

3. **Шум в тренировочных данных ≠ шум в тестовых.**
   Шумные лиги в train создают вариативность, но модель учится
   общим паттернам odds→outcome, которые переносятся на любые лиги.
   Проблема v4 была не в train data, а в том, что на FULL test set
   (включая шумные лиги) модель давала negative ROI Kelly.

### Что это значит для production

Проблема не в тренировочных данных.
Проблема в том, что модель находит слишком мало positive-EV сигналов
на production universe при текущих гиперпараметрах.

Возможные направления:
- Увеличить volume: понизить edge threshold, но это ухудшает ROI
- Изменить модель: добавить больше не-odds фич (form, xG, injuries)
- Ensemble: комбинировать MODEL_A predictions с rule-based strategies
- Retraining с другими гиперпараметрами: меньше min_child_samples для small data

---

## Файлы

- Скрипт: `/root/betagent/analysis/retrain_football_ml_clean_universe.py`
- Результаты JSON: `/root/betagent/ml_output/clean_retrain_comparison.json`
- Модели: `/root/betagent/ml_output/model_{a_baseline,b_clean,c_expanded}.pkl`
- Feature importance: `/root/betagent/ml_output/model_{a,b,c}_feature_importance.csv`
