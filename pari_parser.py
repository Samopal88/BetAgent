import requests
import sqlite3

DB = "betagent.db"

URL = "https://line-lb01-w.pb06e2-resources.com/events/list"
PARAMS = {
    "lang": "ru",
    "scopeMarket": "2300",
}
HEADERS = {
    "user-agent": "Mozilla/5.0",
    "accept": "application/json",
}

FACTOR_HOME = 921
FACTOR_DRAW = 922
FACTOR_AWAY = 923

BAD_TOKENS = [
    "лига про",
    "лиги про",
    "esports",
    "2x2",
    "3x3",
    "3х3",
    "2х2",
    "женщины",
    "жен.",
    "до 19",
    "до 20",
    "до 21",
    "до 23",
    "молодеж",
    "регби",
    "финал",
    "1/2 финала",
    "1/4 финала",
    "1/8 финала",
    "финал 4-х",
    "четвертьфинал",
    "полуфинал",
]

ALLOWED = [
    "англия. премьер-лига. сезон",
    "германия. бундеслига. сезон",
    "италия. серия а. сезон",
    "франция. лига 1. сезон",
    "россия. премьер-лига. сезон",
    "испания. примера дивизион. сезон",
    "нхл. регулярный сезон",
]

def avg(values):
    values = [v for v in values if isinstance(v, (int, float)) and v > 0]
    if not values:
        return None
    return sum(values) / len(values)

def fetch():
    r = requests.get(URL, params=PARAMS, headers=HEADERS, timeout=30)
    r.raise_for_status()
    return r.json()

def build_sport_map(data):
    return {s.get("id"): s.get("name", "") for s in data.get("sports", []) if s.get("id") is not None}

def build_factor_map(data):
    out = {}
    for row in data.get("customFactors", []):
        event_id = row.get("e")
        factors = row.get("factors", [])
        if event_id is None:
            continue
        out[event_id] = factors
    return out

def is_allowed_league(name: str) -> bool:

    l = (name or "").lower()

    if any(x in l for x in BAD_TOKENS):
        return False

    for a in ALLOWED:
        if l.startswith(a):
            return True

    return False

def parse_totals(factors):

    overs = []
    unders = []

    for f in factors:

        pt = str(f.get("pt", ""))

        if "+" in pt or "-" in pt:
            continue

        fid = f.get("f")
        val = f.get("v")

        if not isinstance(val, (int, float)):
            continue

        if fid % 2 == 0:
            unders.append(val)
        else:
            overs.append(val)

    return avg(overs), avg(unders)

def parse(data):

    rows = []

    sport_map = build_sport_map(data)
    factor_map = build_factor_map(data)

    for e in data.get("events", []):

        event_id = e.get("id")

        team1 = e.get("team1")
        team2 = e.get("team2")

        start_time = e.get("startTime")

        sport_id = e.get("sportId")

        if not team1 or not team2:
            continue

        league = sport_map.get(sport_id, "")

        if not is_allowed_league(league):
            continue

        factors = factor_map.get(event_id, [])

        if not factors:
            continue

        home = None
        draw = None
        away = None

        for f in factors:

            fid = f.get("f")
            val = f.get("v")

            if not isinstance(val, (int, float)):
                continue

            if fid == FACTOR_HOME:
                home = val

            elif fid == FACTOR_DRAW:
                draw = val

            elif fid == FACTOR_AWAY:
                away = val

        over, under = parse_totals(factors)

        bad_names = {"хозяева", "гости", ""}
        h_norm = str(team1).strip().lower() if team1 is not None else ""
        a_norm = str(team2).strip().lower() if team2 is not None else ""

        if h_norm in bad_names or a_norm in bad_names or h_norm == a_norm:
            continue

        rows.append(
            dict(
                league=league,
                home_team=team1,
                away_team=team2,
                match_date=start_time,
                bookmaker="pari",
                odds_home=home,
                odds_draw=draw,
                odds_away=away,
                over=over,
                under=under,
            )
        )

    return rows

def save(rows):

    conn = sqlite3.connect(DB)

    cur = conn.cursor()

    cur.execute(
        """
        create table if not exists odds_pari (

            league text,
            home_team text,
            away_team text,

            match_date text,

            bookmaker text,

            odds_home real,
            odds_draw real,
            odds_away real,

            over real,
            under real
        )
        """
    )

    cur.execute("delete from odds_pari")

    cur.executemany(
        """
        insert into odds_pari
        values (

            :league,
            :home_team,
            :away_team,

            :match_date,

            :bookmaker,

            :odds_home,
            :odds_draw,
            :odds_away,

            :over,
            :under
        )
        """,
        rows,
    )

    conn.commit()

    conn.close()

def run():

    data = fetch()

    rows = parse(data)

    save(rows)

    print("pari filtered:", len(rows))

if __name__ == "__main__":
    run()
