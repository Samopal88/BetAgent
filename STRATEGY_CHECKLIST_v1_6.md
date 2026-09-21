# BETAGENT — Чеклист добавления новой стратегии

> Последнее обновление: 05.04.2026  
> Выстрадано на внедрении NLA_BERN_AWAY_DRAW, FL1_BTTS_DOUBLE, SA_AWAY_DRAW, MLS_BTTS_HOME

---

## 1. Бэктест в SQL (проверка гипотезы)

### Проверить данные
```sql
-- Доступные лиги и объём
SELECT league, COUNT(*), MIN(match_date), MAX(match_date) 
FROM backtest_hockey_matches 
WHERE league LIKE '%Швейцар%' 
GROUP BY league;

-- Проверить заполненность ключевых полей (хоккей)
SELECT 
  COUNT(*) as total,
  SUM(CASE WHEN went_ot_or_so IS NOT NULL THEN 1 ELSE 0 END) as has_ot,
  SUM(CASE WHEN odds_draw IS NOT NULL THEN 1 ELSE 0 END) as has_draw_odds
FROM backtest_hockey_matches 
WHERE league='Хоккей. Швейцария. National League.';
```

### Важно: формат дат в backtest_hockey_matches
```sql
-- ❌ Неправильно — не работает для формата DD.MM.YYYY
strftime('%Y', match_date) as year

-- ✅ Правильно
substr(match_date, 7, 4) as year   -- год
substr(match_date, 4, 2) as month  -- месяц
substr(match_date, 1, 2) as day    -- день
```

### Шаблон проверки ROI по годам
```sql
SELECT 
  substr(match_date, 7, 4) as year,
  COUNT(*) as n,
  ROUND(AVG(went_ot_or_so)*100, 1) as draw_pct,
  ROUND(SUM(CASE WHEN went_ot_or_so=1 THEN odds_draw-1 ELSE -1 END)/COUNT(*)*100, 2) as roi
FROM backtest_hockey_matches
WHERE league='...'
  AND <условия стратегии>
GROUP BY year
ORDER BY year;
```

### Минимальные требования для принятия стратегии
- n >= 50 (лучше 100+)
- ROI > +15%
- Сезонов в плюсе >= 4/5
- MaxLS <= 10
- Просадка <= 25% банка

---

## 2. Добавить в `agent_handoff_v7.py`

### 2.1 Детектор лиги — функция `detect_league_key`

Найти функцию и добавить ПЕРЕД `return None`:
```python
# НОВАЯ ЛИГА detection
if any(term in l for term in ["ключевое_слово", "другое_слово"]):
    return "NEW_KEY"
return None
```

⚠️ **Частые ошибки:**
- Пробелы/переносы в строке мешают `str.replace()` — проверяй `repr()` перед патчем
- NLA не находилась потому что не была добавлена в эту функцию (добавили только в `detect_football_league_key`)

### 2.2 Конфиг лиги — `HOCKEY_LEAGUE_CONFIG`

```python
"NEW_KEY": {
    "mode": "single",          # "single" для одной стратегии
    "strategies": ["new_strategy_name"],
    "stake_mode": "flat_pct_1_00"
}
```

### 2.3 WR калибровка — `STRATEGY_HISTORICAL_WR`

```python
"NEW_STRATEGY": 0.342,  # Hit rate из бэктеста
```

### 2.4 min_ev — `STRATEGY_MIN_EV_PCT`

```python
"NEW_STRATEGY": 5,  # Минимальный EV в процентах
```

### 2.5 Отключить калибровку вероятности — `_no_calib`

```python
_no_calib = {"RPL_OVER25_BTTS", "PD_BTTS_DOUBLE", "FL1_BTTS_DOUBLE", "NEW_STRATEGY"}
```

### 2.6 ALLOWED_LEAGUES — вайтлист лиг

```python
"hockey": [
    "НХЛ. Регулярный сезон",
    "Фонбет КХЛ. Регулярный сезон",
    "TheSports KHL",
    "Чехия. Экстралига",
    "Хоккей. Швейцария. National League.",  # точное название из Фонбета!
]
```

⚠️ Название должно совпадать с тем что парсит Фонбет — проверить через:
```sql
SELECT DISTINCT league FROM matches WHERE sport='hockey' AND league LIKE '%...%';
```

### 2.7 Имя стратегии — секция `# Build recommendation`

```python
elif league_key == "NEW_KEY":
    strategy_name = "new_strategy_name"
    strategy_family = "new_strategy_name"
```

### 2.8 Блок обработки — главный `if/elif` в `main()`

```python
elif league_key == "NEW_KEY" and league_config.get("mode") == "single":
    print(f"[NEW_KEY STRATEGY] {match.home_team} vs {match.away_team}")
    hockey_rec, hockey_debug = process_hockey_match(conn, match, args.bankroll)
```

⚠️ Без этого блока матчи попадают в `else` и получают `failed_reason: Unsupported league mode`

### 2.9 Стратегия в `process_hockey_match`

Добавить ветку `elif` ПЕРЕД `else: pick1 = underdog_live(row)`:

```python
elif "new_strategy_name" in strategies:
    # Условия стратегии
    condition_met = <твои фильтры на match.odds_*, match.away_team, etc.>
    
    if condition_met:
        od = match.odds_draw  # или нужный коэф
        implied = 1.0 / od if od > 0 else 0
        model_prob = 0.342  # из бэктеста
        ev = model_prob * od - 1.0
        
        recommendation = {
            "market": "draw",           # "draw" / "home" / "away" / "btts_yes"
            "market_label": "X",        # "X" / "П1" / "П2"
            "odds": od,
            "our_probability": model_prob,
            "market_probability": implied,
            "ev": ev,
            "kelly": 0.01,
            "kelly_quarter": 0.0025,
            "stake_pct": 0.01,
            "stake": round(bankroll * 0.01),
            "confirmed_facts": ["факт 1", "факт 2"],
            "market_error": f"Strategy new_strategy_name: draw",
            "rule": "NEW_STRATEGY",
            "live_rule_family": "new_strategy_name",
            "strategy_name": "new_strategy_name",
            "recommended_action": "BET",  # ← ОБЯЗАТЕЛЬНО, иначе PASS
            "signal_type": "RULE_DRIVEN",
            "decision": "BET",            # ← ОБЯЗАТЕЛЬНО, иначе PASS
        }
        debug_info["markets_match"] = True
        debug_info["both_edges_positive"] = True
        debug_info["final_recommendation"] = True
        return recommendation, debug_info
    else:
        pick1 = None
    pick2 = pick1
```

⚠️ **Критично:** без `"recommended_action": "BET"` и `"decision": "BET"` рекомендация создаётся но всегда идёт в PASS!

---

## 3. Добавить в бэктест whitelist

В функции `fetch_backtest_matches` найти SQL WHERE и добавить лигу:

```python
q += """ AND (
    league LIKE '%КХЛ%' OR league LIKE '%KHL%'
    OR (league LIKE '%Чехия%' AND league LIKE '%Extraliga%')
    OR league LIKE '%NHL%' OR league LIKE '%НХЛ%'
    OR (league LIKE '%Швейцар%' AND league LIKE '%National League%')  -- ← новая лига
)"""
```

---

## 4. Если стратегия не требует hockey_features

Стратегии KHL и CZECH требуют features (`strength_diff_ppg` и др.).  
NHL, NLA и подобные — не требуют (только коэффициенты).

В `process_hockey_match` найти строку и добавить свою стратегию:
```python
features_required = not any(s in strategies for s in [
    "nhl_draw_tight",
    "nla_bern_away_draw",
    "new_strategy_name",  # ← добавить сюда если не нужны features
])
```

И убедиться что `features.items()` защищён:
```python
if features:
    for key, value in features.items():
        ...
```

---

## 5. Для футбольной стратегии

### 5.1 Детектор лиги — `is_new_league()` внутри `detect_rule`

```python
def is_new_league() -> bool:
    return "ключевое_слово" in league or league == "short_code"
```

### 5.2 Правило в `detect_rule`

Добавить перед `return None, None`:
```python
# N. NEW_STRATEGY — описание
# Бэктест: ROI +X%, N/5 сезонов, MaxLS=Y, n=Z
if is_new_league():
    if (hasattr(match, "odds_btts_yes") and match.odds_btts_yes is not None and
            hasattr(match, "odds_over_2_5") and match.odds_over_2_5 is not None):
        over25 = float(match.odds_over_2_5)
        btts = float(match.odds_btts_yes)
        if X.X <= over25 <= X.X and X.X <= btts <= X.X:
            return "NEW_STRATEGY", "btts_yes"
return None, None
```

### 5.3 FOOTBALL_LEAGUE_STAKING

```python
"NEW_LEAGUE_KEY": {
    "NEW_STRATEGY": "flat_pct_1_00",
},
```

### 5.4 detect_football_league_key

```python
# New league detection
if any(term in l for term in ["слово1", "слово2"]):
    return "NEW_LEAGUE_KEY"
```

### 5.5 ALLOWED_LEAGUES["football"]

```python
"football": [
    "Англия. Премьер-Лига",
    ...
    "Франция. Лига 1",   # ← пример добавленной
    "США.",              # ← паттерн для всех лиг США
]
```

### 5.6 GOLDEN_STRATEGIES (если ROI > 15%)

```python
"NEW_STRATEGY": {"roi": 17.1, "min_ev": 0.10},
```

### 5.7 Bypass стандартной валидации ничьей ⚠️ КРИТИЧНО

Если стратегия ставит на ничью но использует **свои** фильтры (командный список, тотал и т.д.) — нужно добавить её в bypass валидатора. Иначе валидатор применит фильтры DRAW_SA (разница в таблице ≤5, атака ≤1.7) и заблокирует 60-80% ставок.

Найти в `enrich_with_math` строку `# Валидация ничьей по данным` и добавить:

```python
# Валидация ничьей по данным
# Стратегии со своей логикой — пропускаем стандартную валидацию
_rule = rec.get("rule") or rec.get("live_rule_family") or rec.get("market_error", "")
_skip_draw_validation = any(x in _rule for x in ["SA_AWAY_DRAW", "NLA_BERN_AWAY_DRAW", "NEW_STRATEGY"])
if market == "draw" and facts and not _skip_draw_validation:
```

⚠️ **Важно:** `rec.get("rule")` может быть None в момент вызова `enrich_with_math` — поле заполняется позже в `save_recommendation`. Поэтому используем `live_rule_family` или `market_error` как fallback.

Признак что нужен bypass:
- `seen=N, BET=18, PASS=60` — большинство отфильтровано
- `avg_odds=15+` — явный баг, коэф ничьей не может быть >6
- В dry-run видно: `RULE PASS: ... | Ничья: разница в таблице X > 5`

---

## 6. Боевой режим — парсер и settler

### 6.1 Парсер линии

Если лига парсится Фонбетом автоматически — добавить в `TARGET_LEAGUES_BY_SPORT` в `parser_v2.py`.  
Если нет — добавить отдельный скрипт по аналогии с `betz_rpl_parser.py`.

### 6.2 Парсер результатов

Критично для хоккея — нужен счёт **основного времени** (без ОТ/SO).

Примеры парсеров:
- КХЛ/НХЛ: `the_sports_khl_parser.py`, `the_sports_nhl_parser.py`
- Футбол: `sportsru_football_results_parser.py`
- Чехия: `liveresult.ru` парсер в `run_pipeline.py`

⚠️ Проверить что новая лига попадает в `LEAGUE_MAP` парсера результатов:
```bash
sqlite3 betagent.db "SELECT league, count(*), max(match_date) FROM results_raw GROUP BY league ORDER BY max(match_date) DESC LIMIT 20;"
```

### 6.3 settler.py

Добавить рынок если нестандартный:
```python
# Уже поддерживаются: home, away, draw, over_2_5, under_2_5, btts_yes, btts_no
```

Для хоккея ОТ — settler использует `results_raw.is_overtime`:
```python
if is_overtime and market in ("draw", "X"):
    home_score = 1
    away_score = 1  # считаем как ничью в основное время
```

### 6.4 run_pipeline.py

Добавить вызов парсера результатов в `task_settle()`.

---

## 7. Проверочные команды

```bash
# Бэктест хоккей
cd /root/betagent && source .venv/bin/activate && source .env
python3 agent_handoff_v7.py --sport hockey --backtest --limit 5000 --no-llm --disable-shadow 2>&1 | tail -40

# Бэктест футбол
python3 agent_handoff_v7.py --sport football --backtest --limit 10000 --no-llm --disable-shadow 2>&1 | tail -100

# Dry-run футбол
python3 agent_handoff_v7.py --sport football --limit 50 --no-llm --disable-shadow --dry-run 2>&1 | grep -E "PASS|BET|RULE|DETECT" | head -40

# Dry-run хоккей
python3 agent_handoff_v7.py --sport hockey --limit 40 --no-llm --disable-shadow --dry-run 2>&1 | grep -E "LEAGUE DETECT|HOCKEY|FAIL|BET" | head -40

# Полный пайплайн
python3 run_pipeline.py --now 2>&1 | tail -50
```

---

## 8. Типичные баги и решения

| Баг | Причина | Решение |
|-----|---------|---------|
| Стратегия не появляется в summary | Не добавлен `elif league_key == "NEW_KEY"` в main() | Добавить блок обработки п.2.8 |
| `seen=N, BET=0, PASS=N` | Нет `"decision": "BET"` в recommendation | Добавить оба поля: `recommended_action` и `decision` |
| `seen=N, BET=18, PASS=60` + `avg_odds=15+` | Валидатор DRAW_SA блокирует ничейные ставки | Добавить стратегию в `_skip_draw_validation` (п.5.7) |
| `rec.get("rule")` возвращает None в валидаторе | Поле "rule" заполняется позже в `save_recommendation` | Использовать `rec.get("live_rule_family")` как fallback |
| `KeyError: 'draw'` в odds_for_market | Рынок должен быть `"D"` не `"draw"` | Использовать `"D"/"H"/"A"` для Pick объекта |
| `AttributeError: 'NoneType'.items()` | features=None но не защищено | Обернуть в `if features:` |
| `НЕ НАЙДЕНО` в str.replace | Пробелы/переносы отличаются | Проверить `repr()` нужного участка кода |
| Лига детектируется но ставок нет | Не добавлена в бэктест whitelist | Добавить в WHERE clause в `fetch_backtest_matches` |
| Неверное название стратегии в summary | Дублирующий `elif league_key ==` | Проверить что нет повторов в strategy_name секции |
| Стратегия в SQL даёт 131 матч, агент 78 | Агент берёт последние N матчей по лимиту | Увеличить `--limit` или проверить через полный прогон |

---

## 9. Шаблон патча через Python

Всегда проверяй перед патчем:
```python
python3 - << 'EOF'
with open('/root/betagent/agent_handoff_v7.py', 'r') as f:
    content = f.read()

# Находим точный текст
idx = content.find('искомая строка')
print(repr(content[idx:idx+200]))
EOF
```

Патч:
```python
python3 - << 'EOF'
with open('/root/betagent/agent_handoff_v7.py', 'r') as f:
    content = f.read()

old = '''точный текст'''
new = '''новый текст'''

if old in content:
    content = content.replace(old, new)
    with open('/root/betagent/agent_handoff_v7.py', 'w') as f:
        f.write(content)
    print("✅ OK")
else:
    print("❌ НЕ НАЙДЕНО")
EOF
```

---

## 10. Дополнения по опыту внедрения MLS_BTTS_HOME (05.04.2026)

### 10.1 Командный список в стратегии — регистр и варианты написания

Если стратегия фильтрует по командам — добавлять все варианты написания через `any(t in home for t in _TEAMS)`:
```python
_MLS_HOME_TEAMS = [
    "интер майами", "портленд тимберс", "фк торонто", "торонто фк",
    "лос-анджелес гэлакси", "лос-анджелес гэлэкси",  # варианты транслитерации
]
home = str(getattr(match, "home_team", "") or "").lower()
if any(t in home for t in _MLS_HOME_TEAMS):
```
⚠️ Всегда приводить `home_team` к lower() перед сравнением.

### 10.2 detect_football_league_key — патч через str.replace ненадёжен

При патче `detect_football_league_key` через Python str.replace легко сломать структуру функции (вставить код в неправильный блок). Всегда проверять `repr()` участка ПЕРЕД патчем и ПОСЛЕ. Признак бага — `IndentationError` или `return None` стоит раньше `l = league.lower()`.

### 10.3 Парсер результатов для новой лиги

Перед внедрением боевой стратегии проверить что лига парсится в `results_raw`:
```bash
sqlite3 betagent.db "SELECT league, count(*), max(match_date) FROM results_raw GROUP BY league ORDER BY max(match_date) DESC LIMIT 20;"
```
Для MLS результаты парсятся через `sportsru_football_results_parser.py`. Нужно добавить лигу в `LEAGUE_MAP` парсера:
```python
LEAGUE_MAP = {
    ...
    "сша. mls": "mls",
}
```
Иначе матчи парсятся но league пишется как последняя найденная (например ligue1).

### 10.4 sportsru_football_results_parser — известные баги

- Парсер брал **время матча** (16:30) как счёт — фикс: искать только `td.score-td`
- Парсер тянул **400+ матчей** из всех лиг мира — фикс: стоп-слова + сброс `current_league=None`
- Мусорные строки **"Первый тайм", "Второй тайм"** как названия команд — фикс: фильтр по skip_words

### 10.5 Фонбет SSL timeout с VPS — не паниковать

Фонбет периодически недоступен с Amsterdam VPS (SSL handshake timeout). При этом `parser_v2.py` через cron работает нормально. Диагностику делать только с сервера напрямую, не через Claude.

### 10.6 the_sports_nhl_parser — не писать будущие матчи в results_raw

Парсер делает `DELETE FROM results_raw WHERE league='nhl'` и вставляет всё заново включая будущие матчи. Фикс — фильтровать только `is_finished=1` перед вставкой:
```python
# В функции save_results_raw, перед DELETE:
rows = [r for r in rows if r[6] == 1]  # is_finished=1 only
```
Без этого updater через reversed matching находит результат похожего матча и закрывает будущую ставку.

### 10.7 updater_results — не закрывать матчи из будущего

Добавлена защита в `mark_finished()` — проверка что `match_date < now()` перед UPDATE:
```python
row = conn.execute("SELECT match_date FROM matches WHERE id=?", (match_id,)).fetchone()
if row:
    match_dt = datetime.strptime(str(row["match_date"])[:16], "%Y-%m-%d %H:%M")
    if match_dt > datetime.now():
        print(f"  ⏭️  match_id={match_id} пропущен — матч ещё не начался")
        return
```
Без этого cron мог закрывать ставки на несыгранные матчи через reversed matching.

### 10.8 parser_v2.py — не перезаписывать коэффициенты finished матчей

После завершения матча Фонбет иногда возвращает мусорные коэффициенты (например btts_yes=10.0). Добавлена защита в `save_matches()`:
```python
cursor.execute("SELECT id, status FROM matches WHERE fonbet_id=?", (m["fonbet_id"],))
_row = cursor.fetchone()
if _row and _row[1] == "finished":
    continue  # не перезаписываем коэффициенты завершённых матчей
```

### 10.9 sportsru_football_results_parser — добавить в task_settle()

Парсер результатов футбола нужно вызывать в `task_settle()` перед `updater_results.py`:
```python
def task_settle():
    task_repair_pending()
    from datetime import datetime, timedelta
    today = datetime.utcnow().strftime("%Y-%m-%d")
    yesterday = (datetime.utcnow() - timedelta(days=1)).strftime("%Y-%m-%d")
    run("sportsru_football_results_parser.py", ["--date", today], timeout=60)
    run("sportsru_football_results_parser.py", ["--date", yesterday], timeout=60)
    run("updater_results.py", ["--settle"], timeout=90)
```
Без этого футбольные ставки не закрываются автоматически.

---

## TENNIS_OVER_AFTER_TB1 — Live стратегия (не внедрена)

**Идея:** Ставить OVER тотала геймов в матче после того как первый сет завершился тай-брейком (6:6 → тай-брейк).

**Логика:** Тай-брейк в первом сете означает равную борьбу → второй и третий сеты тоже будут напряжёнными → больше геймов в итоге.

**Бэктест (backtest_tennis_matches, 2021-2026):**
| Год  | n   | Over% | ROI@1.9 | ROI@1.6 | ROI@1.5 |
|------|-----|-------|---------|---------|---------|
| 2021 | 638 | 79.8% | +51.5%  | +27.6%  | +19.7%  |
| 2022 | 698 | 78.1% | +46.8%  | +24.9%  | +17.1%  |
| 2023 | 705 | 75.9% | +42.6%  | +21.4%  | +13.8%  |
| 2024 | 668 | 73.8% | +40.1%  | +18.1%  | +10.7%  |
| 2025 | 590 | 78.0% | +47.9%  | +24.7%  | +16.9%  |
| 2026 | 221 | 77.8% | +47.3%  | +24.5%  | +16.7%  |

**Применимость:** ATP и WTA, все покрытия, все уровни турниров.

**Что нужно для внедрения:**
1. Live парсер коэффициентов тенниса (Фонбет/Леон)
2. Live монитор счёта матча (первый сет достиг 6:6)
3. Автоматическая отправка ставки при триггере

**Статус:** ❌ Не внедрена — нет live парсера. Сохранить для будущего.

**Приоритет:** Высокий — стратегия стабильна 6/6 лет, n=600+/год.

---

## TENNIS_UNDER_AFTER_BAGEL — Live стратегия (не внедрена)

**Идея:** Ставить UNDER тотала геймов после того как первый сет завершился разгромом (6:0 или 6:1 в любую сторону).

**Логика:** Разгром в первом сете → матч скорее всего закончится 2:0 → мало геймов в итоге.

**Бэктест (backtest_tennis_matches, 2021-2026):**
| Год  | n   | Under% | ROI@1.9 | ROI@1.6 | ROI@1.4 |
|------|-----|--------|---------|---------|---------|
| 2021 | 624 | 72.4%  | +35.2%  | +15.9%  | +1.4%   |
| 2022 | 663 | 71.8%  | +34.9%  | +15.1%  | +0.7%   |
| 2023 | 648 | 74.8%  | +41.8%  | +20.0%  | +5.0%   |
| 2024 | 661 | 71.9%  | +36.0%  | +15.0%  | +0.6%   |
| 2025 | 515 | 72.6%  | +37.4%  | +16.2%  | +1.7%   |
| 2026 | 212 | 69.8%  | +32.0%  | +11.7%  | -2.3%   |

**Минимальный коэф для прибыли:** 1.55+
**Что нужно для внедрения:** Live парсер + live монитор счёта.
**Статус:** ❌ Не внедрена — нет live парсера.
**Приоритет:** Средний — работает но требует живого коэфа >=1.55.

---

## Уточнение TENNIS_OVER_AFTER_TB1 — WTA значительно сильнее

**WTA over после тай-брейка 1-го сета (отдельно):**
| Год  | n   | Over% | ROI@1.9 | ROI@1.6 |
|------|-----|-------|---------|---------|
| 2021 | 284 | 86.3% | +64.5%  | +38.0%  |
| 2022 | 293 | 81.9% | +56.0%  | +31.1%  |
| 2023 | 330 | 79.4% | +50.4%  | +27.0%  |
| 2024 | 277 | 77.6% | +47.1%  | +24.2%  |
| 2025 | 272 | 86.0% | +63.1%  | +37.6%  |
| 2026 |  96 | 83.3% | +56.8%  | +33.3%  |

**Рекомендация при внедрении:** фокус на WTA, минимальный live коэф 1.55+

---

## BL1_BTTS_SHOTS_FILTER — Прематч фильтр (готов к внедрению)

**Идея:** BTTS_YES_CORE в Бундеслиге только когда avg_shots_home_last5 + avg_shots_away_last5 >= 10

**Результат:**
- Baseline: n=641, hit=59.3%, ROI=+19.6%
- Filtered: n=260, hit=62.7%, ROI=+26.4% (+6.8pp)
- 5/5 лет в плюсе, n>=15/год

**Статус:** ✅ Готов к внедрению в agent_handoff_v7.py
**Данные:** backtest_football_stats.shots_home/away (уже собраны)
**Сложность:** Нужен rolling avg последних 5 матчей из backtest_football_stats

---

## TENNIS_WTA_DOMINANT_UNDER — Прематч стратегия (требует подтверждения ROI)

**Идея:** Ставить UNDER тотала геймов когда топ WTA игрок с доминирующей формой играет против явно более слабого соперника.

**Условия входа:**
- Tour: WTA только
- winner_rank <= 10 (топ-10 WTA)
- rank_gap >= 50 (соперник минимум на 50 позиций ниже)
- rolling_dominant_pct >= 60% (побеждала в прямых сетах >= 6 из последних 10 матчей)
- Ставка: UNDER тотала геймов

**Статистика (из backtest_tennis_players, без ROI):**
| Год  | n   | Straight% |
|------|-----|-----------|
| 2021 | ~129 | 77-79%   |
| 2022 | ~129 | 75-78%   |
| 2023 | ~129 | 76-79%   |
| 2024 | ~129 | 73-77%   |
| 2025 | ~129 | 76-80%   |

**Теоретический ROI при avg_odds=1.88:**
- 77% × 0.88 - 23% = **+44.8%**
- При 75%: **+41.0%**
- При консервативном коэфе 1.70: **+30.9%**

**Что нужно для подтверждения:**
- Улучшить JOIN между Jeff Sackmann и betz.su (сейчас только 2% overlap)
- Получить реальный ROI на совпадающих матчах

**Статус:** ⚠️ Требует подтверждения реального ROI через JOIN
**Приоритет:** Высокий — теоретически сильнейшая из найденных стратегий

---

## ТЕННИС — Итоговый вывод

**Найденные стратегии:**
1. TENNIS_OVER_AFTER_TB1 — Live, ROI +47% ✅
2. TENNIS_UNDER_AFTER_BAGEL — Live, ROI +35% ✅  
3. WTA Dominant Winner Under — Прематч, 77%+ straight sets, ROI не подтверждён

**Почему прематч не реализован:**
- Рынка "выиграет в прямых сетах" нет у букмекеров
- Коэф на победу 1.07-1.20 даёт ROI только +7-19% — недостаточно
- Under тотала геймов = правильный рынок но коэфы только в betz.su с русскими именами
- JOIN между Jeff Sackmann (eng) и betz.su (rus) работает только на 6% матчей

**Что нужно для реализации:**
- Live парсер коэфов на under тотала (Фонбет/betz.su)
- Live монитор счёта матча
- Всё это нужно и для тай-брейк стратегии

**Приоритет live парсера:** Высокий — разблокирует 3 теннисные стратегии одновременно
