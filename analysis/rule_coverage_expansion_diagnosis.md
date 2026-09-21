# Rule Coverage Expansion Diagnosis — 2026-04-11

## Executive Summary

**170 football matches** в базе (2026-03-20 — 2026-04-23), 13 активных правил.
Из них **12 прошли хотя бы 1 матч**, но суммарно только **~12 уникальных матчей** из 170 дают rule-driven сигнал.

**Главный bottleneck:** не отсутствие матчей в лигах, а **слишком узкие odds ranges** и **требовательные form/goals thresholds**. BTTS-правила особенно страдают — BTTS odds в live-матчах часто выходят за пределы узких диапазонов (1.95-2.10, 1.75-1.95 и т.д.).

**NLA_BERN_AWAY_DRAW** — 0 матчей в лиге (швейцарский чемпионат не в сезоне).

---

## 1. Funnel Per Rule

| Rule | League Matches | Has Odds | Passed All | Drop-off Rate |
|------|---------------|----------|------------|---------------|
| **DRAW_SA** | 21 | 21 | **1** | 95% |
| **DRAW_BALANCED_LOW_SCORING_SA** | 21 | 21 | **1** | 95% |
| **DRAW_BALANCED_LINE_SA** | 21 | 21 | **1** | 95% |
| **SA_AWAY_DRAW** | 21 | 21 | **0** | 100% |
| **AWAY_SA_STRICT_PLUS** | 21 | 21 | **0** | 100% |
| **BTTS_YES_CORE** | 43 | 43 | **0** | 100% |
| **RPL_OVER25_BTTS** | 19 | 19 | **5** | 74% |
| **PD_BTTS_DOUBLE** | 23 | 23 | **1** | 96% |
| **FL1_BTTS_DOUBLE** | 16 | 16 | **0** | 100% |
| **NLA_BERN_AWAY_DRAW** | 0 | 0 | **0** | N/A |
| **MLS_BTTS_HOME** | 18 | 15 | **1** | 94% |
| **PD_AWAY_VALUE** | 23 | 23 | **1** | 96% |
| **SUMMER_BTTS_HOME** | 30 | 30 | **1** | 97% |

**Итого:** 12 passed из 170 матчей = **7% coverage**.

---

## 2. Top Bottlenecks by Rule

### Serie A Draw Rules (DRAW_SA, DRAW_BALANCED_*)
**Bottleneck:** `max_scored > 1.55` и `max_allowed > 1.75/1.65`
- Большинство матчей Серии А имеют команды со средними голами > 1.55
- Это самый жёсткий фильтр — отсекает ~80% Serie A матчей даже при подходящих odds

### SA_AWAY_DRAW (0 passed)
**Bottleneck:** `away_team not in {Empoli, Genoa, Cremonese, Salernitana, Venezia}`
- Ни один из текущих away-матчей Серии А не содержит эти команды
- Это hard-coded team list, который зависит от сезона

### AWAY_SA_STRICT_PLUS (0 passed)
**Bottleneck:** `no_pos_gap` (4 матча без таблицы) + `away_odds not in [2.05,2.85]`
- Когда away odds есть, они обычно вне диапазона (слишком высокие или слишком низкие)
- Form diff >= 4 — очень жёсткое требование

### BTTS_YES_CORE (0 passed)
**Bottleneck:** `btts_odds not in [1.95,2.10]` для BL1, `[2.00,2.10]` для EPL
- Текущие BTTS odds: 1.40, 1.52, 1.55, 1.67, 1.70, 1.75, 1.85, 1.90, 1.92
- **Ни один матч не попадает в узкий диапазон 1.95-2.10**
- Это главная причина 0% coverage — рынок сейчас даёт BTTS odds ниже порога

### RPL_OVER25_BTTS (5 passed — BEST performing rule)
- Единственное правило с decent coverage
- Bottleneck для остальных: `over25 not in [1.8,2.1]` или `form_pts < 4`

### PD_BTTS_DOUBLE (1 passed)
**Bottleneck:** `over25 not in [1.6,1.9]` — большинство матчей имеют over2.5 > 1.9

### FL1_BTTS_DOUBLE (0 passed)
**Bottleneck:** `over25 not in [1.6,1.9]` (2.08, 2.12) + `btts not in [2.0,2.1]` (1.75)
- Двойной фильтр слишком жёсткий для текущих odds

### NLA_BERN_AWAY_DRAW (0 passed)
**Bottleneck:** `NO_MATCHES_IN_LEAGUE` — швейцарская лига не в сезоне (апрель)

### MLS_BTTS_HOME (1 passed)
**Bottleneck:** `home_team not in MLS list` (Ванкувер, Торонто, Монреаль, Остин — не в списке) + `no_btts_odds` (3 матча)

### PD_AWAY_VALUE (1 passed)
**Bottleneck:** `away_odds not in [2.00,2.50]` — away odds часто 2.85-4.80 или < 2.00

### SUMMER_BTTS_HOME (1 passed)
**Bottleneck:** `league_key=NOR/IRL not in summer` (15 матчей) — NOR и IRL есть в FOOTBALL_LEAGUE_STAKING но НЕ в SUMMER_TEAMS dict внутри `get_pruned_live_rule()`. Также `home_team not in summer list` для большинства команд.

---

## 3. 10 Nearest Matches — Detailed Breakdown

### Match 1: Лейпциг vs Хоффенхайм (BL1, 2026-03-20)
- **BTTS_YES_CORE:** FAIL — btts=1.40 (слишком низкие, рынок уверен в BTTS)
- Все остальные: FAIL — не та лига
- **Вердикт:** Нет rule candidate. BTTS odds слишком низкие для узкого диапазона.

### Match 2: Дженоа vs Удинезе (SA, 2026-03-20)
- **DRAW_SA:** FAIL — draw_odds=2.35 (не в [3.0,3.85])
- **SA_AWAY_DRAW:** FAIL — Удинезе не в списке аутсайдеров
- **Вердикт:** Draw odds слишком низкие — рынок ожидает низовой матч, но не ничью.

### Match 3: Борнмут vs Манчестер Юнайтед (EPL, 2026-03-20)
- **BTTS_YES_CORE:** FAIL — btts=1.85 (не в [2.00,2.10])
- **Вердикт:** BTTS odds ниже порога.

### Match 4: Ахмат vs Ростов (RPL, 2026-03-21)
- **RPL_OVER25_BTTS:** FAIL — over25=2.20 (не в [1.8,2.1])
- **Вердикт:** Over2.5 odds слишком высокие — рынок не ждёт голов.

### Match 5: Брайтон vs Ливерпуль (EPL, 2026-03-21)
- **BTTS_YES_CORE:** FAIL — btts=1.52 (не в [2.00,2.10])
- **Вердикт:** BTTS odds слишком низкие.

### Match 6: Эльче vs Мальорка (PD, 2026-03-21)
- **PD_BTTS_DOUBLE:** FAIL — over25=2.05 (не в [1.6,1.9])
- **PD_AWAY_VALUE:** FAIL — away_odds=3.75 (не в [2.00,2.50])
- **Вердикт:** Оба рынка не попадают.

### Match 7: Бавария vs Унион Берлин (BL1, 2026-03-21)
- **BTTS_YES_CORE:** FAIL — btts=1.92 (не в [1.95,2.10], близко но не проходит!)
- **Вердикт:** BTTS=1.92 — всего 0.03 до порога.

### Match 8: Вольфсбург vs Вердер (BL1, 2026-03-21)
- **BTTS_YES_CORE:** FAIL — btts=1.55 (далеко от [1.95,2.10])
- **Вердикт:** BTTS odds слишком низкие.

### Match 9: Кёльн vs Боруссия М (BL1, 2026-03-21)
- **BTTS_YES_CORE:** FAIL — btts=1.70 (не в [1.95,2.10])
- **Вердикт:** BTTS odds слишком низкие.

### Match 10: Тулуза vs Лорьян (FL1, 2026-03-21)
- **FL1_BTTS_DOUBLE:** FAIL — over25=2.12 (не в [1.6,1.9])
- **Вердикт:** Over2.5 слишком высокий.

---

## 4. Minimal Safe Parameter Expansions

Тестирование расширенных порогов на текущих данных:

| Rule | Current Criteria | Proposed Expansion | Would Pass | Risk |
|------|-----------------|-------------------|------------|------|
| **BTTS_YES_CORE** | EPL: 2.00-2.10, BL1: 1.95-2.10 | EPL: 1.85-2.15, BL1: 1.80-2.15 | ~3-5 | Низкий — расширение на 0.10-0.15 |
| **PD_BTTS_DOUBLE** | over25: 1.6-1.9, btts: 1.75-1.95 | over25: 1.5-2.0, btts: 1.70-2.00 | ~2-3 | Средний — шире диапазон |
| **FL1_BTTS_DOUBLE** | over25: 1.6-1.9, btts: 2.0-2.1 | over25: 1.5-2.15, btts: 1.95-2.15 | ~1-2 | Средний |
| **RPL_OVER25_BTTS** | over25: 1.8-2.1, btts: 1.8-2.1 | over25: 1.7-2.2, btts: 1.7-2.2 | ~2-3 | Низкий — уже лучшее правило |
| **AWAY_SA_STRICT_PLUS** | away_odds: 2.05-2.85, pos_gap: <=-4 | away_odds: 2.00-3.00, pos_gap: <=-2 | ~1-2 | Средний — form diff тоже ослабить |
| **DRAW_SA** | goals <= 1.55, conceded <= 1.75 | goals <= 1.75, conceded <= 2.0 | ~2-3 | Средний — больше голов = меньше ничьих |
| **DRAW_BALANCED_LOW_SCORING_SA** | goals <= 1.55, conceded <= 1.65 | goals <= 1.75, conceded <= 1.85 | ~1-2 | Средний |
| **SUMMER_BTTS_HOME** | DNK/SWE/FIN only | + NOR/IRL + расширить team list | ~3-5 | Низкий — NOR/IRL уже в staking config |

### Конкретные изменения в коде:

```python
# BTTS_YES_CORE (line ~632):
btts_min = 1.85 if is_epl() else 1.80  # было 2.00/1.95
btts_max = 2.15  # было 2.10

# PD_BTTS_DOUBLE (line ~676):
if 1.5 <= over25 <= 2.0 and 1.70 <= btts <= 2.00:  # было 1.6-1.9 / 1.75-1.95

# FL1_BTTS_DOUBLE (line ~698):
if 1.5 <= over25 <= 2.15 and 1.95 <= btts <= 2.15:  # было 1.6-1.9 / 2.0-2.1

# RPL_OVER25_BTTS (line ~658):
if 1.7 <= over25 <= 2.2 and 1.7 <= btts <= 2.2:  # было 1.8-2.1

# AWAY_SA_STRICT_PLUS (line ~603):
if 2.00 <= float(match.odds_away) <= 3.00:  # было 2.05-2.85
if pg is not None and pg <= -2:  # было -4

# DRAW_SA (line ~565):
if max(float(home_scored), float(away_scored)) <= 1.75:  # было 1.55
if max(float(home_allowed), float(away_allowed)) <= 2.0:  # было 1.75

# SUMMER_BTTS_HOME: добавить NOR и IRL в _SUMMER_TEAMS
```

**Ожидаемый результат:** с ~12 до ~25-30 passed матчей из 170 (coverage 7% → 15-18%).

---

## 5. Final Recommendation

### KEEP (оставить без изменений)

| Rule | Reason |
|------|--------|
| **RPL_OVER25_BTTS** | Лучшее покрытие (5/19 = 26%), ROI +13.4%, двойное подтверждение |
| **PD_AWAY_VALUE** | Простое правило (только odds + team name), ROI +14%, n=264 |

### EXPAND (расширить параметры)

| Rule | Expansion | Expected Gain |
|------|-----------|---------------|
| **BTTS_YES_CORE** | Расширить BTTS odds range до 1.80-2.15 | 0 → 3-5 матчей |
| **PD_BTTS_DOUBLE** | Расширить over25 до 1.5-2.0, btts до 1.70-2.00 | 1 → 3-4 матча |
| **FL1_BTTS_DOUBLE** | Расширить over25 до 1.5-2.15, btts до 1.95-2.15 | 0 → 1-2 матча |
| **DRAW_SA** | goals <= 1.75, conceded <= 2.0 | 1 → 3-4 матча |
| **DRAW_BALANCED_LOW_SCORING_SA** | goals <= 1.75, conceded <= 1.85 | 1 → 2-3 матча |
| **AWAY_SA_STRICT_PLUS** | odds 2.00-3.00, pos_gap <= -2 | 0 → 1-2 матча |
| **SUMMER_BTTS_HOME** | Добавить NOR/IRL, расширить team list | 1 → 4-6 матчей |

### DISABLE (отключить live)

| Rule | Reason |
|------|--------|
| **NLA_BERN_AWAY_DRAW** | 0 матчей в лиге (сезон апрель-май, сейчас нет матчей). Оставить только для backtest. |
| **SA_AWAY_DRAW** | Hard-coded team list ({Empoli, Genoa, Cremonese, Salernitana, Venezia}) — зависит от сезона. Если этих команд нет в текущем составе Serie A, правило мертво. Нужно обновить список или перевести в backtest-only. |

---

## 6. Root Cause Analysis

### Почему rule-driven path даёт так мало сигналов:

1. **BTTS odds ranges слишком узкие** — BTTS_YES_CORE требует 1.95-2.10 (BL1) или 2.00-2.10 (EPL). Текущие live odds: 1.40-1.92. **Это #1 причина.** Рынок сейчас оценивает BTTS вероятность выше, чем ожидают правила.

2. **Goals thresholds слишком жёсткие** — DRAW_SA требует avg goals <= 1.55. Большинство команд Серии А забивают больше.

3. **Form thresholds** — PD_BTTS_DOUBLE и FL1_BTTS_DOUBLE требуют away_form_pts >= 6. Это отсекает матчи где away команда в слабой форме.

4. **Seasonal mismatch** — NLA не в сезоне, SUMMER_TEAMS не покрывает NOR/IRL (хотя они есть в staking config).

5. **Data completeness** — только 64/170 матчей имеют form, 46/170 имеют standings. Но rule-driven path частично работает с fallback на season averages.

### Ключевой инсайт:

**BTTS-правила — самый большой источник потенциального volume** (43 матча в EPL/BL1/PD/FL1 с BTTS odds), но все они проваливаются на odds range check. Расширение BTTS диапазонов на 0.10-0.15 даст наибольший прирост coverage при минимальном риске, т.к. эти правила имеют исторически подтверждённый ROI.
