parser_v2.py

Что исправлено:
- можно запускать только по хоккею:
  python parser_v2.py --sport hockey
- можно удалить старые upcoming по хоккею перед новой загрузкой:
  python parser_v2.py --sport hockey --replace-sport
- в вывод больше не лезут заглушки "Хозяева — Гости"
- show_matches умеет показывать только нужный спорт

Рекомендуемый запуск для хоккея:
  python parser_v2.py --sport hockey --replace-sport --show-limit 50

Потом:
  python the_sports_khl_parser.py
  python enricher_from_the_sports.py
  python agent_handoff_v2.py --dry-run --sport hockey --limit 5
