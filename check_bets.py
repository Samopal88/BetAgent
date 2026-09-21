import sqlite3, os
conn = sqlite3.connect(os.getenv("BETAGENT_DB", "betagent.db"))

print("=== Ставки по датам ===")
for r in conn.execute("SELECT DATE(created_at), COUNT(*) as c FROM bets WHERE result='pending' GROUP BY DATE(created_at)").fetchall():
    print(f"  {r[0]}: {r[1]} ставок")

print("\n=== Последние 5 ставок ===")
for r in conn.execute("SELECT created_at, market, odds, stake, result FROM bets ORDER BY created_at DESC LIMIT 5").fetchall():
    print(f"  {r[0]} | {r[1]} @ {r[2]} | {r[3]} руб | {r[4]}")

print("\n=== Всего pending ===")
c = conn.execute("SELECT COUNT(*) FROM bets WHERE result='pending'").fetchone()[0]
print(f"  {c}")
conn.close()
