import sqlite3, os
conn = sqlite3.connect(os.getenv("BETAGENT_DB", "betagent.db"))
conn.row_factory = sqlite3.Row
rows = conn.execute("""
    SELECT m.home_team, m.away_team, m.status, m.home_score, m.away_score,
           b.market, b.result, b.stake, m.match_date
    FROM bets b JOIN matches m ON b.match_id=m.id
    WHERE b.result='pending'
    ORDER BY m.match_date
""").fetchall()
for r in rows:
    print(f"{r['status']:10s} | {r['match_date'][:16]} | {r['home_team']} - {r['away_team']} | {r['market']} | score={r['home_score']}:{r['away_score']} | {r['stake']:.0f}")
conn.close()
