Что делать дальше

Мой совет: НЕ распыляться сразу на КХЛ + НХЛ + футбол во всём пайплайне.

Правильный путь:
1. Узко протестировать один надёжный кусок:
   standings из TheSports
2. Проверить, что:
   - парсер стабильно берёт таблицу
   - данные нормально пишутся в standings
   - agent_handoff видит позиции/очки/голы
3. Только потом добавлять:
   - Livesport/Flashscore для формы
   - NHL
   - футбол

Но сам файл уже сделан расширяемым:
- сейчас заполняется KHL
- потом можно добавить NHL / football просто через другой URL

Как запускать:
1) По уже скачанному HTML:
   python parse_the_sports_standings.py --league khl --html the_sports_standings.html

2) Напрямую с сайта:
   python parse_the_sports_standings.py --league khl

После этого можно проверить:
   sqlite3 betagent.db "select league, team_name, position, points from standings limit 10;"
