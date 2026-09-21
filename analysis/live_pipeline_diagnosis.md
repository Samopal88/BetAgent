# Live Pipeline Diagnosis — 2026-04-10

## Executive Summary

**Найдено 2 бага + 3 operational проблемы.** Pipeline крашился 2 дня подряд из-за `NameError`. После фикса — ставок нет из-за комбинации сломанного LLM ключа, отключённой NHL стратегии и завершившегося KHL сезона.

---

## Статус каждого шага пайплайна

| Шаг | Статус | Детали |
|-----|--------|--------|
| Cron | OK | Cron запускает `run_server.sh` → `run_pipeline.py --now` |
| Parser | FAIL (env) | `parser_v2.py` падает с "Missing dependencies for SOCKS support" при запуске вне venv. В cron работает (venv активирован). |
| Enrichment | OK | Hockey enrichment проходит, football enrichment работает |
| sync_match_facts | WARN | Timeout 180s на Apr 9 (один раз), Apr 10 прошёл |
| Football analysis | OK (no bets) | Pipeline не крашится, но 0 BET |
| Hockey analysis | OK (no bets) | 0 KHL матчей, NHL отключён |
| Archive | OK | Snapshot записывается |
| Telegram notify | OK | Запускается в фоне |

---

## Найденные проблемы

### BUG #1: NameError в run_pipeline.py:183 (ИСПРАВЛЕНО)

**Файл:** `run_pipeline.py`, строки 181-190

**Проблема:** Функции `task_shadow_football` и `task_shadow_hockey` были закомментированы (строки 181, 187), но их **тело** осталось незакомментированным. Код выполнялся как часть `task_bet_hockey()`, вызывая `NameError: name 'mode' is not defined`.

**Влияние:** Pipeline крашился на каждом запуске `run_full()` (Apr 9, Apr 10). Shadow-фаза не достигалась, но и основной анализ хоккея/футбола логгировался до краша.

**Исправление:** Закомментированы строки 182-184 и 188-190.

---

### BUG #2: LLM API ключ — 401 Unauthorized (НЕ ИСПРАВЛЕНО)

**Файл:** `.env` → `LLM_API_KEY`

**Проблема:** API ключ `<REDACTED>` возвращает 401 от OpenRouter. LLM не работает с ~Apr 6.

**Влияние:**
- Без LLM football матчи отклоняются на pre-flight (нет составов → cap 0.570 → нет edge)
- Shadow mode работает только как heuristic fallback (не размещается)
- Все матчи с `signal_type=Medium` без составов блокируются pre-flight

**Решение:** Обновить `LLM_API_KEY` в `.env`.

---

### OPERATIONAL #3: NHL стратегия отключена

**Файл:** `strategies/hockey.py`, строки 43-47

**Проблема:** NHL стратегия `nhl_draw_tight` закомментирована с комментарием "Отключено — стратегия убыточна на реальных данных (ROI -7%)".

**Влияние:** 60 upcoming NHL матчей с коэффициентами (21 с полными odds) полностью игнорируются. Последние 4 ставки (Apr 7-8) были от `nhl_draw_tight` — после этого стратегия отключена.

**Решение:** Это intentional decision. Если нужно — раскомментировать и/или настроить стратегию.

---

### OPERATIONAL #4: KHL сезон закончился

**Проблема:** 0 upcoming KHL матчей в БД. KHL регулярный сезон завершён.

**Влияние:** KHL intersection strategy (underdog_live + defensive_wall) не может сработать — нет матчей.

**Решение:** Естественное ограничение. Новый сезон начнётся осенью.

---

### OPERATIONAL #5: Football pre-flight блокирует матчи без данных

**Файл:** `agent_handoff_v7.py` → `pre_flight_check()`

**Проблема:** ~50% матчей отклоняются на pre-flight из-за отсутствия standings/form/goals данных (скандинавские лиги, MLS, RPL). Оставшиеся матчи отклоняются из-за `no edge`: cap без составов (0.570) + штраф -0.03 не дают преодолеть `market_p + min_edge`.

**Влияние:** 0 football BET без LLM.

**Решение:** LLM нужен для снятия cap (с 0.570 до 0.720 с составами). Или расширить данные enricher.

---

## Воронка (Apr 10, после фикса)

```
matches_in (football):     151 с коэффициентами
  → pre-flight SKIP:       ~50% (нет standings/form/goals)
  → после edge filter:     0 BET (no edge без LLM)
  → final signals:         0

matches_in (hockey):       60 NHL upcoming
  → NHL skip (disabled):   60
  → KHL upcoming:          0
  → final signals:         0
```

---

## Исправленные файлы

| Файл | Изменение |
|------|-----------|
| `run_pipeline.py` | Закомментировано тело `task_shadow_football` и `task_shadow_hockey` (строки 182-184, 188-190) |

---

## Что нужно для возобновления ставок

1. **Критично:** Обновить `LLM_API_KEY` в `.env` — без LLM football не даёт сигналов
2. **Опционально:** Раскомментировать NHL `nhl_draw_tight` в `strategies/hockey.py` — но это может вернуть убытки (ROI -7%)
3. **Опционально:** Расширить football enricher для скандинавских/MLS лиг — уменьшить pre-flight SKIP
