Почему были сплошные PASS

Потому что:
- the_sports_khl_parser.py + enricher_from_the_sports.py создают match_facts
  для матчей TheSports
- agent_handoff_v4.py анализирует матчи Fonbet с odds
- это разные match_id

Итог:
- коэффициенты есть у Fonbet
- факты есть у TheSports
- но они не связаны -> handoff видит пустой payload -> PASS

Что делать:
1) python the_sports_khl_parser.py
2) python enricher_from_the_sports.py
3) python sync_match_facts_to_fonbet.py
4) python agent_handoff_v4.py --dry-run --sport hockey --limit 5
