#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Enrich football_rolling_features with xG rolling averages from understat_matches.

Maps Russian team names to English Understat names, computes rolling 5-match
xG averages (scored, conceded, luck factor) and writes to new columns.
"""
import difflib
import sqlite3
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = str(BASE_DIR / "betagent.db")

# League mapping: understat_league -> (fr_league, fr_country, fr_competition)
LEAGUE_MAP = {
    "EPL": ("Футбол. Англия. Премьер-лига.", "Англия", "Премьер-лига"),
    "La_liga": ("Футбол. Испания. Примера Дивизион.", "Испания", "Примера Дивизион"),
    "Bundesliga": ("Футбол. Германия. Бундеслига.", "Германия", "Бундеслига"),
    "Serie_A": ("Футбол. Италия. Серия A.", "Италия", "Серия A"),
    "Ligue_1": ("Футбол. Франция. Лига 1.", "Франция", "Лига 1"),
    "RFPL": ("Футбол. Россия. Премьер-лига.", "Россия", "Премьер-лига"),
}

# Team name mapping: {understat_english: russian_name}
# Built from known pairs across all target leagues
TEAM_MAP = {
    # EPL
    "Arsenal": "Арсенал",
    "Aston Villa": "Астон Вилла",
    "Bournemouth": "Борнмут",
    "Brentford": "Брентфорд",
    "Brighton": "Брайтон",
    "Burnley": "Бернли",
    "Chelsea": "Челси",
    "Crystal Palace": "Кристал Пэлас",
    "Everton": "Эвертон",
    "Fulham": "Фулхэм",
    "Ipswich": "Ипсвич",
    "Leeds": "Лидс",
    "Leicester": "Лестер",
    "Liverpool": "Ливерпуль",
    "Luton": "Лутон Таун",
    "Manchester City": "Манчестер Сити",
    "Manchester United": "Манчестер Юнайтед",
    "Newcastle United": "Ньюкасл",
    "Norwich": "Норвич",
    "Nottingham Forest": "Ноттингем Форест",
    "Sheffield United": "Шеффилд Юнайтед",
    "Southampton": "Саутгемптон",
    "Sunderland": "Сандерленд",
    "Tottenham": "Тоттенхэм",
    "Watford": "Уотфорд",
    "West Bromwich Albion": "Вест Бромвич",
    "West Ham": "Вест Хэм",
    "Wolverhampton Wanderers": "Вулверхэмптон",
    # La Liga
    "Alaves": "Алавес",
    "Almeria": "Альмерия",
    "Athletic Club": "Атлетик Бильбао",
    "Atletico Madrid": "Атлетико Мадрид",
    "Barcelona": "Барселона",
    "Cadiz": "Кадис",
    "Celta Vigo": "Сельта",
    "Eibar": "Эйбар",
    "Elche": "Эльче",
    "Espanyol": "Эспаньол",
    "Getafe": "Хетафе",
    "Girona": "Жирона",
    "Granada": "Гранада",
    "Las Palmas": "Лас-Пальмас",
    "Leganes": "Леганес",
    "Levante": "Леванте",
    "Mallorca": "Мальорка",
    "Osasuna": "Осасуна",
    "Rayo Vallecano": "Райо Вальекано",
    "Real Betis": "Бетис",
    "Real Madrid": "Реал Мадрид",
    "Real Oviedo": "Овьедо",
    "Real Sociedad": "Реал Сосьедад",
    "Real Valladolid": "Вальядолид",
    "SD Huesca": "Уэска",
    "Sevilla": "Севилья",
    "Valencia": "Валенсия",
    "Villarreal": "Вильярреал",
    # Bundesliga
    "Arminia Bielefeld": "Арминия",
    "Augsburg": "Аугсбург",
    "Bayer Leverkusen": "Байер 04",
    "Bayern Munich": "Бавария",
    "Bochum": "Бохум",
    "Borussia Dortmund": "Боруссия Д",
    "Borussia M.Gladbach": "Боруссия М",
    "Darmstadt": "Дармштадт",
    "Eintracht Frankfurt": "Айнтрахт Фр",
    "FC Cologne": "Кёльн",
    "FC Heidenheim": "Хайденхайм",
    "Fortuna Duesseldorf": "Фортуна Д",
    "Freiburg": "Фрайбург",
    "Greuther Fuerth": "Гройтер Фюрт",
    "Hamburger SV": "Гамбург",
    "Hertha Berlin": "Герта",
    "Hoffenheim": "Хоффенхайм",
    "Holstein Kiel": "Хольштайн",
    "Mainz 05": "Майнц 05",
    "Paderborn": "Падерборн",
    "RasenBallsport Leipzig": "Лейпциг",
    "Schalke 04": "Шальке 04",
    "St. Pauli": "Санкт-Паули",
    "Union Berlin": "Унион Берлин",
    "VfB Stuttgart": "Штутгарт",
    "Werder Bremen": "Вердер",
    "Wolfsburg": "Вольфсбург",
    # Serie A
    "Atalanta": "Аталанта",
    "Bari": "Бари",
    "Benevento": "Беневенто",
    "Bologna": "Болонья",
    "Brescia": "Брешиа",
    "Cagliari": "Кальяри",
    "Carpi": "Карпи",
    "Chievo": "Кьево",
    "Cittadella": "Читтаделла",
    "Como": "Комо",
    "Cremonese": "Кремонезе",
    "Crotone": "Кротоне",
    "Empoli": "Эмполи",
    "Fiorentina": "Фиорентина",
    "Frosinone": "Фрозиноне",
    "Genoa": "Дженоа",
    "Inter": "Интер",
    "Juventus": "Ювентус",
    "Lazio": "Лацио",
    "Lecce": "Лечче",
    "Milan": "Милан",
    "Modena": "Модена",
    "Monza": "Монца",
    "Napoli": "Наполи",
    "Padova": "Падова",
    "Palermo": "Палермо",
    "Parma": "Парма",
    "Perugia": "Перуджа",
    "Pescara": "Пескара",
    "Pisa": "Пиза",
    "Pordenone": "Порденоне",
    "Reggina": "Реджина",
    "Roma": "Рома",
    "Salernitana": "Салернитана",
    "Sampdoria": "Сампдория",
    "Sassuolo": "Сассуоло",
    "SPAL": "СПАЛ",
    "Spezia": "Специя",
    "Torino": "Торино",
    "Udinese": "Удинезе",
    "Venezia": "Венеция",
    "Verona": "Верона",
    "Vicenza": "Виченца",
    # Ligue 1
    "Ajaccio": "Аяччо",
    "Amiens": "Амьен",
    "Angers": "Анже",
    "Auxerre": "Осер",
    "Bordeaux": "Бордо",
    "Brest": "Брест",
    "Clermont Foot": "Клермон",
    "Dijon": "Дижон",
    "Le Havre": "Гавр",
    "Lens": "Ланс",
    "Lille": "Лилль",
    "Lorient": "Лорьян",
    "Lyon": "Лион",
    "Marseille": "Марсель",
    "Metz": "Мец",
    "Monaco": "Монако",
    "Montpellier": "Монпелье",
    "Nantes": "Нант",
    "Nice": "Ницца",
    "Nimes": "Ним",
    "Paris FC": "Париж",
    "Paris Saint Germain": "ПСЖ",
    "Reims": "Реймс",
    "Rennes": "Ренн",
    "Saint-Etienne": "Сент-Этьен",
    "Strasbourg": "Страсбур",
    "Toulouse": "Тулуза",
    "Troyes": "Труа",
    # RFPL
    "Akhmat Grozny": "Ахмат",
    "Akron Tolyatti": "Акрон",
    "Anzhi Makhachkala": "Анжи",
    "Arsenal Tula": "Арсенал Тула",
    "Baltika": "Балтика",
    "CSKA Moscow": "ЦСКА",
    "Dinamo Moscow": "Динамо М",
    "Fakel Voronezh": "Факел",
    "FC Khimki": "Химки",
    "FC Orenburg": "Оренбург",
    "FC Rostov": "Ростов",
    "FC Sochi": "Сочи",
    "FC Tyumen": "Тюмень",
    "FC Ufa": "Уфа",
    "Krasnodar": "Краснодар",
    "Krylia Sovetov": "Крылья Советов",
    "Lokomotiv Moscow": "Локомотив М",
    "Makhachkala": "Махачкала",
    "Nizhny Novgorod": "Пари НН",
    "Rubin Kazan": "Рубин",
    "Spartak Moscow": "Спартак М",
    "Tambov": "Тамбов",
    "Torpedo Moscow": "Торпедо М",
    "Ural": "Урал",
    "Yenisey": "Енисей",
    "Zenit": "Зенит",
    # Serie A - additional mappings for FR table names
    "Inter": "Интер М",
    "Genoa": "Дженоа",
    "SPAL": "СПАЛ 2013",
    "Spezia": "Специя 1906",
    # RFPL - additional mappings
    "Tambov": "ФК Тамбов",
}

# Reverse map: russian -> english
RU_TO_EN = {v: k for k, v in TEAM_MAP.items()}


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_columns(conn: sqlite3.Connection):
    """Add xG columns if they don't exist."""
    cols = [c["name"] for c in conn.execute("PRAGMA table_info(football_rolling_features)").fetchall()]
    new_cols = [
        "home_xg_5 REAL",
        "away_xg_5 REAL",
        "home_xga_5 REAL",
        "away_xga_5 REAL",
        "home_luck_5 REAL",
        "away_luck_5 REAL",
        "home_xg_overperform REAL",
        "away_xg_overperform REAL",
    ]
    for col_def in new_cols:
        col_name = col_def.split()[0]
        if col_name not in cols:
            conn.execute(f"ALTER TABLE football_rolling_features ADD COLUMN {col_def}")
            print(f"  Added column: {col_name}")
    conn.commit()


def build_fuzzy_map(conn: sqlite3.Connection, us_league: str, fr_league: str) -> dict[str, str]:
    """Build english->russian team name mapping using exact + fuzzy matching."""
    us_teams = [r[0] for r in conn.execute(
        "SELECT DISTINCT home_team FROM understat_matches WHERE league = ?", (us_league,)
    ).fetchall()]
    fr_teams = [r[0] for r in conn.execute(
        "SELECT DISTINCT home_team FROM football_rolling_features WHERE league = ?", (fr_league,)
    ).fetchall()]

    mapping = {}  # english -> russian
    used_fr = set()

    # Phase 1: exact matches from TEAM_MAP
    for en in us_teams:
        ru = TEAM_MAP.get(en)
        if ru and ru in fr_teams:
            mapping[en] = ru
            used_fr.add(ru)

    # Phase 2: fuzzy match remaining
    remaining_us = [t for t in us_teams if t not in mapping]
    remaining_fr = [t for t in fr_teams if t not in used_fr]

    for en in remaining_us:
        best_match = difflib.get_close_matches(en, remaining_fr, n=1, cutoff=0.45)
        if best_match:
            mapping[en] = best_match[0]
            used_fr.add(best_match[0])

    return mapping


def compute_rolling_xg(conn: sqlite3.Connection, us_league: str, team_en: str, before_date: str) -> dict:
    """Compute rolling 5-match xG stats for a team before a given date."""
    # Get last 5 matches for this team (as home or away) before the date
    rows = conn.execute("""
        SELECT
            match_date,
            CASE WHEN home_team = ? THEN home_xg ELSE away_xg END as xg_for,
            CASE WHEN home_team = ? THEN away_xg ELSE home_xg END as xg_again,
            CASE WHEN home_team = ? THEN home_goals ELSE away_goals END as goals_for
        FROM understat_matches
        WHERE league = ?
          AND (home_team = ? OR away_team = ?)
          AND match_date < ?
        ORDER BY match_date DESC
        LIMIT 5
    """, (team_en, team_en, team_en, us_league, team_en, team_en, before_date)).fetchall()

    if not rows:
        return None

    n = len(rows)
    xg_for_avg = sum(r["xg_for"] for r in rows) / n
    xg_again_avg = sum(r["xg_again"] for r in rows) / n
    luck_avg = sum(r["goals_for"] - r["xg_for"] for r in rows) / n

    return {
        "xg_5": round(xg_for_avg, 4),
        "xga_5": round(xg_again_avg, 4),
        "luck_5": round(luck_avg, 4),
    }


def main():
    conn = get_conn()
    ensure_columns(conn)

    total_updated = 0
    league_stats = {}

    for us_league, (fr_league, fr_country, fr_comp) in LEAGUE_MAP.items():
        print(f"\n=== {us_league} -> {fr_league} ===")

        # Check if this league has rows in football_rolling_features
        fr_count = conn.execute(
            "SELECT COUNT(*) FROM football_rolling_features WHERE league = ? AND country = ? AND competition = ?",
            (fr_league, fr_country, fr_comp)
        ).fetchone()[0]
        if fr_count == 0:
            print(f"  No rows found, skipping")
            continue

        # Build team name mapping
        team_map = build_fuzzy_map(conn, us_league, fr_league)
        print(f"  Team mapping: {len(team_map)} pairs")
        for en, ru in sorted(team_map.items()):
            print(f"    {en} -> {ru}")

        # Get all matches for this league
        matches = conn.execute("""
            SELECT id, match_date, home_team, away_team, home_form_gf_5, away_form_gf_5
            FROM football_rolling_features
            WHERE league = ? AND country = ? AND competition = ?
            ORDER BY match_date
        """, (fr_league, fr_country, fr_comp)).fetchall()

        updated = 0
        for m in matches:
            home_ru = m["home_team"]
            away_ru = m["away_team"]
            match_date = m["match_date"]

            # Map to English names
            home_en = None
            away_en = None
            for en, ru in team_map.items():
                if ru == home_ru:
                    home_en = en
                if ru == away_ru:
                    away_en = en

            if not home_en or not away_en:
                continue

            # Compute rolling xG for home team
            home_xg = compute_rolling_xg(conn, us_league, home_en, match_date)
            away_xg = compute_rolling_xg(conn, us_league, away_en, match_date)

            if not home_xg or not away_xg:
                continue

            # Compute overperform
            home_form_gf = m["home_form_gf_5"] or 0
            away_form_gf = m["away_form_gf_5"] or 0
            home_overperform = round(home_form_gf - home_xg["xg_5"], 4)
            away_overperform = round(away_form_gf - away_xg["xg_5"], 4)

            conn.execute("""
                UPDATE football_rolling_features SET
                    home_xg_5 = ?, away_xg_5 = ?,
                    home_xga_5 = ?, away_xga_5 = ?,
                    home_luck_5 = ?, away_luck_5 = ?,
                    home_xg_overperform = ?, away_xg_overperform = ?
                WHERE id = ?
            """, (
                home_xg["xg_5"], away_xg["xg_5"],
                home_xg["xga_5"], away_xg["xga_5"],
                home_xg["luck_5"], away_xg["luck_5"],
                home_overperform, away_overperform,
                m["id"],
            ))
            updated += 1

        conn.commit()
        coverage = updated / fr_count * 100 if fr_count > 0 else 0
        print(f"  Updated: {updated}/{fr_count} ({coverage:.1f}%)")
        total_updated += updated
        league_stats[us_league] = (updated, fr_count, coverage)

    # Summary
    print("\n" + "=" * 70)
    print("XG FEATURES ENRICHMENT SUMMARY")
    print("=" * 70)
    print(f"\nTotal rows updated: {total_updated}")
    print(f"\n{'League':<12} {'Updated':>7} {'Total':>7} {'Coverage':>10}")
    print("-" * 40)
    for league, (upd, tot, cov) in league_stats.items():
        print(f"{league:<12} {upd:>7} {tot:>7} {cov:>9.1f}%")

    # Sample rows
    print("\n=== Sample updated rows ===")
    rows = conn.execute("""
        SELECT league, match_date, home_team, away_team,
               home_form_gf_5, home_xg_5, home_xga_5, home_luck_5, home_xg_overperform,
               away_form_gf_5, away_xg_5, away_xga_5, away_luck_5, away_xg_overperform
        FROM football_rolling_features
        WHERE home_xg_5 IS NOT NULL
        ORDER BY match_date DESC
        LIMIT 10
    """).fetchall()

    for r in rows:
        print(f"\n{r['league'][:30]} | {r['match_date']}")
        print(f"  {r['home_team']:20s} xG={r['home_xg_5']:.2f} xGA={r['home_xga_5']:.2f} luck={r['home_luck_5']:+.2f} over={r['home_xg_overperform']:+.2f}")
        print(f"  {r['away_team']:20s} xG={r['away_xg_5']:.2f} xGA={r['away_xga_5']:.2f} luck={r['away_luck_5']:+.2f} over={r['away_xg_overperform']:+.2f}")

    conn.close()


if __name__ == "__main__":
    main()
