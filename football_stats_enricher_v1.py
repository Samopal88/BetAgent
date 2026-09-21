import sqlite3
import time
import requests
from datetime import datetime

DB_PATH = "/root/betagent/betagent.db"

HEADERS = {
    "User-Agent": "Mozilla/5.0"
}

def get_matches_without_stats(conn):
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, source_match_id
        FROM football_matches
        WHERE shots_home IS NULL
    """)
    return cursor.fetchall()

def fetch_stats(match_id):
    url = f"https://betz.su/line/?detail={match_id}"
    r = requests.get(url, headers=HEADERS, timeout=20)

    if r.status_code != 200:
        return None

    html = r.text

    # базовый пример парсинга
    def extract(label):
        if label in html:
            part = html.split(label)[1]
            val = part.split("<")[0]
            return val.strip()
        return None

    stats = {
        "shots_home": extract("Shots Home"),
        "shots_away": extract("Shots Away"),
        "possession_home": extract("Possession Home"),
        "possession_away": extract("Possession Away"),
    }

    return stats


def update_stats(conn, match_db_id, stats):
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE football_matches
        SET
            shots_home = ?,
            shots_away = ?,
            possession_home = ?,
            possession_away = ?
        WHERE id = ?
    """, (
        stats["shots_home"],
        stats["shots_away"],
        stats["possession_home"],
        stats["possession_away"],
        match_db_id
    ))

    conn.commit()


def main():
    conn = sqlite3.connect(DB_PATH)

    matches = get_matches_without_stats(conn)

    print(f"найдено матчей без статы: {len(matches)}")

    for i, (db_id, source_id) in enumerate(matches):

        try:
            stats = fetch_stats(source_id)

            if stats:
                update_stats(conn, db_id, stats)

            if i % 100 == 0:
                print(f"обработано {i}")

            time.sleep(1.2)

        except Exception as e:
            print("error", e)

    print("done")


if __name__ == "__main__":
    main()
