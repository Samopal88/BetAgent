import sqlite3
import re
from collections import defaultdict, Counter
from datetime import datetime, timezone

DB = "betagent.db"
MATCH_WINDOW_HOURS = 12


def avg(vals):
    vals = [v for v in vals if isinstance(v, (int, float)) and v > 0]
    if not vals:
        return None
    return round(sum(vals) / len(vals), 4)


def best(book_vals):
    book_vals = [
        (book, val)
        for book, val in book_vals
        if isinstance(val, (int, float)) and val > 0
    ]
    if not book_vals:
        return None, None
    book, val = max(book_vals, key=lambda x: x[1])
    return book, val


def safe_float(v):
    return v if isinstance(v, (int, float)) else None


def parse_dt(value):
    if value is None:
        return None

    if isinstance(value, (int, float)):
        ts = float(value)
        if ts > 10_000_000_000:
            ts /= 1000.0
        try:
            return datetime.fromtimestamp(ts, tz=timezone.utc)
        except Exception:
            return None

    s = str(value).strip()
    if not s:
        return None

    if s.isdigit():
        try:
            ts = int(s)
            if ts > 10_000_000_000:
                ts /= 1000.0
            return datetime.fromtimestamp(ts, tz=timezone.utc)
        except Exception:
            pass

    if s.endswith("Z"):
        s = s[:-1] + "+00:00"

    variants = [s]
    if " " in s and "T" not in s:
        variants.append(s.replace(" ", "T", 1))

    for item in variants:
        try:
            dt = datetime.fromisoformat(item)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except Exception:
            continue

    return None


def same_day_bucket(dt):
    if dt is None:
        return None
    return dt.strftime("%Y-%m-%d")


def time_close_enough(dt1, dt2, hours=MATCH_WINDOW_HOURS):
    if dt1 is None or dt2 is None:
        return True
    diff = abs((dt1 - dt2).total_seconds()) / 3600.0
    return diff <= hours


def clean_team_base(name: str) -> str:
    if not name:
        return ""
    s = str(name).lower().strip()
    s = s.replace("ё", "е")
    s = s.replace("—", "-").replace("–", "-")
    s = s.replace("'", "").replace('"', "")
    s = re.sub(r"[().,]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


ALIASES_EXACT = {
    "edmonton oilers": "эдмонтон",
    "utah hockey club": "юта",
    "utah mammoth": "юта",
    "юта мэммот": "юта",
    "юта маммот": "юта",
    "юта хоккей клаб": "юта",
    "los angeles kings": "лос-анджелес",
    "la kings": "лос-анджелес",
    "los angeles": "лос-анджелес",
    "лос анджелес кингз": "лос-анджелес",
    "лос анджелес": "лос-анджелес",
    "лос-анджелес кингз": "лос-анджелес",
    "лос-анджелес": "лос-анджелес",
    "new york islanders": "айлендерс",
    "ny islanders": "айлендерс",
    "айлендерс": "айлендерс",
    "florida panthers": "флорида",
    "флорида пантерз": "флорида",
    "anaheim ducks": "анахайм",
    "анахайм дакс": "анахайм",
    "boston bruins": "бостон",
    "бостон брюинз": "бостон",
    "minnesota wild": "миннесота",
    "миннесота уайлд": "миннесота",
    "columbus blue jackets": "коламбус",
    "коламбус блю джекетс": "коламбус",
    "san jose sharks": "сан-хосе",
    "сан хосе шаркс": "сан-хосе",
    "pittsburgh penguins": "питтсбург",
    "питтсбург пингвинз": "питтсбург",
    "carolina hurricanes": "каролина",
    "каролина харрикейнз": "каролина",
    "new jersey devils": "нью-джерси",
    "nj devils": "нью-джерси",
    "нью-джерси девилз": "нью-джерси",
    "buffalo sabres": "баффало",
    "buffalo sabers": "баффало",
    "баффало сейбрз": "баффало",
    "баффало сэйбрз": "баффало",
    "seattle kraken": "сиэтл",
    "сиэтл кракен": "сиэтл",
    "colorado avalanche": "колорадо",
    "колорадо эвеланш": "колорадо",
    "winnipeg jets": "виннипег",
    "виннипег джетс": "виннипег",
    "nashville predators": "нэшвилл",
    "нэшвилл предаторз": "нэшвилл",
    "montreal canadiens": "монреаль",
    "монреаль канадиенс": "монреаль",
    "st louis blues": "сент-луис",
    "saint louis blues": "сент-луис",
    "ст луис блюз": "сент-луис",
    "ст. луис": "сент-луис",
    "toronto maple leafs": "торонто",
    "торонто мейпл лифс": "торонто",
    "detroit red wings": "детройт",
    "детройт ред уингз": "детройт",
    "philadelphia flyers": "филадельфия",
    "филадельфия флайерз": "филадельфия",
    "calgary flames": "калгари",
    "калгари флеймз": "калгари",
    "vancouver canucks": "ванкувер",
    "ванкувер кэнакс": "ванкувер",
    "vegas golden knights": "вегас",
    "вегас голден найтс": "вегас",
    "washington capitals": "вашингтон",
    "вашингтон кэпиталз": "вашингтон",
    "ottawa senators": "оттава",
    "оттава сенаторз": "оттава",
    "tampa bay lightning": "тампа-бэй",
    "тампа бэй": "тампа-бэй",
    "тампа-бэй лайтнинг": "тампа-бэй",
    "пари нижний новгород": "пари нн",
    "нижний новгород": "пари нн",
    "цска москва": "цска",
    "динамо моск": "динамо москва",
    "локомотив моск": "локомотив москва",
    "локомотив м": "локомотив москва",
    "динамо мах": "динамо махачкала",
    "динамо мх": "динамо махачкала",
    "крылья сов.": "крылья советов",
    "пари сен-жермен": "псж",
    "paris saint-germain": "псж",
    "paris sg": "псж",
    "bayer leverkusen": "байер леверкузен",
    "bayer 04 leverkusen": "байер леверкузен",
    "байер 04": "байер леверкузен",
    "borussia dortmund": "боруссия дортмунд",
    "дортмунд": "боруссия дортмунд",
    "borussia monchengladbach": "боруссия менхенгладбах",
    "боруссия м": "боруссия менхенгладбах",
    "eintracht frankfurt": "айнтрахт франкфурт",
    "st pauli": "санкт-паули",
    "koln": "кельн",
    "fc koln": "кельн",
    "werder bremen": "вердер",
    "tsg hoffenheim": "хоффенхайм",
    "sc freiburg": "фрайбург",
    "vfl wolfsburg": "вольфсбург",
    "rb leipzig": "лейпциг",
    "hamburger sv": "гамбург",
    "hsv": "гамбург",
}


def apply_aliases(s: str) -> str:
    if s in ALIASES_EXACT:
        return ALIASES_EXACT[s]
    s = re.sub(r"\b(fc|fk|hc|sc|ac|bc|bk|sk|pfc|hockey club)\b", " ", s)
    s = re.sub(r"\b(football club|club de football)\b", " ", s)
    s = re.sub(r"\bu\s?\d+\b", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    if s in ALIASES_EXACT:
        return ALIASES_EXACT[s]
    return s


def norm_team(name: str) -> str:
    s = clean_team_base(name)
    s = apply_aliases(s)
    s = s.replace(" - ", "-").replace("- ", "-").replace(" -", "-")
    s = re.sub(r"\s+", " ", s).strip()
    return s


def unique_rows(rows):
    seen = set()
    out = []
    for x in rows:
        key = (
            x["source"], x["league"], x["home_team"], x["away_team"], x["match_date"],
            x["odds_home"], x["odds_draw"], x["odds_away"], x["over"], x["under"],
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(x)
    return out


def build_index(rows, source_name):
    by_pair = defaultdict(list)
    by_pair_day = defaultdict(list)
    all_rows = []

    for league, home, away, match_date, oh, od, oa, over, under in rows:
        if source_name == "pari" and league and "нхл" in str(league).lower():
            continue

        item = {
            "league": league,
            "home_team": home,
            "away_team": away,
            "norm_home": norm_team(home),
            "norm_away": norm_team(away),
            "match_date": match_date,
            "dt": parse_dt(match_date),
            "odds_home": safe_float(oh),
            "odds_draw": safe_float(od),
            "odds_away": safe_float(oa),
            "over": safe_float(over),
            "under": safe_float(under),
            "source": source_name,
            "matched": False,
        }
        all_rows.append(item)
        day = same_day_bucket(item["dt"])
        by_pair[(item["norm_home"], item["norm_away"])].append(item)
        by_pair[(item["norm_away"], item["norm_home"])].append(item)
        by_pair_day[(item["norm_home"], item["norm_away"], day)].append(item)
        by_pair_day[(item["norm_away"], item["norm_home"], day)].append(item)

    return {"by_pair": by_pair, "by_pair_day": by_pair_day, "all_rows": all_rows}


def load_odds_table(cur, table_name):
    rows = cur.execute(f"""
        select league, home_team, away_team, match_date,
               odds_home, odds_draw, odds_away, over, under
        from {table_name}
    """).fetchall()
    return build_index(rows, table_name.replace("odds_", ""))


def load_fonbet_matches(cur):
    rows = cur.execute("""
        select league, home_team, away_team, match_date,
               odds_home, odds_draw, odds_away,
               null as over, null as under
        from matches
        where sport in ('hockey', 'football')
          and status='upcoming'
    """).fetchall()
    return build_index(rows, "fonbet")


def collect_candidates(index_data, home, away, match_date):
    n_home = norm_team(home)
    n_away = norm_team(away)
    dt = parse_dt(match_date)
    day = same_day_bucket(dt)

    candidates = []
    candidates.extend(index_data["by_pair_day"].get((n_home, n_away, day), []))
    if not candidates:
        candidates.extend(index_data["by_pair"].get((n_home, n_away), []))

    filtered = [x for x in candidates if time_close_enough(dt, x["dt"])]
    if not filtered and candidates and (dt is None or all(x["dt"] is None for x in candidates)):
        filtered = candidates

    return unique_rows(filtered)


def table_exists(cur, table_name):
    row = cur.execute(
        "select name from sqlite_master where type='table' and name=?",
        (table_name,),
    ).fetchone()
    return row is not None


def main():
    conn = sqlite3.connect(DB)
    cur = conn.cursor()

    for table_name in ("matches", "odds_pari", "odds_leon"):
        if not table_exists(cur, table_name):
            raise RuntimeError(f"Таблица {table_name} не найдена")

    cur.execute("drop table if exists odds_merged")

    cur.execute("""
        create table odds_merged (
            match_id integer,
            league text,
            home_team text,
            away_team text,
            match_date text,
            avg_home real,
            avg_draw real,
            avg_away real,
            best_home_book text,
            best_home real,
            best_draw_book text,
            best_draw real,
            best_away_book text,
            best_away real,
            avg_over real,
            avg_under real
        )
    """)

    fonbet = load_fonbet_matches(cur)
    pari = load_odds_table(cur, "odds_pari")
    leon = load_odds_table(cur, "odds_leon")

    matches = cur.execute("""
        select id, league, home_team, away_team, match_date
        from matches
        where sport in ('hockey', 'football')
          and status='upcoming'
        order by match_date
    """).fetchall()

    insert_rows = []
    matched_counter = Counter()

    for match_id, league, home, away, match_date in matches:
        fonbet_candidates = collect_candidates(fonbet, home, away, match_date)
        pari_candidates = collect_candidates(pari, home, away, match_date)
        leon_candidates = collect_candidates(leon, home, away, match_date)

        for item in fonbet_candidates + pari_candidates + leon_candidates:
            item["matched"] = True

        candidates = unique_rows(fonbet_candidates + pari_candidates + leon_candidates)
        if not candidates:
            matched_counter["no_match"] += 1
            continue

        sources = "+".join(sorted(set(x["source"] for x in candidates)))
        matched_counter[sources] += 1

        insert_rows.append((
            match_id, league, home, away, match_date,
            avg([x["odds_home"] for x in candidates]),
            avg([x["odds_draw"] for x in candidates]),
            avg([x["odds_away"] for x in candidates]),
            *best([(x["source"], x["odds_home"]) for x in candidates]),
            *best([(x["source"], x["odds_draw"]) for x in candidates]),
            *best([(x["source"], x["odds_away"]) for x in candidates]),
            avg([x["over"] for x in candidates]),
            avg([x["under"] for x in candidates]),
        ))

    cur.executemany("""
        insert into odds_merged values (
            ?,?,?,?, ?,?,?,?, ?,?, ?,?, ?,?, ?,?
        )
    """, insert_rows)

    conn.commit()
    print("merged:", len(insert_rows))
    print("stats:")
    for k, v in sorted(matched_counter.items()):
        print(f"  {k}: {v}")
    conn.close()


if __name__ == "__main__":
    main()
