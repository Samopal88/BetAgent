#!/usr/bin/env python3
"""Backfill existing pending tennis signals into bets table."""
import sqlite3, sys, os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = str(BASE_DIR / "betagent.db")


def load_name_lookup(conn):
    """Load tennis_name_lookup: Fonbet betz_name -> stable English name."""
    lookup = {}
    for betz_name, eng_name in conn.execute(
        "SELECT betz_name, eng_name FROM tennis_name_lookup"
    ).fetchall():
        lookup[betz_name.strip().lower()] = eng_name.strip().lower()
    return lookup


def load_name_mapping(conn):
    """Load confident (needs_review=0) Russian -> English name mapping."""
    mapping = {}
    for rus, eng in conn.execute(
        "SELECT rus_name, eng_name FROM tennis_player_mapping WHERE needs_review = 0"
    ).fetchall():
        mapping[rus.strip()] = eng.strip()
    return mapping


def canonicalize_name(raw_name, name_map, name_lookup):
    """Resolve any name variant to a stable canonical form."""
    key = raw_name.strip().lower()
    if key in name_lookup:
        return name_lookup[key]
    if key in name_map:
        return name_map[key].lower()
    return key


def normalize_tennis_russian_name(raw_name: str) -> str:
    return " ".join((raw_name or "").strip().lower().replace("ё", "е").replace(".", "").split())


def build_tennis_live_identity(source_match_id, player1, player2, match_date, market):
    source_key = (source_match_id or "").strip()
    if source_key:
        return f"tennis_live:{source_key}:{market}"
    return "tennis_live_fallback:{p1}:{p2}:{date}:{market}".format(
        p1=normalize_tennis_russian_name(player1),
        p2=normalize_tennis_russian_name(player2),
        date=(match_date or "")[:10],
        market=market,
    )


def build_tennis_match_identity(source_match_id, player1, player2, match_date):
    source_key = (source_match_id or "").strip()
    if source_key:
        return f"tennis_live_match:{source_key}"
    return "tennis_live_match_fallback:{p1}:{p2}:{date}".format(
        p1=normalize_tennis_russian_name(player1),
        p2=normalize_tennis_russian_name(player2),
        date=(match_date or "")[:10],
    )


def backfill():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")

    name_map = load_name_mapping(conn)
    name_lookup = load_name_lookup(conn)
    signal_cols = {row[1] for row in conn.execute("PRAGMA table_info(tennis_signals)").fetchall()}
    for col_name, col_type in (
        ("source_match_id", "TEXT"),
        ("live_identity", "TEXT"),
        ("bet_id", "INTEGER"),
        ("signal_key", "TEXT"),
    ):
        if col_name not in signal_cols:
            conn.execute(f"ALTER TABLE tennis_signals ADD COLUMN {col_name} {col_type}")
    conn.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_tennis_signals_signal_key_pending
        ON tennis_signals(signal_key)
        WHERE signal_key IS NOT NULL
          AND TRIM(signal_key) <> ''
          AND COALESCE(NULLIF(TRIM(result), ''), 'pending') = 'pending'
          AND COALESCE(status, 'pending') = 'pending'
    """)
    conn.commit()

    # Get real pending signals that don't already have a linked bet.
    signals = conn.execute("""
        SELECT id, match_date, league, player1, player2, player1_eng, player2_eng,
               surface, odds_p1, odds_p2, market, our_probability, market_probability,
               ev, edge, kelly, kelly_quarter, stake_pct, confidence, signal_type,
               confirmed_facts, source_match_id, live_identity, bet_id, signal_key
        FROM tennis_signals
        WHERE COALESCE(NULLIF(TRIM(result), ''), 'pending') = 'pending'
          AND bet_id IS NULL
    """).fetchall()

    if not signals:
        print("No pending tennis signals to backfill")
        conn.close()
        return

    print(f"Found {len(signals)} pending tennis signals")

    # Get bankroll
    row = conn.execute("SELECT COALESCE(SUM(profit),0) FROM bets WHERE result IN ('won','lost')").fetchone()
    initial = float(os.getenv("BETAGENT_BANK", "100000"))
    bankroll = initial + float(row[0] or 0)
    print(f"Bankroll: {bankroll:.0f} RUB")

    created = 0
    skipped = 0

    for sig in signals:
        (sig_id, match_date, league, p1, p2, p1_eng, p2_eng,
         surface, odds_p1, odds_p2, market, our_prob, market_prob,
         ev, edge, kelly, kelly_q, stake_pct, confidence, signal_type,
         facts, source_match_id, live_identity, bet_id, signal_key) = sig

        live_identity = live_identity or signal_key or build_tennis_live_identity(
            source_match_id, p1, p2, match_date, market
        )
        match_identity = build_tennis_match_identity(source_match_id, p1, p2, match_date)

        # Check if bet already exists
        existing = conn.execute("SELECT id FROM bets WHERE created_by = ?", (live_identity,)).fetchone()
        if existing:
            conn.execute(
                "UPDATE tennis_signals SET bet_id = ?, live_identity = ?, signal_key = ? WHERE id = ?",
                (existing[0], live_identity, live_identity, sig_id),
            )
            skipped += 1
            print(f"  SKIP (already in bets): {p1} vs {p2}")
            continue

        # Create matches entry
        fonbet_id = source_match_id or match_identity
        conn.execute("""
            INSERT OR IGNORE INTO matches (fonbet_id, sport, league, home_team, away_team, match_date)
            VALUES (?, 'tennis', ?, ?, ?, ?)
        """, (fonbet_id, league, p1, p2, match_date))
        match_id = conn.execute("SELECT id FROM matches WHERE fonbet_id = ?", (fonbet_id,)).fetchone()[0]

        stake_amount = round(bankroll * stake_pct, 2)
        odds = odds_p1 if market == "player1_win" else odds_p2

        # Create bets entry
        cursor = conn.execute("""
            INSERT INTO bets (
                match_id, market, odds, our_probability, ev, kelly_quarter,
                stake, stake_pct, result, created_at, signal_type, confidence,
                created_by, edge, model_prob, market_prob
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', datetime('now'), ?, ?,
                      ?, ?, ?, ?)
        """, (
            match_id, market, odds, our_prob, ev, kelly_q,
            stake_amount, stake_pct, signal_type, confidence,
            live_identity, edge, our_prob, market_prob,
        ))
        bet_id = cursor.lastrowid
        conn.execute(
            "UPDATE tennis_signals SET bet_id = ?, live_identity = ?, signal_key = ? WHERE id = ?",
            (bet_id, live_identity, live_identity, sig_id),
        )
        created += 1
        print(f"  BET: {p1} vs {p2} | {market} @ {odds:.2f} | stake={stake_amount:.0f}")

    conn.commit()
    conn.close()
    print(f"\nBackfill complete: {created} created, {skipped} skipped")

if __name__ == "__main__":
    backfill()
