КАК СИСТЕМА ПОНИМАЕТ, ЧТО СТАВКА ЗАШЛА

1) parser.py или отдельный updater_results.py обновляет таблицу matches:
   - status = 'finished'
   - home_score = ...
   - away_score = ...

2) settler.py берёт из bets все result='pending'

3) Для каждой ставки:
   - если market='home_win' и home_score > away_score -> won
   - если market='draw' и home_score == away_score -> won
   - если market='away_win' и away_score > home_score -> won
   - иначе lost

4) profit:
   - won  -> stake * (odds - 1)
   - lost -> -stake

5) Затем пишется запись в accuracy_log

ЧТО ВАЖНО СЕЙЧАС

В parser.py таблица matches уже имеет поля:
- status
- home_score
- away_score

Но текущий parser.py, который ты присылал, при update делает только:
- odds_home
- odds_draw
- odds_away
- updated_at

То есть сам parser пока НЕ обновляет финальный статус и счёт.
Из-за этого settler.py пока не сможет ничего закрыть автоматически,
ПОКА кто-то не заполнит:
- status='finished'
- home_score
- away_score

Значит нужен ещё один шаг:

ВАРИАНТ A (лучший):
- сделать updater_results.py, который будет ходить в API Фонбета и обновлять счёт/статус

ВАРИАНТ B (временно):
- руками обновлять finished матчи в SQLite
- потом запускать settler.py

КАК ЗАПУСКАТЬ

python settler.py
