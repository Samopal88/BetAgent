Что произошло

Ошибка:
sqlite3.OperationalError: table match_facts has no column named home_goals_allowed_avg

Почему:
- в betagent.db уже была старая таблица match_facts
- новый enricher пишет в расширенную схему
- SQLite не добавляет такие колонки автоматически

Что делать

1. Запусти миграцию:
   python migrate_match_facts_schema.py

2. Потом снова:
   python enricher_from_the_sports.py

3. Потом:
   python agent_handoff_v2.py --dry-run --sport hockey --limit 5
