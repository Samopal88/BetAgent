#!/usr/bin/env python3
"""Settle pending tennis signals manually using normalized_results table.

Handles the 14 stuck pending tennis signals by matching against normalized_results.
Fixes the NULL sets_winner crash in updater_results.py by using normalized data.
"""
import sys
import sqlite3
import re
from pathlib import Path

DB = Path("/mnt/data/betagent/betagent.db")


def _latin_key(name: str) -> str:
    """Extract comparable latin key from player name."""
    if not name:
        return ""

    # Get surname (last word, or first if last is short initial)
    parts = name.strip().replace(".", "").split()
    if not parts:
        return ""
    if len(parts) >= 2 and len(parts[-1]) <= 3:
        surname = parts[0]
    else:
        surname = parts[-1]

    # Transliteration map
    translit = {
        "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e",
        "ё": "e", "ж": "zh", "з": "z", "и": "i", "й": "i", "к": "k",
        "л": "l", "м": "m", "н": "n", "о": "o", "п": "p", "р": "r",
        "с": "s", "т": "t", "у": "u", "ф": "f", "х": "h", "ц": "c",
        "ч": "ch", "ш": "sh", "щ": "sh", "ъ": "", "ы": "y", "ь": "",
        "э": "e", "ю": "u", "я": "ia",
    }
    value = surname.lower().replace("ё", "е")
    for cyrillic, latin in translit.items():
        value = value.replace(cyrillic, latin)
    value = re.sub(r"[^a-z]", "", value)
    value = value.replace("ou", "u").replace("oo", "u")
    return value


def _skeleton(name: str) -> str:
    """Remove vowels for skeleton matching."""
    return re.sub(r"[aeiouy]", "", _latin_key(name))


def find_result(conn, p1: str, p2: str, match_date: str) -> tuple | None:
    """Find normalized result for a match, returning (winner_name, p1_score, p2_score) or None."""
    key1 = _latin_key(p1)
    key2 = _latin_key(p2)
    skel1 = _skeleton(p1)
    skel2 = _skeleton(p2)

    # Filter to within 3 days of match date
    rows = conn.execute("""
        SELECT participant_1, participant_2, winner_name, score_p1, score_p2
        FROM normalized_results
        WHERE sport = 'tennis'
          AND match_date BETWEEN date(?, '-3 days') AND date(?, '+3 days')
    """, (match_date, match_date)).fetchall()

    for row in rows:
        p1_r = row["participant_1"]
        p2_r = row["participant_2"]
        winner = row["winner_name"]

        k1 = _latin_key(p1_r)
        k2 = _latin_key(p2_r)
        s1 = _skeleton(p1_r)
        s2 = _skeleton(p2_r)

        direct = (k1 == key1 and k2 == key2) or (k1 == key2 and k2 == key1)
        skeleton = (s1 == skel1 and s2 == skel2) or (s1 == skel2 and s2 == skel1)
        partial = (
            len(k2) >= 4 and len(key2) >= 4 and
            (
                (k1 == key1 and (key2.endswith(k2) or k2.endswith(key2))) or
                (k2 == key1 and (key1.endswith(k2) or k2.endswith(key1))) or
                (k1 == key2 and (key2.endswith(k1) or k1.endswith(key2))) or
                (k2 == key2 and (key1.endswith(k1) or k1.endswith(key1)))
            )
        )

        if direct or skeleton or partial:
            return (winner, row["score_p1"], row["score_p2"])

    return None


def resolve_signal(p1: str, p2: str, market: str, result: tuple | None) -> str:
    """
    Determine if a bet won or lost.

    market: 'player1_win' or 'player2_win'
    result: (winner_name, score_p1, score_p2) or None
    """
    if result is None:
        return "lost"  # No result found → assume lost

    winner = result[0]
    winner_key = _latin_key(winner)

    if market == "player1_win":
        pick_key = _latin_key(p1)
    elif market == "player2_win":
        pick_key = _latin_key(p2)
    else:
        return "lost"

    # Direct or skeleton match of winner against pick
    if winner_key == pick_key or _skeleton(winner) == _skeleton(p1) or _skeleton(winner) == _skeleton(p2):
        return "won"

    return "lost"


def settle_signal(conn, signal_id: int, p1: str, p2: str, market: str,
                  odds_p1: float, odds_p2: float, match_date: str, dry_run: bool = False):
    """Settle a single tennis signal."""
    result = find_result(conn, p1, p2, match_date)
    outcome = resolve_signal(p1, p2, market, result)

    # Calculate profit
    if outcome == "won":
        if market == "player1_win":
            profit = odds_p1 - 1.0
        else:
            profit = odds_p2 - 1.0
    else:
        profit = -1.0

    print(f"  Signal {signal_id}: {p1} vs {p2} ({match_date}) | market={market}")
    print(f"    Result found: {result}")
    print(f"    → {outcome.upper()} (profit: {profit:+.4f})")

    if not dry_run:
        conn.execute("""
            UPDATE tennis_signals
            SET status = 'settled',
                result = ?,
                profit = ?,
                settled_at = datetime('now')
            WHERE id = ?
        """, (outcome, profit, signal_id))

    return outcome, profit


def settle_bet(conn, signal_id: int, market: str, odds: float, stake: float,
               outcome: str, dry_run: bool = False):
    """Settle the corresponding bet in bets table."""
    bet_rows = conn.execute("""
        SELECT id, stake FROM bets
        WHERE bet_id = ? AND result = 'pending'
    """, (signal_id,)).fetchall()

    for bet in bet_rows:
        if outcome == "won":
            profit = stake * (odds - 1.0)
        else:
            profit = -stake

        print(f"    Bet {bet['id']}: stake={stake:.2f} odds={odds} → {outcome.upper()} profit={profit:+.2f}")

        if not dry_run:
            conn.execute("""
                UPDATE bets
                SET result = ?,
                    profit = ?,
                    settled_at = datetime('now')
                WHERE id = ?
            """, (outcome, profit, bet["id"]))


def main():
    dry_run = "--dry-run" in sys.argv

    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row

    pending = conn.execute("""
        SELECT id, player1, player2, match_date, market,
               odds_p1, odds_p2, status
        FROM tennis_signals
        WHERE status = 'pending'
        ORDER BY match_date DESC
    """).fetchall()

    print(f"Found {len(pending)} pending tennis signals")
    print(f"Mode: {'DRY RUN' if dry_run else 'LIVE'}\n")

    stats = {"won": 0, "lost": 0, "future": 0, "skipped": 0}
    total_profit = 0.0

    for s in pending:
        print(f"\n{'='*60}")
        # Skip future matches
        if s["match_date"] > "2026-05-10":
            print(f"  Signal {s['id']}: {s['player1']} vs {s['player2']} ({s['match_date']}) → FUTURE (skip)")
            stats["future"] += 1
            continue

        outcome, profit = settle_signal(
            conn, s["id"], s["player1"], s["player2"],
            s["market"], s["odds_p1"], s["odds_p2"], s["match_date"], dry_run
        )
        stats[outcome] += 1
        total_profit += profit

        # Settle corresponding bet
        if s["odds_p1"] > 0:
            stake = conn.execute(
                "SELECT stake FROM bets WHERE bet_id = ? AND result = 'pending' LIMIT 1",
                (s["id"],)
            ).fetchone()
            if stake:
                settle_bet(conn, s["id"], s["market"],
                          s["odds_p1"] if s["market"] == "player1_win" else s["odds_p2"],
                          stake["stake"], outcome, dry_run)

    if not dry_run:
        conn.commit()

    print(f"\n{'='*60}")
    print(f"Summary: {stats}")
    print(f"Total profit (per unit): {total_profit:+.4f}")
    if not dry_run:
        print("COMMITTED to database.")
    else:
        print("Dry run — no changes made.")


if __name__ == "__main__":
    main()
