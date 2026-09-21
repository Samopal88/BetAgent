#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Rule Coverage Diagnostic — analyzes why get_pruned_live_rule() produces so few signals.
Tests every active rule against current matches in the DB, tracking funnel drop-off.
"""
import sqlite3, json, sys, os
from datetime import datetime, timedelta
from pathlib import Path

DB_PATH = Path(os.getenv("BETAGENT_DB", "/root/betagent/betagent.db"))

def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

# ============================================================
# Replicate the exact logic from get_pruned_live_rule()
# ============================================================

def normalize_league(league):
    m = {
        "SA": "Италия. Серия А", "BL1": "Германия. Бундеслига",
        "FL1": "Франция. Лига 1", "EPL": "Англия. Премьер-Лига",
        "PD": "Испания. Примера дивизион", "DNK": "Дания. Суперлига",
        "SWE": "Швеция. Аллсвенскан", "FIN": "Финляндия. Вейккаусліга",
        "NOR": "Норвегия. Элитесериен", "IRL": "Ирландия. Премьер-лига",
    }
    return m.get(league, league)

def is_serie_a(l): return "серия а" in l or "serie a" in l or l == "sa"
def is_bundesliga(l): return "бундеслига" in l or "bundesliga" in l or l == "bl1"
def is_ligue1(l): return "лига 1" in l or "ligue 1" in l or l == "fl1"
def is_epl(l): return ("англия" in l and "премьер" in l) or "premier league" in l or l == "epl" or l == "pl"
def is_pd(l): return "примера" in l or "primera" in l or "laliga" in l or "la liga" in l or l == "pd" or l == "sp1"
def is_rpl(l): return "россия" in l or l == "rpl" or l == "r1" or "rpl" in l
def is_fl1(l): return "франц" in l or "ligue" in l or l == "fl1" or l == "f1"
def is_nla(l): return "швейцар" in l or "national league" in l or l == "nla"
def is_mls(l): return "сша" in l or "mls" in l

def detect_league_key(league):
    l = league.lower()
    if any(x in l for x in ["сша", "mls"]): return "MLS"
    if any(x in l for x in ["англия", "premier league", "epl", "pl"]): return "EPL"
    if any(x in l for x in ["германия", "бундеслига", "bundesliga", "bl1"]): return "BUNDESLIGA"
    if any(x in l for x in ["италия", "серия а", "serie a", "sa"]): return "SERIE_A"
    if any(x in l for x in ["испания", "примера", "laliga", "la liga", "pd"]): return "LALIGA"
    if any(x in l for x in ["франция", "лига 1", "ligue 1", "fl1"]): return "LIGUE_1"
    if any(x in l for x in ["швейцар", "national league", "nla"]): return "NLA"
    if any(x in l for x in ["россия", "rpl", "r1"]): return "RPL"
    if any(x in l for x in ["дания", "dansk", "dnk"]): return "DNK"
    if any(x in l for x in ["швеция. премьер", "швеция. аллсвен", "allsvenskan", "swe"]): return "SWE"
    if any(x in l for x in ["норвегия. суперлига", "eliteserien", "nor"]): return "NOR"
    if any(x in l for x in ["финляндия. суперлига", "вейккаус", "veikkausliiga", "fin"]): return "FIN"
    if any(x in l for x in ["ирландия. премьер", "irl"]): return "IRL"
    return None

SUMMER_TEAMS = {
    "DNK": ["Виборг", "Оденсе", "Норшелланн"],
    "SWE": ["Хеккен"],
    "FIN": ["СИК", "Хака"],
}

MLS_HOME_TEAMS = [
    "интер майами", "портленд тимберс", "фк торонто", "торонто фк",
    "атланта юнайтед", "орландо сити", "нэшвилл",
    "лос-анджелес гэлакси", "лос-анджелес гэлэкси",
    "сан-хосе эртквейкс", "сан-хосе"
]

SA_AWAY_TEAMS = {'Empoli', 'Genoa', 'Cremonese', 'Salernitana', 'Venezia'}

def eval_rule(rule_name, m, f):
    """Evaluate a single rule against match + facts. Returns (passed, fail_reason)."""
    league = normalize_league(m["league"]).lower()
    home_pos = f.get("home_position")
    away_pos = f.get("away_position")
    home_scored = f.get("home_goals_scored_avg")
    away_scored = f.get("away_goals_scored_avg")
    home_allowed = f.get("home_goals_allowed_avg")
    away_allowed = f.get("away_goals_allowed_avg")
    home_form = json.loads(f["home_form"]) if f.get("home_form") else []
    away_form = json.loads(f["away_form"]) if f.get("away_form") else []
    home_form_pts = sum(3 if x == "W" else (1 if x == "D" else 0) for x in home_form)
    away_form_pts = sum(3 if x == "W" else (1 if x == "D" else 0) for x in away_form)
    _has_home_form = len(home_form) >= 2
    _has_away_form = len(away_form) >= 2

    def table_diff():
        if home_pos is None or away_pos is None: return None
        return abs(int(home_pos) - int(away_pos))
    def pos_gap():
        if home_pos is None or away_pos is None: return None
        return int(away_pos) - int(home_pos)
    def form_gap():
        return home_form_pts - away_form_pts

    # --- DRAW_SA ---
    if rule_name == "DRAW_SA":
        if not is_serie_a(league): return False, "not_serie_a"
        if m["odds_draw"] is None: return False, "no_draw_odds"
        od = float(m["odds_draw"])
        if not (3.0 <= od <= 3.85): return False, f"draw_odds={od:.2f} not in [3.0,3.85]"
        td = table_diff()
        if td is None: return False, "no_table_diff"
        if td > 5: return False, f"table_diff={td}>5"
        if abs(form_gap()) > 3: return False, f"form_gap={abs(form_gap())}>3"
        if any(v is None for v in [home_scored, away_scored, home_allowed, away_allowed]):
            return False, "missing_goals_data"
        if max(float(home_scored), float(away_scored)) > 1.55:
            return False, f"max_scored={max(float(home_scored),float(away_scored)):.2f}>1.55"
        if max(float(home_allowed), float(away_allowed)) > 1.75:
            return False, f"max_allowed={max(float(home_allowed),float(away_allowed)):.2f}>1.75"
        if _has_home_form and home_form_pts > 7:
            return False, f"home_form_pts={home_form_pts}>7"
        return True, "PASS"

    # --- DRAW_BALANCED_LOW_SCORING_SA ---
    if rule_name == "DRAW_BALANCED_LOW_SCORING_SA":
        if not is_serie_a(league): return False, "not_serie_a"
        if m["odds_draw"] is None: return False, "no_draw_odds"
        od = float(m["odds_draw"])
        if not (3.0 <= od <= 3.6): return False, f"draw_odds={od:.2f} not in [3.0,3.6]"
        td = table_diff()
        if td is None: return False, "no_table_diff"
        if td > 6: return False, f"table_diff={td}>6"
        if abs(form_gap()) > 3: return False, f"form_gap={abs(form_gap())}>3"
        if any(v is None for v in [home_scored, away_scored, home_allowed, away_allowed]):
            return False, "missing_goals_data"
        if max(float(home_scored), float(away_scored)) > 1.55:
            return False, f"max_scored={max(float(home_scored),float(away_scored)):.2f}>1.55"
        if max(float(home_allowed), float(away_allowed)) > 1.65:
            return False, f"max_allowed={max(float(home_allowed),float(away_allowed)):.2f}>1.65"
        return True, "PASS"

    # --- DRAW_BALANCED_LINE_SA ---
    if rule_name == "DRAW_BALANCED_LINE_SA":
        if not is_serie_a(league): return False, "not_serie_a"
        if m["odds_draw"] is None: return False, "no_draw_odds"
        od = float(m["odds_draw"])
        if not (3.05 <= od <= 3.65): return False, f"draw_odds={od:.2f} not in [3.05,3.65]"
        if m["odds_home"] is None or m["odds_away"] is None:
            return False, "no_home_or_away_odds"
        oh, oa = float(m["odds_home"]), float(m["odds_away"])
        if abs(oh - oa) > 0.95: return False, f"odds_gap={abs(oh-oa):.2f}>0.95"
        if min(oh, oa) < 2.0: return False, f"min_odds={min(oh,oa):.2f}<2.0"
        td = table_diff()
        if td is None: return False, "no_table_diff"
        if td > 5: return False, f"table_diff={td}>5"
        if abs(form_gap()) > 4: return False, f"form_gap={abs(form_gap())}>4"
        return True, "PASS"

    # --- SA_AWAY_DRAW ---
    if rule_name == "SA_AWAY_DRAW":
        if not is_serie_a(league): return False, "not_serie_a"
        if m["odds_draw"] is None: return False, "no_draw_odds"
        away = m["away_team"] or ""
        if away not in SA_AWAY_TEAMS: return False, f"away={away} not in {SA_AWAY_TEAMS}"
        od = float(m["odds_draw"])
        if not ((3.0 <= od <= 3.15) or (3.45 <= od <= 4.6)):
            return False, f"draw_odds={od:.2f} not in bimodal"
        if m["odds_under_2_5"] is None: return False, "no_under_2_5_odds"
        if float(m["odds_under_2_5"]) > 2.0: return False, f"under_2_5={float(m['odds_under_2_5']):.2f}>2.0"
        # Historical form check skipped for live (needs DB lookup)
        return True, "PASS"

    # --- AWAY_SA_STRICT_PLUS ---
    if rule_name == "AWAY_SA_STRICT_PLUS":
        if not is_serie_a(league): return False, "not_serie_a"
        if m["odds_away"] is None: return False, "no_away_odds"
        oa = float(m["odds_away"])
        if not (2.05 <= oa <= 2.85): return False, f"away_odds={oa:.2f} not in [2.05,2.85]"
        pg = pos_gap()
        if pg is None: return False, "no_pos_gap"
        if pg > -4: return False, f"pos_gap={pg}>-4"
        if (away_form_pts - home_form_pts) < 4:
            return False, f"form_diff={away_form_pts-home_form_pts}<4"
        if home_allowed is None or away_scored is None:
            return False, "missing_goals_data"
        if float(home_allowed) < 1.30: return False, f"home_allowed={float(home_allowed):.2f}<1.30"
        if float(away_scored) < 1.25: return False, f"away_scored={float(away_scored):.2f}<1.25"
        return True, "PASS"

    # --- BTTS_YES_CORE ---
    if rule_name == "BTTS_YES_CORE":
        if m["odds_btts_yes"] is None: return False, "no_btts_odds"
        btts = float(m["odds_btts_yes"])
        btts_min = 2.00 if is_epl(league) else 1.95
        btts_max = 2.10
        if not (btts_min <= btts <= btts_max):
            return False, f"btts_odds={btts:.2f} not in [{btts_min},{btts_max}]"
        if not (is_bundesliga(league) or is_epl(league)):
            return False, f"not_epl_or_bl1 (league={league})"
        # form stats - fallback to season averages
        hs = float(home_scored) if home_scored is not None else 0
        aws = float(away_scored) if away_scored is not None else 0
        ha = float(home_allowed) if home_allowed is not None else 0
        awa = float(away_allowed) if away_allowed is not None else 0
        if hs < 1.0: return False, f"home_scored={hs:.2f}<1.0"
        if aws < 1.0: return False, f"away_scored={aws:.2f}<1.0"
        if ha < 0.8: return False, f"home_allowed={ha:.2f}<0.8"
        if awa < 0.8: return False, f"away_allowed={awa:.2f}<0.8"
        return True, "PASS"

    # --- RPL_OVER25_BTTS ---
    if rule_name == "RPL_OVER25_BTTS":
        if not is_rpl(league): return False, "not_rpl"
        if m["odds_over_2_5"] is None: return False, "no_over_2_5_odds"
        if m["odds_btts_yes"] is None: return False, "no_btts_odds"
        o25 = float(m["odds_over_2_5"])
        btts = float(m["odds_btts_yes"])
        if not (1.8 <= o25 <= 2.1): return False, f"over25={o25:.2f} not in [1.8,2.1]"
        if not (1.8 <= btts <= 2.1): return False, f"btts={btts:.2f} not in [1.8,2.1]"
        if _has_home_form and _has_away_form:
            if home_form_pts < 4 or away_form_pts < 4:
                return False, f"form_pts home={home_form_pts}/away={away_form_pts}<4"
        return True, "PASS"

    # --- PD_BTTS_DOUBLE ---
    if rule_name == "PD_BTTS_DOUBLE":
        if not is_pd(league): return False, "not_pd"
        if m["odds_over_2_5"] is None: return False, "no_over_2_5_odds"
        if m["odds_btts_yes"] is None: return False, "no_btts_odds"
        o25 = float(m["odds_over_2_5"])
        btts = float(m["odds_btts_yes"])
        if not (1.6 <= o25 <= 1.9): return False, f"over25={o25:.2f} not in [1.6,1.9]"
        if not (1.75 <= btts <= 1.95): return False, f"btts={btts:.2f} not in [1.75,1.95]"
        if _has_away_form and away_form_pts < 6:
            return False, f"away_form_pts={away_form_pts}<6"
        return True, "PASS"

    # --- FL1_BTTS_DOUBLE ---
    if rule_name == "FL1_BTTS_DOUBLE":
        if not is_fl1(league): return False, "not_fl1"
        if m["odds_over_2_5"] is None: return False, "no_over_2_5_odds"
        if m["odds_btts_yes"] is None: return False, "no_btts_odds"
        o25 = float(m["odds_over_2_5"])
        btts = float(m["odds_btts_yes"])
        if not (1.6 <= o25 <= 1.9): return False, f"over25={o25:.2f} not in [1.6,1.9]"
        if not (2.0 <= btts <= 2.1): return False, f"btts={btts:.2f} not in [2.0,2.1]"
        if _has_away_form and away_form_pts < 6:
            return False, f"away_form_pts={away_form_pts}<6"
        return True, "PASS"

    # --- NLA_BERN_AWAY_DRAW ---
    if rule_name == "NLA_BERN_AWAY_DRAW":
        if not is_nla(league): return False, "not_nla"
        away = (m["away_team"] or "").lower()
        if "берн" not in away: return False, f"away={m['away_team']} not берн"
        if m["odds_draw"] is None: return False, "no_draw_odds"
        od = float(m["odds_draw"])
        if not (4.0 <= od <= 5.2): return False, f"draw_odds={od:.2f} not in [4.0,5.2]"
        return True, "PASS"

    # --- MLS_BTTS_HOME ---
    if rule_name == "MLS_BTTS_HOME":
        if not is_mls(league): return False, "not_mls"
        if m["odds_btts_yes"] is None: return False, "no_btts_odds"
        btts = float(m["odds_btts_yes"])
        home = (m["home_team"] or "").lower()
        if not any(t in home for t in MLS_HOME_TEAMS):
            return False, f"home={m['home_team']} not in MLS list"
        if not (1.50 <= btts <= 1.75): return False, f"btts={btts:.2f} not in [1.50,1.75]"
        return True, "PASS"

    # --- PD_AWAY_VALUE ---
    if rule_name == "PD_AWAY_VALUE":
        if not is_pd(league): return False, "not_pd"
        if m["odds_away"] is None: return False, "no_away_odds"
        oa = float(m["odds_away"])
        if not (2.00 <= oa <= 2.50): return False, f"away_odds={oa:.2f} not in [2.00,2.50]"
        away = (m["away_team"] or "").lower()
        if any(t in away for t in ("сельта", "селта", "celta", "жирон", "giron", "валенс", "valenc")):
            return False, f"away={m['away_team']} excluded"
        return True, "PASS"

    # --- SUMMER_BTTS_HOME ---
    if rule_name == "SUMMER_BTTS_HOME":
        slk = detect_league_key(league)
        if slk not in SUMMER_TEAMS: return False, f"league_key={slk} not in summer"
        home = m["home_team"] or ""
        if not any(t in home for t in SUMMER_TEAMS[slk]):
            return False, f"home={home} not in summer list"
        if m["odds_btts_yes"] is None: return False, "no_btts_odds"
        btts = float(m["odds_btts_yes"])
        if not (1.55 <= btts <= 1.85): return False, f"btts={btts:.2f} not in [1.55,1.85]"
        # month check
        try:
            md = int(str(m["match_date"] or "")[:7].split("-")[1])
        except:
            md = 0
        if not (4 <= md <= 11): return False, f"month={md} not in [4,11]"
        return True, "PASS"

    return False, "unknown_rule"


ACTIVE_RULES = [
    "DRAW_SA", "DRAW_BALANCED_LOW_SCORING_SA", "DRAW_BALANCED_LINE_SA",
    "SA_AWAY_DRAW", "AWAY_SA_STRICT_PLUS",
    "BTTS_YES_CORE", "RPL_OVER25_BTTS", "PD_BTTS_DOUBLE", "FL1_BTTS_DOUBLE",
    "NLA_BERN_AWAY_DRAW", "MLS_BTTS_HOME", "PD_AWAY_VALUE", "SUMMER_BTTS_HOME",
]

RULE_LEAGUES = {
    "DRAW_SA": ["Италия. Серия А"],
    "DRAW_BALANCED_LOW_SCORING_SA": ["Италия. Серия А"],
    "DRAW_BALANCED_LINE_SA": ["Италия. Серия А"],
    "SA_AWAY_DRAW": ["Италия. Серия А"],
    "AWAY_SA_STRICT_PLUS": ["Италия. Серия А"],
    "BTTS_YES_CORE": ["Англия. Премьер-Лига", "Германия. Бундеслига"],
    "RPL_OVER25_BTTS": ["Россия. Премьер-Лига"],
    "PD_BTTS_DOUBLE": ["Испания. Примера дивизион"],
    "FL1_BTTS_DOUBLE": ["Франция. Лига 1"],
    "NLA_BERN_AWAY_DRAW": ["Швейцария"],
    "MLS_BTTS_HOME": ["США. MLS"],
    "PD_AWAY_VALUE": ["Испания. Примера дивизион"],
    "SUMMER_BTTS_HOME": ["Дания", "Швеция", "Финляндия", "Норвегия", "Ирландия"],
}


def run_diagnostic():
    conn = get_conn()

    # Get all football matches
    matches = conn.execute("""
        SELECT m.*, f.home_form, f.away_form, f.home_position, f.away_position,
               f.home_goals_scored_avg, f.away_goals_scored_avg,
               f.home_goals_allowed_avg, f.away_goals_allowed_avg,
               f.lineup_data_available, f.h2h_summary, f.notes
        FROM matches m
        LEFT JOIN match_facts f ON f.match_id = m.id
        WHERE m.sport = 'football'
        ORDER BY m.match_date
    """).fetchall()

    total_matches = len(matches)
    print(f"Total football matches in DB: {total_matches}")

    # ============================================================
    # 1. FUNNEL PER RULE
    # ============================================================
    funnel = {}
    for rule in ACTIVE_RULES:
        leagues = RULE_LEAGUES[rule]
        # Step 1: matches in target leagues
        league_matches = [m for m in matches if any(l.lower() in (m["league"] or "").lower() for l in leagues)]

        # Step 2: matches with required odds present
        has_odds = []
        for m in league_matches:
            if rule in ("DRAW_SA", "DRAW_BALANCED_LOW_SCORING_SA", "DRAW_BALANCED_LINE_SA",
                        "SA_AWAY_DRAW", "NLA_BERN_AWAY_DRAW"):
                if m["odds_draw"] is not None: has_odds.append(m)
            elif rule in ("BTTS_YES_CORE", "MLS_BTTS_HOME", "SUMMER_BTTS_HOME"):
                if m["odds_btts_yes"] is not None: has_odds.append(m)
            elif rule in ("RPL_OVER25_BTTS", "PD_BTTS_DOUBLE", "FL1_BTTS_DOUBLE"):
                if m["odds_over_2_5"] is not None and m["odds_btts_yes"] is not None: has_odds.append(m)
            elif rule in ("AWAY_SA_STRICT_PLUS", "PD_AWAY_VALUE"):
                if m["odds_away"] is not None: has_odds.append(m)
            else:
                has_odds.append(m)

        # Step 3: matches passing odds ranges
        odds_range_pass = []
        odds_range_fails = {}
        for m in has_odds:
            facts = dict(m)
            passed, reason = eval_rule(rule, m, facts)
            if passed:
                odds_range_pass.append(m)
            else:
                odds_range_fails[reason] = odds_range_fails.get(reason, 0) + 1

        funnel[rule] = {
            "total_matches": total_matches,
            "league_matches": len(league_matches),
            "has_odds_count": len(has_odds),
            "has_odds_list": has_odds,
            "passed_all": len(odds_range_pass),
            "odds_range_fails": odds_range_fails,
            "passed_matches": odds_range_pass,
        }

    # ============================================================
    # 2. LOW-DATA STRATEGIES ANALYSIS (last 7 days)
    # ============================================================
    low_data_rules = ["SUMMER_BTTS_HOME", "MLS_BTTS_HOME", "PD_AWAY_VALUE", "NLA_BERN_AWAY_DRAW"]
    low_data_analysis = {}

    for rule in low_data_rules:
        leagues = RULE_LEAGUES[rule]
        rule_matches = [m for m in matches if any(l.lower() in (m["league"] or "").lower() for l in leagues)]

        fail_reasons = {}
        for m in rule_matches:
            facts = dict(m)
            passed, reason = eval_rule(rule, m, facts)
            if not passed:
                fail_reasons[reason] = fail_reasons.get(reason, 0) + 1

        low_data_analysis[rule] = {
            "total_in_league": len(rule_matches),
            "passed": len([m for m in rule_matches if eval_rule(rule, m, dict(m))[0]]),
            "fail_reasons": dict(sorted(fail_reasons.items(), key=lambda x: -x[1])),
        }

    # ============================================================
    # 3. 10 NEAREST MATCHES - detailed breakdown
    # ============================================================
    nearest = matches[:10]
    nearest_breakdown = []

    for m in nearest:
        facts = dict(m)
        match_info = {
            "home": m["home_team"],
            "away": m["away_team"],
            "league": m["league"],
            "date": m["match_date"],
            "odds": {
                "home": m["odds_home"], "draw": m["odds_draw"], "away": m["odds_away"],
                "over_2_5": m["odds_over_2_5"], "btts_yes": m["odds_btts_yes"],
                "under_2_5": m["odds_under_2_5"],
            }
        }

        rule_results = {}
        for rule in ACTIVE_RULES:
            passed, reason = eval_rule(rule, m, facts)
            rule_results[rule] = {"passed": passed, "fail_reason": reason}

        nearest_breakdown.append({**match_info, "rules": rule_results})

    # ============================================================
    # 4. BOTTLENECK ANALYSIS
    # ============================================================
    bottlenecks = {}
    for rule in ACTIVE_RULES:
        f = funnel[rule]
        if f["league_matches"] == 0:
            bottlenecks[rule] = "NO_MATCHES_IN_LEAGUE"
        elif f["has_odds_count"] == 0:
            bottlenecks[rule] = "NO_ODDS_DATA"
        elif f["passed_all"] == 0:
            top_fails = sorted(f["odds_range_fails"].items(), key=lambda x: -x[1])[:3]
            bottlenecks[rule] = [f"{r}: {c}" for r, c in top_fails]
        else:
            bottlenecks[rule] = f"OK ({f['passed_all']} matches)"

    # ============================================================
    # 5. SAFE EXPANSION ANALYSIS
    # ============================================================
    # For each rule, test relaxed thresholds
    expansions = {}
    for rule in ACTIVE_RULES:
        f = funnel[rule]
        if f["passed_all"] > 0:
            continue  # already has matches, skip

        # Try relaxed versions
        relaxed_count = 0
        for m in f["has_odds_list"]:
            facts = dict(m)
            # Test specific relaxations per rule
            if rule == "DRAW_SA":
                # Relax: table_diff <= 8, goals <= 1.75, conceded <= 2.0
                league = normalize_league(m["league"]).lower()
                if not is_serie_a(league): continue
                if m["odds_draw"] is None: continue
                od = float(m["odds_draw"])
                if not (3.0 <= od <= 3.85): continue
                home_pos = facts.get("home_position")
                away_pos = facts.get("away_position")
                if home_pos is None or away_pos is None: continue
                td = abs(int(home_pos) - int(away_pos))
                if td > 8: continue
                hs = facts.get("home_goals_scored_avg")
                aws = facts.get("away_goals_scored_avg")
                ha = facts.get("home_goals_allowed_avg")
                awa = facts.get("away_goals_allowed_avg")
                if any(v is None for v in [hs, aws, ha, awa]): continue
                if max(float(hs), float(aws)) <= 1.75 and max(float(ha), float(awa)) <= 2.0:
                    relaxed_count += 1

            elif rule == "DRAW_BALANCED_LOW_SCORING_SA":
                league = normalize_league(m["league"]).lower()
                if not is_serie_a(league): continue
                if m["odds_draw"] is None: continue
                od = float(m["odds_draw"])
                if not (3.0 <= od <= 3.6): continue
                home_pos = facts.get("home_position")
                away_pos = facts.get("away_position")
                if home_pos is None or away_pos is None: continue
                td = abs(int(home_pos) - int(away_pos))
                if td > 8: continue
                hs = facts.get("home_goals_scored_avg")
                aws = facts.get("away_goals_scored_avg")
                ha = facts.get("home_goals_allowed_avg")
                awa = facts.get("away_goals_allowed_avg")
                if any(v is None for v in [hs, aws, ha, awa]): continue
                if max(float(hs), float(aws)) <= 1.75 and max(float(ha), float(awa)) <= 1.85:
                    relaxed_count += 1

            elif rule == "BTTS_YES_CORE":
                if m["odds_btts_yes"] is None: continue
                btts = float(m["odds_btts_yes"])
                if not (1.90 <= btts <= 2.15): continue  # relaxed from 1.95-2.10
                hs = facts.get("home_goals_scored_avg")
                aws = facts.get("away_goals_scored_avg")
                ha = facts.get("home_goals_allowed_avg")
                awa = facts.get("away_goals_allowed_avg")
                if hs is not None and aws is not None and ha is not None and awa is not None:
                    if float(hs) >= 0.8 and float(aws) >= 0.8 and float(ha) >= 0.6 and float(awa) >= 0.6:
                        relaxed_count += 1

            elif rule == "RPL_OVER25_BTTS":
                if m["odds_over_2_5"] is None or m["odds_btts_yes"] is None: continue
                o25 = float(m["odds_over_2_5"])
                btts = float(m["odds_btts_yes"])
                if 1.7 <= o25 <= 2.2 and 1.7 <= btts <= 2.2:  # relaxed
                    relaxed_count += 1

            elif rule == "PD_BTTS_DOUBLE":
                if m["odds_over_2_5"] is None or m["odds_btts_yes"] is None: continue
                o25 = float(m["odds_over_2_5"])
                btts = float(m["odds_btts_yes"])
                if 1.5 <= o25 <= 2.0 and 1.70 <= btts <= 2.0:  # relaxed
                    relaxed_count += 1

            elif rule == "FL1_BTTS_DOUBLE":
                if m["odds_over_2_5"] is None or m["odds_btts_yes"] is None: continue
                o25 = float(m["odds_over_2_5"])
                btts = float(m["odds_btts_yes"])
                if 1.5 <= o25 <= 2.0 and 1.95 <= btts <= 2.15:  # relaxed
                    relaxed_count += 1

            elif rule == "AWAY_SA_STRICT_PLUS":
                league = normalize_league(m["league"]).lower()
                if not is_serie_a(league): continue
                if m["odds_away"] is None: continue
                oa = float(m["odds_away"])
                if not (2.00 <= oa <= 3.00): continue  # relaxed
                home_pos = facts.get("home_position")
                away_pos = facts.get("away_position")
                if home_pos is None or away_pos is None: continue
                pg = int(away_pos) - int(home_pos)
                if pg > -2: continue  # relaxed from -4
                ha = facts.get("home_goals_allowed_avg")
                aws = facts.get("away_goals_scored_avg")
                if ha is not None and aws is not None:
                    if float(ha) >= 1.20 and float(aws) >= 1.15:  # relaxed
                        relaxed_count += 1

        expansions[rule] = {
            "current_passed": f["passed_all"],
            "relaxed_would_pass": relaxed_count,
        }

    # ============================================================
    # PRINT RESULTS
    # ============================================================
    print("\n" + "="*80)
    print("RULE COVERAGE DIAGNOSTIC")
    print("="*80)

    print("\n## 1. FUNNEL PER RULE")
    print(f"{'Rule':<35} {'Total':>6} {'League':>7} {'Odds':>5} {'Passed':>7}")
    print("-"*70)
    for rule in ACTIVE_RULES:
        f = funnel[rule]
        print(f"{rule:<35} {f['total_matches']:>6} {f['league_matches']:>7} {f['has_odds_count']:>5} {f['passed_all']:>7}")

    print("\n## 2. LOW-DATA STRATEGIES")
    for rule in low_data_rules:
        a = low_data_analysis[rule]
        print(f"\n### {rule}")
        print(f"  Matches in league: {a['total_in_league']}")
        print(f"  Passed all criteria: {a['passed']}")
        print(f"  Top fail reasons:")
        for reason, count in list(a["fail_reasons"].items())[:5]:
            print(f"    - {reason}: {count}")

    print("\n## 3. 10 NEAREST MATCHES")
    for i, m in enumerate(nearest_breakdown):
        print(f"\n### Match {i+1}: {m['home']} vs {m['away']}")
        print(f"  League: {m['league']} | Date: {m['date']}")
        print(f"  Odds: H={m['odds']['home']} D={m['odds']['draw']} A={m['odds']['away']} O2.5={m['odds']['over_2_5']} BTTS={m['odds']['btts_yes']}")
        for rule in ACTIVE_RULES:
            r = m["rules"][rule]
            status = "PASS" if r["passed"] else f"FAIL ({r['fail_reason']})"
            print(f"  {rule:<35} {status}")

    print("\n## 4. BOTTLENECKS")
    for rule in ACTIVE_RULES:
        b = bottlenecks[rule]
        if isinstance(b, list):
            print(f"  {rule}: {'; '.join(b)}")
        else:
            print(f"  {rule}: {b}")

    print("\n## 5. SAFE EXPANSIONS")
    for rule, e in expansions.items():
        if e["relaxed_would_pass"] > 0:
            print(f"  {rule}: current={e['current_passed']}, relaxed={e['relaxed_would_pass']}")

    # ============================================================
    # Save to JSON for report generation
    # ============================================================
    report_data = {
        "funnel": {k: {kk: vv for kk, vv in v.items() if kk != "passed_matches"} for k, v in funnel.items()},
        "low_data": low_data_analysis,
        "nearest": nearest_breakdown,
        "bottlenecks": bottlenecks,
        "expansions": expansions,
        "total_matches": total_matches,
        "timestamp": datetime.now().isoformat(),
    }

    # Fix typo
    report_data["bottlenecks"] = bottlenecks

    with open("/root/betagent/analysis/rule_coverage_data.json", "w") as f:
        json.dump(report_data, f, ensure_ascii=False, indent=2, default=str)

    print(f"\nData saved to /root/betagent/analysis/rule_coverage_data.json")

if __name__ == "__main__":
    run_diagnostic()
