Почему раньше не было коэффициентов

Потому что agent_handoff_v2.py брал upcoming-матчи вообще все подряд,
включая записи из TheSports KHL, которые мы добавили для standings/results,
но у них odds_home/odds_away = NULL.

Фикс:
- agent_handoff_v3.py берёт только матчи, где odds_home и odds_away НЕ NULL

Как запускать:
  python parser_v2.py --sport hockey --replace-sport --show-limit 50
  python the_sports_khl_parser.py
  python enricher_from_the_sports.py
  python agent_handoff_v3.py --dry-run --sport hockey --limit 5
