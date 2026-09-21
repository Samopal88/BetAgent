import os
import requests
import sqlite3

API_KEY = os.getenv("ODDS_API_KEY", "")

SPORTS = {
    "hockey_nhl": "icehockey_nhl",
    "football_epl": "soccer_epl"
}

DB = "betagent.db"


def avg(values):

    values = [v for v in values if v]

    if not values:
        return None

    return sum(values) / len(values)



def fetch_odds(sport):

    url = f"https://api.the-odds-api.com/v4/sports/{sport}/odds"

    params = {

        "apiKey": API_KEY,

        "regions": "eu,uk",

        "markets": "h2h,totals",

        "oddsFormat": "decimal"

    }

    r = requests.get(url, params=params)

    r.raise_for_status()

    return r.json()



def parse_events(data):

    rows = []

    for event in data:

        home = event["home_team"]
        away = event["away_team"]

        match_date = event["commence_time"]

        odds_home = []
        odds_draw = []
        odds_away = []

        totals_over = []
        totals_under = []

        for book in event.get("bookmakers", []):

            for market in book.get("markets", []):

                if market["key"] == "h2h":

                    for o in market["outcomes"]:

                        if o["name"] == home:
                            odds_home.append(o["price"])

                        elif o["name"] == away:
                            odds_away.append(o["price"])

                        elif o["name"].lower() == "draw":
                            odds_draw.append(o["price"])


                if market["key"] == "totals":

                    for o in market["outcomes"]:

                        if o["name"] == "Over":
                            totals_over.append(o["price"])

                        elif o["name"] == "Under":
                            totals_under.append(o["price"])


        rows.append({

            "league": event["sport_title"],

            "home_team": home,
            "away_team": away,

            "match_date": match_date,

            "bookmaker": "avg",

            "odds_home": avg(odds_home),
            "odds_draw": avg(odds_draw),
            "odds_away": avg(odds_away),

            "over": avg(totals_over),
            "under": avg(totals_under)

        })


    return rows



def save(rows):

    conn = sqlite3.connect(DB)

    cur = conn.cursor()

    cur.execute("""

    CREATE TABLE IF NOT EXISTS odds_avg (

        league TEXT,
        home_team TEXT,
        away_team TEXT,
        match_date TEXT,

        bookmaker TEXT,

        odds_home REAL,
        odds_draw REAL,
        odds_away REAL,

        over REAL,
        under REAL

    )

    """)

    cur.executemany("""

    INSERT INTO odds_avg

    VALUES (

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

    """, rows)

    conn.commit()

    conn.close()



def run():

    all_rows = []

    for sport in SPORTS.values():

        data = fetch_odds(sport)

        rows = parse_events(data)

        all_rows.extend(rows)


    save(all_rows)

    print("parsed:", len(all_rows))



if __name__ == "__main__":

    run()

