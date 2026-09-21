#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tennis_name_mapping_expand.py

1) Expand tennis_player_mapping with both name forms:
   - 'Ига Свёнтек' (full Russian name)
   - 'Свёнтек И.' (surname + initial — betz display format)
2) Create tennis_name_lookup table for efficient JOINs:
   betz_name -> eng_name
3) Report coverage stats.
"""
import sqlite3
import re
from collections import defaultdict
from pathlib import Path

DB_PATH = str(Path(__file__).parent / "betagent.db")

CYR_INITIAL = {
    'А': 'A', 'Б': 'B', 'В': 'V', 'Г': 'G', 'Д': 'D', 'Е': 'E',
    'Ё': 'Yo', 'Ж': 'Zh', 'З': 'Z', 'И': 'I', 'Й': 'Y', 'К': 'K', 'Л': 'L',
    'М': 'M', 'Н': 'N', 'О': 'O', 'П': 'P', 'Р': 'R', 'С': 'S',
    'Т': 'T', 'У': 'U', 'Ф': 'F', 'Х': 'Kh', 'Ц': 'Ts', 'Ч': 'Ch',
    'Ш': 'Sh', 'Щ': 'Sch', 'Ъ': '', 'Ы': 'Y', 'Ь': '', 'Э': 'E',
    'Ю': 'Yu', 'Я': 'Ya',
}


def _norm(s: str) -> str:
    return s.lower().replace('\u0451', '\u0435').replace('\u0401', '\u0435')


def extract_surname_and_initial(rus_name: str):
    """
    Parse a Russian name -> (surname, short_initial_cyrillic, is_initial_form)

    'Ига Свёнтек'         -> ('Свёнтек', 'И', False)
    'Соболенко А.'        -> ('Соболенко', 'А', True)
    'Давидович Фокина А.' -> ('Давидович Фокина', 'А', True)
    'Мариано Навоне'      -> ('Навоне', 'М', False)
    """
    name = rus_name.strip()
    parts = name.split()

    if len(parts) >= 2:
        last = parts[-1]
        clean_last = last.rstrip('.')
        # Check if last token is an initial: short alphabetic + optional dots
        if len(clean_last) <= 3 and clean_last.isalpha():
            surname = ' '.join(parts[:-1]).rstrip('.')
            init_cyr = clean_last.upper()
            return surname, init_cyr, True

    if len(parts) >= 2:
        # Full Russian name: last word = surname, first word gives initial
        surname = parts[-1]
        init_cyr = parts[0][0].upper()
        return surname, init_cyr, False

    return name, '', False


def main():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")

    # ---- Create lookup table ----
    conn.execute("""
        CREATE TABLE IF NOT EXISTS tennis_name_lookup (
            betz_name TEXT PRIMARY KEY,
            eng_name TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()

    # ---- Get all confident mappings ----
    rows = conn.execute(
        "SELECT eng_name, rus_name, tour, confidence, match_method FROM tennis_player_mapping WHERE needs_review=0"
    ).fetchall()
    print(f"Confident mappings to expand: {len(rows)}")

    lookup_entries = []   # (betz_name, eng_name)
    mapping_variants = []  # (eng_name, rus_name_short, tour, conf, method)

    for eng_name, rus_name, tour, conf, method in rows:
        rus_clean = rus_name.strip()
        lookup_entries.append((rus_clean, eng_name))

        surname, initial_cyr, was_initial_form = extract_surname_and_initial(rus_name)
        if not surname:
            continue

        if not was_initial_form and initial_cyr:
            # Generate surname+initial variant: "Свёнтек И." (betz format)
            short_form = f"{surname} {initial_cyr}."
            lookup_entries.append((short_form, eng_name))
            mapping_variants.append((eng_name, short_form, tour, conf, f"{method}_variant", 0))

            # Also: "И. Свёнтек" (some betz screens show it this way)
            reversed_form = f"{initial_cyr}. {surname}"
            lookup_entries.append((reversed_form, eng_name))

    # Deduplicate lookup
    seen = set()
    unique_lookup = []
    for betz, eng in lookup_entries:
        key = _norm(betz)
        if key not in seen:
            seen.add(key)
            unique_lookup.append((betz, eng))

    # Insert lookup
    BATCH = 500
    batch = []
    for betz, eng in unique_lookup:
        batch.append((betz, eng))
        if len(batch) >= BATCH:
            conn.executemany(
                "INSERT OR REPLACE INTO tennis_name_lookup (betz_name, eng_name) VALUES (?, ?)",
                batch)
            conn.commit()
            batch.clear()
    if batch:
        conn.executemany(
            "INSERT OR REPLACE INTO tennis_name_lookup (betz_name, eng_name) VALUES (?, ?)",
            batch)
        conn.commit()

    # Insert mapping variant entries
    batch = []
    for eng, rus, tour, conf, meth, rev in mapping_variants:
        batch.append((eng, rus, tour, conf, meth, rev))
        if len(batch) >= BATCH:
            conn.executemany(
                "INSERT OR REPLACE INTO tennis_player_mapping (eng_name, rus_name, tour, confidence, match_method, needs_review) VALUES (?, ?, ?, ?, ?, ?)",
                batch)
            conn.commit()
            batch.clear()
    if batch:
        conn.executemany(
            "INSERT OR REPLACE INTO tennis_player_mapping (eng_name, rus_name, tour, confidence, match_method, needs_review) VALUES (?, ?, ?, ?, ?, ?)",
            batch)
        conn.commit()

    # ---- Coverage stats ----
    total_betz_names = conn.execute(
        "SELECT COUNT(*) FROM (SELECT DISTINCT player1 FROM backtest_tennis_matches UNION SELECT DISTINCT player2 FROM backtest_tennis_matches)"
    ).fetchone()[0]

    lookup_count = conn.execute("SELECT COUNT(*) FROM tennis_name_lookup").fetchone()[0]

    matches_p1 = conn.execute(
        "SELECT COUNT(*) FROM backtest_tennis_matches m JOIN tennis_name_lookup t ON t.betz_name = m.player1"
    ).fetchone()[0]

    matches_p2 = conn.execute(
        "SELECT COUNT(*) FROM backtest_tennis_matches m JOIN tennis_name_lookup t ON t.betz_name = m.player2"
    ).fetchone()[0]

    matches_both = conn.execute(
        "SELECT COUNT(*) FROM backtest_tennis_matches m "
        "JOIN tennis_name_lookup t1 ON t1.betz_name = m.player1 "
        "JOIN tennis_name_lookup t2 ON t2.betz_name = m.player2"
    ).fetchone()[0]

    total_matches = conn.execute("SELECT COUNT(*) FROM backtest_tennis_matches").fetchone()[0]

    jeff_total_players = conn.execute(
        "SELECT COUNT(*) FROM (SELECT DISTINCT LOWER(winner_name) FROM backtest_tennis_players UNION SELECT DISTINCT LOWER(loser_name) FROM backtest_tennis_players)"
    ).fetchone()[0]

    eng_in_lookup = conn.execute("SELECT COUNT(DISTINCT eng_name) FROM tennis_name_lookup").fetchone()[0]

    print(f"\n{'='*60}")
    print(f"COVERAGE STATS")
    print(f"{'='*60}")
    print(f"Total betz unique names:        {total_betz_names}")
    print(f"Lookup entries:                 {lookup_count}")
    print(f"Mapping variant entries added:  {len(mapping_variants)}")
    print(f"Eng names covered in lookup:    {eng_in_lookup}/{jeff_total_players}")
    print(f"")
    print(f"Betz matches total:             {total_matches}")
    print(f"Matches p1 mappable:            {matches_p1} ({matches_p1/total_matches*100:.1f}%)")
    print(f"Matches p2 mappable:            {matches_p2} ({matches_p2/total_matches*100:.1f}%)")
    print(f"Matches BOTH mappable:          {matches_both} ({matches_both/total_matches*100:.1f}%)")

    # Players with multiple betz forms
    print(f"\n--- Players with multiple name forms in lookup (top 20) ---")
    multi = conn.execute("""
        SELECT eng_name, GROUP_CONCAT(betz_name) as variants, COUNT(*) as nforms
        FROM tennis_name_lookup
        GROUP BY eng_name HAVING nforms > 1
        ORDER BY nforms DESC LIMIT 20
    """).fetchall()
    for eng, variants, n in multi:
        print(f"  {eng} ({n}): {variants}")

    # Jeff players NOT yet in lookup
    jeff_players = set()
    for col in ('winner_name', 'loser_name'):
        for r in conn.execute(f"SELECT DISTINCT {col} FROM backtest_tennis_players WHERE {col} IS NOT NULL"):
            jeff_players.add(r[0].lower())

    eng_names = set(r[0].lower() for r in conn.execute("SELECT DISTINCT eng_name FROM tennis_player_mapping WHERE needs_review=0").fetchall())

    unmatched_jeff = len(jeff_players - eng_names)
    print(f"\nJeff Sackmann players not in mapping: {unmatched_jeff}/{len(jeff_players)}")

    conn.close()
    print("\nDONE")


if __name__ == "__main__":
    main()
