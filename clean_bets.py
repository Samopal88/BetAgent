#!/usr/bin/env python3
"""
clean_bets.py — очищает pending ставки.

Запуск:
  python clean_bets.py --dry-run          # показать что будет удалено
  python clean_bets.py                    # удалить дубли
  python clean_bets.py --all              # удалить ВСЕ pending
  python clean_bets.py --all --sport football  # удалить все pending по футболу
  python clean_bets.py --all --sport hockey    # удалить все pending по хоккею
"""
import sqlite3, os, argparse
from pathlib import Path

DB = Path(os.getenv("BETAGENT_DB", "betagent.db"))

ap = argparse.ArgumentParser()
ap.add_argument("--dry-run", action="store_true")
ap.add_argument("--all", action="store_true", help="Удалить все pending")
ap.add_argument("--sport", default=None, help="football или hockey")
args = ap.parse_args()

conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row

sport_filter = ""
sport_params = []
if args.sport:
    sport_filter = "AND m.sport = ?"
    sport_params = [args.sport]
    print(f"Фильтр: только {args.sport}")

if args.all:
    count = conn.execute(f"""
        SELECT COUNT(*) FROM bets b
        JOIN matches m ON b.match_id = m.id
        WHERE b.result='pending' {sport_filter}
    """, sport_params).fetchone()[0]

    if not args.dry_run:
        conn.execute(f"""
            DELETE FROM bets WHERE id IN (
                SELECT b.id FROM bets b
                JOIN matches m ON b.match_id = m.id
                WHERE b.result='pending' {sport_filter}
            )
        """, sport_params)
        conn.commit()
        print(f"✅ Удалено {count} pending ставок")
    else:
        print(f"[DRY-RUN] Будет удалено {count} pending ставок")
    conn.close()
    exit()

# Удаляем только дубли
dups = conn.execute(f"""
    SELECT b.match_id, b.market, COUNT(*) as cnt, MAX(b.id) as newest_id
    FROM bets b JOIN matches m ON b.match_id = m.id
    WHERE b.result = 'pending' {sport_filter}
    GROUP BY b.match_id, b.market
    HAVING COUNT(*) > 1
""", sport_params).fetchall()

if not dups:
    print("✅ Дублей нет")
    conn.close()
    exit()

ids_to_delete = []
for d in dups:
    old = conn.execute("""
        SELECT id FROM bets
        WHERE match_id=? AND market=? AND result='pending' AND id != ?
    """, (d["match_id"], d["market"], d["newest_id"])).fetchall()
    for r in old:
        ids_to_delete.append(r[0])

print(f"Дублей к удалению: {len(ids_to_delete)}")
if not args.dry_run and ids_to_delete:
    conn.execute(f"DELETE FROM bets WHERE id IN ({','.join(map(str, ids_to_delete))})")
    conn.commit()
    print(f"✅ Удалено {len(ids_to_delete)} дублей")

remaining = conn.execute("SELECT COUNT(*) FROM bets WHERE result='pending'").fetchone()[0]
print(f"Остаток pending: {remaining}")
conn.close()
