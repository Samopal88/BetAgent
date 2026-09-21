#!/usr/bin/env python3
"""
BETAGENT — Sub-market filter analysis.
Uses backtest_football_stats for rolling averages (corners, YC, shots)
linked to backtest_matches via league + team name mapping.
"""
import sqlite3
from collections import defaultdict

DB = "betagent.db"

# League codes (backtest_matches) → Russian league names (backtest_football_stats)
STATS_LEAGUE = {
    "SA":  "Футбол. Италия. Серия A.",
    "EPL": "Футбол. Англия. Премьер-лига.",
    "BL1": "Футбол. Германия. Бундеслига.",
    "FL1": "Футбол. Франция. Лига 1.",
    "PD":  "Футбол. Испания. Примера Дивизион.",
    "RPL": ("Футбол. Россия. Премьер-Лига.", "Футбол. Россия. Премьер-лига."),
}

# English → Russian team name mapping
TEAM_MAP = {
    # Serie A
    "Atalanta": "Аталанта", "Bologna": "Болонья", "Cagliari": "Кальяри",
    "Como": "Комо", "Cremonese": "Кремонезе", "Empoli": "Эмполи",
    "Fiorentina": "Фиорентина", "Frosinone": "Фрозиноне", "Genoa": "Дженоа",
    "Inter": "Интер Милан", "Juventus": "Ювентус", "Lazio": "Лацио",
    "Lecce": "Лечче", "Milan": "Милан", "Monza": "Монца", "Napoli": "Наполи",
    "Parma": "Парма", "Pisa": "Пиза", "Roma": "Рома",
    "Salernitana": "Салернитана", "Sampdoria": "Сампдория", "Sassuolo": "Сассуоло",
    "Spezia": "Специя 1906", "Torino": "Торино", "Udinese": "Удинезе",
    "Venezia": "Венеция", "Verona": "Верона",
    # EPL
    "Arsenal": "Арсенал", "Aston Villa": "Астон Вилла", "Bournemouth": "Борнмут",
    "Brentford": "Брентфорд", "Brighton": "Брайтон", "Burnley": "Бернли",
    "Chelsea": "Челси", "Crystal Palace": "Кристал Пэлас", "Everton": "Эвертон",
    "Fulham": "Фулхэм", "Ipswich": "Ипсвич", "Leeds": "Лидс",
    "Leicester": "Лестер", "Liverpool": "Ливерпуль", "Luton": "Лутон Таун",
    "Man City": "Манчестер Сити", "Man United": "Манчестер Юнайтед",
    "Newcastle": "Ньюкасл", "Norwich": "Норвич", "Nott'm Forest": "Ноттингем Форест",
    "Sheffield United": "Шеффилд Юнайтед", "Southampton": "Саутгемптон",
    "Sunderland": "Сандерленд", "Tottenham": "Тоттенхэм", "Watford": "Уотфорд",
    "West Ham": "Вест Хэм", "Wolves": "Вулверхэмптон",
    # Bundesliga
    "Augsburg": "Аугсбург", "Bayern Munich": "Бавария", "Bielefeld": "Арминия",
    "Bochum": "Бохум", "Darmstadt": "Дармштадт 98", "Dortmund": "Боруссия Дортмунд",
    "Ein Frankfurt": "Айнтрахт Франкфурт", "FC Koln": "Кёльн",
    "Freiburg": "Фрайбург", "Greuther Furth": "Фюрт", "Hamburg": "Гамбург",
    "Heidenheim": "Хайденхайм", "Hertha": "Герта", "Hoffenheim": "Хоффенхайм",
    "Holstein Kiel": "Киль", "Leverkusen": "Байер 04", "M'gladbach": "Боруссия Мёнхенгладбах",
    "Mainz": "Майнц 05", "RB Leipzig": "Лейпциг", "Schalke 04": "Шальке 04",
    "St Pauli": "Санкт-Паули", "Stuttgart": "Штутгарт", "Union Berlin": "Унион Берлин",
    "Werder Bremen": "Вердер", "Wolfsburg": "Вольфсбург",
    # Ligue 1
    "Ajaccio": "Аяччо", "Angers": "Анже", "Auxerre": "Осер", "Bordeaux": "Бордо",
    "Brest": "Брест", "Clermont": "Клермон", "Le Havre": "Гавр", "Lens": "Ланс",
    "Lille": "Лилль", "Lorient": "Лорьян", "Lyon": "Лион", "Marseille": "Марсель",
    "Metz": "Мец", "Monaco": "Монако", "Montpellier": "Монпелье", "Nantes": "Нант",
    "Nice": "Ницца", "Paris FC": "Париж", "Paris SG": "ПСЖ", "Reims": "Реймс",
    "Rennes": "Ренн", "St Etienne": "Сент-Этьен", "Strasbourg": "Страсбур",
    "Toulouse": "Тулуза", "Troyes": "Труа",
    # La Liga
    "Alaves": "Алавес", "Almeria": "Альмерия", "Ath Bilbao": "Атлетик Бильбао",
    "Ath Madrid": "Атлетико Мадрид", "Barcelona": "Барселона", "Betis": "Бетис",
    "Cadiz": "Кадис", "Celta": "Сельта", "Elche": "Эльче", "Espanol": "Эспаньол",
    "Getafe": "Хетафе", "Girona": "Жирона", "Granada": "Гранада",
    "Las Palmas": "Лас-Пальмас", "Leganes": "Леганес", "Levante": "Леванте",
    "Mallorca": "Мальорка", "Osasuna": "Осасуна", "Oviedo": "Овьедо",
    "Real Madrid": "Реал Мадрид", "Sevilla": "Севилья", "Sociedad": "Реал Сосьедад",
    "Valencia": "Валенсия", "Valladolid": "Вальядолид", "Vallecano": "Райо Вальекано",
    "Villarreal": "Вильярреал",
}


def russian_name(team):
    return TEAM_MAP.get(team, team)


def get_conn():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn


def compute_rolling_avgs(conn, league_stats, team_eng, match_date, is_home=True):
    """Rolling avg corners/shots/yc for team (English name → Russian) before match_date."""
    team_ru = russian_name(team_eng)
    if is_home:
        team_col = "home_team"
        c_col, s_col, y_col = "corners_home", "shots_home", "yc_home"
    else:
        team_col = "away_team"
        c_col, s_col, y_col = "corners_away", "shots_away", "yc_away"

    if isinstance(league_stats, tuple):
        placeholders = ",".join(["?" for _ in league_stats])
        where = f"league IN ({placeholders}) AND {team_col} = ? AND match_date < ?"
        params = list(league_stats) + [team_ru, match_date]
    else:
        where = f"league = ? AND {team_col} = ? AND match_date < ?"
        params = [league_stats, team_ru, match_date]

    rows = conn.execute(
        f"SELECT {c_col}, {s_col}, {y_col} FROM backtest_football_stats WHERE {where} ORDER BY match_date DESC LIMIT 5",
        params).fetchall()

    if len(rows) < 3:
        return None

    c_valid = [float(r[0]) for r in rows if r[0] is not None]
    s_valid = [float(r[1]) for r in rows if r[1] is not None]
    y_valid = [float(r[2]) for r in rows if r[2] is not None]

    c_avg = sum(c_valid) / len(c_valid) if len(c_valid) >= 3 else None
    s_avg = sum(s_valid) / len(s_valid) if len(s_valid) >= 3 else None
    y_avg = sum(y_valid) / len(y_valid) if len(y_valid) >= 3 else None

    return {"match_count": len(rows), "corners_avg": round(c_avg,2) if c_avg else None,
            "shots_avg": round(s_avg,2) if s_avg else None, "yc_avg": round(y_avg,2) if y_avg else None}


def rolling_full(conn, league_stats, ht, at, md):
    h = compute_rolling_avgs(conn, league_stats, ht, md, True)
    a = compute_rolling_avgs(conn, league_stats, at, md, False)
    if h is None or a is None:
        return None
    return {"home_corners": h["corners_avg"], "home_shots": h["shots_avg"], "home_yc": h["yc_avg"],
            "away_corners": a["corners_avg"], "away_shots": a["shots_avg"], "away_yc": a["yc_avg"]}


def hit(m, market):
    hs, aw = m["home_score"], m["away_score"]
    if hs is None or aw is None: return False
    if market == "draw":      return hs == aw
    if market == "btts_yes":  return hs > 0 and aw > 0
    if market == "over_2_5":  return (hs + aw) > 2
    return False


def odds(m, market):
    map_ = {"draw": m.get("odds_draw"), "btts_yes": m.get("odds_btts_yes"),
            "over_2_5": m.get("odds_over_2_5")}
    v = map_.get(market)
    return float(v) if v and v > 0 else None


def analyze(strategy, code, market, extra_sql, filters):
    ls = STATS_LEAGUE[code]
    conn = get_conn()
    rows = conn.execute(f"""
        SELECT * FROM backtest_matches WHERE league = ? AND home_score IS NOT NULL
          AND CAST(substr(match_date,1,4) AS INTEGER) BETWEEN 2021 AND 2025 {extra_sql}
        ORDER BY match_date ASC""", [code]).fetchall()
    if not rows:
        print(f"  No matches for {strategy}")
        conn.close()
        return None

    stats = []
    for r in rows:
        m = dict(r)
        o = odds(m, market)
        if o is None: continue
        roll = rolling_full(conn, ls, m["home_team"], m["away_team"], m["match_date"])
        stats.append({"match": m, "roll": roll, "year": int(m["match_date"][:4]),
                      "hit": hit(m, market), "odds": o})
    conn.close()

    bl = defaultdict(lambda: {"n":0,"h":0,"s":0.0,"p":0.0})
    for s in stats:
        d = bl[s["year"]]; st = 1.0; pr = st*(s["odds"]-1) if s["hit"] else -st
        d["n"]+=1; d["h"]+=s["hit"]; d["s"]+=st; d["p"]+=pr
    bn = sum(d["n"] for d in bl.values()); bh = sum(d["h"] for d in bl.values())
    bs = sum(d["s"] for d in bl.values()); bp = sum(d["p"] for d in bl.values())
    bhp = bh/bn*100 if bn else 0; broi = bp/bs*100 if bs else 0
    byy = {y: {"n":d["n"], "hit_pct": round(d["h"]/d["n"]*100,1) if d["n"] else 0,
               "roi": round(d["p"]/d["s"]*100,1) if d["s"] else 0} for y,d in sorted(bl.items())}

    res = {"strategy": strategy, "market": market,
           "baseline": {"total": {"n": bn, "hit_pct": round(bhp,1), "roi": round(broi,1)}, "by_year": byy},
           "filters": {}}

    for fname, fcond in filters.items():
        fy = defaultdict(lambda: {"n":0,"h":0,"s":0.0,"p":0.0}); skipped = 0
        for s in stats:
            if s["roll"] is None:
                skipped += 1
                d = fy[s["year"]]; st = 1.0; pr = st*(s["odds"]-1) if s["hit"] else -st
                d["n"]+=1; d["h"]+=s["hit"]; d["s"]+=st; d["p"]+=pr
                continue
            if fcond(s["roll"]):
                d = fy[s["year"]]; st = 1.0; pr = st*(s["odds"]-1) if s["hit"] else -st
                d["n"]+=1; d["h"]+=s["hit"]; d["s"]+=st; d["p"]+=pr
        tn=sum(d["n"] for d in fy.values()); th=sum(d["h"] for d in fy.values())
        ts=sum(d["s"] for d in fy.values()); tp=sum(d["p"] for d in fy.values())
        fhp = th/tn*100 if tn else 0; froi = tp/ts*100 if ts else 0; diff = round(froi - broi, 1)
        pos = sum(1 for d in fy.values() if d["p"] > 0); nnz = sum(1 for d in fy.values() if d["n"] > 0)
        fyy = {y: {"n":d["n"], "hit_pct": round(d["h"]/d["n"]*100,1) if d["n"] else 0,
                   "roi": round(d["p"]/d["s"]*100,1) if d["s"] else 0} for y,d in sorted(fy.items())}
        res["filters"][fname] = {"total":{"n":tn,"hit_pct":round(fhp,1),"roi":round(froi,1)},
                                 "roi_diff":diff,"by_year":fyy,"pos_yrs":pos,"nnz":nnz,"skipped":skipped}
    return res


def qualifies(f):
    return f["roi_diff"] > 5.0 and f["pos_yrs"] >= 4 and all(d["n"]>=15 for d in f["by_year"].values() if d["n"]>0)


def report(all):
    print("\n" + "="*110)
    print("BETAGENT — Sub-market Filter Analysis")
    print("="*110)
    qc = 0
    for r in all:
        bl = r["baseline"]["total"]
        print(f"\n{'─'*95}\nSTRATEGY: {r['strategy']}  ({r['market']})\n{'─'*95}")
        print(f"  BASELINE: n={bl['n']}, hit%={bl['hit_pct']:.1f}%, ROI={bl['roi']:.1f}%")
        for y,d in sorted(r["baseline"]["by_year"].items()):
            print(f"    {y}: n={d['n']:4d}  hit%={d['hit_pct']:.1f}%  ROI={d['roi']:.1f}%")
        best_f, best_d = max(r["filters"].items(), key=lambda x: x[1]["roi_diff"])
        for fname, fd in sorted(r["filters"].items()):
            ft=fd["total"]
            mark = " ◄" if fname==best_f else ""
            print(f"\n  Filter: {fname} ({ft['n']}){mark}")
            print(f"    hit%={ft['hit_pct']:.1f}%  ROI={ft['roi']:.1f}%  vs_bl={fd['roi_diff']:+.1f}pp  skip={fd['skipped']}")
            yp=[]; ydata=0
            for y in sorted(fd["by_year"].keys()):
                d=fd["by_year"][y]
                yp.append(f"{y}: n={d['n']:3d} hit%={d['hit_pct']:.0f}% ROI={d['roi']:+.0f}%")
                if d["n"]>0: ydata+=1
            print(f"    Years: {' | '.join(yp)}")
        ft = best_d["total"]
        qual = qualifies(best_d)
        if qual:
            print(f"\n  ► ADD {best_f}  (n={ft['n']}, ROI={ft['roi']:.1f}%, {best_d['roi_diff']:+.0f}pp)"); qc+=1
        else:
            reasons=[]
            if best_d["roi_diff"]<=5: reasons.append(f"ROI+={best_d['roi_diff']:.0f}pp")
            if best_d["pos_yrs"]<4: reasons.append(f"pos={best_d['pos_yrs']}/5")
            low=[y for y,d in best_d["by_year"].items() if d["n"]>0 and d["n"]<15]
            if low: reasons.append(f"n<15: {low}")
            print(f"\n  ► NO  ({'; '.join(reasons)})")
    print(f"\n{'='*110}\nSUMMARY: {qc} filter(s) qualified\n{'='*110}")
    print(f"{'Strategy':<28} {'Base n':>6} {'Base R':>7} {'Best Filter':>32} {'Fil n':>6} {'Fil R':>7} {'Diff':>7} {'Rec':>4}")
    print("-"*110)
    for r in all:
        bl=r["baseline"]["total"]; bf,bd=max(r["filters"].items(),key=lambda x:x[1]["roi_diff"]); ft=bd["total"]
        print(f"{r['strategy']:<28}{bl['n']:>6} {bl['roi']:>6.1f}% {bf:>32}{ft['n']:>6} {ft['roi']:>6.1f}% {bd['roi_diff']:>+6.1f}pp {'ADD' if qualifies(bd) else 'NO':>4}")


def main():
    all = []
    print("[1/7] SA_AWAY_DRAW...")
    r = analyze("SA_AWAY_DRAW","SA","draw",
        " AND away_team IN ('Empoli','Genoa','Cremonese','Salernitana','Venezia')"
        " AND odds_draw BETWEEN 3.0 AND 4.5"
        " AND odds_under_2_5 IS NOT NULL AND odds_under_2_5 <= 2.0",
        {
            "A: home_corners<=4.5": lambda r: r["home_corners"] is not None and r["home_corners"]<=4.5,
            "B: home_shots<=5.0": lambda r: r["home_shots"] is not None and r["home_shots"]<=5.0,
            "C: home_yc>=2.0": lambda r: r["home_yc"] is not None and r["home_yc"]>=2.0,
            "D: home_corners<=4.5&away_corners>=3.5": lambda r: r["home_corners"] is not None and r["home_corners"]<=4.5 and r["away_corners"] is not None and r["away_corners"]>=3.5,
            "E: home_corners<=4.0": lambda r: r["home_corners"] is not None and r["home_corners"]<=4.0,
            "F: home_shots<=4.5": lambda r: r["home_shots"] is not None and r["home_shots"]<=4.5,
            "G: home_yc>=2.5": lambda r: r["home_yc"] is not None and r["home_yc"]>=2.5,
            "H: home_corners<=4.5&home_yc>=2": lambda r: r["home_corners"] is not None and r["home_corners"]<=4.5 and r["home_yc"] is not None and r["home_yc"]>=2.0,
        })
    if r: all.append(r)

    print("[2/7] BTTS_YES_CORE EPL...")
    r = analyze("BTTS_YES_CORE_EPL","EPL","btts_yes",
        " AND odds_btts_yes BETWEEN 2.00 AND 2.10",
        {
            "A: home_shots>=5&away_shots>=4": lambda r: r["home_shots"] is not None and r["home_shots"]>=5 and r["away_shots"] is not None and r["away_shots"]>=4,
            "B: home_corners>=5&away_corners>=4": lambda r: r["home_corners"] is not None and r["home_corners"]>=5 and r["away_corners"] is not None and r["away_corners"]>=4,
            "C: home_shots>=5": lambda r: r["home_shots"] is not None and r["home_shots"]>=5,
            "D: home_shots>=4&away_shots>=3": lambda r: r["home_shots"] is not None and r["home_shots"]>=4 and r["away_shots"] is not None and r["away_shots"]>=3,
            "E: home_shots+away_shots>=10": lambda r: r["home_shots"] is not None and r["away_shots"] is not None and r["home_shots"]+r["away_shots"]>=10,
            "F: home_yc>=2&away_yc>=2": lambda r: r["home_yc"] is not None and r["home_yc"]>=2.0 and r["away_yc"] is not None and r["away_yc"]>=2.0,
        })
    if r: all.append(r)

    print("[3/7] BTTS_YES_CORE BL1...")
    r = analyze("BTTS_YES_CORE_BL1","BL1","btts_yes",
        " AND odds_btts_yes BETWEEN 1.95 AND 2.10",
        {
            "A: home_shots>=5&away_shots>=4": lambda r: r["home_shots"] is not None and r["home_shots"]>=5 and r["away_shots"] is not None and r["away_shots"]>=4,
            "B: home_corners>=5&away_corners>=4": lambda r: r["home_corners"] is not None and r["home_corners"]>=5 and r["away_corners"] is not None and r["away_corners"]>=4,
            "C: home_shots>=5": lambda r: r["home_shots"] is not None and r["home_shots"]>=5,
            "D: home_shots>=4&away_shots>=3": lambda r: r["home_shots"] is not None and r["home_shots"]>=4 and r["away_shots"] is not None and r["away_shots"]>=3,
            "E: home_shots+away_shots>=10": lambda r: r["home_shots"] is not None and r["away_shots"] is not None and r["home_shots"]+r["away_shots"]>=10,
            "F: home_yc>=2&away_yc>=2": lambda r: r["home_yc"] is not None and r["home_yc"]>=2.0 and r["away_yc"] is not None and r["away_yc"]>=2.0,
        })
    if r: all.append(r)

    print("[4/7] FL1_BTTS_DOUBLE...")
    r = analyze("FL1_BTTS_DOUBLE","FL1","btts_yes",
        " AND odds_over_2_5 BETWEEN 1.6 AND 1.9 AND odds_btts_yes BETWEEN 2.0 AND 2.1",
        {
            "A: home_yc>=2.0": lambda r: r["home_yc"] is not None and r["home_yc"]>=2.0,
            "B: home_shots>=5": lambda r: r["home_shots"] is not None and r["home_shots"]>=5,
            "C: home_shots>=5&away_shots>=4": lambda r: r["home_shots"] is not None and r["home_shots"]>=5 and r["away_shots"] is not None and r["away_shots"]>=4,
            "D: home_shots>=4.5": lambda r: r["home_shots"] is not None and r["home_shots"]>=4.5,
            "E: home_shots+away_shots>=10": lambda r: r["home_shots"] is not None and r["away_shots"] is not None and r["home_shots"]+r["away_shots"]>=10,
        })
    if r: all.append(r)

    print("[5/7] PD_BTTS_DOUBLE...")
    r = analyze("PD_BTTS_DOUBLE","PD","btts_yes",
        " AND odds_over_2_5 BETWEEN 1.6 AND 1.9 AND odds_btts_yes BETWEEN 1.75 AND 1.95",
        {
            "A: away_shots>=4": lambda r: r["away_shots"] is not None and r["away_shots"]>=4,
            "B: home_corners>=5": lambda r: r["home_corners"] is not None and r["home_corners"]>=5,
            "C: away_shots>=4&home_corners>=4": lambda r: r["away_shots"] is not None and r["away_shots"]>=4 and r["home_corners"] is not None and r["home_corners"]>=4,
            "D: home_shots>=5&away_shots>=4": lambda r: r["home_shots"] is not None and r["home_shots"]>=5 and r["away_shots"] is not None and r["away_shots"]>=4,
            "E: home_shots+away_shots>=10": lambda r: r["home_shots"] is not None and r["away_shots"] is not None and r["home_shots"]+r["away_shots"]>=10,
            "F: home_yc>=2.0": lambda r: r["home_yc"] is not None and r["home_yc"]>=2.0,
        })
    if r: all.append(r)

    print("[6/7] RPL_OVER25_BTTS...")
    r = analyze("RPL_OVER25_BTTS","RPL","over_2_5",
        " AND odds_over_2_5 BETWEEN 1.8 AND 2.1 AND odds_btts_yes BETWEEN 1.8 AND 2.1",
        {
            "A: home_shots>=5": lambda r: r["home_shots"] is not None and r["home_shots"]>=5,
            "B: home_shots+away_shots>=9": lambda r: r["home_shots"] is not None and r["away_shots"] is not None and r["home_shots"]+r["away_shots"]>=9,
            "C: home_corners>=4&away_corners>=3": lambda r: r["home_corners"] is not None and r["home_corners"]>=4 and r["away_corners"] is not None and r["away_corners"]>=3,
            "D: home_shots>=4.5&away_shots>=4.0": lambda r: r["home_shots"] is not None and r["home_shots"]>=4.5 and r["away_shots"] is not None and r["away_shots"]>=4.0,
            "E: home_yc>=2.0": lambda r: r["home_yc"] is not None and r["home_yc"]>=2.0,
        })
    if r: all.append(r)

    print("[7/7] MLS_BTTS_HOME — no stats data, SKIPPED")
    report(all)


if __name__ == "__main__":
    main()
