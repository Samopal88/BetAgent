fetch_khl_form_v2.py — как использовать

1. Положи файл рядом с:
- betagent.db
- parser.py
- enricher.py
- agent_handoff.py

2. Запуск:
python fetch_khl_form_v2.py

или:
python fetch_khl_form_v2.py --limit 10

3. Что делает:
- обновляет форму команд КХЛ в таблице match_facts
- берёт средние голы из standings
- добавляет мотивацию
- использует кэш в папке .cache_khl
- устойчивее переносит таймауты khl.ru

4. Дальше:
python agent_handoff.py --dry-run --sport hockey --limit 5
