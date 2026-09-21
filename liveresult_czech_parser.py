#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os, re, sqlite3, argparse, time
from datetime import datetime, timedelta
import requests
from bs4 import BeautifulSoup

DB_PATH = os.environ.get("BETAGENT_DB", "betagent.db")
URL = "https://www.liveresult.ru/hockey/Czech-Republic/Extraliga/results/"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

TEAM_MAP = {
    "маунтфилд градец кралове": "маунтфилд",
    "оцеларжи тршинец": "тршинец",
    "хк пардубице": "пардубице",
    "бк млада болеслав": "млада болеслав",
    "хк комета брно": "комета брно",
    "хк спарта прага": "спарта прага",
    "били тигри либерец": "либерец",
    "энерги карловы вары": "карловы вары",
    "хк витковице": "витковице",
    "хк оломоуц": "оломоуц",
    "хк литвинов": "литвинов",
    "хк пльзень": "пльзень",
}

def normalize(name):
    n = name.lower().strip()
    return TEAM_MAP.get(n, n)

def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def fetch_html(url):
    r = requests.get(url, headers=HEADERS, timeout=15)
    r.raise_for_status()
    return r.text

def get_rt_score(match_url):
    """Заходим на страницу матча и берём счёт после 3-х периодов (без ОТ/буллитов)"""
    try:
        time.sleep(0.5)
        html = fetch_html(match_url)
        soup = BeautifulSoup(html, "html.parser")
        
        # Ищем live-match-events-group-header — счёт накапливается по периодам
        # Первый период: 0:0, Второй период: 2:0, Третий период: 0:2
        # Счёт после третьего периода = сумма всех трёх периодов
        
        groups = soup.find_all("div", class_="live-match-events-group")
        
        period_scores = []
        went_ot = False
        
        for group in groups:
            header = group.find("div", class_="live-match-events-group-header")
            if not header:
                continue
            title_el = header.find("div", class_="title")
            score_el = header.find("div", class_="score")
            if not title_el or not score_el:
                continue
            title = title_el.get_text(strip=True)
            score = score_el.get_text(strip=True)
            
            sm = re.match(r'^(\d+):(\d+)$', score)
            if not sm:
                continue
                
            if title in ("Первый период", "Второй период", "Третий период"):
                period_scores.append((int(sm.group(1)), int(sm.group(2))))
            elif title in ("Овертайм", "Серия буллитов"):
                went_ot = True
        
        if len(period_scores) >= 3:
            # Суммируем голы за 3 периода
            home_rt = sum(p[0] for p in period_scores[:3])
            away_rt = sum(p[1] for p in period_scores[:3])
            return home_rt, away_rt, went_ot
            
    except Exception as e:
        print(f"  ⚠️ Ошибка парсинга страницы матча: {e}")
    return None, None, False

def parse_results(days=3):
    html = fetch_html(URL)
    soup = BeautifulSoup(html, "html.parser")
    matches_div = soup.find("div", class_="matches-list")
    if not matches_div:
        print("❌ matches-list не найден")
        return []

    results = []
    current_date = None
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

    for el in matches_div.children:
        if not hasattr(el, 'get'):
            continue
        cls = " ".join(el.get("class", []))

        # Дата
        if "matches-list-date" in cls:
            time_el = el.find("time")
            if time_el:
                d = time_el.get_text(strip=True)
                m = re.match(r'(\d{2})\.(\d{2})\.(\d{4})', d)
                if m:
                    current_date = f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
                    if current_date < cutoff:
                        break
            continue

        # Матч
        if "matches-list-match" in cls and current_date:
            if not el.find("span", class_="is-finished"):
                continue

            score_el = el.find("span", class_="score")
            if not score_el:
                continue
            score_text = score_el.get_text(strip=True)
            sm = re.match(r'^(\d+):(\d+)', score_text)
            if not sm:
                continue

            home_score = int(sm.group(1))
            away_score = int(sm.group(2))

            team1_el = el.find("span", class_="team1")
            team2_el = el.find("span", class_="team2")
            if not team1_el or not team2_el:
                continue

            t1 = team1_el.find("span", class_=lambda c: not c or "win" not in c)
            t2 = team2_el.find("span", class_=lambda c: not c or "win" not in c)
            home = normalize(t1.get_text(strip=True) if t1 else team1_el.get_text(strip=True))
            away = normalize(t2.get_text(strip=True) if t2 else team2_el.get_text(strip=True))

            if not home or not away:
                continue

            # Получаем URL страницы матча
            match_url = el.get("href", "")
            if match_url and not match_url.startswith("http"):
                match_url = "https://www.liveresult.ru" + match_url

            # Берём счёт основного времени
            rt_home, rt_away, went_ot = None, None, False
            if match_url:
                print(f"  Парсим страницу: {home} — {away}")
                rt_home, rt_away, went_ot = get_rt_score(match_url)

            results.append({
                "league": "czech",
                "match_date": current_date,
                "home_team": home,
                "away_team": away,
                "home_score": rt_home if rt_home is not None else home_score,
                "away_score": rt_away if rt_away is not None else away_score,
                "went_ot": went_ot,
                "full_home_score": home_score,
                "full_away_score": away_score,
            })

    return results

def save_results(conn, results):
    saved = 0
    for r in results:
        existing = conn.execute("""
            SELECT id FROM results_raw
            WHERE league='czech' AND home_team=? AND away_team=? AND match_date=? AND is_finished=1
        """, (r["home_team"], r["away_team"], r["match_date"])).fetchone()
        if existing:
            # Обновляем если счёт изменился
            conn.execute("""
                UPDATE results_raw SET home_score=?, away_score=? 
                WHERE league='czech' AND home_team=? AND away_team=? AND match_date=?
            """, (r["home_score"], r["away_score"], r["home_team"], r["away_team"], r["match_date"]))
            continue
        conn.execute("""
            INSERT INTO results_raw (league, match_date, home_team, away_team, home_score, away_score, is_finished, source)
            VALUES ('czech', ?, ?, ?, ?, ?, 1, 'liveresult.ru_rt')
        """, (r["match_date"], r["home_team"], r["away_team"], r["home_score"], r["away_score"]))
        saved += 1
    conn.commit()
    return saved

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=3)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    conn = get_conn()
    print("Парсим чешскую экстралигу (liveresult.ru) — счёт основного времени...")
    results = parse_results(args.days)
    print(f"\nНайдено матчей: {len(results)}")
    for r in results:
        ot_str = " [ОТ/Б]" if r["went_ot"] else ""
        print(f"  {r['home_team']} {r['home_score']}:{r['away_score']} {r['away_team']} | {r['match_date']}{ot_str} (итог {r['full_home_score']}:{r['full_away_score']})")
    if not args.dry_run:
        saved = save_results(conn, results)
        print(f"Сохранено/обновлено: {saved}")
    conn.close()

if __name__ == "__main__":
    main()
