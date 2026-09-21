#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BETAGENT — golden_bet_selector.py
Выбирает 1 ЖБ ставку в день используя ЛЛМ.
"""
import sqlite3, json, os, sys, argparse
from datetime import datetime, date, timedelta
from pathlib import Path

# Загружаем .env
_env_file = Path(__file__).parent / ".env"
if _env_file.exists():
    for _line in _env_file.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())

DB_PATH = Path(os.getenv("BETAGENT_DB", "betagent.db"))
LLM_API_URL = os.getenv("LLM_API_URL", "https://openrouter.ai/api/v1/chat/completions")
LLM_MODEL = os.getenv("LLM_MODEL", "anthropic/claude-3.7-sonnet")
LLM_API_KEY = os.getenv("LLM_API_KEY", "")

# Стратегии с доказанным ROI > 15% (только активные!)
GOLDEN_STRATEGIES = {
    "DRAW_SA": {"roi": 45.3, "min_ev": 0.12},
    "nhl_draw_tight": {"roi": 44.1, "min_ev": 0.08},
    "hockey_underdog_defensive": {"roi": 28.0, "min_ev": 0.06},
    "BTTS_YES_CORE": {"roi": 20.9, "min_ev": 0.12},
    "czech_home_favorite": {"roi": 17.0, "min_ev": 0.06},
    "DRAW_BALANCED_LINE_SA": {"roi": 16.1, "min_ev": 0.12},
    "SA_AWAY_DRAW": {"roi": 64.5, "min_ev": 0.10},
    "FL1_BTTS_DOUBLE": {"roi": 17.1, "min_ev": 0.10},
    "SUMMER_BTTS_HOME": {"roi": 22.8, "min_ev": 0.08},
}

# Отключённые стратегии — не включать в ЖБ
DISABLED_STRATEGIES = {"DRAW_BL1_FL1", "BTTS_FL1"}

def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def get_tomorrow_bets(conn):
    """Берёт все pending ставки на матчи ЗАВТРАШНЕГО дня."""
    tomorrow = (date.today() + timedelta(days=1)).strftime("%Y-%m-%d")
    
    rows = conn.execute("""
        SELECT b.id, b.match_id, b.market, b.market as market_label, b.odds, b.stake,
        b.ev, b.our_probability, b.market_probability,
               m.home_team, m.away_team, m.match_date, m.sport, m.league,
               m.odds_home, m.odds_draw, m.odds_away,
               b.reasons as confirmed_facts, b.rule as strategy_name, b.rule as live_rule_family,
               b.created_at
        FROM bets b
        JOIN matches m ON m.id = b.match_id
        WHERE b.result = 'pending'
        AND DATE(m.match_date) = ?
        AND b.is_golden = 0
        ORDER BY b.ev DESC
    """, (tomorrow,)).fetchall()
    return rows
def get_match_facts(conn, match_id: int) -> dict:
    """Берёт полные данные о матче."""
    facts = {}
    
    # match_facts
    mf = conn.execute("""
        SELECT * FROM match_facts WHERE match_id = ?
    """, (match_id,)).fetchone()
    if mf:
        facts.update(dict(mf))
    
    # standings
    match = conn.execute("SELECT home_team, away_team, league FROM matches WHERE id=?", (match_id,)).fetchone()
    if match:
        for team, role in [(match['home_team'], 'home'), (match['away_team'], 'away')]:
            st = conn.execute("""
                SELECT position, played, wins, draws, losses, goals_for, goals_against, points
                FROM standings WHERE team_name LIKE ? ORDER BY updated_at DESC LIMIT 1
            """, (f"%{team.split()[0]}%",)).fetchone()
            if st:
                facts[f"{role}_standing"] = dict(st)
    
    return facts

def build_llm_prompt(bets: list, facts_map: dict) -> str:
    """Строит промпт для ЛЛМ."""
    
    from datetime import date as _date
    today_str = _date.today().strftime("%d.%m.%Y")
    prompt = f"""You are a sports betting expert. Today is {today_str}. Select ONE best bet of the day.

SELECTION CRITERIA:
1. Clear logic why this bet should win (not just high EV)
2. Statistical edge (team form, table positions)
3. Market inefficiency — bookmaker overpriced the odds
4. Confidence >= 7/10

If NO suitable bet — return verdict "НЕТ ЖБ" with explanation in Russian.

TODAY'S CANDIDATES:
"""
    
    for i, bet in enumerate(bets, 1):
        bet_dict = dict(bet)
        match_id = bet_dict['match_id']
        facts = facts_map.get(match_id, {})
        
        prompt += f"\n--- Кандидат {i} ---\n"
        prompt += f"Матч: {bet_dict['home_team']} — {bet_dict['away_team']}\n"
        prompt += f"Лига: {bet_dict['league']}\n"
        prompt += f"Дата: {bet_dict['match_date']}\n"
        prompt += f"Ставка: {bet_dict['market_label']} @ {bet_dict['odds']}\n"
        prompt += f"EV: +{bet_dict['ev']*100:.1f}%\n"
        prompt += f"Наша вероятность: {bet_dict['our_probability']*100:.1f}% vs рыночная {bet_dict['market_probability']*100:.1f}%\n"
        prompt += f"Стратегия: {bet_dict.get('live_rule_family') or bet_dict.get('strategy_name', 'unknown')}\n"
        
        if bet_dict.get('confirmed_facts'):
            try:
                cf = json.loads(bet_dict['confirmed_facts']) if isinstance(bet_dict['confirmed_facts'], str) else bet_dict['confirmed_facts']
                if cf:
                    prompt += f"Подтверждённые факты: {', '.join(cf[:3])}\n"
            except:
                pass
        
        # Данные о матче
        if facts:
            home_pos = facts.get('home_position')
            away_pos = facts.get('away_position')
            if home_pos and away_pos:
                prompt += f"Позиции: хозяева #{home_pos}, гости #{away_pos}\n"
            
            home_form = facts.get('form_last_5_home', [])
            away_form = facts.get('form_last_5_away', [])
            if home_form:
                prompt += f"Форма хозяев (5 матчей): {home_form}\n"
            if away_form:
                prompt += f"Форма гостей (5 матчей): {away_form}\n"
            
            hg = facts.get('home_goals_scored_avg')
            ag = facts.get('away_goals_scored_avg')
            if hg and ag:
                prompt += f"Голы: хозяева {hg:.2f}/матч, гости {ag:.2f}/матч\n"
    
    prompt += """
YOUR RESPONSE (strict JSON, reasoning in Russian):
{
  "choice": 1,
  "confidence": 8,
  "reasoning": "Объяснение на русском почему эта ставка лучшая (2-3 предложения)",
  "risk_factors": "Что может помешать (на русском)",
  "verdict": "ЖБ" or "НЕТ ЖБ"
}"""
    
    return prompt

def call_llm(prompt: str) -> str:
    """Вызывает LLM через OpenRouter."""
    import urllib.request
    
    payload = json.dumps({
        "model": LLM_MODEL,
        "max_tokens": 600,
        "messages": [{"role": "user", "content": prompt}]
    }).encode()
    
    req = urllib.request.Request(
        LLM_API_URL,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {LLM_API_KEY}",
        }
    )
    
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read())
        return data["choices"][0]["message"]["content"]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--min-ev", type=float, default=0.07)
    args = ap.parse_args()
    
    conn = get_conn()
    
    # Берём ставки дня
    bets = get_tomorrow_bets(conn)
    print(f"Ставок сегодня: {len(bets)}")
    
    if not bets:
        print("Нет ставок для анализа")
        return
    
    # Фильтруем по EV и стратегии
    candidates = []
    for bet in bets:
        ev = bet['ev'] or 0
        bet_d = dict(bet)
        strategy = bet_d.get('live_rule_family') or bet_d.get('strategy_name') or ''
        
        if ev < args.min_ev:
            continue
        
        # Исключаем отключённые стратегии
        if any(s in strategy for s in DISABLED_STRATEGIES):
            continue
        
        # Проверяем стратегию
        strategy_ok = any(s in strategy for s in GOLDEN_STRATEGIES.keys())
        if not strategy_ok and ev < 0.15:
            continue
        
        # Минимальный EV для стратегии
        for s_name, s_cfg in GOLDEN_STRATEGIES.items():
            if s_name in strategy and ev < s_cfg["min_ev"]:
                strategy_ok = False
                break
            
        candidates.append(bet)
    
    print(f"Кандидатов после фильтра: {len(candidates)}")
    
    if not candidates:
        print("Нет кандидатов на ЖБ")
        return
    
    # Собираем факты
    facts_map = {}
    for bet in candidates:
        facts_map[bet['match_id']] = get_match_facts(conn, bet['match_id'])
    
    # Строим промпт
    prompt = build_llm_prompt(candidates, facts_map)
    
    if args.dry_run:
        print("\n--- ПРОМПТ ДЛЯ ЛЛМ ---")
        print(prompt[:2000])
        print("...")
        return
    
    # Вызываем ЛЛМ
    print("\nОтправляем в ЛЛМ...")
    try:
        content = call_llm(prompt)
        
        # Парсим JSON
        import re
        json_match = re.search(r'\{.*\}', content, re.DOTALL)
        if json_match:
            result = json.loads(json_match.group())
            print(f"\n{'='*50}")
            print(f"РЕЗУЛЬТАТ ЖБ АНАЛИЗА")
            print(f"{'='*50}")
            print(f"Вердикт: {result.get('verdict')}")
            print(f"Уверенность: {result.get('confidence')}/10")
            print(f"Обоснование: {result.get('reasoning')}")
            print(f"Риски: {result.get('risk_factors')}")
            
            choice = result.get('choice')
            if choice and result.get('verdict') == 'ЖБ':
                chosen_bet = candidates[choice - 1]
                print(f"\nВыбрана ставка: {chosen_bet['home_team']} — {chosen_bet['away_team']}")
                print(f"  {chosen_bet['market_label']} @ {chosen_bet['odds']} | EV: +{chosen_bet['ev']*100:.1f}%")
                
                # Помечаем как ЖБ + сохраняем reasoning и confidence
                conn.execute("""
                    UPDATE bets SET
                        is_golden=1,
                        golden_confidence=?,
                        golden_reasoning=?
                    WHERE id=?
                """, (
                    result.get('confidence', 0),
                    result.get('reasoning', '') + ' | Риски: ' + result.get('risk_factors', ''),
                    chosen_bet['id']
                ))
                conn.commit()
                print("  ✅ Помечена как ЖБ")
        else:
            print(f"Ответ ЛЛМ: {content}")
            
    except Exception as e:
        print(f"Ошибка ЛЛМ: {e}")
    
    conn.close()

if __name__ == "__main__":
    main()
