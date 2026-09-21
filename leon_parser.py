import requests
import sqlite3

DB = "betagent.db"

URL = "https://leon.ru/api-2/betline/events/all"

HEADERS = {
    "user-agent": "Mozilla/5.0",
    "accept": "application/json",
}

PARAMS = {
    "ctag": "ru-RU",
    "hideClosed": "true",
    "flags": "reg,urlv2,orn2,mm2,rrc,nodup",
}

ALLOWED = [
    "англия. премьер-лига",
    "германия. бундеслига",
    "италия. серия а",
    "франция. лига 1",
    "россия. премьер-лига",
    "сша. нхл",
]

BAD = [
    "женщины",
    "до 19",
    "до 20",
    "до 21",
    "до 23",
    "esport",
    "ehockey",
    "кибер",
    "2x2",
    "3x3",
    "лиги про",
    "лига чемпионов",
    "лига европы",
    "швейцар",
    "чех",
]

def ok_league(name):

    if not name:
        return False

    name=name.lower()

    if any(x in name for x in BAD):
        return False

    for a in ALLOWED:

        if name.startswith(a):

            return True

    return False


def avg(vals):

    vals=[v for v in vals if isinstance(v,(int,float))]

    if not vals:
        return None

    return sum(vals)/len(vals)


def fetch():

    r=requests.get(URL,params=PARAMS,headers=HEADERS)

    r.raise_for_status()

    return r.json()



def build_league(event):

    league=event.get("league",{}) or {}

    region=league.get("region",{}) or {}

    r=region.get("name","")

    l=league.get("name","")

    if r and l:

        return f"{r}. {l}"

    return l or r



def parse(data):

    rows=[]

    for e in data.get("events",[]):

        league=build_league(e)

        if not ok_league(league):

            continue


        home=None
        away=None

        for c in e.get("competitors",[]):

            if c.get("homeAway")=="HOME":

                home=c.get("name")

            elif c.get("homeAway")=="AWAY":

                away=c.get("name")


        if not home or not away:

            continue


        home_k=None
        draw_k=None
        away_k=None

        overs=[]
        unders=[]


        for m in e.get("markets",[]):

            name=(m.get("name") or "").lower()


            if "1х2" in name or name=="исход":

                for r in m.get("runners",[]):

                    k=r.get("price")

                    if r.get("name")=="1":

                        home_k=k

                    elif r.get("name") in ("x","X"):

                        draw_k=k

                    elif r.get("name")=="2":

                        away_k=k


            if "тотал" in name:

                for r in m.get("runners",[]):

                    k=r.get("price")

                    if not isinstance(k,(int,float)):

                        continue

                    if "больше" in (r.get("name") or "").lower():

                        overs.append(k)

                    else:

                        unders.append(k)



        rows.append(dict(

            league=league,

            home_team=home,
            away_team=away,

            match_date=e.get("kickoff"),

            bookmaker="leon",

            odds_home=home_k,
            odds_draw=draw_k,
            odds_away=away_k,

            over=avg(overs),
            under=avg(unders),

        ))


    return rows



def save(rows):

    conn=sqlite3.connect(DB)

    cur=conn.cursor()

    cur.execute("drop table if exists odds_leon")

    cur.execute("""

    create table odds_leon(

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

    """)


    cur.executemany("""

    insert into odds_leon

    values(

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

    """,rows)


    conn.commit()

    conn.close()



def run():

    data=fetch()

    rows=parse(data)

    save(rows)

    print("leon filtered:",len(rows))



if __name__=="__main__":

    run()

