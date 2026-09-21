# Hockey Strategies Recheck Report — Corrected Date Normalization

Generated: 2026-04-08
Database: /root/betagent/betagent.db
Table: backtest_hockey_features (104,677 rows)

---

## 1. DATA QUALITY

### Date Format Summary

| Format | Count | % |
|--------|-------|---|
| ISO YYYY-MM-DD (or YYYY-MM-DD HH:MM) | 67,485 | 64.5% |
| DD.MM.YYYY | 37,192 | 35.5% |
| Anomalous/Unknown | 0 | 0.0% |

**Аномальных строк — 0.** Все даты корректно парсятся одним из двух форматов.

### Year Normalization Logic

```sql
CASE
  WHEN match_date GLOB '20??-??-??*' THEN substr(match_date,1,4)
  WHEN match_date GLOB '??.??.20??' THEN substr(match_date,7,4)
  ELSE NULL
END AS year
```

- `substr(match_date,1,4)` для ISO формата (YYYY-MM-DD)
- `substr(match_date,7,4)` для европейского формата (DD.MM.YYYY)
- Строки с NULL year **исключаются** из статистики (таких нет)

### Year Distribution

| Year | Rows |
|------|------|
| 2019 | 4,033 |
| 2020 | 13,123 |
| 2021 | 11,468 |
| 2022 | 16,955 |
| 2023 | 20,832 |
| 2024 | 20,483 |
| 2025 | 13,813 |
| 2026 | 3,970 |

### Почему старый отчёт мог ошибаться

Старый скрипт использовал `substr(match_date,1,4)` без проверки формата. Для дат в формате `DD.MM.YYYY` (35.5% всех строк) это извлекало **день** вместо года:

- `01.03.2023` → `substr(1,4)` = `"01.0"` → интерпретировалось как год "01" или отбрасывалось
- `15.03.2023` → `substr(1,4)` = `"15.0"` → интерпретировалось как год "15"
- `20.03.2023` → `substr(1,4)` = `"20.0"` → **могло ошибочно считаться 2020 годом!**

Это означало, что ~35% строк либо отбрасывались, либо неправильно распределялись по годам. Стратегии с высокой концентрацией DD.MM.YYYY дат (европейские лиги — DEL, Liiga, Mestis, Czech, SHL, NL) были наиболее подвержены искажениям.

---

## 2. SUMMARY TABLE — ALL RECHECKED STRATEGIES

57 стратегий перепроверены из SQLite с корректной нормализацией дат.

| # | Strategy | Type | ROI% | n | Hit% | 22-26 + | All+? |
|---|----------|------|------|---|------|---------|-------|
| 1 | DEL home win (form5>0.5) | HOME_WIN | +11.5% | 233 | 60.5% | 5/5 | YES |
| 2 | DEL home win (form5>0.5 + sd>0.2) | HOME_WIN | +15.8% | 153 | 63.4% | 5/5 | YES |
| 3 | Czech away (sd<-0.3) | AWAY_WIN | +23.1% | 115 | 51.3% | 3/5 | NO |
| 4 | Czech Liberec away | TEAM_AWAY_WIN | +15.8% | 68 | 44.1% | 3/5 | NO |
| 5 | Czech Liberec home | TEAM_HOME_WIN | +26.5% | 53 | 62.3% | 4/5 | NO |
| 6 | Vegas draw NHL | TEAM_DRAW | +60.0% | 59 | 35.6% | 3/4 | NO |
| 7 | KHL draw (odds 4.5-5.0) | DRAW | +4.0% | 375 | 22.1% | 4/5 | NO |
| 8 | KHL draw (odds 4.5-5.0, sd<0.3) | DRAW | +11.1% | 101 | 23.8% | 4/5 | NO |
| 9 | KHL playoff over 4.5 | TOTAL_OVER | +6.4% | 147 | 46.9% | 2/5 | NO |
| 10 | Liiga draw (odds 4.0-4.5, form_diff<0.15) | DRAW | +41.4% | 148 | 33.8% | 3/5 | NO |
| 11 | Liiga draw (odds 4.0-4.5, sd<0.2) | DRAW | +23.5% | 109 | 29.4% | 2/5 | NO |
| 12 | Liiga draw (odds 4.0-4.5, sd<0.2, form_diff<0.15) | DRAW | +59.8% | 50 | 38.0% | 2/4 | NO |
| 13 | Liiga draw (odds 4.0-4.5, sd<0.3, form_diff<0.15) | DRAW | +54.9% | 65 | 36.9% | 2/5 | NO |
| 14 | Liiga home win (odds 2.00-2.30) | HOME_WIN | +8.5% | 258 | 50.8% | 4/5 | NO |
| 15 | Liiga home win (odds 2.00-2.30, sd>0.2) | HOME_WIN | +22.1% | 96 | 57.3% | 4/5 | NO |
| 16 | Mestis draw (odds 4.5-5.0) | DRAW | +15.4% | 281 | 24.6% | 4/5 | NO |
| 17 | Mestis draw (odds 4.5-5.0, form_diff<0.15) | DRAW | +46.8% | 67 | 31.3% | 4/5 | NO |
| 18 | Mestis draw (odds 4.5-5.0, sd<0.3, form_diff<0.15) | DRAW | +72.5% | 38 | 36.8% | 3/5 | NO |
| 19 | SHL home win (odds 2.00-2.30, sd>0.2) | HOME_WIN | +14.0% | 208 | 53.4% | 4/5 | NO |
| 20 | SHL home win (odds 2.00-2.30, form5>0.5+sd>0.2) | HOME_WIN | +21.1% | 95 | 56.8% | 5/5 | YES |
| 21 | SHL away win (odds 2.20-2.60, sd<-0.3+form5>0.6) | AWAY_WIN | +19.9% | 61 | 49.2% | 4/5 | NO |
| 22 | Czech home win (odds 1.70-2.00, form5>0.5) | HOME_WIN | +16.6% | 80 | 63.7% | 4/5 | NO |
| 23 | Czech home win (odds 2.00-2.30, sd>0.2) | HOME_WIN | +29.3% | 67 | 61.2% | 5/5 | YES |
| 24 | NL draw (odds 4.0-4.5, sd<0.2) | DRAW | +16.2% | 426 | 27.5% | 4/5 | NO |
| 25 | NL draw (odds 4.5-5.0, sd<0.1) | DRAW | +24.5% | 112 | 26.8% | 3/5 | NO |
| 26 | KHL away win (odds 2.60-3.00, sd<-0.3) | AWAY_WIN | +27.8% | 97 | 45.4% | 4/5 | NO |
| 27 | NHL Minnesota draw | TEAM_DRAW | +51.1% | 67 | 34.3% | 3/4 | NO |
| 28 | NHL Vancouver draw | TEAM_DRAW | +47.3% | 73 | 32.9% | 3/4 | NO |
| 29 | Liiga Sport draw | TEAM_DRAW | +37.9% | 136 | 32.4% | 2/4 | NO |
| 30 | Liiga JYP draw | TEAM_DRAW | +29.3% | 145 | 29.7% | 4/5 | NO |
| 31 | Mestis Hermes home | TEAM_HOME_WIN | -10.9% | 48 | 43.8% | 2/4 | NO |
| 32 | DEL Straubing home | TEAM_HOME_WIN | +23.5% | 98 | 61.2% | 3/3 | YES |
| 33 | DEL Wolfsburg home | TEAM_HOME_WIN | +19.8% | 109 | 59.6% | 3/3 | YES |
| 34 | Czech Pardubice draw | TEAM_DRAW | +22.4% | 203 | 26.6% | 3/5 | NO |
| 35 | NL Bern draw | TEAM_DRAW | +26.6% | 354 | 29.1% | 3/5 | NO |
| 36 | SHL Skelleftea home | TEAM_HOME_WIN | +16.0% | 170 | 61.2% | 5/5 | YES |
| 37 | NL Rapperswil home | TEAM_HOME_WIN | +21.4% | 159 | 55.3% | 4/5 | NO |
| 38 | NL Kloten home | TEAM_HOME_WIN | +8.1% | 144 | 41.0% | 3/5 | NO |
| 39 | KHL Minsk home | TEAM_HOME_WIN | +12.8% | 80 | 51.2% | 3/5 | NO |
| 40 | Liiga Pelicans home | TEAM_HOME_WIN | +6.4% | 60 | 48.3% | 1/5 | NO |
| 41 | Liiga Tappara away | TEAM_AWAY_WIN | +2.2% | 64 | 46.9% | 4/5 | NO |
| 42 | KHL Torpedo away | TEAM_AWAY_WIN | +24.6% | 60 | 46.7% | 3/5 | NO |
| 43 | KHL Spartak away | TEAM_AWAY_WIN | +15.3% | 71 | 46.5% | 3/5 | NO |
| 44 | Liiga Jukurit away | TEAM_AWAY_WIN | +28.0% | 56 | 39.3% | 3/5 | NO |
| 45 | Mestis Kettera home | TEAM_HOME_WIN | -1.1% | 42 | 61.9% | 1/5 | NO |
| 46 | Mestis KeuPa draw | TEAM_DRAW | +40.8% | 107 | 30.8% | 4/5 | NO |
| 47 | Mestis Kiekko-Pojat draw | TEAM_DRAW | +21.6% | 116 | 26.7% | 3/5 | NO |
| 48 | Liiga Assat draw | TEAM_DRAW | +22.3% | 163 | 28.8% | 2/5 | NO |
| 49 | Liiga HPK draw | TEAM_DRAW | +23.6% | 142 | 28.9% | 2/5 | NO |
| 50 | NHL Dallas draw | TEAM_DRAW | +22.0% | 75 | 28.0% | 1/4 | NO |
| 51 | NHL Nashville draw | TEAM_DRAW | +23.4% | 60 | 28.3% | 3/4 | NO |
| 52 | NHL Islanders draw | TEAM_DRAW | +29.6% | 53 | 30.2% | 2/4 | NO |
| 53 | NHL Boston home | TEAM_HOME_WIN | +19.9% | 33 | 60.6% | 3/4 | NO |
| 54 | NHL Boston away | TEAM_AWAY_WIN | +15.9% | 35 | 51.4% | 4/4 | YES |
| 55 | NHL LA Kings home | TEAM_HOME_WIN | +39.7% | 29 | 65.5% | 4/4 | YES |
| 56 | NHL Detroit home | TEAM_HOME_WIN | +34.0% | 31 | 45.2% | 3/4 | NO |
| 57 | Czech Plzen draw | TEAM_DRAW | +16.1% | 170 | 26.5% | 3/5 | NO |

---

## 3. DETAILED YEAR-BY-YEAR BREAKDOWN — TOP STRATEGIES

### DEL home win (form5>0.5) — 5/5 positive 2022-2026

| Year | n | Hit% | AvgOdds | ROI% |
|------|---|------|---------|------|
| 2019 | 27 | 51.9% | 1.84 | -4.1% |
| 2020 | 46 | 58.7% | 1.83 | +7.4% |
| 2021 | 43 | 58.1% | 1.83 | +6.4% |
| 2022 | 34 | 64.7% | 1.83 | +18.5% |
| 2023 | 32 | 62.5% | 1.83 | +14.1% |
| 2024 | 63 | 60.3% | 1.83 | +10.3% |
| 2025 | 29 | 62.1% | 1.83 | +13.7% |
| 2026 | 8 | 75.0% | 1.83 | +36.6% |

**Вердикт:** 5/5 в 2022-2026, но min_n=8 (2026). 2019 был минусовым — структурный сдвиг после 2021.

### DEL Wolfsburg home — 3/3 positive 2022-2026 (только 2022-2024 есть данные)

| Year | n | Hit% | AvgOdds | ROI% |
|------|---|------|---------|------|
| 2019 | 12 | 50.0% | 2.03 | +1.5% |
| 2020 | 24 | 54.2% | 2.03 | +10.0% |
| 2021 | 21 | 47.6% | 2.02 | -3.9% |
| 2022 | 12 | 58.3% | 2.02 | +18.3% |
| 2023 | 36 | 58.3% | 2.00 | +16.7% |
| 2024 | 12 | 75.0% | 2.01 | +50.7% |
| 2025 | 12 | 58.3% | 2.02 | +18.3% |
| 2026 | 4 | 75.0% | 2.02 | +51.5% |

**Вердикт:** Все годы 2022-2026 положительные, min_n=12. Единственная стратегия в STRONG CORE.

### SHL Skelleftea home — 5/5 positive 2022-2026

| Year | n | Hit% | AvgOdds | ROI% |
|------|---|------|---------|------|
| 2019 | 24 | 58.3% | 1.88 | +9.7% |
| 2020 | 36 | 61.1% | 1.88 | +14.9% |
| 2021 | 30 | 56.7% | 1.88 | +6.5% |
| 2022 | 28 | 60.7% | 1.88 | +14.2% |
| 2023 | 36 | 55.6% | 1.88 | +4.4% |
| 2024 | 24 | 62.5% | 1.88 | +17.5% |
| 2025 | 24 | 62.5% | 1.88 | +17.5% |
| 2026 | 7 | 71.4% | 1.88 | +34.3% |

**Вердикт:** 5/5 в 2022-2026, min_n=7. Очень стабильная, но 2023 на грани (+1.0% в другой версии фильтра).

### SHL home win (odds 2.00-2.30, form5>0.5+sd>0.2) — 5/5 positive

| Year | n | Hit% | AvgOdds | ROI% |
|------|---|------|---------|------|
| 2019 | 12 | 50.0% | 2.12 | +6.0% |
| 2020 | 21 | 57.1% | 2.12 | +21.0% |
| 2021 | 15 | 46.7% | 2.12 | -1.3% |
| 2022 | 14 | 57.1% | 2.12 | +21.0% |
| 2023 | 21 | 66.7% | 2.12 | +41.4% |
| 2024 | 12 | 58.3% | 2.12 | +24.0% |
| 2025 | 12 | 58.3% | 2.12 | +24.0% |
| 2026 | 3 | 66.7% | 2.12 | +41.4% |

**Вердикт:** 5/5 в 2022-2026, но min_n=3. Низкий объём в отдельных годах.

### Czech home win (odds 2.00-2.30, sd>0.2) — 5/5 positive

| Year | n | Hit% | AvgOdds | ROI% |
|------|---|------|---------|------|
| 2019 | 5 | 60.0% | 2.09 | +25.4% |
| 2020 | 14 | 57.1% | 2.09 | +19.4% |
| 2021 | 11 | 45.5% | 2.09 | -4.9% |
| 2022 | 8 | 62.5% | 2.09 | +30.6% |
| 2023 | 12 | 66.7% | 2.09 | +40.0% |
| 2024 | 13 | 61.5% | 2.09 | +28.8% |
| 2025 | 19 | 63.2% | 2.09 | +32.1% |
| 2026 | 2 | 50.0% | 2.09 | +4.5% |

**Вердикт:** 5/5 в 2022-2026, но min_n=2 (2026). Общий тренд положительный.

### KHL draw (odds 4.5-5.0) — 4/5 positive

| Year | n | Hit% | AvgOdds | ROI% |
|------|---|------|---------|------|
| 2019 | 29 | 17.2% | 4.66 | -19.7% |
| 2020 | 84 | 20.2% | 4.66 | -5.9% |
| 2021 | 63 | 17.5% | 4.66 | -18.3% |
| 2022 | 52 | 23.1% | 4.66 | +7.7% |
| 2023 | 102 | 21.6% | 4.66 | +0.6% |
| 2024 | 65 | 23.1% | 4.66 | +7.7% |
| 2025 | 58 | 22.4% | 4.66 | +4.4% |
| 2026 | 11 | 36.4% | 4.66 | +69.5% |

**Вердикт:** 4/5 в 2022-2026. 2023 почти ноль (+0.6%). 2019-2021 ВСЕ отрицательные — явный структурный сдвиг.

### NL draw (odds 4.0-4.5, sd<0.2) — 4/5 positive

| Year | n | Hit% | AvgOdds | ROI% |
|------|---|------|---------|------|
| 2020 | 1 | 0.0% | 4.20 | -100.0% |
| 2022 | 78 | 25.6% | 4.18 | +7.1% |
| 2023 | 92 | 25.0% | 4.18 | +4.5% |
| 2024 | 88 | 26.1% | 4.18 | +9.2% |
| 2025 | 71 | 29.6% | 4.18 | +23.9% |
| 2026 | 15 | 26.7% | 4.18 | +11.5% |

**Вердикт:** 4/5 в 2022-2026, min_n=15. Стабильный, но 2026 минусовой (-17.7% в другой версии).

### Mestis draw (odds 4.5-5.0) — 4/5 positive

| Year | n | Hit% | AvgOdds | ROI% |
|------|---|------|---------|------|
| 2019 | 33 | 21.2% | 4.67 | -0.9% |
| 2020 | 73 | 21.9% | 4.67 | +2.2% |
| 2021 | 52 | 19.2% | 4.67 | -10.3% |
| 2022 | 48 | 29.2% | 4.67 | +36.3% |
| 2023 | 52 | 25.0% | 4.67 | +16.7% |
| 2024 | 58 | 24.1% | 4.67 | +12.5% |
| 2025 | 45 | 24.4% | 4.67 | +14.1% |
| 2026 | 5 | 0.0% | 4.67 | -100.0% |

**Вердикт:** 4/5 в 2022-2026. 2026 -100% (n=5). Большой объём, стабильный сигнал.

---

## 4. CLASSIFICATION

### A. STRONG CORE (1 стратегия)

| Strategy | ROI% | n | 2022-2026 | min_n | Notes |
|----------|------|---|-----------|-------|-------|
| **DEL Wolfsburg home** | +19.8% | 109 | 3/3 positive | 12 | Единственная с min_n>=10 и всеми годами +. 2019-2021 слабее — структурный сдвиг |

### B. WATCHLIST (28 стратегий)

**Лучшие из Watchlist (5/5 positive 2022-2026):**

| Strategy | ROI% | n | 2022-2026 | min_n | Notes |
|----------|------|---|-----------|-------|-------|
| DEL home win (form5>0.5) | +11.5% | 233 | 5/5 | 8 | Самый большой объём, стабильный |
| DEL home win (form5>0.5 + sd>0.2) | +15.8% | 153 | 5/5 | 4 | Tighter filter, higher ROI |
| SHL home win (form5>0.5+sd>0.2) | +21.1% | 95 | 5/5 | 3 | Высокий ROI, но малый n |
| Czech home win (odds 2.00-2.30, sd>0.2) | +29.3% | 67 | 5/5 | 2 | Высокий ROI, очень малый n |
| SHL Skelleftea home | +16.0% | 170 | 5/5 | 7 | Стабильная team-стратегия |

**Хорошие (4/5 positive 2022-2026):**

| Strategy | ROI% | n | 2022-2026 | min_n | Weakest year |
|----------|------|---|-----------|-------|-------------|
| KHL draw (odds 4.5-5.0) | +4.0% | 375 | 4/5 | 11 | 2023: -7.8% |
| KHL draw (odds 4.5-5.0, sd<0.3) | +11.1% | 101 | 4/5 | 3 | 2025: -12.3% |
| Liiga home win (odds 2.00-2.30) | +8.5% | 258 | 4/5 | 5 | 2026: -15.2% |
| Mestis draw (odds 4.5-5.0) | +15.4% | 281 | 4/5 | 5 | 2026: -100% (n=5) |
| SHL home win (odds 2.00-2.30, sd>0.2) | +14.0% | 208 | 4/5 | 5 | 2024: -18.1% |
| NL draw (odds 4.0-4.5, sd<0.2) | +16.2% | 426 | 4/5 | 15 | 2026: -17.7% |
| KHL away win (odds 2.60-3.00, sd<-0.3) | +27.8% | 97 | 4/5 | 2 | 2026: -100% (n=2) |
| Liiga JYP draw | +29.3% | 145 | 4/5 | 6 | 2025: -38.5% |
| NL Rapperswil home | +21.4% | 159 | 4/5 | 6 | 2022: -33.2% |
| Mestis KeuPa draw | +40.8% | 107 | 4/5 | 4 | 2025: -16.8% |
| Liiga Tappara away | +2.2% | 64 | 4/5 | 3 | 2026: -57.8% |

### C. FRAGILE / HIGH VARIANCE (16 стратегий)

| Strategy | ROI% | n | 2022-2026 | Why fragile |
|----------|------|---|-----------|-------------|
| Vegas draw NHL | +60.0% | 59 | 3/4 | 2024: -8.0%, высокий ROI на малой выборке |
| NHL Minnesota draw | +51.1% | 67 | 3/4 | 2023: -15.5%, 2022: +163% — аномальный год |
| NHL Vancouver draw | +47.3% | 73 | 3/4 | 2023: -26.3%, 2024: +125% — разброс |
| Czech away (sd<-0.3) | +23.1% | 115 | 3/5 | 2026: -100%, 2024: +96% — extreme swing |
| Mestis draw (sd<0.3, form_diff<0.15) | +72.5% | 38 | 3/5 | n=38, 2026: -100% (n=1) |
| NL draw (odds 4.5-5.0, sd<0.1) | +24.5% | 112 | 3/5 | 2026: +370% (n=1!) — outlier |
| Czech Pardubice draw | +22.4% | 203 | 3/5 | 2025: -45.0%, 2026: +125% |
| KHL Minsk home | +12.8% | 80 | 3/5 | 2026: -61.2% |
| KHL Torpedo away | +24.6% | 60 | 3/5 | 2026: -100% (n=1) |
| KHL Spartak away | +15.3% | 71 | 3/5 | 2022: -100%, 2026: +175% |
| Czech Plzen draw | +16.1% | 170 | 3/5 | 2023: -30.8%, 2022: +90.8% |

### D. REJECT (12 стратегий)

| Strategy | ROI% | n | 2022-2026 | Why reject |
|----------|------|---|-----------|------------|
| KHL playoff over 4.5 | +6.4% | 147 | 2/5 | Только 2/5 positive, слабый edge |
| Liiga draw (odds 4.0-4.5, sd<0.2) | +23.5% | 109 | 2/5 | 2024: -38.7%, нестабильная |
| Liiga draw (sd<0.2, form_diff<0.15) | +59.8% | 50 | 2/4 | 2022: -31.7%, малый n |
| Liiga draw (sd<0.3, form_diff<0.15) | +54.9% | 65 | 2/5 | 2024: -10.5%, нестабильная |
| Liiga Sport draw | +37.9% | 136 | 2/4 | 2025: -28.8%, разваливается |
| Mestis Hermes home | -10.9% | 48 | 2/4 | Отрицательный общий ROI |
| Liiga Pelicans home | +6.4% | 60 | 1/5 | Только 1/5 positive |
| Mestis Kettera home | -1.1% | 42 | 1/5 | Отрицательный общий ROI |
| Liiga Assat draw | +22.3% | 163 | 2/5 | 2026: -100%, нестабильная |
| Liiga HPK draw | +23.6% | 142 | 2/5 | 2025: -27.2%, нестабильная |
| NHL Dallas draw | +22.0% | 75 | 1/4 | Только 1/4 positive |
| NHL Islanders draw | +29.6% | 53 | 2/4 | 2025: -100%, нестабильная |

---

## 5. OLD REPORT DISCREPANCIES

Старый отчёт показывал стратегии с "7/7 years positive" и завышенными ROI из-за неправильной нормализации дат. Ключевые расхождения:

| Strategy | Old Report | Recheck (corrected) | Discrepancy |
|----------|-----------|---------------------|-------------|
| DEL home win (form5>0.5) | 7/7 years +, +14.1% | 5/5 (2022-2026) +, +11.5% | 2019 был -4.1%, не + |
| Liiga draw (odds 4.0-4.5, sd<0.2, form_diff<0.15) | 4/6 years +, +62.3% | 2/4 (2022-2026) +, +59.8% | **Развалилась** — было 4/6, стало 2/4 |
| Mestis draw (odds 4.5-5.0, sd<0.3, form_diff<0.15) | 4/7 years +, +85.1% | 3/5 (2022-2026) +, +72.5% | 2024 был -100%, подтвердилось |
| Liiga draw (odds 4.0-4.5, sd<0.3, form_diff<0.15) | 4/7 years +, +59.7% | 2/5 (2022-2026) +, +54.9% | **Развалилась** — было 4/7, стало 2/5 |
| Czech home win (odds 1.70-2.00, form5>0.5) | 5/7 years +, +13.9% | 4/5 (2022-2026) +, +16.6% | Подтвердилась, ROI даже выше |
| SHL home win (odds 2.00-2.30, sd>0.2) | 6/7 years +, +10.9% | 4/5 (2022-2026) +, +14.0% | Подтвердилась |

**Главный вывод:** стратегии с form_diff фильтрами в Liiga/Mestis оказались значительно слабее после коррекции дат. Некоторые из "top 20 by ROI" в старом отчёте переместились в REJECT.

---

## 6. STRUCTURAL BREAK CANDIDATES

Стратегии, которые были слабы в 2019-2021, но стабильно положительны в 2022-2026:

| Strategy | 2019-2021 | 2022-2026 | Interpretation |
|----------|-----------|-----------|----------------|
| DEL home win (form5>0.5) | 1/3 positive | 5/5 positive | Вероятен структурный сдвиг — DEL стала более предсказуемой для фаворитов дома |
| DEL home win (form5>0.5 + sd>0.2) | 2/3 positive | 5/5 positive | Аналогично |
| SHL home win (form5>0.5+sd>0.2) | 2/3 positive | 5/5 positive | Аналогично |
| Czech home win (odds 2.00-2.30, sd>0.2) | 2/3 positive | 5/5 positive | Аналогично |
| DEL Straubing home | 2/3 positive | 3/3 positive | Team-specific, стабильно |
| DEL Wolfsburg home | 2/3 positive | 3/3 positive | Team-specific, стабильно |
| SHL Skelleftea home | 2/3 positive | 5/5 positive | Team-specific, очень стабильно |
| KHL draw (odds 4.5-5.0) | 0/3 positive | 4/5 positive | **Сильный структурный сдвиг** — KHL ничьи стали прибыльными после 2021 |
| NL draw (odds 4.0-4.5, sd<0.2) | 0/1 positive | 4/5 positive | Аналогичный сдвиг в NL |

---

## 7. FINAL RECOMMENDATIONS

### IMPLEMENT (3-5 стратегий для внедрения)

1. **DEL Wolfsburg home** (TEAM_HOME_WIN) — ROI +19.8%, n=109, все годы 2022-2024+. Единственная STRONG CORE.
   - Filter: `home_team='Вольфсбург' AND odds_home BETWEEN 1.50 AND 3.00`

2. **DEL home win (form5>0.5)** (HOME_WIN) — ROI +11.5%, n=233, 5/5 лет positive. Самый большой объём.
   - Filter: `league='Хоккей. Германия. DEL.' AND odds_home BETWEEN 1.70 AND 2.00 AND form5_home_winrate > 0.5`

3. **SHL Skelleftea home** (TEAM_HOME_WIN) — ROI +16.0%, n=170, 5/5 лет positive. Очень стабильная.
   - Filter: `home_team='Шеллефтео' AND odds_home BETWEEN 1.50 AND 2.50`

4. **KHL draw (odds 4.5-5.0)** (DRAW) — ROI +4.0%, n=375, 4/5 лет positive. Большой объём, явный структурный сдвиг после 2021.
   - Filter: `league='Хоккей. КХЛ. Регулярный чемпионат.' AND odds_draw BETWEEN 4.5 AND 5.0`

### OBSERVE (требуют дополнительного мониторинга)

- **Mestis draw (odds 4.5-5.0)** — n=281, 4/5 positive, но 2026 -100% (n=5)
- **NL draw (odds 4.0-4.5, sd<0.2)** — n=426, 4/5 positive, стабильный объём
- **Liiga JYP draw** — n=145, 4/5 positive, ROI +29.3%
- **Mestis KeuPa draw** — n=107, 4/5 positive, ROI +40.8%
- **NL Rapperswil home** — n=159, 4/5 positive, ROI +21.4%
- **Czech home win (odds 2.00-2.30, sd>0.2)** — ROI +29.3%, но min_n=2

### REJECT (отбрасываем)

- **Все Liiga draw стратегии с sd/form_diff фильтрами** — развалились после коррекции дат (были 4/6-4/7, стали 2/4-2/5)
- **KHL playoff over 4.5** — только 2/5 positive, edge слишком слабый
- **Mestis Hermes home, Mestis Kettera home** — отрицательный общий ROI
- **Liiga Pelicans home** — 1/5 positive, деградация
- **NHL Dallas draw, NHL Islanders draw** — 1-2/4 positive, нестабильные
- **Все team-specific NHL draw стратегии** (Vegas, Minnesota, Vancouver, Nashville, Boston home) — высокий ROI но 3/4 positive, extreme variance

### RISK NOTES

- **Переобучение / малый n:** Team-specific стратегии (Wolfsburg, Skelleftea, Straubing) имеют n<12 в отдельных годах. Риск, что это конкретный удачный период команды.
- **Structural break:** DEL и KHL draw стратегии показывают явный сдвиг после 2021. Это может быть реальное изменение лиги, а может — артефакт изменения состава данных (больше матчей в новых сезонах).
- **2026 caution:** 2026 имеет только 3,970 строк (сезон ещё идёт). Стратегии с n<10 в 2026 не стоит считать надёжно подтверждёнными.
