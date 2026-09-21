import sqlite3, os
conn = sqlite3.connect(os.getenv("BETAGENT_DB", "betagent.db"))
for r in conn.execute("SELECT team_name, position FROM standings WHERE league='nhl' ORDER BY position"):
    print(f"  {r[1]}. {r[0]}")
conn.close()
