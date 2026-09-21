import sqlite3, os
conn = sqlite3.connect(os.getenv("BETAGENT_DB", "betagent.db"))
conn.row_factory = sqlite3.Row

print("=== Матч Автомобилист ===")
r = conn.execute("""
    SELECT m.id, m.status, m.home_score, m.away_score,
           b.id as bet_id, b.result, b.market, b.odds
    FROM matches m
    JOIN bets b ON b.match_id = m.id
    WHERE m.home_team LIKE '%Автомобилист%'
""").fetchone()
if r:
    print(dict(r))
else:
    print("Не найден")

print("\n=== Все finished матчи с pending ставками ===")
rows = conn.execute("""
    SELECT m.home_team, m.away_team, m.status, m.home_score, m.away_score,
           b.result, b.market
    FROM matches m JOIN bets b ON b.match_id = m.id
    WHERE m.status = 'finished' AND b.result = 'pending'
""").fetchall()
for r in rows:
    print(dict(r))

conn.close()
