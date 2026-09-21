# CLV_TRACKING_SPEC.md
# BETAGENT — CLV Tracking Specification

Версия: v1 draft  
Статус: ready to implement

---

## 1. Цель

CLV tracking нужен для ответа на главный вопрос платформы:

**есть ли у системы реальный рыночный edge?**

ROI на короткой дистанции шумный.  
CLV показывает, **бьём ли мы closing line**.

Если модель системно получает цену лучше, чем closing odds, это сильный сигнал качества отбора.

---

## 2. Что считать CLV

Для каждого bet / recommendation нужно хранить:

- `open_odds` — коэффициент в момент первого появления матча в линии / snapshot
- `bet_odds` — коэффициент в момент принятия решения / создания ставки
- `closing_odds` — коэффициент непосредственно перед стартом матча
- `market` — home / draw / away / other
- `bet_probability` = `1 / bet_odds`
- `closing_probability` = `1 / closing_odds`

---

## 3. Базовые формулы

### 3.1 Простая CLV в odds

```text
clv_odds = bet_odds - closing_odds
```

Для back/ставки на исход:

- если `bet_odds > closing_odds` → хорошо
- если `bet_odds < closing_odds` → плохо

---

### 3.2 CLV в implied probability

```text
bet_implied_prob = 1 / bet_odds
closing_implied_prob = 1 / closing_odds
clv_prob = closing_implied_prob - bet_implied_prob
```

Интерпретация:

- `clv_prob > 0` → рынок к закрытию считает исход **более вероятным**, чем в момент ставки
- это хорошо для back-беттора

---

### 3.3 CLV percent

```text
clv_pct = (bet_odds / closing_odds) - 1
```

Или в probability-space:

```text
clv_prob_pct = (closing_implied_prob / bet_implied_prob) - 1
```

Для платформы удобнее хранить оба варианта.

---

## 4. Что является closing line

Для первой версии:

**closing odds = последний доступный snapshot odds перед началом матча**

Окно поиска:
- брать последний snapshot до `match_date`
- желательно за 0–15 минут до старта
- если такого нет — брать самый поздний snapshot до старта

Если нет ни одного snapshot до старта:
- `closing_odds = NULL`
- bet помечается как `clv_unavailable`

---

## 5. Источники данных

### 5.1 Уже доступные таблицы

В проекте уже архивируются:

- `odds_history`
- `match_feature_snapshots`
- `recommendation_snapshots`

Из них для CLV базово нужен `odds_history`.

### 5.2 Связка

CLV должен считаться по:

- `bets.match_id`
- `bets.market`
- `bets.odds`
- `matches.match_date`
- `odds_history` по тому же матчу

---

## 6. Новая таблица

```sql
CREATE TABLE IF NOT EXISTS clv_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    bet_id INTEGER,
    match_id INTEGER NOT NULL,
    sport TEXT,
    league TEXT,
    home_team TEXT,
    away_team TEXT,
    match_date TEXT,
    market TEXT NOT NULL,

    open_odds REAL,
    bet_odds REAL NOT NULL,
    closing_odds REAL,

    open_implied_prob REAL,
    bet_implied_prob REAL,
    closing_implied_prob REAL,

    clv_odds REAL,
    clv_pct REAL,
    clv_prob REAL,
    clv_prob_pct REAL,

    status TEXT DEFAULT 'pending',
    result TEXT,
    profit REAL,

    source_table TEXT DEFAULT 'bets',
    source_id TEXT,
    calculated_at TEXT NOT NULL,
    notes TEXT
);
```

Индексы:

```sql
CREATE INDEX IF NOT EXISTS idx_clv_history_bet_id ON clv_history(bet_id);
CREATE INDEX IF NOT EXISTS idx_clv_history_match_id ON clv_history(match_id);
CREATE INDEX IF NOT EXISTS idx_clv_history_calculated_at ON clv_history(calculated_at);
CREATE INDEX IF NOT EXISTS idx_clv_history_sport ON clv_history(sport);
```

---

## 7. Как выбирать odds по market

### 1X2 market mapping

- `market = home` → использовать `odds_home`
- `market = draw` → использовать `odds_draw`
- `market = away` → использовать `odds_away`

Для следующих версий:
- тоталы
- форы
- tennis moneyline
- mma moneyline
- basketball spread / total

Но v1 надо делать только на том, что уже стабильно хранится.

---

## 8. Алгоритм расчёта

### Для каждой ставки из `bets`

1. взять:
   - `bet_id`
   - `match_id`
   - `market`
   - `odds as bet_odds`

2. найти матч в `matches`
   - `sport`
   - `league`
   - `home_team`
   - `away_team`
   - `match_date`

3. из `odds_history` найти:
   - `open_odds` = самый ранний snapshot odds по этому market
   - `closing_odds` = самый поздний snapshot odds до `match_date`

4. посчитать:
   - implied probabilities
   - clv_odds
   - clv_pct
   - clv_prob
   - clv_prob_pct

5. записать результат в `clv_history`

---

## 9. Когда запускать

### v1
Запускать после settle или в конце pipeline:

- после `historical_archive_v1.py --snapshot`
- лучше отдельным шагом `task_clv()`

### Рекомендуемый порядок
1. parse
2. archive snapshot
3. bet / settle
4. clv update

---

## 10. KPI и отчёты

Нужно считать:

### Production metrics
- average CLV
- median CLV
- % bets with positive CLV
- CLV by sport
- CLV by league
- CLV by odds band
- CLV by model / module

### Research metrics
- CLV for legacy production
- CLV for shadow engine
- CLV by validator mode
- CLV by confidence band
- CLV by shortlist strategy

---

## 11. Ключевая интерпретация

### Если:
- ROI отрицательный
- CLV положительный

Это может означать:
- edge есть, но выборка маленькая
- variance / unlucky run
- плохой settlement period

### Если:
- ROI положительный
- CLV отрицательный

Это тревожный сигнал:
- скорее всего lucky run
- стратегия не бьёт closing market
- production нельзя масштабировать без доп.проверки

### Если:
- ROI положительный
- CLV положительный

Это лучший сигнал.

---

## 12. Что считать success criteria

Для production / research:

- positive average CLV
- >50% ставок с положительным CLV
- стабильный CLV across leagues / modules
- отсутствие сильной деградации на отдельных рынках

---

## 13. Ограничения v1

v1 НЕ решает:

- closing line с нескольких букмекеров
- многорынковые линии кроме 1X2
- линии без snapshot coverage
- live-betting CLV

Это нормально.  
Главное — быстро внедрить базовый измеритель edge.

---

## 14. Практическое правило для проекта

**Новые стратегии, LLM-модули и расширение на новые спорты нельзя двигать в production, если они не показывают внятный CLV на shadow/backtest уровне.**
