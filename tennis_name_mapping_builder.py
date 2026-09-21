#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tennis_name_mapping_builder.py

Build a robust mapping between Jeff Sackmann English player names
and Russian bookmaker-style player names (betz.su / our history).

Schema confirmed (2026-04-07):
  backtest_tennis_players: winner_name, loser_name (English) + tour
  backtest_tennis_matches: player1, player2 (Russian) + tour
"""
import sqlite3
import logging
import re
import difflib
import time
from collections import defaultdict
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)

DB_PATH = str(Path(__file__).parent / "betagent.db")

# ---------------------------------------------------------------
# Russian -> Cyrillic initial -> English initial
# ---------------------------------------------------------------
CYR_INITIAL = {
    'А': 'A', 'Б': 'B', 'В': 'V', 'Г': 'G', 'Д': 'D', 'Е': 'E',
    'Ё': 'Yo', 'Ж': 'Zh', 'З': 'Z', 'И': 'I', 'Й': 'Y', 'К': 'K', 'Л': 'L',
    'М': 'M', 'Н': 'N', 'О': 'O', 'П': 'P', 'Р': 'R', 'С': 'S',
    'Т': 'T', 'У': 'U', 'Ф': 'F', 'Х': 'Kh', 'Ц': 'Ts', 'Ч': 'Ch',
    'Ш': 'Sh', 'Щ': 'Sch', 'Ъ': '', 'Ы': 'Y', 'Ь': '', 'Э': 'E',
    'Ю': 'Yu', 'Я': 'Ya',
}

# ---------------------------------------------------------------
# Known tennis-specific variants: Russian surname (lowercase!) -> {English surname, ...}
# ALL keys are lowercase Cyrillic.
# ---------------------------------------------------------------
KNOWN_VARIANTS = {
    'собол':     {'Sabalenka'},  # partial — Соболенко but also Соболева etc
    'соболенко': {'Sabalenka'},
    'свёнтек':   {'Swiatek'},
    'свентек':   {'Swiatek'},
    'рыбакин':   {'Rybakina', 'Rybakin'},
    'рыбакина':  {'Rybakina'},
    'павлюченков': {'Pavlyuchenkova'},
    'хачанов':   {'Khachanov'},
    'кудерметов': {'Kudermetova'},
    'звонарев':  {'Zvonareva', 'Zvonarev'},
    'касаткин':  {'Kasatkina'},
    'медведев':  {'Medvedev'},
    'рублев':    {'Rublev'},
    'рублев':    {'Rublev'},
    'джокович':  {'Djokovic'},
    'зверев':    {'Zverev'},
    'циципас':   {'Tsitsipas'},
    'андреев':   {'Andreev'},
    'андеева':   {'Andreeva'},
    'андреева':  {'Andreeva'},
    'потапов':   {'Potapova'},
    'потапова':  {'Potapova'},
    'самсонов':  {'Samsonova'},  # could be Samsonov but WTA context
    'самсонова': {'Samsonova'},
    'шнайдер':   {'Schneider'},
    'шнайдера':  {'Schneider'},
    'гаске':     {'Gasquet'},
    'монфис':    {'Monfils'},
    'тиафо':     {'Tiafoe'},
    'фриц':      {'Fritz'},
    'штрикер':   {'Stricker'},
    'оже-альяссим': {'Auger-Aliassime'},
    'оже альяссим': {'Auger-Aliassime'},
    'вавринка':  {'Wawrinka'},
    'фучович':   {'Fucsovics'},
    'баутиста-агут': {'Bautista-Agut'},
    'баутиста агут': {'Bautista-Agut'},
    'димитров':  {'Dimitrov'},
    'рун':       {'Rune'},
    'алькарас':  {'Alcaraz'},
    'синнер':    {'Sinner'},
    'музетти':   {'Musetti'},
    'де минор':  {'De Minaur'},
    'хуркач':    {'Hurkacz'},
    'алексеев':  {'Alekseeva'},
    'алексеева': {'Alekseeva'},
    'александров': {'Alexandrova'},
    'козлов':    {'Kozlova'},
    'козлова':   {'Kozlova'},
    'савиных':   {'Savinykh'},
    'калинск':   {'Kalinskaya'},
    'остапенк':  {'Ostapenko'},
    'саснов':    {'Sasnovich'},
    'саснович':  {'Sasnovich'},
    'мертенс':   {'Mertens'},
    'гарсия':    {'Garcia'},
    'бенчич':    {'Bencic'},
    'коллинс':   {'Collins'},
    'бузков':    {'Buzkova', 'Bouzkova'},
    'бузкова':   {'Buzkova'},
    'боузков':   {'Bouzkova'},
    'мухов':     {'Muchova'},
    'мухова':    {'Muchova'},
    'вондроушов': {'Vondrousova'},
    'вондров':   {'Vondrousova'},
    'вондрова':  {'Vondrousova'},
    'аванес':    {'Avanesyan', 'Avanesova'},
    'берреттин': {'Berrettini'},
    'шелбайх':   {'Shelbayh'},
    'шелбах':    {'Shelbayh'},
    'бублик':    {'Bublik'},
    'кецманович':{'Kecmanovic'},
    'молчан':    {'Molcan'},
    'маннарин':  {'Mannarino'},
    'удварди':   {'Udvardy'},
    'волынец':   {'Volynets'},
    'доден':     {'Dodin'},
    'пол':       {'Paul'},
    'навоне':    {'Navone'},
    'трунгеллит': {'Trungelliti'},
    'трунхельити': {'Trungelliti'},
    'бурручаг':  {'Burruchaga'},
    'халеп':     {'Halep'},
    'рахимов':   {'Rakhimova'},
    'раимова':   {'Rakhimova'},
    'завацк':    {'Zavatska'},
    'фрухвиртов':{'Fruhvirtova'},
    'синяков':   {'Siniakova'},
    'крейчиков': {'Krejcikova'},
    'плишков':   {'Pliskova'},
    'свитол':    {'Svitolina'},
    'томлянов':  {'Tomljanovic'},
    'петрович':  {'Petrovic'},
    'лайович':   {'Lajovic'},
    'ковинич':   {'Kovinic'},
    'данилович': {'Danilovic'},
    'стеванович':{'Stevanovic'},
    'гауф':      {'Gauff'},
    'бадоса':    {'Badosa'},
    'пер':       {'Pera'},
    'кристиан':  {'Cristian'},
    'минен':     {'Minen'},
}

# ---------------------------------------------------------------
# Transliteration
# ---------------------------------------------------------------
RUS_LATIN_MAP = {
    'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd',
    'е': 'e', 'ё': 'yo', 'ж': 'zh', 'з': 'z', 'и': 'i',
    'й': 'y', 'к': 'k', 'л': 'l', 'м': 'm', 'н': 'n',
    'о': 'o', 'п': 'p', 'р': 'r', 'с': 's', 'т': 't',
    'у': 'u', 'ф': 'f', 'х': 'kh', 'ц': 'ts', 'ч': 'ch',
    'ш': 'sh', 'щ': 'shch', 'ъ': '', 'ы': 'y', 'ь': '',
    'э': 'e', 'ю': 'yu', 'я': 'ya', 'і': 'i',
}

ALT_REPLACEMENTS = [
    ('shch', ['sch']),
    ('kh', ['h']),
    ('ts', ['tz']),
    ('zh', ['j']),
    ('yo', ['jo']),
    ('yu', ['iu']),
    ('ya', ['ia']),
]


def transliterate_rus(text: str) -> str:
    out = []
    for ch in text.lower():
        out.append(RUS_LATIN_MAP.get(ch, ch))
    return ''.join(out).strip()


def transliterate_variants(bare: str) -> set:
    """Given a Cyrillic surname, return a set of possible Roman forms."""
    base = transliterate_rus(bare)
    results = {base}
    for pat, alts in ALT_REPLACEMENTS:
        new_set = set(results)
        for candidate in results:
            if pat in candidate:
                for alt in alts:
                    new_set.add(candidate.replace(pat, alt))
        results = new_set
    return results


# ---------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------
def normalize_eng(name):
    """
    'Frances Tiafoe' -> ('frances', 'tiafoe', 'F')
    'Jan Lennard Struff' -> ('jan', 'lennard struff', 'J')
    """
    name = re.sub(r'\s+', ' ', name.strip().lower())
    parts = name.split()
    if not parts:
        return '', '', ''
    if len(parts) == 1:
        return parts[0], '', ''
    first = parts[0]
    surname = ' '.join(parts[1:])
    initial = first[0].upper() if first else ''
    return first, surname, initial


def _normalize_ё(s: str) -> str:
    return s.replace('\u0451', '\u0435').replace('\u0401', '\u0435')


def _ends_with_initial_token(token: str) -> bool:
    """Check if token looks like a Cyrillic initial: single letter (with optional dots)."""
    clean = token.strip('.')
    if not clean or len(clean) > 2:
        return False
    if not clean.isalpha():
        return False
    if all(c.isupper() for c in clean):
        return True
    # Lowercase Cyrillic single char
    if len(clean) == 1 and '\u0400' <= clean[0] <= '\u04FF':
        return True
    return False


def _extract_initial(tokens: list) -> str:
    """Extract first English initial from a list of tokens."""
    for tok in tokens:
        clean = tok.strip('.')
        if clean and clean[0].upper() in CYR_INITIAL:
            return CYR_INITIAL[clean[0].upper()]
    return ''


def normalize_rus(name: str):
    """
    Russian bookmaker name -> (bare_surname_lower, initial_letter)

    Patterns:
      "Соболенко А."   -> ('соболенко', 'A')    surname + initial
      "Андреева М."    -> ('андреева', 'M')
      "Шмидлова А.К."  -> ('шмидлова', 'A')     double initial
      "Джокович Н."    -> ('джокович', 'N')
      "Де Минаур А."   -> ('де минаур', 'A')
      "Адам Уолтон"    -> ('уолтон', 'A')         full name, first is given
      "Адамович П."    -> ('адамович', 'P')
    """
    name = re.sub(r'\s+', ' ', name.strip())
    normed = _normalize_ё(name)
    parts = normed.split()

    if len(parts) >= 2:
        last_token = parts[-1]
        if _ends_with_initial_token(last_token):
            # Surname(s) + initial
            bare_parts = parts[:-1]
            bare = _normalize_ё(' '.join(bare_parts)).lower()
            initial_eng = _extract_initial([last_token])
            return bare, initial_eng

    if len(parts) >= 2:
        # Full name: first word(s) = given, last = surname
        bare = _normalize_ё(parts[-1]).lower()
        initial_eng = CYR_INITIAL.get(parts[0][0].upper(), '')
        return bare, initial_eng

    return name.lower(), ''


# ---------------------------------------------------------------
# Similarity
# ---------------------------------------------------------------
def fuzzy_sim(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a, b).ratio() * 100


# ---------------------------------------------------------------
# DB
# ---------------------------------------------------------------
def sqlite_conn(path):
    conn = sqlite3.connect(path, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def execute_with_retry(conn, sql, params=(), retries=3):
    for attempt in range(retries):
        try:
            return conn.execute(sql, params)
        except sqlite3.OperationalError as e:
            if 'locked' in str(e).lower() and attempt < retries - 1:
                time.sleep(1)
                continue
            raise


# ---------------------------------------------------------------
# Main
# ---------------------------------------------------------------
def main():
    conn = sqlite_conn(DB_PATH)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS tennis_player_mapping (
            eng_name TEXT PRIMARY KEY,
            rus_name TEXT,
            tour TEXT,
            confidence REAL,
            match_method TEXT,
            needs_review INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS tennis_player_mapping_review (
            rus_name TEXT,
            eng_candidate TEXT,
            confidence REAL,
            reason TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()

    # ---- Collect English names ----
    eng_names = {}
    all_eng = set()
    for col in ('winner_name', 'loser_name'):
        cur = execute_with_retry(conn,
            f"SELECT DISTINCT {col}, tour FROM backtest_tennis_players WHERE {col} IS NOT NULL AND {col} != ''")
        for raw_name, tour in cur.fetchall():
            key = raw_name.strip().lower()
            if key in eng_names:
                eng_names[key] = (raw_name.strip(), tour, *normalize_eng(raw_name))
            else:
                eng_names[key] = (raw_name.strip(), tour, *normalize_eng(raw_name))
            all_eng.add(key)

    log.info(f"English unique names: {len(all_eng)}")

    # Index: surname_lower -> set of eng keys
    eng_by_surname = defaultdict(set)
    for key in all_eng:
        _, surname, _ = normalize_eng(key)
        eng_by_surname[surname].add(key)

    log.info(f"English unique surnames indexed: {len(eng_by_surname)}")

    # ---- Collect Russian names ----
    rus_names = {}
    for col in ('player1', 'player2'):
        cur = execute_with_retry(conn,
            f"SELECT DISTINCT {col}, tour FROM backtest_tennis_matches WHERE {col} IS NOT NULL AND {col} != ''")
        for raw_name, tour in cur.fetchall():
            key = raw_name.strip()
            if key in rus_names:
                continue
            bare, initial = normalize_rus(raw_name)
            rus_names[key] = (raw_name.strip(), bare, initial, tour)

    log.info(f"Russian unique names: {len(rus_names)}")

    # ---- Matching ----
    confident_matches = []
    review_matches = []
    review_table_rows = []
    matched_rus = set()

    batch = []
    BATCH_SIZE = 200

    for rus_full, (rus_orig, bare_rus, rus_initial, rus_tour) in rus_names.items():
        bare_lower = bare_rus.strip().lower()

        candidates = []  # (eng_key, score, method)

        require_initial = bool(rus_initial)

        # ---- 1) Known variants (direct surname lookup) ----
        # Try exact match first, then prefix match
        matched_known = False
        for kv_key in KNOWN_VARIANTS:
            if bare_lower == kv_key or bare_lower.startswith(kv_key):
                for eng_surname in KNOWN_VARIANTS[kv_key]:
                    for eng_key in all_eng:
                        _, e_surname, e_initial = normalize_eng(eng_key)
                        if e_surname.lower() == eng_surname.lower():
                            if rus_initial and e_initial:
                                if rus_initial[0].upper() == e_initial[0].upper():
                                    candidates.append((eng_key, 98.0, 'known_variant'))
                                else:
                                    candidates.append((eng_key, 80.0, 'known_variant_init_mismatch'))
                            elif rus_initial:
                                candidates.append((eng_key, 90.0, 'known_variant_eng_no_init'))
                            else:
                                candidates.append((eng_key, 95.0, 'known_variant_no_initial'))
                                matched_known = True
                break  # only match first (most specific) KNOWN_VARIANTS key

        # ---- 2) Transliteration + exact surname match ----
        trans_variants = transliterate_variants(bare_lower)
        for tv in trans_variants:
            if tv in eng_by_surname:
                for ek in eng_by_surname[tv]:
                    _, e_surname, e_initial = normalize_eng(ek)
                    if rus_initial and e_initial:
                        if rus_initial[0].upper() == e_initial[0].upper():
                            candidates.append((ek, 96.0, 'exact_translit'))
                        else:
                            candidates.append((ek, 78.0, 'exact_translit_init_mismatch'))
                    else:
                        candidates.append((ek, 88.0, 'exact_translit_no_init'))

        # ---- 3) Fuzzy match on transliteration variants ----
        for tv in trans_variants:
            # Only English surnames within reasonable length of the bare
            min_len = max(1, len(tv) - 3)
            max_len = len(tv) + 3
            for e_surname, ek_set in eng_by_surname.items():
                if not (min_len <= len(e_surname) <= max_len):
                    continue
                sim = fuzzy_sim(tv, e_surname)
                if sim < 68:
                    continue
                for ek in ek_set:
                    _, _, e_init = normalize_eng(ek)
                    score = sim
                    parts = ['fuzzy']
                    if rus_initial and e_init:
                        if rus_initial[0].upper() == e_init[0].upper():
                            score = min(sim + 5, 99)
                            parts.append('init_match')
                        else:
                            score = max(sim - 15, 45)
                            # If initial mismatch and fuzzy is low, drop
                            if sim < 80:
                                continue
                            parts.append('init_mismatch')
                    elif rus_initial:
                        # We have a Cyrillic initial but no English initial
                        # => could be first-name based surname like "Paul"
                        # or first name without initial (rare for tennis)
                        # Only keep if very high similarity
                        if sim < 85:
                            continue
                        parts.append('no_init_but_rus_has_init')
                    else:
                        if sim < 75:
                            continue
                        parts.append('no_init')

                    if score >= 60:
                        candidates.append((ek, score, '_'.join(parts)))

        # ---- Deduplicate: keep best score per eng_key ----
        best_per_eng = {}
        for ek, sc, mt in candidates:
            if ek not in best_per_eng or sc > best_per_eng[ek][0]:
                best_per_eng[ek] = (sc, mt)

        scored = sorted([(sc, mt, ek) for ek, (sc, mt) in best_per_eng.items()],
                        key=lambda x: -x[0])

        if not scored:
            continue

        best_score, best_method, best_eng = scored[0]
        second_score = scored[1][0] if len(scored) > 1 else 0

        # Collision
        collision = second_score >= 72 and (best_score - second_score) < 8
        is_certain = 'mismatch' not in best_method

        if collision:
            review_matches.append((rus_full, best_eng, best_score,
                                   f"collision 2nd={scored[1][2]} ({second_score:.0f})"))
            review_table_rows.append((rus_full, best_eng, best_score,
                f"collision with {scored[1][2]} ({second_score:.0f} vs {best_score:.0f})"))
            matched_rus.add(rus_full)
            batch.append((best_eng, rus_full, rus_tour, best_score, best_method, 1))
        elif best_score >= 90 and is_certain:
            confident_matches.append((rus_full, best_eng, best_score, best_method))
            matched_rus.add(rus_full)
            batch.append((best_eng, rus_full, rus_tour, best_score, best_method, 0))
        elif best_score >= 80 and is_certain:
            close_alts = [sc for sc, _, _ in scored[:5] if sc >= 78]
            if len(close_alts) > 1 and (close_alts[0] - close_alts[1]) < 5:
                review_matches.append((rus_full, best_eng, best_score, "close_alts_80"))
                review_table_rows.append((rus_full, best_eng, best_score,
                    f"close alternatives: {scored[1][2]}={scored[1][0]:.0f}"))
                matched_rus.add(rus_full)
                batch.append((best_eng, rus_full, rus_tour, best_score, best_method, 1))
            else:
                confident_matches.append((rus_full, best_eng, best_score, best_method))
                matched_rus.add(rus_full)
                batch.append((best_eng, rus_full, rus_tour, best_score, best_method, 0))
        else:
            # < 80, or initial mismatch (always review even at high scores)
            review_matches.append((rus_full, best_eng, best_score, best_method))
            review_table_rows.append((rus_full, best_eng, best_score, best_method))
            matched_rus.add(rus_full)
            batch.append((best_eng, rus_full, rus_tour, best_score, best_method, 1))

        if len(batch) >= BATCH_SIZE:
            conn.executemany(
                """INSERT OR REPLACE INTO tennis_player_mapping
                   (eng_name, rus_name, tour, confidence, match_method, needs_review)
                   VALUES (?, ?, ?, ?, ?, ?)""", batch)
            conn.commit()
            batch.clear()

    if batch:
        conn.executemany(
            """INSERT OR REPLACE INTO tennis_player_mapping
               (eng_name, rus_name, tour, confidence, match_method, needs_review)
               VALUES (?, ?, ?, ?, ?, ?)""", batch)
        conn.commit()

    if review_table_rows:
        rb = []
        for rus, eng, conf, reason in review_table_rows:
            rb.append((rus, eng, conf, reason))
            if len(rb) >= BATCH_SIZE:
                conn.executemany(
                    """INSERT INTO tennis_player_mapping_review
                       (rus_name, eng_candidate, confidence, reason) VALUES (?, ?, ?, ?)""", rb)
                conn.commit()
                rb = []
        if rb:
            conn.executemany(
                """INSERT INTO tennis_player_mapping_review
                   (rus_name, eng_candidate, confidence, reason) VALUES (?, ?, ?, ?)""", rb)
            conn.commit()

    # ---- Stats ----
    total_confident = len(confident_matches)
    total_review = len(review_matches)
    unmatched = len(rus_names) - len(matched_rus)

    log.info("=" * 60)
    log.info("RESULTS")
    log.info("=" * 60)
    log.info(f"Total English names:    {len(all_eng)}")
    log.info(f"Total Russian names:    {len(rus_names)}")
    log.info(f"Confident matches:      {total_confident}")
    log.info(f"Review matches:         {total_review}")
    log.info(f"Unmatched Russian:      {unmatched}")

    mapping_total = conn.execute("SELECT COUNT(*) FROM tennis_player_mapping").fetchone()[0]
    confident_db = conn.execute("SELECT COUNT(*) FROM tennis_player_mapping WHERE needs_review=0").fetchone()[0]
    review_db = conn.execute("SELECT COUNT(*) FROM tennis_player_mapping WHERE needs_review=1").fetchone()[0]
    review_table_count = conn.execute("SELECT COUNT(*) FROM tennis_player_mapping_review").fetchone()[0]
    log.info(f"DB tennis_player_mapping: {mapping_total} total (confident={confident_db}, review={review_db})")
    log.info(f"DB tennis_player_mapping_review: {review_table_count} rows")

    # Examples
    log.info("\n--- 30 confident matches ---")
    for i, (rus, eng, conf, method) in enumerate(confident_matches[:30]):
        log.info(f"  {i+1:3d}. {rus:40s} -> {eng} ({conf:.0f}, {method})")

    log.info("\n--- 30 review matches ---")
    for i, (rus, eng, conf, reason) in enumerate(review_matches[:30]):
        log.info(f"  {i+1:3d}. {rus:40s} -> {eng} ({conf:.0f}, {reason})")

    log.info("\n--- 30 unmatched Russian names ---")
    unmatched_list = [name for name in rus_names if name not in matched_rus]
    for i, name in enumerate(sorted(unmatched_list)[:30]):
        log.info(f"  {i+1:3d}. {name}")

    log.info("\n--- Sample rows (top 15) ---")
    for row in conn.execute("SELECT * FROM tennis_player_mapping ORDER BY confidence DESC LIMIT 15"):
        log.info(f"  {row}")

    conn.close()

    # Usability statement
    ratio = total_confident / max(len(rus_names), 1) * 100
    log.info("\n" + "=" * 60)
    if ratio >= 35 and total_confident > 200:
        log.info("MAPPING USABILITY: Yes — usable for joining tennis history across sources.")
        log.info(f"  {total_confident} confident matches ({ratio:.0f}% of Russian names).")
        log.info(f"  {total_review} need manual review.")
        log.info(f"  {unmatched} unmatched (rare/low-tier or name-format mismatch).")
        log.info("  Use: SELECT * FROM tennis_player_mapping WHERE needs_review=0")
    else:
        log.info(f"MAPPING USABILITY: Partial ({ratio:.0f}% confident). Manual review needed first.")
    log.info("=" * 60)


if __name__ == "__main__":
    main()
