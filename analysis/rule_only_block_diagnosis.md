# Rule-Only Block Diagnosis — 2026-04-11

## Executive Summary

**Rule-driven стратегии АРХИТЕКТУРНО способны работать без ML.**
Баги нет. Но pipeline спроектирован так, что rule-driven path покрывает лишь малую часть матчей, а остальные зависят от LLM.

**Ключевой вывод:** rule-driven сигналы НЕ блокируются pre-flight и НЕ блокируются edge filter. Проблема в другом — rule-driven стратегии покрывают узкий набор матчей, а для остальных нужен LLM.

---

## 1. Может ли rule-driven стратегия опубликовать сигнал БЕЗ ML?

**ДА.** Функция `build_rule_recommendation()` (`agent_handoff_v7.py:753-1011`) создаёт полностью самодостаточную рекомендацию:

| Поле validator.py | Источник в rule_rec | Статус |
|---|---|---|
| `market` | `market` из правила | OK |
| `decision` | `"BET"` | OK |
| `odds` | `match.odds_*` | OK |
| `market_probability` | `1.0 / odds` | OK |
| `our_probability` | `rule_probabilities[rule_name]` (хардкод из бэктеста) | OK |
| `ev` | `our_p * odds - 1` | OK |
| `signal_type` | `"Medium"` | OK |
| `confidence` | `rule_confidence[rule_name]` (5-7) | OK |
| `lineup_data_available` | `facts.get("lineup_data_available")` | OK |
| `confirmed_facts` | Список фактов (4-6 штук) | OK |
| `market_error` | `market_error_map[rule_name]` | OK |

**Вывод:** rule-driven стратегия НЕ зависит от ML. Все поля для валидации заполняются из:
- правил (rule name, market, probability, confidence)
- odds (Fonbet API)
- facts (enricher: standings, form, goals)

---

## 2. Pipeline: rule-only path

Полный путь rule-driven сигнала (`agent_handoff_v7.py`):

```
for match in matches:                                        # line 4419
  │
  ├─ hockey? → process_hockey_match() → continue             # line 4440-4616
  │
  ├─ build_payload()                                          # line 4618
  ├─ pre_flight_check() → live_skip_reason                    # line 4639
  │     (но rule-driven path НЕ использует этот skip!)
  │
  ├─ rule_name, market = get_pruned_live_rule(match, facts)   # line 4664
  │     │
  │     ├─ Rule matched? NO → continue to pre-flight skip
  │     └─ Rule matched? YES ↓
  │           │
  │           ├─ build_rule_recommendation()                  # line 4690
  │           │   → rule_rec: all fields populated
  │           │
  │           ├─ calibrate_probability()                      # line 4698
  │           │   EXCEPT for _no_calib rules:
  │           │   RPL_OVER25_BTTS, PD_BTTS_DOUBLE, FL1_BTTS_DOUBLE,
  │           │   NLA_BERN_AWAY_DRAW, SA_AWAY_DRAW, SUMMER_BTTS_HOME,
  │           │   MLS_BTTS_HOME
  │           │
  │           ├─ enrich_with_math()                           # line 4699
  │           │   → edge check: our_p > market_p + min_edge
  │           │   → if fail: market = "pass"
  │           │
  │           ├─ validate_recommendation()                    # line 4768
  │           │   → EV >= 0.03, Kelly > 0, odds >= 1.50,
  │           │     confirmed_facts >= 1, confidence_cap > 0
  │           │
  │           ├─ enforce_validator_gate()                     # line 4770
  │           │
  │           └─ if valid → save + bet                        # line 4834
  │                 continue  ← never reaches pre-flight skip
  │
  └─ pre-flight skip (live_skip_reason)                       # line 4867
        └─ continue → LLM/heuristic fallback                  # line 4892
```

**Обязательные поля для публикации:**

1. `rule_name` + `market` from `get_pruned_live_rule()` — все criteria met
2. `our_probability` from `rule_probabilities` dict
3. `odds` — not None for the target market
4. `confirmed_facts` — >= 1 element (always 4+)
5. `market_error` — always present
6. `confidence` — 5-7, always > 1 (cap > 0)
7. Edge check in `enrich_with_math`: `our_p > market_p + min_edge`

---

## 3. Pre-flight блокировка: почему ~50% матчей отклоняются

Pre-flight check (`agent_handoff_v7.py:2712-2787`) проверяет 6 правил:

| Правило | Условие блокировки | Влияние на rule-driven |
|---|---|---|
| `require_any_data` | нет standings И form И goals | НЕТ — rule-driven путь проходит ДО pre-flight |
| `min_form_for_llm` | max(home_form, away_form) < 3 | НЕТ —同上 |
| `require_table_for_medium_without_lineups` | нет standings | НЕТ —同上 |
| `block_if_no_h2h_and_short_form_and_no_lineups` | False для football | НЕТ |
| **football: both_have_form** | len(home_form) < 3 ИЛИ len(away_form) < 3 | НЕТ —同上 |
| `medium_without_lineups_requires` | min_form < 4 ИЛИ нет таблицы | НЕТ —同上 |

**Критически важно:** rule-driven check (`get_pruned_live_rule`) на строке 4664 выполняется ДО pre-flight skip на строке 4867. Если правило срабатывает, `continue` на строке 4841/4892 не даёт коду дойти до pre-flight.

~50% матчей блокируются pre-flight, потому что:
- Это матчи **не из Serie A / EPL / BL1 / La Liga / RPL / Ligue 1**
- Или матчи без данных формы/таблицы (скандинавские лиги, MLS)
- Эти матчи **не прошли бы rule-driven filter всё равно**, т.к. правила привязаны к конкретным лигам

**Вывод:** pre-flight НЕ блокирует rule-driven сигналы. Он блокирует матчи, для которых нет rule-driven стратегии.

---

## 4. Edge filter: расчёт и влияние

`enrich_with_math()` (`agent_handoff_v7.py:3194-3209`) — единственное место, где rule-driven сигнал может быть отброшен математически:

```python
min_edge = profile.get("min_edge_vs_market")        # 0.025 для football
# или 0.015 для BTTS/totals (min_edge_vs_market_btts)

if our_p <= market_p + min_edge:
    rec["market"] = "pass"  ← SIGNAL DROPPED
```

### Проверка для каждой rule стратегии:

| Rule | our_p | Типичный odds | market_p | Edge | min_edge | Проходит? |
|------|-------|--------------|----------|------|----------|-----------|
| DRAW_SA | 0.40 | 3.2 | 0.313 | +0.087 | 0.025 | YES |
| DRAW_BALANCED_LOW_SCORING_SA | 0.40 | 3.3 | 0.303 | +0.097 | 0.025 | YES |
| DRAW_BALANCED_LINE_SA | 0.37 | 3.3 | 0.303 | +0.067 | 0.025 | YES |
| AWAY_SA_STRICT_PLUS | 0.42 | 2.4 | 0.417 | +0.003 | 0.025 | **RISKY** |
| SA_AWAY_DRAW | 0.483 | 3.5 | 0.286 | +0.197 | 0.025 | YES |
| BTTS_YES_CORE | 0.60 | 2.05 | 0.488 | +0.112 | 0.015 | YES |
| RPL_OVER25_BTTS | 0.57 | 1.95 | 0.513 | +0.057 | 0.015 | YES |
| PD_BTTS_DOUBLE | 0.62 | 1.85 | 0.541 | +0.079 | 0.015 | YES |
| FL1_BTTS_DOUBLE | 0.576 | 2.05 | 0.488 | +0.088 | 0.015 | YES |
| NLA_BERN_AWAY_DRAW | 0.342 | 4.5 | 0.222 | +0.120 | 0.015 | YES |
| SUMMER_BTTS_HOME | 0.734 | 1.70 | 0.588 | +0.146 | 0.015 | YES |
| MLS_BTTS_HOME | 0.693 | 1.65 | 0.606 | +0.087 | 0.015 | YES |
| PD_AWAY_VALUE | 0.504 | 2.25 | 0.444 | +0.060 | 0.025 | YES |

**Проблема:** `AWAY_SA_STRICT_PLUS` (our_p=0.42) имеет edge всего +0.003 при required +0.025. Эта стратегия может быть отброшена edge filter.

**НО:** если `calibrate_probability()` применяется (для стратегий НЕ из `_no_calib`), penalties снижают our_p:
- cap без составов: 0.57 — не влияет на 0.40
- no H2H penalty: -0.01 → 0.39
- short form penalty: -0.01~-0.02 → 0.37-0.38

После калибровки DRAW_SA: 0.40 → 0.38-0.39, edge = 0.39 - 0.313 = +0.077 > 0.025. **Всё ещё проходит.**

**Вывод:** edge filter НЕ блокирует rule-driven стратегии в большинстве случаев. Исключение — `AWAY_SA_STRICT_PLUS` с его низким our_p=0.42.

---

## 5. Возможность bypass ML

Есть 3 режима работы без LLM:

### Режим A: `--no-llm` (без `--disable-shadow`)
```
call_llm() → football: PASS (line 3408)
→ simulate_llm_response(payload) → heuristic recommendation (line 4910)
  → shadow_only = True для football (line 1866)
  → NOT counted as bet (line 5053: if not shadow_only)
```
Результат: shadow recommendations генерируются, но НЕ размещаются.

### Режим B: `--no-llm --disable-shadow`
```
call_llm() → football: PASS
→ rec = {"market": "pass", ...}  (line 4898)
→ continue
```
Результат: всегда PASS. Нет ставок.

### Режим C: `--pure-ba` (pure backtest-approved)
```
simulate_llm_response() → pure_ba_mode: True (line 1742)
→ forces market from ba_rule, our_p = market_p + 0.08 (line 1753)
→ НЕ shadow_only
→ может пройти валидацию
```
Результат: работает, но только для матчей с `is_backtest_approved = True`.

**Вывод:** `--pure-ba` — единственный режим, который публикует сигналы без LLM. Но он ограничен BA-approved матчами.

---

## 6. Какие стратегии реально дают кандидатов

Для каждой rule стратегии, условия прохождения:

### DRAW_SA
- Лига: Serie A
- odds_draw: 3.0-3.85
- table_diff <= 5, form_gap <= 3
- both avg goals <= 1.55, both conceded <= 1.75
- home_form_pts <= 7
- Требуется: standings + goals + form

### DRAW_BALANCED_LOW_SCORING_SA
- Лига: Serie A
- odds_draw: 3.0-3.6
- table_diff <= 6, form_gap <= 3
- both avg goals <= 1.55, both conceded <= 1.65
- Требуется: standings + goals

### DRAW_BALANCED_LINE_SA
- Лига: Serie A
- odds_draw: 3.05-3.65
- abs(home_odds - away_odds) <= 0.95, both >= 2.0
- table_diff <= 5, form_gap <= 4
- Требуется: standings + odds

### SA_AWAY_DRAW
- Лига: Serie A
- away_team in {Empoli, Genoa, Cremonese, Salernitana, Venezia}
- odds_draw: 3.0-3.15 ИЛИ 3.45-4.6
- odds_under_2_5 <= 2.0
- home_form (historical) <= 6pts
- Требуется: odds + historical form

### AWAY_SA_STRICT_PLUS
- Лига: Serie A
- odds_away: 2.05-2.85
- pos_gap <= -4 (away выше)
- away_form - home_form >= 4
- home_allowed >= 1.30, away_scored >= 1.25
- Требуется: standings + form + goals

### BTTS_YES_CORE
- Лига: EPL или BL1
- odds_btts_yes: EPL 2.00-2.10, BL1 1.95-2.10
- both score >= 1.0, both concede >= 0.8
- Требуется: form_details (goals)

### RPL_OVER25_BTTS
- Лига: RPL
- odds_over_2_5: 1.8-2.1 И odds_btts_yes: 1.8-2.1
- home_form_pts >= 4 И away_form_pts >= 4
- Требуется: form (>= 2 matches each side)

### PD_BTTS_DOUBLE
- Лига: La Liga
- odds_over_2_5: 1.6-1.9 И odds_btts_yes: 1.75-1.95
- away_form_pts >= 6 (или форма >= 2 матчей)
- Требуется: odds + form

### FL1_BTTS_DOUBLE
- Лига: Ligue 1
- odds_over_2_5: 1.6-1.9 И odds_btts_yes: 2.0-2.1
- away_form_pts >= 6 (или форма >= 2 матчей)
- Требуется: odds + form

### NLA_BERN_AWAY_DRAW
- Лига: Swiss NLA
- away_team: "берн"
- odds_draw: 4.0-5.2
- Требуется: ТОЛЬКО odds (минимум данных!)

### MLS_BTTS_HOME
- Лига: MLS
- home_team in specific list
- odds_btts_yes: 1.50-1.75
- Требуется: ТОЛЬКО odds + team name

### PD_AWAY_VALUE
- Лига: La Liga
- odds_away: 2.00-2.50
- away_team NOT in excluded list
- Требуется: ТОЛЬКО odds + team name

---

## Ответы на вопросы

### 1. Могут ли rule-driven стратегии работать без ML?

**ДА.** `build_rule_recommendation()` создаёт полностью валидную рекомендацию со всеми полями, без вызова LLM. Probability берётся из `rule_probabilities` dict (historical win rates from backtest).

### 2. Блокирует ли их pre-flight?

**НЕТ.** Rule-driven path (строка 4664) выполняется ДО pre-flight skip (строка 4867). Если правило срабатывает, `continue` не даёт коду дойти до pre-flight. Pre-flight блокирует только матчи, для которых rule-driven стратегии не нашли совпадений.

### 3. Блокирует ли их edge filter?

**В ОСНОВНОМ НЕТ.** Edge filter (`enrich_with_math`, строка 3194) проверяет `our_p > market_p + min_edge`. Для большинства rule стратегий edge достаточен (0.06-0.20 при required 0.015-0.025).

**Единственная проблемная стратегия:** `AWAY_SA_STRICT_PLUS` (our_p=0.42, edge ~0.003 при required 0.025).

### 4. Где именно сигнал отбрасывается?

Сигнал отбрасывается на одном из 3 этапов:

| Этап | Строка | Причина | Сколько |
|---|---|---|---|
| `get_pruned_live_rule` | 4664 | Нет совпадения с правилом (не та лига, odds не в range, form/goals критерии не met) | ~95%+ матчей |
| `enrich_with_math` edge filter | 3194 | `our_p <= market_p + min_edge` | ~0-5% прошедших правил |
| `validate_recommendation` | 4768 | EV < 0.03, Kelly <= 0, exposure > 50% | Зависит от состояния банка |

**Основная причина 0 BET:** rule-driven стратегии покрывают малую часть матчей (только Serie A, EPL, BL1, RPL, La Liga, Ligue 1, NLA, MLS). Матчи из других лиг не проходят `get_pruned_live_rule()` и уходят в pre-flight → LLM fallback → LLM недоступен → PASS.

---

## Рекомендации

### Минимальный фикс: shadow mode как betting source

Проблема не в rule-driven стратегиях — они работают корректно. Проблема в том, что `--no-llm` режим использует `simulate_llm_response()` с `shadow_only=True`, и эти рекомендации не считаются ставками.

**Вариант 1 (быстрый):** Для rule-driven матчей shadow mode не нужен — они уже прошли. Проблема только для НЕ-rule матчей. Если нужно больше ставок без LLM, нужно расширить покрытие rule-driven стратегий.

**Вариант 2 (расширить rule coverage):** Добавить rule-driven стратегии для лиг, которые сейчас попадают в pre-flight SKIP:
- Добавить летние BTTS правила для скандинавских лиг (уже есть `SUMMER_BTTS_HOME`)
- Добавить простые odds-only правила для MLS (уже есть `MLS_BTTS_HOME`)
- Проверить, почему `SUMMER_BTTS_HOME` и `MLS_BTTS_HOME` не срабатывают — они требуют минимум данных (только odds + team name)

**Вариант 3 (исправить AWAY_SA_STRICT_PLUS):** Поднять `our_probability` с 0.42 до 0.45+, иначе edge filter отбрасывает сигнал:
```python
# line 785
"AWAY_SA_STRICT_PLUS": 0.45,  # было 0.42
```

### Архитектурное улучшение

Разделить pipeline на два независимых потока:

```
Rule-driven stream:  get_pruned_live_rule → build_rule_rec → calibrate → validate → bet
ML stream:           pre_flight → call_llm → calibrate → validate → bet
```

Сейчас rule-driven stream уже независим, но `--no-llm` флаг не влияет на него. Это корректно. Однако если цель — иметь работающий pipeline без LLM, нужно расширить rule-driven покрытие.
