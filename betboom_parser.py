from playwright.sync_api import sync_playwright
import sqlite3

DB = "betagent.db"


URLS = [

    "https://betboom.ru/sport/ice-hockey",
    "https://betboom.ru/sport/football"

]


def parse_page(page):

    cards = page.query_selector_all('[data-test="event-card"]')

    rows = []

    for c in cards:

        try:

            teams = c.query_selector_all('[data-test="team-name"]')

            odds = c.query_selector_all('[data-test="outcome-odds"]')

            if len(teams) < 2 or len(odds) < 2:
                continue


            home = teams[0].inner_text().strip()
            away = teams[1].inner_text().strip()

            odds_home = float(odds[0].inner_text())
            odds_away = float(odds[1].inner_text())


            rows.append({

                "league": "betboom",

                "home_team": home,
                "away_team": away,

                "match_date": "",

                "bookmaker": "betboom",

                "odds_home": odds_home,
                "odds_away": odds_away

            })

        except:
            pass


    return rows



def save(rows):

    conn = sqlite3.connect(DB)

    cur = conn.cursor()

    cur.execute("""

    CREATE TABLE IF NOT EXISTS odds_betboom (

        league TEXT,

        home_team TEXT,
        away_team TEXT,

        match_date TEXT,

        bookmaker TEXT,

        odds_home REAL,
        odds_away REAL

    )

    """)

    cur.executemany("""

    INSERT INTO odds_betboom

    VALUES (

        :league,

        :home_team,
        :away_team,

        :match_date,

        :bookmaker,

        :odds_home,
        :odds_away

    )

    """, rows)

    conn.commit()

    conn.close()



def run():

    rows = []

    with sync_playwright() as p:

        browser = p.chromium.launch(headless=True)

        page = browser.new_page()


        for url in URLS:

            print("loading:", url)

            page.goto(url)

            page.wait_for_timeout(5000)

            rows.extend(parse_page(page))


        browser.close()


    save(rows)

    print("betboom parsed:", len(rows))



if __name__ == "__main__":

    run()

