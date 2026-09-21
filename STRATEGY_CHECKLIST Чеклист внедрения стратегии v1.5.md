# BETAGENT — Чеклист добавления новой стратегии

> Последнее обновление: 25.03.2026  
> Выстрадано на внедрении NLA_BERN_AWAY_DRAW, FL1_BTTS_DOUBLE и SA_AWAY_DRAW

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

Если лига парсится Фонбетом автоматически — ничего делать не нужно.  
Если нет — добавить отдельный скрипт по аналогии с `betz_rpl_parser.py`.

### 6.2 Парсер результатов

Критично для хоккея — нужен счёт **основного времени** (без ОТ/SO).

Примеры парсеров:
- КХЛ/НХЛ: `the_sports_khl_parser.py`, `the_sports_nhl_parser.py`
- Чехия: `liveresult.ru` парсер в `run_pipeline.py`

Для NLA (Швейцария) — нужно добавить парсер результатов!

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
python3 agent_handoff_v7.py --sport football --backtest --limit 10000 --no-llm --disable-shadow 2>&1 | tail -60

# Dry-run хоккей (видим что детектируется)
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
    print("OK")
else:
    print("НЕ НАЙДЕНО!")

with open('/root/betagent/agent_handoff_v7.py', 'w') as f:
    f.write(content)
EOF
```
