Что произошло

Ошибка:
sqlite3.OperationalError: table standings has no column named wins

Это значит:
- в betagent.db уже была старая таблица standings
- новый parser ожидает новую схему standings
- SQLite не умеет сам расширять такую схему в момент INSERT

Что делать

1. Запусти миграцию:
   python migrate_standings_schema.py

2. Потом снова:
   python the_sports_khl_parser.py

Если хочешь самый грубый вариант:
- можно было бы просто удалить таблицу standings
- но этот файл делает аккуратнее и пытается перенести совместимые данные
