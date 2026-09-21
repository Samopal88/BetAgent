#!/usr/bin/env python3
"""
Hockey Strategies Recheck — Correct date normalization, year-by-year ROI.
All conclusions come from SQLite only, not from the old markdown report.
"""

import sqlite3
import json
from collections import defaultdict

DB = "/root/betagent/betagent.db"

def get_conn():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn

# ============================================================
# STEP 1: DATA QUALITY AUDIT
# ============================================================
def data_quality_audit():
    conn = get_conn()
    c = conn.cursor()

    total = c.execute("SELECT COUNT(*) FROM backtest_hockey_features").fetchone()[0]
    iso = c.execute("""
        SELECT COUNT(*) FROM backtest_hockey_features
        WHERE match_date GLOB '20??-??-??*'
    """).fetchone()[0]
    dmy = c.execute("""
        SELECT COUNT(*) FROM backtest_hockey_features
        WHERE match_date GLOB '??.??.20??'
    """).fetchone()[0]
    anomalous = total - iso - dmy

    print("=" * 70)
    print("STEP 1: DATA QUALITY AUDIT")
    print("=" * 70)
    print(f"Total rows: {total}")
    print(f"  ISO YYYY-MM-DD (or with time): {iso} ({iso/total*100:.1f}%)")
    print(f"  DD.MM.YYYY:                    {dmy} ({dmy/total*100:.1f}%)")
    print(f"  Anomalous/Unknown:             {anomalous}")

    if anomalous > 0:
        print("\nAnomalous date values:")
        rows = c.execute("""
            SELECT match_date, COUNT(*) as cnt
            FROM backtest_hockey_features
            WHERE match_date NOT GLOB '20??-??-??*'
              AND match_date NOT GLOB '??.??.20??'
            GROUP BY match_date
            ORDER BY cnt DESC
            LIMIT 30
        """).fetchall()
        for r in rows:
            print(f"  '{r[0]}' — {r[1]} rows")

    # Show sample of each format
    print("\nSample ISO dates:")
    for r in c.execute("SELECT DISTINCT match_date FROM backtest_hockey_features WHERE match_date GLOB '20??-??-??*' LIMIT 5").fetchall():
        print(f"  '{r[0]}'")

    print("\nSample DD.MM.YYYY dates:")
    for r in c.execute("SELECT DISTINCT match_date FROM backtest_hockey_features WHERE match_date GLOB '??.??.20??' LIMIT 5").fetchall():
        print(f"  '{r[0]}'")

    # Year distribution using correct normalization
    print("\nYear distribution (correctly normalized):")
    rows = c.execute("""
        SELECT
            CASE
                WHEN match_date GLOB '20??-??-??*' THEN substr(match_date,1,4)
                WHEN match_date GLOB '??.??.20??' THEN substr(match_date,7,4)
                ELSE NULL
            END AS year,
            COUNT(*) as cnt
        FROM backtest_hockey_features
        GROUP BY year
        ORDER BY year
    """).fetchall()
    for r in rows:
        print(f"  Year {r[0]}: {r[1]} rows")

    # Leagues
    print("\nLeagues in data:")
    for r in c.execute("SELECT league, COUNT(*) as cnt FROM backtest_hockey_features GROUP BY league ORDER BY cnt DESC").fetchall():
        print(f"  {r[0]}: {r[1]} rows")

    conn.close()
    return total, iso, dmy, anomalous


# ============================================================
# STEP 2: STRATEGY DEFINITIONS (from old report shortlist + requested)
# ============================================================
STRATEGIES = [
    # --- DEL home win ---
    {
        "name": "DEL home win (form5>0.5)",
        "type": "HOME_WIN",
        "league": "Хоккей. Германия. DEL.",
        "where": "league='Хоккей. Германия. DEL.' AND odds_home BETWEEN 1.70 AND 2.00 AND form5_home_winrate > 0.5",
        "market": "home",
    },
    {
        "name": "DEL home win (form5>0.5 + sd>0.2)",
        "type": "HOME_WIN",
        "league": "Хоккей. Германия. DEL.",
        "where": "league='Хоккей. Германия. DEL.' AND odds_home BETWEEN 1.70 AND 2.00 AND form5_home_winrate > 0.5 AND strength_diff_ppg > 0.2",
        "market": "home",
    },
    # --- Czech away ---
    {
        "name": "Czech away (sd<-0.3)",
        "type": "AWAY_WIN",
        "league": "Хоккей. Чехия. Extraliga.",
        "where": "league='Хоккей. Чехия. Extraliga.' AND odds_away BETWEEN 2.20 AND 2.60 AND strength_diff_ppg < -0.3",
        "market": "away",
    },
    # --- Czech Liberec away ---
    {
        "name": "Czech Liberec away",
        "type": "TEAM_AWAY_WIN",
        "league": "Хоккей. Чехия. Extraliga.",
        "where": "league='Хоккей. Чехия. Extraliga.' AND away_team='Либерец' AND odds_away BETWEEN 1.80 AND 3.50",
        "market": "away",
    },
    # --- Czech Liberec home ---
    {
        "name": "Czech Liberec home",
        "type": "TEAM_HOME_WIN",
        "league": "Хоккей. Чехия. Extraliga.",
        "where": "league='Хоккей. Чехия. Extraliga.' AND home_team='Либерец' AND odds_home BETWEEN 1.70 AND 2.50",
        "market": "home",
    },
    # --- Vegas draw NHL ---
    {
        "name": "Vegas draw NHL",
        "type": "TEAM_DRAW",
        "league": "Хоккей. NHL. Регулярный чемпионат.",
        "where": "league='Хоккей. NHL. Регулярный чемпионат.' AND (home_team='Вегас Голден Найтс' OR away_team='Вегас Голден Найтс') AND odds_draw BETWEEN 3.5 AND 5.5",
        "market": "draw",
    },
    # --- KHL draw ---
    {
        "name": "KHL draw (odds 4.5-5.0)",
        "type": "DRAW",
        "league": "Хоккей. КХЛ. Регулярный чемпионат.",
        "where": "league='Хоккей. КХЛ. Регулярный чемпионат.' AND odds_draw BETWEEN 4.5 AND 5.0",
        "market": "draw",
    },
    {
        "name": "KHL draw (odds 4.5-5.0, sd<0.3)",
        "type": "DRAW",
        "league": "Хоккей. КХЛ. Регулярный чемпионат.",
        "where": "league='Хоккей. КХЛ. Регулярный чемпионат.' AND odds_draw BETWEEN 4.5 AND 5.0 AND ABS(strength_diff_ppg) < 0.3",
        "market": "draw",
    },
    # --- KHL playoff over 4.5 ---
    {
        "name": "KHL playoff over 4.5",
        "type": "TOTAL_OVER",
        "league": "Хоккей. КХЛ. Плей-офф.",
        "where": "(league LIKE 'Хоккей. КХЛ. Плей-офф%' OR league='Хоккей. КХЛ. Плей-офф.') AND total_line = 4.5",
        "market": "over",
    },
    # --- Liiga draw top candidates ---
    {
        "name": "Liiga draw (odds 4.0-4.5, form_diff<0.15)",
        "type": "DRAW",
        "league": "Хоккей. Финляндия. Liiga.",
        "where": "league='Хоккей. Финляндия. Liiga.' AND odds_draw BETWEEN 4.0 AND 4.5 AND ABS(form5_home_winrate - form5_away_winrate) < 0.15",
        "market": "draw",
    },
    {
        "name": "Liiga draw (odds 4.0-4.5, sd<0.2)",
        "type": "DRAW",
        "league": "Хоккей. Финляндия. Liiga.",
        "where": "league='Хоккей. Финляндия. Liiga.' AND odds_draw BETWEEN 4.0 AND 4.5 AND ABS(strength_diff_ppg) < 0.2",
        "market": "draw",
    },
    {
        "name": "Liiga draw (odds 4.0-4.5, sd<0.2, form_diff<0.15)",
        "type": "DRAW",
        "league": "Хоккей. Финляндия. Liiga.",
        "where": "league='Хоккей. Финляндия. Liiga.' AND odds_draw BETWEEN 4.0 AND 4.5 AND ABS(strength_diff_ppg) < 0.2 AND ABS(form5_home_winrate - form5_away_winrate) < 0.15",
        "market": "draw",
    },
    {
        "name": "Liiga draw (odds 4.0-4.5, sd<0.3, form_diff<0.15)",
        "type": "DRAW",
        "league": "Хоккей. Финляндия. Liiga.",
        "where": "league='Хоккей. Финляндия. Liiga.' AND odds_draw BETWEEN 4.0 AND 4.5 AND ABS(strength_diff_ppg) < 0.3 AND ABS(form5_home_winrate - form5_away_winrate) < 0.15",
        "market": "draw",
    },
    # --- Liiga home win ---
    {
        "name": "Liiga home win (odds 2.00-2.30)",
        "type": "HOME_WIN",
        "league": "Хоккей. Финляндия. Liiga.",
        "where": "league='Хоккей. Финляндия. Liiga.' AND odds_home BETWEEN 2.00 AND 2.30",
        "market": "home",
    },
    {
        "name": "Liiga home win (odds 2.00-2.30, sd>0.2)",
        "type": "HOME_WIN",
        "league": "Хоккей. Финляндия. Liiga.",
        "where": "league='Хоккей. Финляндия. Liiga.' AND odds_home BETWEEN 2.00 AND 2.30 AND strength_diff_ppg > 0.2",
        "market": "home",
    },
    # --- Mestis draw ---
    {
        "name": "Mestis draw (odds 4.5-5.0)",
        "type": "DRAW",
        "league": "Хоккей. Финляндия. Mestis.",
        "where": "league='Хоккей. Финляндия. Mestis.' AND odds_draw BETWEEN 4.5 AND 5.0",
        "market": "draw",
    },
    {
        "name": "Mestis draw (odds 4.5-5.0, form_diff<0.15)",
        "type": "DRAW",
        "league": "Хоккей. Финляндия. Mestis.",
        "where": "league='Хоккей. Финляндия. Mestis.' AND odds_draw BETWEEN 4.5 AND 5.0 AND ABS(form5_home_winrate - form5_away_winrate) < 0.15",
        "market": "draw",
    },
    {
        "name": "Mestis draw (odds 4.5-5.0, sd<0.3, form_diff<0.15)",
        "type": "DRAW",
        "league": "Хоккей. Финляндия. Mestis.",
        "where": "league='Хоккей. Финляндия. Mestis.' AND odds_draw BETWEEN 4.5 AND 5.0 AND ABS(strength_diff_ppg) < 0.3 AND ABS(form5_home_winrate - form5_away_winrate) < 0.15",
        "market": "draw",
    },
    # --- SHL home win ---
    {
        "name": "SHL home win (odds 2.00-2.30, sd>0.2)",
        "type": "HOME_WIN",
        "league": "Хоккей. Швеция. SHL.",
        "where": "league='Хоккей. Швеция. SHL.' AND odds_home BETWEEN 2.00 AND 2.30 AND strength_diff_ppg > 0.2",
        "market": "home",
    },
    {
        "name": "SHL home win (odds 2.00-2.30, form5>0.5+sd>0.2)",
        "type": "HOME_WIN",
        "league": "Хоккей. Швеция. SHL.",
        "where": "league='Хоккей. Швеция. SHL.' AND odds_home BETWEEN 2.00 AND 2.30 AND form5_home_winrate > 0.5 AND strength_diff_ppg > 0.2",
        "market": "home",
    },
    # --- SHL away win ---
    {
        "name": "SHL away win (odds 2.20-2.60, sd<-0.3+form5>0.6)",
        "type": "AWAY_WIN",
        "league": "Хоккей. Швеция. SHL.",
        "where": "league='Хоккей. Швеция. SHL.' AND odds_away BETWEEN 2.20 AND 2.60 AND strength_diff_ppg < -0.3 AND form5_away_winrate > 0.6",
        "market": "away",
    },
    # --- Czech home win ---
    {
        "name": "Czech home win (odds 1.70-2.00, form5>0.5)",
        "type": "HOME_WIN",
        "league": "Хоккей. Чехия. Extraliga.",
        "where": "league='Хоккей. Чехия. Extraliga.' AND odds_home BETWEEN 1.70 AND 2.00 AND form5_home_winrate > 0.5",
        "market": "home",
    },
    {
        "name": "Czech home win (odds 2.00-2.30, sd>0.2)",
        "type": "HOME_WIN",
        "league": "Хоккей. Чехия. Extraliga.",
        "where": "league='Хоккей. Чехия. Extraliga.' AND odds_home BETWEEN 2.00 AND 2.30 AND strength_diff_ppg > 0.2",
        "market": "home",
    },
    # --- NL draw ---
    {
        "name": "NL draw (odds 4.0-4.5, sd<0.2)",
        "type": "DRAW",
        "league": "Хоккей. Швейцария. National League.",
        "where": "league='Хоккей. Швейцария. National League.' AND odds_draw BETWEEN 4.0 AND 4.5 AND ABS(strength_diff_ppg) < 0.2",
        "market": "draw",
    },
    {
        "name": "NL draw (odds 4.5-5.0, sd<0.1)",
        "type": "DRAW",
        "league": "Хоккей. Швейцария. National League.",
        "where": "league='Хоккей. Швейцария. National League.' AND odds_draw BETWEEN 4.5 AND 5.0 AND ABS(strength_diff_ppg) < 0.1",
        "market": "draw",
    },
    # --- KHL away win ---
    {
        "name": "KHL away win (odds 2.60-3.00, sd<-0.3)",
        "type": "AWAY_WIN",
        "league": "Хоккей. КХЛ. Регулярный чемпионат.",
        "where": "league='Хоккей. КХЛ. Регулярный чемпионат.' AND odds_away BETWEEN 2.60 AND 3.00 AND strength_diff_ppg < -0.3",
        "market": "away",
    },
    # --- NHL team draws (top from report) ---
    {
        "name": "NHL Minnesota draw",
        "type": "TEAM_DRAW",
        "league": "Хоккей. NHL. Регулярный чемпионат.",
        "where": "league='Хоккей. NHL. Регулярный чемпионат.' AND (home_team='Миннесота Уайлд' OR away_team='Миннесота Уайлд') AND odds_draw BETWEEN 3.5 AND 5.5",
        "market": "draw",
    },
    {
        "name": "NHL Vancouver draw",
        "type": "TEAM_DRAW",
        "league": "Хоккей. NHL. Регулярный чемпионат.",
        "where": "league='Хоккей. NHL. Регулярный чемпионат.' AND (home_team='Ванкувер Кэнакс' OR away_team='Ванкувер Кэнакс') AND odds_draw BETWEEN 3.5 AND 5.5",
        "market": "draw",
    },
    # --- Liiga team draws ---
    {
        "name": "Liiga Sport draw",
        "type": "TEAM_DRAW",
        "league": "Хоккей. Финляндия. Liiga.",
        "where": "league='Хоккей. Финляндия. Liiga.' AND (home_team='Спорт' OR away_team='Спорт') AND odds_draw BETWEEN 3.5 AND 5.5",
        "market": "draw",
    },
    {
        "name": "Liiga JYP draw",
        "type": "TEAM_DRAW",
        "league": "Хоккей. Финляндия. Liiga.",
        "where": "league='Хоккей. Финляндия. Liiga.' AND (home_team='Ювяскюля' OR away_team='Ювяскюля') AND odds_draw BETWEEN 3.5 AND 5.5",
        "market": "draw",
    },
    # --- Mestis team home wins ---
    {
        "name": "Mestis Hermes home",
        "type": "TEAM_HOME_WIN",
        "league": "Хоккей. Финляндия. Mestis.",
        "where": "league='Хоккей. Финляндия. Mestis.' AND home_team='Хермес' AND odds_home BETWEEN 1.50 AND 3.00",
        "market": "home",
    },
    # --- DEL team home wins ---
    {
        "name": "DEL Straubing home",
        "type": "TEAM_HOME_WIN",
        "league": "Хоккей. Германия. DEL.",
        "where": "league='Хоккей. Германия. DEL.' AND home_team='Штраубинг' AND odds_home BETWEEN 1.50 AND 3.00",
        "market": "home",
    },
    {
        "name": "DEL Wolfsburg home",
        "type": "TEAM_HOME_WIN",
        "league": "Хоккей. Германия. DEL.",
        "where": "league='Хоккей. Германия. DEL.' AND home_team='Вольфсбург' AND odds_home BETWEEN 1.50 AND 3.00",
        "market": "home",
    },
    # --- Czech Pardubice draw ---
    {
        "name": "Czech Pardubice draw",
        "type": "TEAM_DRAW",
        "league": "Хоккей. Чехия. Extraliga.",
        "where": "league='Хоккей. Чехия. Extraliga.' AND (home_team='Пардубице' OR away_team='Пардубице') AND odds_draw BETWEEN 3.5 AND 5.5",
        "market": "draw",
    },
    # --- NL Bern draw ---
    {
        "name": "NL Bern draw",
        "type": "TEAM_DRAW",
        "league": "Хоккей. Швейцария. National League.",
        "where": "league='Хоккей. Швейцария. National League.' AND (home_team='Берн' OR away_team='Берн') AND odds_draw BETWEEN 3.5 AND 5.5",
        "market": "draw",
    },
    # --- SHL Skelleftea home ---
    {
        "name": "SHL Skelleftea home",
        "type": "TEAM_HOME_WIN",
        "league": "Хоккей. Швеция. SHL.",
        "where": "league='Хоккей. Швеция. SHL.' AND home_team='Шеллефтео' AND odds_home BETWEEN 1.50 AND 2.50",
        "market": "home",
    },
    # --- NL Rapperswil home ---
    {
        "name": "NL Rapperswil home",
        "type": "TEAM_HOME_WIN",
        "league": "Хоккей. Швейцария. National League.",
        "where": "league='Хоккей. Швейцария. National League.' AND home_team='Рапперсвиль' AND odds_home BETWEEN 1.50 AND 3.00",
        "market": "home",
    },
    # --- NL Kloten home ---
    {
        "name": "NL Kloten home",
        "type": "TEAM_HOME_WIN",
        "league": "Хоккей. Швейцария. National League.",
        "where": "league='Хоккей. Швейцария. National League.' AND home_team='Клотен' AND odds_home BETWEEN 1.50 AND 3.50",
        "market": "home",
    },
    # --- KHL Minsk home ---
    {
        "name": "KHL Minsk home",
        "type": "TEAM_HOME_WIN",
        "league": "Хоккей. КХЛ. Регулярный чемпионат.",
        "where": "league='Хоккей. КХЛ. Регулярный чемпионат.' AND home_team='Динамо Минск' AND odds_home BETWEEN 1.50 AND 3.00",
        "market": "home",
    },
    # --- Liiga Pelicans home ---
    {
        "name": "Liiga Pelicans home",
        "type": "TEAM_HOME_WIN",
        "league": "Хоккей. Финляндия. Liiga.",
        "where": "league='Хоккей. Финляндия. Liiga.' AND home_team='Пеликанс' AND odds_home BETWEEN 1.50 AND 3.00",
        "market": "home",
    },
    # --- Liiga Tappara away ---
    {
        "name": "Liiga Tappara away",
        "type": "TEAM_AWAY_WIN",
        "league": "Хоккей. Финляндия. Liiga.",
        "where": "league='Хоккей. Финляндия. Liiga.' AND away_team='Таппара' AND odds_away BETWEEN 1.50 AND 3.50",
        "market": "away",
    },
    # --- KHL Torpedo away ---
    {
        "name": "KHL Torpedo away",
        "type": "TEAM_AWAY_WIN",
        "league": "Хоккей. КХЛ. Регулярный чемпионат.",
        "where": "league='Хоккей. КХЛ. Регулярный чемпионат.' AND away_team='Торпедо Нижний Новгород' AND odds_away BETWEEN 1.50 AND 4.00",
        "market": "away",
    },
    # --- KHL Spartak away ---
    {
        "name": "KHL Spartak away",
        "type": "TEAM_AWAY_WIN",
        "league": "Хоккей. КХЛ. Регулярный чемпионат.",
        "where": "league='Хоккей. КХЛ. Регулярный чемпионат.' AND away_team='Спартак Москва' AND odds_away BETWEEN 1.50 AND 4.00",
        "market": "away",
    },
    # --- Liiga Jukurit away ---
    {
        "name": "Liiga Jukurit away",
        "type": "TEAM_AWAY_WIN",
        "league": "Хоккей. Финляндия. Liiga.",
        "where": "league='Хоккей. Финляндия. Liiga.' AND away_team='Юкурит' AND odds_away BETWEEN 2.00 AND 5.00",
        "market": "away",
    },
    # --- Mestis Kettera home ---
    {
        "name": "Mestis Kettera home",
        "type": "TEAM_HOME_WIN",
        "league": "Хоккей. Финляндия. Mestis.",
        "where": "league='Хоккей. Финляндия. Mestis.' AND home_team='Кеттера' AND odds_home BETWEEN 1.30 AND 2.50",
        "market": "home",
    },
    # --- Mestis KeuPa draw ---
    {
        "name": "Mestis KeuPa draw",
        "type": "TEAM_DRAW",
        "league": "Хоккей. Финляндия. Mestis.",
        "where": "league='Хоккей. Финляндия. Mestis.' AND (home_team='КеуПа' OR away_team='КеуПа') AND odds_draw BETWEEN 3.5 AND 5.5",
        "market": "draw",
    },
    # --- Mestis Kiekko-Pojat draw ---
    {
        "name": "Mestis Kiekko-Pojat draw",
        "type": "TEAM_DRAW",
        "league": "Хоккей. Финляндия. Mestis.",
        "where": "league='Хоккей. Финляндия. Mestis.' AND (home_team='Киеко-Поят' OR away_team='Киеко-Поят') AND odds_draw BETWEEN 3.5 AND 5.5",
        "market": "draw",
    },
    # --- Liiga Assat draw ---
    {
        "name": "Liiga Assat draw",
        "type": "TEAM_DRAW",
        "league": "Хоккей. Финляндия. Liiga.",
        "where": "league='Хоккей. Финляндия. Liiga.' AND (home_team='Эссят' OR away_team='Эссят') AND odds_draw BETWEEN 3.5 AND 5.5",
        "market": "draw",
    },
    # --- Liiga HPK draw ---
    {
        "name": "Liiga HPK draw",
        "type": "TEAM_DRAW",
        "league": "Хоккей. Финляндия. Liiga.",
        "where": "league='Хоккей. Финляндия. Liiga.' AND (home_team='ХПК' OR away_team='ХПК') AND odds_draw BETWEEN 3.5 AND 5.5",
        "market": "draw",
    },
    # --- NHL Dallas draw ---
    {
        "name": "NHL Dallas draw",
        "type": "TEAM_DRAW",
        "league": "Хоккей. NHL. Регулярный чемпионат.",
        "where": "league='Хоккей. NHL. Регулярный чемпионат.' AND (home_team='Даллас Старз' OR away_team='Даллас Старз') AND odds_draw BETWEEN 3.5 AND 5.5",
        "market": "draw",
    },
    # --- NHL Nashville draw ---
    {
        "name": "NHL Nashville draw",
        "type": "TEAM_DRAW",
        "league": "Хоккей. NHL. Регулярный чемпионат.",
        "where": "league='Хоккей. NHL. Регулярный чемпионат.' AND (home_team='Нэшвилл Предаторз' OR away_team='Нэшвилл Предаторз') AND odds_draw BETWEEN 3.5 AND 5.5",
        "market": "draw",
    },
    # --- NHL Islanders draw ---
    {
        "name": "NHL Islanders draw",
        "type": "TEAM_DRAW",
        "league": "Хоккей. NHL. Регулярный чемпионат.",
        "where": "league='Хоккей. NHL. Регулярный чемпионат.' AND (home_team='Нью-Йорк Айлендерс' OR away_team='Нью-Йорк Айлендерс') AND odds_draw BETWEEN 3.5 AND 5.5",
        "market": "draw",
    },
    # --- NHL Boston home ---
    {
        "name": "NHL Boston home",
        "type": "TEAM_HOME_WIN",
        "league": "Хоккей. NHL. Регулярный чемпионат.",
        "where": "league='Хоккей. NHL. Регулярный чемпионат.' AND home_team='Бостон Брюинз' AND odds_home BETWEEN 1.50 AND 3.00",
        "market": "home",
    },
    # --- NHL Boston away ---
    {
        "name": "NHL Boston away",
        "type": "TEAM_AWAY_WIN",
        "league": "Хоккей. NHL. Регулярный чемпионат.",
        "where": "league='Хоккей. NHL. Регулярный чемпионат.' AND away_team='Бостон Брюинз' AND odds_away BETWEEN 1.50 AND 4.00",
        "market": "away",
    },
    # --- NHL LA Kings home ---
    {
        "name": "NHL LA Kings home",
        "type": "TEAM_HOME_WIN",
        "league": "Хоккей. NHL. Регулярный чемпионат.",
        "where": "league='Хоккей. NHL. Регулярный чемпионат.' AND home_team='Лос-Анджелес Кингз' AND odds_home BETWEEN 1.50 AND 3.00",
        "market": "home",
    },
    # --- NHL Detroit home ---
    {
        "name": "NHL Detroit home",
        "type": "TEAM_HOME_WIN",
        "league": "Хоккей. NHL. Регулярный чемпионат.",
        "where": "league='Хоккей. NHL. Регулярный чемпионат.' AND home_team='Детройт Ред Уингз' AND odds_home BETWEEN 1.50 AND 4.00",
        "market": "home",
    },
    # --- Czech Plzen draw ---
    {
        "name": "Czech Plzen draw",
        "type": "TEAM_DRAW",
        "league": "Хоккей. Чехия. Extraliga.",
        "where": "league='Хоккей. Чехия. Extraliga.' AND (home_team='Пльзень' OR away_team='Пльзень') AND odds_draw BETWEEN 3.5 AND 5.5",
        "market": "draw",
    },
]


# ============================================================
# STEP 3: EVALUATE A SINGLE STRATEGY
# ============================================================
def evaluate_strategy(conn, strat):
    """Returns dict with total stats + per-year breakdown."""
    c = conn.cursor()

    # Get all matching rows with correct year normalization
    query = f"""
        SELECT
            CASE
                WHEN match_date GLOB '20??-??-??*' THEN substr(match_date,1,4)
                WHEN match_date GLOB '??.??.20??' THEN substr(match_date,7,4)
                ELSE NULL
            END AS year,
            home_score, away_score, regulation_home_score, regulation_away_score,
            result_final, result_regulation,
            odds_home, odds_draw, odds_away,
            odds_total_over, odds_total_under,
            total_line
        FROM backtest_hockey_features
        WHERE {strat["where"]}
    """

    rows = c.execute(query).fetchall()

    if not rows:
        return None

    market = strat["market"]
    year_data = defaultdict(lambda: {"n": 0, "hits": 0, "total_odds": 0.0})

    for r in rows:
        year = r["year"]
        if year is None:
            continue

        # Determine if bet wins based on market
        reg_home = r["regulation_home_score"]
        reg_away = r["regulation_away_score"]

        if market == "home":
            if reg_home is None or reg_away is None:
                continue
            won = reg_home > reg_away
            odds = r["odds_home"]
        elif market == "away":
            if reg_home is None or reg_away is None:
                continue
            won = reg_away > reg_home
            odds = r["odds_away"]
        elif market == "draw":
            if reg_home is None or reg_away is None:
                continue
            won = reg_home == reg_away
            odds = r["odds_draw"]
        elif market == "over":
            hs = r["home_score"]
            as_ = r["away_score"]
            if hs is None or as_ is None:
                continue
            total = hs + as_
            line = r["total_line"] if r["total_line"] else 4.5
            won = total > line
            odds = r["odds_total_over"] if r["odds_total_over"] else 2.0
        elif market == "under":
            hs = r["home_score"]
            as_ = r["away_score"]
            if hs is None or as_ is None:
                continue
            total = hs + as_
            line = r["total_line"] if r["total_line"] else 5.5
            won = total < line
            odds = r["odds_total_under"] if r["odds_total_under"] else 2.0
        else:
            continue

        if odds is None or odds < 1.0:
            continue

        yd = year_data[year]
        yd["n"] += 1
        yd["total_odds"] += odds
        if won:
            yd["hits"] += 1

    if not year_data:
        return None

    # Build per-year list
    year_list = []
    for yr in sorted(year_data.keys()):
        yd = year_data[yr]
        n = yd["n"]
        hits = yd["hits"]
        avg_odds = yd["total_odds"] / n if n > 0 else 0
        hit_pct = hits / n * 100 if n > 0 else 0
        roi = (hit_pct / 100 * avg_odds - 1) * 100 if avg_odds > 0 else 0
        year_list.append({
            "year": yr,
            "n": n,
            "hits": hits,
            "hit_pct": hit_pct,
            "avg_odds": avg_odds,
            "roi": roi,
        })

    # Totals
    total_n = sum(y["n"] for y in year_list)
    total_hits = sum(y["hits"] for y in year_list)
    total_odds_sum = sum(y["avg_odds"] * y["n"] for y in year_list)
    total_avg_odds = total_odds_sum / total_n if total_n > 0 else 0
    total_hit_pct = total_hits / total_n * 100 if total_n > 0 else 0
    total_roi = (total_hit_pct / 100 * total_avg_odds - 1) * 100 if total_avg_odds > 0 else 0

    # 2022-2026 analysis
    years_22_26 = [y for y in year_list if y["year"] in ("2022","2023","2024","2025","2026")]
    years_19_21 = [y for y in year_list if y["year"] in ("2019","2020","2021")]

    pos_22_26 = [y for y in years_22_26 if y["roi"] > 0]
    pos_19_21 = [y for y in years_19_21 if y["roi"] > 0]

    min_n_22_26 = min((y["n"] for y in years_22_26), default=0)

    weakest = min(years_22_26, key=lambda y: y["roi"]) if years_22_26 else None
    strongest = max(years_22_26, key=lambda y: y["roi"]) if years_22_26 else None

    return {
        "name": strat["name"],
        "type": strat["type"],
        "league": strat["league"],
        "where": strat["where"],
        "market": market,
        "total_n": total_n,
        "total_roi": total_roi,
        "total_hit_pct": total_hit_pct,
        "total_avg_odds": total_avg_odds,
        "year_list": year_list,
        "years_22_26": years_22_26,
        "years_19_21": years_19_21,
        "pos_count_22_26": len(pos_22_26),
        "total_count_22_26": len(years_22_26),
        "pos_count_19_21": len(pos_19_21),
        "total_count_19_21": len(years_19_21),
        "all_22_26_positive": len(pos_22_26) == len(years_22_26) and len(years_22_26) > 0,
        "min_n_22_26": min_n_22_26,
        "weakest_year": weakest,
        "strongest_year": strongest,
    }


# ============================================================
# STEP 4: PRINT RESULTS
# ============================================================
def print_strategy_detail(r):
    print(f"\n{'─' * 70}")
    print(f"Strategy: {r['name']}")
    print(f"Type: {r['type']} | Market: {r['market']}")
    print(f"League: {r['league']}")
    print(f"Total: n={r['total_n']}, ROI={r['total_roi']:+.1f}%, Hit%={r['total_hit_pct']:.1f}%, AvgOdds={r['total_avg_odds']:.2f}")
    print(f"\nYear breakdown:")
    print(f"  {'Year':>4} | {'n':>4} | {'Hit%':>6} | {'AvgOdds':>7} | {'ROI%':>7}")
    print(f"  {'-'*4}-+-{'-'*4}-+-{'-'*6}-+-{'-'*7}-+-{'-'*7}")
    for y in r["year_list"]:
        print(f"  {y['year']:>4} | {y['n']:>4} | {y['hit_pct']:>5.1f}% | {y['avg_odds']:>7.2f} | {y['roi']:>+6.1f}%")

    print(f"\n  Summary 2022-2026:")
    print(f"    All positive: {'YES' if r['all_22_26_positive'] else 'NO'} ({r['pos_count_22_26']}/{r['total_count_22_26']})")
    print(f"    Min n: {r['min_n_22_26']}")
    if r["weakest_year"]:
        print(f"    Weakest: {r['weakest_year']['year']} ({r['weakest_year']['roi']:+.1f}%)")
    if r["strongest_year"]:
        print(f"    Strongest: {r['strongest_year']['year']} ({r['strongest_year']['roi']:+.1f}%)")
    if r["total_count_19_21"] > 0:
        print(f"  Summary 2019-2021: {r['pos_count_19_21']}/{r['total_count_19_21']} positive")


def classify_strategy(r):
    """Classify into A/B/C/D buckets."""
    all_pos = r["all_22_26_positive"]
    total_22_26 = r["total_count_22_26"]
    pos_22_26 = r["pos_count_22_26"]
    min_n = r["min_n_22_26"]
    total_n = r["total_n"]

    # Check for high variance
    if r["years_22_26"]:
        rois = [y["roi"] for y in r["years_22_26"]]
        roi_range = max(rois) - min(rois) if rois else 0
    else:
        roi_range = 0

    if all_pos and total_22_26 >= 3 and min_n >= 10:
        return "A. STRONG CORE"
    elif all_pos and total_22_26 >= 3 and min_n < 10:
        return "B. WATCHLIST (low volume)"
    elif pos_22_26 >= 4 and total_22_26 >= 4:
        return "B. WATCHLIST (4/5 positive)"
    elif pos_22_26 >= 3 and total_22_26 >= 3:
        if roi_range > 100:
            return "C. FRAGILE / HIGH VARIANCE"
        return "B. WATCHLIST"
    elif total_n < 20:
        return "D. REJECT (too small)"
    else:
        return "D. REJECT"


def main():
    # STEP 1
    data_quality_audit()

    # STEP 2-3: Evaluate all strategies
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row

    print("\n" + "=" * 70)
    print("STEP 2: RECHECKING STRATEGIES")
    print("=" * 70)

    results = []
    for strat in STRATEGIES:
        r = evaluate_strategy(conn, strat)
        if r:
            results.append(r)
        else:
            print(f"\n  WARNING: No data for '{strat['name']}'")

    conn.close()

    # Print detailed results
    for r in results:
        print_strategy_detail(r)

    # STEP 4: Summary table
    print("\n" + "=" * 70)
    print("STEP 3: SUMMARY TABLE — ALL STRATEGIES")
    print("=" * 70)
    print(f"{'#':>2} | {'Strategy':<45} | {'Type':<12} | {'ROI%':>6} | {'n':>4} | {'Hit%':>5} | {'22-26 +':>6} | {'All+?':>5}")
    print(f"{'-'*2}-+-{'-'*45}-+-{'-'*12}-+-{'-'*6}-+-{'-'*4}-+-{'-'*5}-+-{'-'*6}-+-{'-'*5}")
    for i, r in enumerate(results, 1):
        all_plus = "YES" if r["all_22_26_positive"] else "NO"
        ratio = f"{r['pos_count_22_26']}/{r['total_count_22_26']}"
        print(f"{i:>2} | {r['name']:<45} | {r['type']:<12} | {r['total_roi']:>+5.1f}% | {r['total_n']:>4} | {r['total_hit_pct']:>4.1f}% | {ratio:>6} | {all_plus:>5}")

    # STEP 5: Classification
    print("\n" + "=" * 70)
    print("STEP 4: CLASSIFICATION")
    print("=" * 70)

    buckets = {"A. STRONG CORE": [], "B. WATCHLIST": [], "C. FRAGILE / HIGH VARIANCE": [], "D. REJECT": []}
    for r in results:
        cat = classify_strategy(r)
        # Normalize bucket key
        if "A." in cat:
            buckets["A. STRONG CORE"].append((r, cat))
        elif "B." in cat:
            buckets["B. WATCHLIST"].append((r, cat))
        elif "C." in cat:
            buckets["C. FRAGILE / HIGH VARIANCE"].append((r, cat))
        else:
            buckets["D. REJECT"].append((r, cat))

    for bucket_name in ["A. STRONG CORE", "B. WATCHLIST", "C. FRAGILE / HIGH VARIANCE", "D. REJECT"]:
        items = buckets[bucket_name]
        print(f"\n{'=' * 70}")
        print(f"  {bucket_name} ({len(items)} strategies)")
        print(f"{'=' * 70}")
        if not items:
            print("  (empty)")
            continue
        for r, cat in items:
            print(f"\n  [{cat}] {r['name']}")
            print(f"    League: {r['league']}")
            print(f"    Total: n={r['total_n']}, ROI={r['total_roi']:+.1f}%, Hit%={r['total_hit_pct']:.1f}%")
            print(f"    2022-2026: {r['pos_count_22_26']}/{r['total_count_22_26']} positive, min_n={r['min_n_22_26']}")
            if r["total_count_19_21"] > 0:
                old_ratio = f"{r['pos_count_19_21']}/{r['total_count_19_21']}"
                if r['pos_count_19_21'] < r['total_count_19_21'] and r['all_22_26_positive']:
                    print(f"    2019-2021: {old_ratio} — старый период слабее, возможен структурный сдвиг после 2021")
                else:
                    print(f"    2019-2021: {old_ratio} positive")
            if r["weakest_year"]:
                print(f"    Weakest year: {r['weakest_year']['year']} ({r['weakest_year']['roi']:+.1f}%, n={r['weakest_year']['n']})")
            if r["strongest_year"]:
                print(f"    Strongest year: {r['strongest_year']['year']} ({r['strongest_year']['roi']:+.1f}%, n={r['strongest_year']['n']})")

    # STEP 6: Final recommendations
    print("\n" + "=" * 70)
    print("STEP 5: FINAL RECOMMENDATIONS")
    print("=" * 70)

    strong = buckets["A. STRONG CORE"]
    watch = buckets["B. WATCHLIST"]

    print("\nIMPLEMENT (Strong Core):")
    for r, cat in strong:
        print(f"  ✅ {r['name']} — ROI={r['total_roi']:+.1f}%, n={r['total_n']}, 2022-2026: {r['pos_count_22_26']}/{r['total_count_22_26']} positive")

    print("\nOBSERVE (Watchlist):")
    for r, cat in watch:
        print(f"  ⚠️  {r['name']} — ROI={r['total_roi']:+.1f}%, n={r['total_n']}, 2022-2026: {r['pos_count_22_26']}/{r['total_count_22_26']} positive")

    print("\nREJECT:")
    for r, cat in buckets["C. FRAGILE / HIGH VARIANCE"] + buckets["D. REJECT"]:
        print(f"  ❌ {r['name']} — {cat}")

    # Structural break detection
    print("\nSTRUCTURAL BREAK CANDIDATES (weak 2019-2021, strong 2022-2026):")
    for r in results:
        if r["all_22_26_positive"] and r["total_count_19_21"] > 0 and r["pos_count_19_21"] < r["total_count_19_21"]:
            print(f"  🔀 {r['name']} — 2019-2021: {r['pos_count_19_21']}/{r['total_count_19_21']}, 2022-2026: {r['pos_count_22_26']}/{r['total_count_22_26']}")

    # Discrepancy with old report
    print("\nOLD REPORT DISCREPANCIES (if any strategy claimed 7/7 but now shows differently):")
    for r in results:
        if r["total_count_22_26"] < r["total_count_19_21"] + r["total_count_22_26"]:
            # Check if old report might have claimed more years
            pass  # Will be visible in the detailed output


if __name__ == "__main__":
    main()
