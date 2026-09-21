# -*- coding: utf-8 -*-
"""
Football rule engine — pruned portfolio.

Extracted from agent_handoff_v7.py (lines 430-762).
No logic changes — identical thresholds, order, and behaviour.

Dependencies:
  - strategies.football: normalize_rule_league_name, detect_football_league_key
  - sqlite3.Connection (optional, for SA_AWAY_DRAW backtest form lookup)
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, Optional, Tuple

from strategies.football import (
    SA_AWAY_TEAMS,
    SUMMER_TEAMS,
    detect_football_league_key,
    normalize_rule_league_name,
)

if TYPE_CHECKING:
    import sqlite3


# ---------------------------------------------------------------------------
# SA_AWAY_DRAW backtest form helper
# ---------------------------------------------------------------------------

def _get_sa_backtest_home_form_pts(
    conn: Optional["sqlite3.Connection"],
    team: str,
    league: str,
    before_date: str,
    min_matches: int = 3,
    n: int = 5,
) -> Optional[int]:
    """Compute home team form points from backtest_matches for SA_AWAY_DRAW in backtest mode.
    Returns sum of points (W=3, D=1, L=0) for the last N home-team matches, or None
    if fewer than min_matches are found (fail-safe: caller should allow the bet)."""
    if conn is None:
        return None
    rows = conn.execute("""
        SELECT CASE WHEN home_score > away_score THEN 3
                    WHEN home_score = away_score THEN 1
                    ELSE 0 END as pts
        FROM backtest_matches
        WHERE home_team = ? AND league = ?
          AND match_date < ? AND home_score IS NOT NULL
        ORDER BY match_date DESC LIMIT ?
    """, (team, league, before_date, n)).fetchall()
    if len(rows) < min_matches:
        return None
    return sum(r[0] for r in rows)


# ---------------------------------------------------------------------------
# get_pruned_live_rule
# ---------------------------------------------------------------------------

def get_pruned_live_rule(
    match: Any,
    facts: Dict[str, Any],
    conn: Optional["sqlite3.Connection"] = None,
) -> Tuple[Optional[str], Optional[str]]:
    """
    Проверяет матч на соответствие правилам из pruned portfolio.
    Возвращает (rule_name, market) или (None, None) если нет совпадений.

    Правила взяты из strategy_portfolio_v3_pruned_walkforward.py:
    1. DRAW_SA -> draw
    2. DRAW_BL1_FL1 -> draw
    3. AWAY_SA -> away
    4. DRAW_BALANCED_LOW_SCORING_SA -> draw
    5. DRAW_BALANCED_LINE_SA -> draw
    6. DRAW_BALANCED_LINE_BL1 -> draw
    7. AWAY_SA_STRICT_PLUS -> away
    8. BTTS_YES_CORE -> btts_yes
    """
    if (match.sport or "").lower() != "football":
        return None, None
    league = normalize_rule_league_name(getattr(match, "league", "")).lower()
    home_pos = facts.get("home_position")
    away_pos = facts.get("away_position")
    home_scored = facts.get("home_goals_scored_avg")
    away_scored = facts.get("away_goals_scored_avg")
    home_allowed = facts.get("home_goals_allowed_avg")
    away_allowed = facts.get("away_goals_allowed_avg")
    home_form = facts.get("form_last_5_home") or []
    away_form = facts.get("form_last_5_away") or []

    # Вычисляем form points для правил
    home_form_pts = sum(3 if x.upper() == "W" else (1 if x.upper() == "D" else 0) for x in home_form)
    away_form_pts = sum(3 if x.upper() == "W" else (1 if x.upper() == "D" else 0) for x in away_form)

    # Флаг наличия формы: считаем значимой только при >= 2 матчей
    _has_home_form = len(home_form) >= 2
    _has_away_form = len(away_form) >= 2

    # League detector closures bound to normalized league name
    def is_serie_a() -> bool:
        return "серия а" in league or "serie a" in league or league == "sa"
    def is_bundesliga() -> bool:
        return "бундеслига" in league or "bundesliga" in league or league == "bl1"
    def is_ligue1() -> bool:
        return "лига 1" in league or "ligue 1" in league or league == "fl1"
    def is_epl() -> bool:
        return ("англия" in league and "премьер" in league) or "premier league" in league or league == "epl" or league == "pl"
    def is_pd() -> bool:
        return "примера" in league or "primera" in league or "laliga" in league or "la liga" in league or league == "pd" or league == "sp1"
    def is_rpl() -> bool:
        return "россия" in league or league == "rpl" or league == "r1" or "rpl" in league
    def is_fl1() -> bool:
        return "франц" in league or "ligue" in league or league == "fl1" or league == "f1"
    def is_nla() -> bool:
        return "швейцар" in league or "national league" in league or league == "nla"
    def is_mls() -> bool:
        return "сша" in league or "mls" in league or league == "mls"

    def table_diff() -> Optional[int]:
        if home_pos is None or away_pos is None:
            return None
        return abs(int(home_pos) - int(away_pos))

    def pos_gap() -> Optional[int]:
        if home_pos is None or away_pos is None:
            return None
        return int(away_pos) - int(home_pos)  # + home better, - away better

    def form_gap() -> int:
        return home_form_pts - away_form_pts  # + home better

    # Calculate average goals scored and conceded in last 5 matches
    def calc_form_stats() -> tuple:
        home_goals = []
        home_conceded = []
        away_goals = []
        away_conceded = []

        # Extract goals from form data if available
        for match_data in facts.get("home_form_details", []):
            if isinstance(match_data, dict) and "goals_for" in match_data and "goals_against" in match_data:
                home_goals.append(match_data["goals_for"])
                home_conceded.append(match_data["goals_against"])

        for match_data in facts.get("away_form_details", []):
            if isinstance(match_data, dict) and "goals_for" in match_data and "goals_against" in match_data:
                away_goals.append(match_data["goals_for"])
                away_conceded.append(match_data["goals_against"])

        # Calculate averages
        form_scored_last5_home = sum(home_goals) / len(home_goals) if home_goals else 0
        form_conceded_last5_home = sum(home_conceded) / len(home_conceded) if home_conceded else 0
        form_scored_last5_away = sum(away_goals) / len(away_goals) if away_goals else 0
        form_conceded_last5_away = sum(away_conceded) / len(away_conceded) if away_conceded else 0

        # Fallback to season averages if form details not available
        if not home_goals and home_scored is not None:
            form_scored_last5_home = float(home_scored)
        if not home_conceded and home_allowed is not None:
            form_conceded_last5_home = float(home_allowed)
        if not away_goals and away_scored is not None:
            form_scored_last5_away = float(away_scored)
        if not away_conceded and away_allowed is not None:
            form_conceded_last5_away = float(away_allowed)

        return (
            form_scored_last5_home,
            form_conceded_last5_home,
            form_scored_last5_away,
            form_conceded_last5_away,
        )

    # 1. DRAW_SA
    if (is_serie_a() and match.odds_draw is not None and
            3.0 <= float(match.odds_draw) <= 3.85):
        td = table_diff()
        if td is not None and td <= 5 and abs(form_gap()) <= 3:
            if all(v is not None for v in [home_scored, away_scored, home_allowed, away_allowed]):
                if (max(float(home_scored), float(away_scored)) <= 1.55 and
                        max(float(home_allowed), float(away_allowed)) <= 1.75):
                    if _has_home_form and home_form_pts > 7:
                        pass  # home team too strong, skip
                    else:
                        return "DRAW_SA", "draw"

    # 2. DRAW_BL1 — DISABLED (ROI -1.36% на полном периоде 2021-2026)
    pass

    # 3. AWAY_SA — DISABLED (ROI -7.82%)
    pass

    # 4. DRAW_BALANCED_LOW_SCORING_SA
    if (is_serie_a() and match.odds_draw is not None and
            3.0 <= float(match.odds_draw) <= 3.6):
        td = table_diff()
        if td is not None and td <= 6 and abs(form_gap()) <= 3:
            if all(v is not None for v in [home_scored, away_scored, home_allowed, away_allowed]):
                if (max(float(home_scored), float(away_scored)) <= 1.55 and
                        max(float(home_allowed), float(away_allowed)) <= 1.65):
                    return "DRAW_BALANCED_LOW_SCORING_SA", "draw"

    # 5. DRAW_BALANCED_LINE_SA
    if (is_serie_a() and match.odds_draw is not None and
            3.05 <= float(match.odds_draw) <= 3.65):
        if (match.odds_home is not None and match.odds_away is not None and
                abs(float(match.odds_home) - float(match.odds_away)) <= 0.95 and
                min(float(match.odds_home), float(match.odds_away)) >= 2.0):
            td = table_diff()
            if td is not None and td <= 5 and abs(form_gap()) <= 4:
                return "DRAW_BALANCED_LINE_SA", "draw"

    # 6. DRAW_BALANCED_LINE_BL1 — DISABLED (ROI -1.43%)
    pass

    # 7. AWAY_SA_STRICT_PLUS
    if (is_serie_a() and match.odds_away is not None and
            2.05 <= float(match.odds_away) <= 2.85):
        pg = pos_gap()
        if pg is not None and pg <= -4:  # away team better in table
            if (away_form_pts - home_form_pts) >= 4:  # away form better
                if home_allowed is not None and away_scored is not None:
                    if float(home_allowed) >= 1.30 and float(away_scored) >= 1.25:
                        return "AWAY_SA_STRICT_PLUS", "away"

    # 8. SA_AWAY_DRAW — ничья когда аутсайдер едет в гости в Серии А
    # Бэктест: ROI +80% после добавления фильтра home_form <= 6pts
    if (is_serie_a() and match.odds_draw is not None and
            match.away_team in SA_AWAY_TEAMS):
        od = float(match.odds_draw)
        if ((3.0 <= od <= 3.15) or (3.45 <= od <= 4.6)):
            if (hasattr(match, "odds_under_2_5") and match.odds_under_2_5 is not None
                    and float(match.odds_under_2_5) <= 2.0):
                sa_home_form_pts = _get_sa_backtest_home_form_pts(
                    conn, match.home_team, "SA", match.match_date)
                if sa_home_form_pts is not None and sa_home_form_pts > 6:
                    pass  # home team too strong, draw unlikely
                else:
                    return "SA_AWAY_DRAW", "draw"

    # 9. BTTS_YES_CORE
    if hasattr(match, "odds_btts_yes") and match.odds_btts_yes is not None:
        btts_odds = float(match.odds_btts_yes)
        # FL1 отключена (BTTS rate 47.6% в 2025)
        # EPL: 1.97-2.15 (5/5 сезонов), BL1: 1.95-2.10
        btts_min = 2.00 if is_epl() else 1.95
        btts_max = 2.10
        if btts_min <= btts_odds <= btts_max:
            if is_bundesliga() or is_epl():  # FL1 disabled
                # Calculate form stats
                (form_scored_last5_home,
                 form_conceded_last5_home,
                 form_scored_last5_away,
                 form_conceded_last5_away) = calc_form_stats()

                # Apply BTTS_YES_CORE rule criteria
                if (form_scored_last5_home >= 1.0 and
                    form_scored_last5_away >= 1.0 and
                    form_conceded_last5_home >= 0.8 and
                    form_conceded_last5_away >= 0.8):
                    return "BTTS_YES_CORE", "btts_yes"

    # 9. RPL_OVER25_BTTS — Over 2.5 с двойным подтверждением в РПЛ
    # Логика: оба рынка (Over2.5 + BTTS) одновременно в «голевом» диапазоне —
    #         двойной сигнал рынка о результативном матче
    # Бэктест: ROI +13.4%, 5/5 сезонов, MaxLS=8, n=178 | тренд 2025: +21% ⬆️
    if is_rpl():
        if (hasattr(match, "odds_over_2_5") and match.odds_over_2_5 is not None and
                hasattr(match, "odds_btts_yes") and match.odds_btts_yes is not None):
            over25 = float(match.odds_over_2_5)
            btts = float(match.odds_btts_yes)
            if 1.8 <= over25 <= 2.1 and 1.8 <= btts <= 2.1:
                if _has_home_form and _has_away_form:
                    if home_form_pts < 4 or away_form_pts < 4:
                        pass  # one of teams in cold form, skip
                    else:
                        return "RPL_OVER25_BTTS", "over_2_5"
                else:
                    return "RPL_OVER25_BTTS", "over_2_5"

    # 10. PD_BTTS_DOUBLE — BTTS с двойным подтверждением в Ла Лиге
    # Логика: низкий Over2.5 (1.6-1.9) + BTTS (1.75-1.95) — рынок согласен
    #         что матч будет голевым, ставим на BTTS как более точный исход
    # Бэктест: ROI +15%, 5/5 сезонов, MaxLS=6, n=201 | тренд 2024-2025: +28%/+19% ⬆️
    if is_pd():
        if (hasattr(match, "odds_over_2_5") and match.odds_over_2_5 is not None and
                hasattr(match, "odds_btts_yes") and match.odds_btts_yes is not None):
            over25 = float(match.odds_over_2_5)
            btts = float(match.odds_btts_yes)
            if 1.6 <= over25 <= 1.9 and 1.75 <= btts <= 1.95:
                if _has_away_form and away_form_pts < 6:
                    pass  # away team not scoring enough
                else:
                    return "PD_BTTS_DOUBLE", "btts_yes"
    # 10b. PD_AWAY_VALUE — La Liga away value at odds 2.00-2.50
    # Бэктест: ROI +14%, 5/6 сезонов positive, n=264 total (~44/year)
    # Avoid: Celta, Girona, Valencia (negative ROI)
    if is_pd():
        if hasattr(match, "odds_away") and match.odds_away is not None:
            away_odds = float(match.odds_away)
            if 2.00 <= away_odds <= 2.50:
                away_name = str(getattr(match, "away_team", "") or "").lower()
                if not any(t in away_name for t in ("сельта", "селта", "celta", "жирон", "giron", "валенс", "valenc")):
                    return "PD_AWAY_VALUE", "away"
    # 11. FL1_BTTS_DOUBLE — BTTS с двойным подтверждением в Лиге 1
    # Бэктест: ROI +17.55%, 5/5 сезонов, MaxLS=4, n=302
    if is_fl1():
        if (hasattr(match, "odds_over_2_5") and match.odds_over_2_5 is not None and
                hasattr(match, "odds_btts_yes") and match.odds_btts_yes is not None):
            over25 = float(match.odds_over_2_5)
            btts = float(match.odds_btts_yes)
            if 1.6 <= over25 <= 1.9 and 2.0 <= btts <= 2.1:
                if _has_away_form and away_form_pts < 6:
                    pass  # away team not scoring enough
                else:
                    return "FL1_BTTS_DOUBLE", "btts_yes"

    # 12. NLA_BERN_AWAY_DRAW — ничья когда Берн играет в гостях
    # Бэктест: ROI +50.39%, 5/5 сезонов, MaxLS=7, n=76
    if is_nla():
        if (hasattr(match, 'away_team') and
                'берн' in str(getattr(match, 'away_team', '')).lower() and
                hasattr(match, 'odds_draw') and match.odds_draw is not None):
            od = float(match.odds_draw)
            if 4.0 <= od <= 5.2:
                return "NLA_BERN_AWAY_DRAW", "draw"

    # 13. MLS_BTTS_HOME — BTTS когда топ-атакующие команды MLS играют дома
    # Бэктест: ROI +11.5%, 6/6 сезонов, MaxLS=5, n=374, winrate=69.3%
    if is_mls():
        if hasattr(match, "odds_btts_yes") and match.odds_btts_yes is not None:
            btts = float(match.odds_btts_yes)
            home = str(getattr(match, "home_team", "") or "").lower()
            _MLS_HOME_TEAMS = [
                "интер майами", "портленд тимберс", "фк торонто", "торонто фк",
                "атланта юнайтед", "орландо сити", "нэшвилл",
                "лос-анджелес гэлакси", "лос-анджелес гэлэкси",
                "сан-хосе эртквейкс", "сан-хосе"
            ]
            if any(t in home for t in _MLS_HOME_TEAMS):
                if 1.50 <= btts <= 1.75:
                    return "MLS_BTTS_HOME", "btts_yes"

    # 14. SUMMER_BTTS_HOME — BTTS когда топ-команды играют дома (летние лиги)
    # Бэктест: ROI +22.8%, 5/5 сезонов, n=203, winrate=73.4%, MaxLS=5
    _slk = detect_football_league_key(league)
    if _slk in SUMMER_TEAMS:
        _sh = getattr(match, "home_team", "") or ""
        _sb = getattr(match, "odds_btts_yes", None)
        _sm = 0
        try:
            _sm = int(str(getattr(match, "match_date", "") or "")[:7].split("-")[1])
        except Exception:
            pass
        if (any(t in _sh for t in SUMMER_TEAMS[_slk]) and
                _sb is not None and 1.55 <= float(_sb) <= 1.85 and
                4 <= _sm <= 11):
            return "SUMMER_BTTS_HOME", "btts_yes"

    # 15. ECU_BTTS_NO — Эквадор Серия А, btts_no при btts_yes коэф 1.90-2.15
    # Бэктест: ROI +32.5%, 7/7 сезонов, MaxLS=2, DD=1.9%, n=84, HR_no=76.2%
    def is_ecu_a() -> bool:
        ll = league.lower()
        return any(x in ll for x in ["эквадор", "ecuador"]) and any(x in ll for x in ["серия а", "serie a"])
    if is_ecu_a():
        if (hasattr(match, "odds_btts_yes") and match.odds_btts_yes is not None and
                hasattr(match, "odds_btts_no") and match.odds_btts_no is not None):
            if 1.90 <= float(match.odds_btts_yes) <= 2.15:
                return "ECU_BTTS_NO", "btts_no"

    return None, None
