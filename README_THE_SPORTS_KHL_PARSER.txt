the_sports_khl_parser.py

Что делает:
- парсит KHL страницу TheSports без pandas
- сохраняет:
  1) standings
  2) results_raw
  3) matches (обновляет finished/upcoming и score)

Как запускать:
1. По сохранённому HTML:
   python the_sports_khl_parser.py --html the_sports_standings.html

2. Напрямую с сайта:
   python the_sports_khl_parser.py

Что дальше:
- после этого agent/enricher уже сможет использовать standings
- а settler сможет закрывать ставки, если матч finished и score уже обновлены
