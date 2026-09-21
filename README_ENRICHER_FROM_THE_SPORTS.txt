enricher_from_the_sports.py

Что делает:
- читает standings + results_raw + matches
- заполняет match_facts для upcoming матчей KHL
- считает:
  - форму последних 5
  - средние голы за/против
  - H2H summary
  - позиции / очки / мотивацию

Как запускать:
1) Сначала:
   python the_sports_khl_parser.py

2) Потом:
   python enricher_from_the_sports.py

3) Потом:
   python agent_handoff_v2.py --dry-run --sport hockey --limit 5
