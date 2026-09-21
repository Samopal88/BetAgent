#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BETAGENT — settler.py

Задача:
- находит в betagent.db ставки со статусом pending
- смотрит match.status, home_score, away_score
- если матч завершён, рассчитывает win/loss
- пишет result, profit
- пишет строку в accuracy_log
- при первом закрытии ставки пишет settled_at

ВАЖНО:
Этот файл НЕ тянет результаты с Фонбета сам.
Он работает, когда в таблице matches уже есть:
- status = 'finished'
- home_score
- away_score

SETTLEMENT PATH (triple-path):
1. Try normalized_results first (canonical winner/score, no fuzzy matching)
2. For tennis: try tennis_live_results (sets format, surname matching)
3. Fall back to results_raw via existing fuzzy matching if not found
4. Log which path was used for each settlement

Запуск:
  python settler.py
"""

import os
import re
import sqlite3
from datetime import datetime, timedelta

DB_PATH = os.getenv("BETAGENT_DB", "betagent.db")


def ensure_settled_at_column(conn: sqlite3.Connection) -> None:
    """
    Безопасно добавляет колонку bets.settled_at, если её ещё нет.
    Это нужно для корректных уведомлений только по реально новым закрытиям.
    """
    cols = [row[1] for row in conn.execute("PRAGMA table_info(bets)").fetchall()]
    if "settled_at" not in cols:
        conn.execute("ALTER TABLE bets ADD COLUMN settled_at TEXT")
        conn.commit()
        print("Добавлена колонка bets.settled_at")


def result_for_market(market: str, home_score: int, away_score: int, sport: str = None):
    # Поддерживаем оба формата: "home"/"away"/"draw" и "home_win"/"away_win"
    if market in ("home", "home_win", "П1"):
        won = home_score > away_score
    elif market in ("draw", "X"):
        won = home_score == away_score
    elif market in ("away", "away_win", "П2"):
        won = away_score > home_score
    elif market in ("btts_yes", "ОЗ да"):
        won = home_score > 0 and away_score > 0
    elif market in ("btts_no", "ОЗ нет"):
        won = home_score == 0 or away_score == 0
    elif market in ("over_2_5", "тб 2.5", "ТБ 2.5"):
        won = (home_score + away_score) > 2
    elif market in ("under_2_5", "тм 2.5", "ТМ 2.5"):
        won = (home_score + away_score) <= 2
    elif market in ("over_1_5", "тб 1.5", "ТБ 1.5"):
        won = (home_score + away_score) > 1
    elif market in ("under_1_5", "тм 1.5", "ТМ 1.5"):
        won = (home_score + away_score) <= 1
    elif market in ("player1_win",):
        won = home_score > away_score
    elif market in ("player2_win",):
        won = away_score > home_score
    else:
        return None
    return "won" if won else "lost"


def _try_normalized_settle(conn, sport, home_team, away_team, match_date, market):
    """
    Try to settle a bet using normalized_results.
    Returns (result, home_score, away_score, source_label) or None.
    """
    try:
        from result_normalization import (
            lookup_normalized_result,
            result_for_market_normalized,
        )
    except ImportError:
        return None

    norm = lookup_normalized_result(
        conn, sport, home_team, away_team,
        str(match_date)[:10], market
    )

    if norm and norm["confidence"] >= 0.8:
        result = result_for_market_normalized(
            market, norm["winner_side"],
            norm["score_p1"], norm["score_p2"],
            norm.get("is_overtime", 0), sport
        )
        if result is not None:
            return (result, norm["score_p1"], norm["score_p2"],
                    f"normalized({norm['source']},conf={norm['confidence']:.1f})")

    return None


def _try_tennis_settle(conn, home_team, away_team, match_date, market):
    """
    Settle tennis bets using tennis_live_results.
    Matches by surname substring in winner_name/loser_name.
    Checks match_date +/- 1 day (match may have completed a day later).
    Returns (result, home_score, away_score, source_label) or None.
    """
    def _surname(name: str) -> str:
        if not name:
            return ""
        parts = name.strip().replace(".", "").split()
        if not parts:
            return ""
        if len(parts) >= 2 and len(parts[-1]) <= 1:
            return parts[0]
        return parts[-1]

    translit_map = str.maketrans({
        "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e",
        "ё": "e", "ж": "zh", "з": "z", "и": "i", "й": "i", "к": "k",
        "л": "l", "м": "m", "н": "n", "о": "o", "п": "p", "р": "r",
        "с": "s", "т": "t", "у": "u", "ф": "f", "х": "h", "ц": "c",
        "ч": "ch", "ш": "sh", "щ": "sh", "ъ": "", "ы": "y", "ь": "",
        "э": "e", "ю": "u", "я": "ia",
    })

    def _latin_key(name: str) -> str:
        value = _surname(name).lower().replace("ё", "е")
        value = value.translate(translit_map)
        value = re.sub(r"[^a-z]", "", value)
        value = value.replace("ou", "u").replace("oo", "u")
        return value

    def _skeleton(name: str) -> str:
        return re.sub(r"[aeiouy]", "", _latin_key(name))

    def _name_tokens(name: str) -> set[str]:
        if not name:
            return set()
        value = name.lower().replace("ё", "е").replace(".", " ")
        value = value.translate(translit_map)
        tokens = re.findall(r"[a-z]+", value)
        return {t for t in tokens if len(t) >= 2}

    def _edit_distance(a: str, b: str) -> int:
        if len(a) > len(b):
            a, b = b, a
        prev = list(range(len(a) + 1))
        for j in range(1, len(b) + 1):
            curr = [j] + [0] * len(a)
            for i in range(1, len(a) + 1):
                curr[i] = min(prev[i] + 1, curr[i - 1] + 1,
                              prev[i - 1] + (0 if a[i - 1] == b[j - 1] else 1))
            prev = curr
        return prev[-1]

    def _same_player(left: str, right: str) -> bool:
        left_key = _latin_key(left)
        right_key = _latin_key(right)
        if left_key and right_key and left_key == right_key:
            return True
        left_skeleton = _skeleton(left)
        right_skeleton = _skeleton(right)
        if left_skeleton and right_skeleton and left_skeleton == right_skeleton:
            return True
        if left_skeleton and right_skeleton and len(left_skeleton) >= 3 and len(right_skeleton) >= 3:
            if _edit_distance(left_skeleton, right_skeleton) <= 1:
                return True
        if left_key and right_key and len(left_key) >= 4 and len(right_key) >= 4:
            if left_key.endswith(right_key) or right_key.endswith(left_key):
                return True
            if _edit_distance(left_key, right_key) <= max(1, min(len(left_key), len(right_key)) // 3):
                return True
        left_tokens = _name_tokens(left)
        right_tokens = _name_tokens(right)
        if left_tokens and right_tokens and left_tokens.intersection(right_tokens):
            return True
        if left_tokens and right_tokens:
            for lt in left_tokens:
                for rt in right_tokens:
                    if len(lt) >= 4 and len(rt) >= 4 and _edit_distance(lt, rt) <= 1:
                        return True
        return False

    s1 = _surname(home_team)
    s2 = _surname(away_team)
    if not s1 or not s2:
        return None

    home_key = _latin_key(home_team)
    away_key = _latin_key(away_team)
    home_skeleton = _skeleton(home_team)
    away_skeleton = _skeleton(away_team)

    try:
        dt = datetime.strptime(str(match_date)[:10], "%Y-%m-%d")
        dates = [
            str(match_date)[:10],
            (dt + timedelta(days=1)).strftime("%Y-%m-%d"),
            (dt - timedelta(days=1)).strftime("%Y-%m-%d"),
            (dt + timedelta(days=2)).strftime("%Y-%m-%d"),
            (dt + timedelta(days=3)).strftime("%Y-%m-%d"),
            (dt - timedelta(days=2)).strftime("%Y-%m-%d"),
        ]
    except Exception:
        dates = [str(match_date)[:10]]

    cancelled_partial = None  # store partial-match cancellation as fallback

    for d in dates:
        rows = conn.execute("""
            SELECT winner_name, loser_name, sets_winner, sets_loser, score_detail
            FROM tennis_live_results
            WHERE match_date = ?
        """, (d,)).fetchall()

        row = None
        for candidate in rows:
            winner_key = _latin_key(candidate[0])
            loser_key = _latin_key(candidate[1])
            winner_skeleton = _skeleton(candidate[0])
            loser_skeleton = _skeleton(candidate[1])

            direct_match = (
                (_same_player(candidate[0], home_team) and _same_player(candidate[1], away_team)) or
                (_same_player(candidate[0], away_team) and _same_player(candidate[1], home_team))
            )
            skeleton_match = (
                (winner_skeleton == home_skeleton and loser_skeleton == away_skeleton) or
                (winner_skeleton == away_skeleton and loser_skeleton == home_skeleton)
            )
            # Compound-surname partial match: "Мерида-Агилар Д" -> "meridaagilar"
            # vs "Даниель Мерида Агилар" -> "agilar". "meridaagilar".endswith("agilar") is True.
            partial_match = (
                len(loser_key) >= 4 and len(away_key) >= 4 and
                (
                    (winner_key == home_key and (away_key.endswith(loser_key) or loser_key.endswith(away_key))) or
                    (winner_key == away_key and (home_key.endswith(loser_key) or loser_key.endswith(home_key)))
                )
            )

            if direct_match or skeleton_match or partial_match:
                row = candidate
                break

            # For cancellations: if at least one player matches, keep as fallback
            score_detail_c = candidate[4] or ""
            if (candidate[2] is None or candidate[3] is None) and "отмен" in score_detail_c.lower():
                one_side_match = (
                    _same_player(candidate[0], home_team) or _same_player(candidate[0], away_team) or
                    _same_player(candidate[1], home_team) or _same_player(candidate[1], away_team)
                )
                if one_side_match and cancelled_partial is None:
                    cancelled_partial = candidate

        if row:
            break
    else:
        if cancelled_partial:
            score_detail_c = cancelled_partial[4] or ""
            return ("cancelled", None, None, f"tennis_live(cancelled={score_detail_c})")
        return None

    winner_name = row[0]
    sets_winner = row[2]  # e.g. 2 (player1 won 2 sets)
    sets_loser = row[3]   # e.g. 0
    score_detail = row[4] or ""

    if sets_winner is None or sets_loser is None:
        if "отмен" in score_detail.lower() or "cancel" in score_detail.lower():
            return ("cancelled", None, None, f"tennis_live(cancelled={score_detail})")
        return None

    # Determine if home_team (player1) won
    if _same_player(winner_name, home_team) or s1.lower() in winner_name.lower():
        home_won = True
    else:
        home_won = False

    # Use sets score as the "score" for result_for_market
    home_score = int(sets_winner) if home_won else int(sets_loser)
    away_score = int(sets_loser) if home_won else int(sets_winner)

    result = result_for_market(market, home_score, away_score, sport="tennis")
    if result is not None:
        return (result, home_score, away_score,
                f"tennis_live(sets={sets_winner}:{sets_loser})")

    return None


def _sync_tennis_signal(conn, bet_id: int, result: str, profit: float, settled_at: str, winner_name: str | None = None) -> None:
    """Keep tennis_signals aligned with the canonical bets row."""
    try:
        conn.execute("""
            UPDATE tennis_signals
            SET status = ?,
                result = ?,
                profit = ?,
                settled_at = COALESCE(settled_at, ?),
                winner_name = COALESCE(?, winner_name)
            WHERE bet_id = ?
        """, (result, result, profit, settled_at, winner_name, bet_id))
    except sqlite3.OperationalError:
        # Older local DBs may not have the stabilized tennis_signals columns.
        return


def settle_bets():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # Гарантируем наличие поля времени закрытия ставки
    ensure_settled_at_column(conn)

    # Синхронизируем matches из results_raw (fallback path).
    # Ищем по дате матча И по дате+1 день — чтобы late-night матчи (23:30+),
    # у которых результат в источнике датирован следующим днём, тоже закрывались.
    cur.execute("""
        UPDATE matches
        SET home_score = (
            SELECT rr.home_score FROM results_raw rr
            WHERE rr.is_finished = 1
              AND (rr.match_date LIKE substr(matches.match_date,1,10) || '%'
                   OR rr.match_date LIKE date(substr(matches.match_date,1,10), '+1 day') || '%')
              AND (rr.home_team = matches.home_team
                   OR matches.home_team LIKE '%' || substr(rr.home_team,1,4) || '%'
                   OR rr.home_team LIKE '%' || substr(matches.home_team,1,4) || '%')
            ORDER BY rr.id DESC LIMIT 1),
            away_score = (
            SELECT rr.away_score FROM results_raw rr
            WHERE rr.is_finished = 1
              AND (rr.match_date LIKE substr(matches.match_date,1,10) || '%'
                   OR rr.match_date LIKE date(substr(matches.match_date,1,10), '+1 day') || '%')
              AND (rr.home_team = matches.home_team
                   OR matches.home_team LIKE '%' || substr(rr.home_team,1,4) || '%'
                   OR rr.home_team LIKE '%' || substr(matches.home_team,1,4) || '%')
            ORDER BY rr.id DESC LIMIT 1),
            status = 'finished'
        WHERE id IN (
            SELECT m.id FROM matches m JOIN bets b ON b.match_id = m.id
            WHERE b.result = 'pending' AND m.status != 'finished'
              AND EXISTS (
                SELECT 1 FROM results_raw rr WHERE rr.is_finished=1
                  AND (rr.match_date LIKE substr(m.match_date,1,10) || '%'
                       OR rr.match_date LIKE date(substr(m.match_date,1,10), '+1 day') || '%')
                  AND (rr.home_team = m.home_team
                       OR m.home_team LIKE '%' || substr(rr.home_team,1,4) || '%'
                       OR rr.home_team LIKE '%' || substr(m.home_team,1,4) || '%')))
    """)
    synced = cur.rowcount
    conn.commit()
    if synced:
        print(f"Синхронизировано матчей: {synced}")

    pending_tennis_total = conn.execute("""
        SELECT COUNT(*)
        FROM bets b
        JOIN matches m ON m.id = b.match_id
        WHERE b.result = 'pending'
          AND m.sport = 'tennis'
    """).fetchone()[0]

    cur.execute("""
        SELECT
            b.id,
            b.match_id,
            b.market,
            b.odds,
            b.stake,
            b.our_probability,
            m.sport,
            m.league,
            m.home_team,
            m.away_team,
            m.home_score,
            m.away_score,
            m.status,
            m.match_date
        FROM bets b
        JOIN matches m ON m.id = b.match_id
        WHERE b.result = 'pending'
          AND (
            (m.status = 'finished'
             AND m.home_score IS NOT NULL
             AND m.away_score IS NOT NULL)
            OR m.sport = 'tennis'
          )
    """)
    rows = cur.fetchall()

    settled = 0
    normalized_count = 0
    tennis_live_count = 0
    raw_count = 0
    tennis_ready = 0
    tennis_settled = 0
    tennis_mapping_failed = 0

    for row in rows:
        (
            bet_id,
            match_id,
            market,
            odds,
            stake,
            our_probability,
            sport,
            league,
            home_team,
            away_team,
            home_score,
            away_score,
            match_status,
            match_date
        ) = row

        if sport == "tennis":
            tennis_ready += 1

        if sport == "tennis":
            # Tennis must be settled against explicit winner/loser while
            # preserving the original player1/player2 order from matches.
            tennis_result = _try_tennis_settle(
                conn, home_team, away_team, match_date, market
            )
            if tennis_result:
                result, home_score, away_score, source_label = tennis_result
                tennis_live_count += 1
                if result != "cancelled":
                    cur.execute("""
                        UPDATE matches
                        SET status = 'finished',
                            home_score = ?,
                            away_score = ?,
                            updated_at = ?
                        WHERE id = ?
                    """, (
                        home_score,
                        away_score,
                        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        match_id,
                    ))
                else:
                    cur.execute("""
                        UPDATE matches
                        SET status = 'cancelled',
                            updated_at = ?
                        WHERE id = ?
                    """, (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), match_id))
            else:
                if home_score is not None and away_score is not None:
                    result = result_for_market(market, home_score, away_score, sport="tennis")
                    if result is None:
                        tennis_mapping_failed += 1
                        continue
                    source_label = "match_score"
                else:
                    tennis_mapping_failed += 1
                    continue
        else:
            # PATH 1: Try normalized_results first for non-tennis sports.
            norm_result = _try_normalized_settle(
                conn, sport, home_team, away_team, match_date, market
            )
            if norm_result:
                result, home_score, away_score, source_label = norm_result
                normalized_count += 1
            else:
            # PATH 3: Fall back to raw results_raw logic
            # Для хоккея берём счёт основного времени из results_raw
                if sport == "hockey":
                    rt = conn.execute("""
                        SELECT home_score, away_score, is_overtime
                        FROM results_raw
                        WHERE is_finished = 1
                          AND instr(home_team, '(') = 0
                          AND instr(away_team, '(') = 0
                          AND (
                            (home_team = ? AND away_team = ?) OR
                            (home_team LIKE ? AND away_team LIKE ?) OR
                            (home_team LIKE ? AND away_team LIKE ?)
                          )
                          AND match_date LIKE ?
                        ORDER BY CASE WHEN source = 'betz.su' THEN 0 ELSE 1 END,
                                 updated_at DESC,
                                 id DESC
                        LIMIT 1
                    """, (
                        home_team,
                        away_team,
                        f"%{home_team.split()[0]}%",
                        f"%{away_team.split()[0]}%",
                        f"%{home_team.split()[0].lower()}%",
                        f"%{away_team.split()[0].lower()}%",
                        str(match_date)[:10] + "%"
                    )).fetchone()

                    if rt:
                        home_score = rt[0]
                        away_score = rt[1]
                        is_overtime = rt[2] if rt[2] is not None else 0

                        # OT/SO матч — в основное время была ничья.
                        # Для рынка X достаточно равного счёта в основное время.
                        if is_overtime and market in ("draw", "X"):
                            home_score = 1
                            away_score = 1

                result = result_for_market(market, home_score, away_score, sport)
                if result is None:
                    continue
                raw_count += 1
                source_label = "raw"

        if result == "won":
            profit = round(stake * (odds - 1), 2)
            actual_result = 1
        elif result == "lost":
            profit = round(-stake, 2)
            actual_result = 0
        elif result == "cancelled":
            profit = 0.0
            actual_result = None
        else:
            continue

        settled_at_now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # ВАЖНО:
        # settled_at заполняем только в момент первого перевода pending -> won/lost.
        # COALESCE защищает от повторной перезаписи, если файл прогонят ещё раз.
        cur.execute("""
            UPDATE bets
            SET result = ?, profit = ?, settled_at = COALESCE(settled_at, ?)
            WHERE id = ?
        """, (result, profit, settled_at_now, bet_id))

        if actual_result is not None:
            cur.execute("""
                INSERT INTO accuracy_log (
                    sport, league, market, predicted_prob, actual_result, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                sport,
                league,
                market,
                our_probability,
                actual_result,
                settled_at_now
            ))

        settled += 1
        if sport == "tennis":
            tennis_settled += 1
            _sync_tennis_signal(conn, bet_id, result, profit, settled_at_now, home_team if home_score and (home_score > (away_score or 0)) else away_team)
        print(f"SETTLED [{source_label}]: {home_team} vs {away_team} | "
              f"{market} -> {result} | profit={profit}")

    conn.commit()
    conn.close()

    print(
        "Tennis settlement | "
        f"pending_total={pending_tennis_total} | ready_with_score={tennis_ready} | "
        f"closed={tennis_settled} | mapping_failed={tennis_mapping_failed}"
    )
    print(f"Done. Settled bets: {settled} "
          f"(normalized={normalized_count}, tennis_live={tennis_live_count}, "
          f"raw_fallback={raw_count})")


if __name__ == "__main__":
    settle_bets()
