# Settlement Fix Summary — 2026-04-23

## Что было сломано
- tennis bets оставались `pending` после завершения матча.
- `task_settle()` в `run_pipeline.py` не повторял полный путь ручного settle из `web_panel.py`.
- `tennis_results_updater.py` при ручном запуске без аргументов тянул только текущий день.
- `settler.py` не закрывал tennis bet, если в `matches` уже был `finished` + `home_score/away_score`, но не нашёлся дополнительный матч в `tennis_live_results`.
- в `settler.py` использовался `timedelta` без импорта.
- в `tg_bot.py` tennis active predictions могли показывать `П1 ()` / `П2 ()`.

## Что изменено
- `run_pipeline.py`
  - `task_settle()` теперь делает полный путь:
    - `repair_pending_bets_v2.py` если существует
    - `tennis_results_updater.py --days 3` если существует
    - `updater_results.py --settle`
    - `settler.py` если существует
    - `tg_bot.py --notify results`
  - timeout для settlement шагов поднят до `240s`.
  - добавлена telemetry: `pending_before`, `pending_after`, `tennis_pending_after`, `closed_now`, `settled_today`.
- `web_panel.py`
  - `/api/settle_now` синхронизирован с тем же порядком и timeout `240s`.
- `updater_results.py`
  - добавлен `--debug-tennis`.
  - добавлена tennis-диагностика:
    - `pending`
    - `with_result`
    - `close_candidates`
    - `no_match_score`
    - `no_result_source`
    - `mapping_failed`
    - `match_not_finished`
  - улучшена диагностика `mapping_failed`: теперь это related tennis result по игрокам, а не любой результат на дату.
  - `run_settler_now()` теперь запускает `settler.py` по абсолютному пути файла проекта, а не через относительный путь из текущей директории.
- `settler.py`
  - добавлен импорт `timedelta`.
  - добавлен импорт `re` для tennis name matcher.
  - tennis settlement теперь умеет закрывать ставку по уже записанному `matches.home_score/away_score`, даже если live mapping не сработал.
  - tennis matcher усилен: теперь сравнение переживает варианты написания фамилий через translit/skeleton, например `Боултер K` ↔ `Кэти Бултер`.
  - добавлен tennis summary: `pending_total`, `ready_with_score`, `closed`, `mapping_failed`.
- `tennis_results_updater.py`
  - default `--days` изменён с `1` на `3`, чтобы ручной запуск `python3 tennis_results_updater.py` подтягивал не только текущий день.
- `tg_bot.py`
  - tennis active predictions теперь показывают `П1 (home_team)` / `П2 (away_team)`.
  - если имя пустое, скобки не выводятся.

## Что выполнено на рабочей БД
Запуски:
- `python3 tennis_results_updater.py`
- `python3 updater_results.py --settle --debug-tennis`
- `python3 settler.py`

Результат:
- `2026-04-23` tennis bet закрывается корректно:
  - `bet_id=939`
  - `Вальехо А-Д — Димитров Г`
  - `market=player2_win`
  - `result=lost`
  - `profit=-313.24`
  - `match_score=1:0`
- дополнительно закрыты за `2026-04-22`:
  - `bet_id=935` — `Крюгер Э — Кенин С` → `won`, `profit=316.44`
  - `bet_id=940` — `Галфи Д — Томлянович А` → `won`, `profit=313.24`
  - `bet_id=934` — `Таунсенд Т — Боултер K` → `lost`, `profit=-316.44`
- SQL после финальных прогонов:
  - `pending_tennis_after = 8`
  - `closed_tennis_today = 4`

Проверка на `2026-04-23`:
- pending tennis на `2026-04-23` нет.
- единственная tennis ставка на эту дату уже закрыта (`bet_id=939`).

## Остаток pending tennis
После финального прогона осталось `8` pending tennis:
- `6` — `match_not_finished`
- `2` — `no_result_source`

Старые матчи без найденного источника результата:
- `bet_id=933` — `Микелсен А — Чина Ф` (`2026-04-22`)
- `bet_id=936` — `Атман Т — Кецманович М` (`2026-04-22`)

Эти ставки не закрывались вручную без результата.
