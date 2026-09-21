#!/usr/bin/env python3
"""Парсер tennis-data.co.uk — ATP и WTA с коэфами Pinnacle/B365"""
import requests, csv, io, sqlite3, logging
from pathlib import Path

DB_PATH = "betagent.db"
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger(__name__)

HEADERS = {'User-Agent': 'Mozilla/5.0'}

ATP_TOURNAMENTS = [
    'ausopen','frenchopen','wimbledon','usopen',
    'doha','dubai','miami','houston','monte-carlo','barcelona',
    'madrid','rome','halle','queens','hamburg','eastbourne',
    'bastad','umag','kitzbuhel','montreal','toronto','cincinnati',
    'winston-salem','metz','chengdu','beijing','shanghai',
    'vienna','basel','paris','stockholm'
]

WTA_TOURNAMENTS = [
    'ausopen','frenchopen','wimbledon','usopen',
    'doha','dubai','miami','stuttgart','madrid','rome',
    'eastbourne','berlin','bad-homburg','toronto','montreal',
    'cincinnati','cleveland','guadalajara','ostrava','chicago',
    'beijing','wuhan','zhengzhou','guangzhou','seoul',
    'luxembourg','linz','zhuhai'
]

YEARS = range(2021, 2027)

def ensure_table(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS tennis_data_odds (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tour TEXT, year INTEGER, tournament TEXT,
            surface TEXT, round TEXT, best_of INTEGER,
            winner TEXT, loser TEXT,
            w_rank INTEGER, l_rank INTEGER,
            w_sets INTEGER, l_sets INTEGER,
            score TEXT,
            b365_winner REAL, b365_loser REAL,
            ps_winner REAL, ps_loser REAL,
            created_at TEXT DEFAULT (datetime('now')),
            UNIQUE(tour, year, tournament, winner, loser, round)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tdo_winner ON tennis_data_odds(winner, year)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tdo_loser ON tennis_data_odds(loser, year)")
    conn.commit()

def parse_csv(url, tour, year, tournament, conn):
    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        r.raise_for_status()
    except:
        return 0
    
    reader = csv.DictReader(r.content.decode('latin-1').splitlines())
    n = 0
    for row in reader:
        try:
            winner = row.get('Winner','').strip()
            loser = row.get('Loser','').strip()
            if not winner or not loser:
                continue
            
            # Счёт по сетам
            score_parts = []
            for i in range(1,6):
                w = row.get(f'W{i}','').strip()
                l = row.get(f'L{i}','').strip()
                if w and l:
                    score_parts.append(f'{w}-{l}')
            
            conn.execute("""
                INSERT OR IGNORE INTO tennis_data_odds
                (tour, year, tournament, surface, round, best_of,
                 winner, loser, w_rank, l_rank, w_sets, l_sets, score,
                 b365_winner, b365_loser, ps_winner, ps_loser)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                tour, year, tournament,
                row.get('Surface','').strip(),
                row.get('Round','').strip(),
                int(row.get('Best of',3) or 3),
                winner, loser,
                int(row.get('WRank',0) or 0) or None,
                int(row.get('LRank',0) or 0) or None,
                int(row.get('Wsets',0) or 0) or None,
                int(row.get('Lsets',0) or 0) or None,
                '-'.join(score_parts),
                float(row.get('B365W',0) or 0) or None,
                float(row.get('B365L',0) or 0) or None,
                float(row.get('PSW',0) or 0) or None,
                float(row.get('PSL',0) or 0) or None,
            ))
            n += conn.execute("SELECT changes()").fetchone()[0]
        except Exception as e:
            continue
    conn.commit()
    return n

def main():
    conn = sqlite3.connect(DB_PATH)
    ensure_table(conn)
    total = 0
    
    for year in YEARS:
        for tour, tournaments in [('ATP', ATP_TOURNAMENTS), ('WTA', WTA_TOURNAMENTS)]:
            prefix = '' if tour=='ATP' else 'w'
            for t in tournaments:
                url = f'http://www.tennis-data.co.uk/{year}{prefix}/{t}.csv'
                n = parse_csv(url, tour, year, t, conn)
                if n > 0:
                    log.info(f'{tour} {year} {t}: +{n}')
                    total += n
    
    log.info(f'Готово! Всего: +{total}')
    conn.close()

if __name__ == '__main__':
    main()
