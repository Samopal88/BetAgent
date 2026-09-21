#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
betz_nhl_results_parser.py — парсит результаты НХЛ/КХЛ с betz.su/res/result.php
Пишет в results_raw.
"""
import argparse, logging, re, sqlite3, time
from datetime import datetime, timedelta
import requests
from bs4 import BeautifulSoup

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/123.0 Safari/537.36",
    "Referer": "https://betz.su/",
}

# Маппинг полных названий → короткие (Фонбет)
TEAM_MAP = {
    "Анахайм Дакс": "Анахайм", "Бостон Брюинз": "Бостон",
    "Баффало Сейбрз": "Баффало", "Калгари Флэймз": "Калгари",
    "Каролина Харрикейнз": "Каролина", "Чикаго Блэкхокс": "Чикаго",
    "Колорадо Эвеланш": "Колорадо", "Коламбус Блю Джекетс": "Коламбус",
    "Даллас Старз": "Даллас", "Детройт Ред Уингз": "Детройт",
    "Эдмонтон Ойлерз": "Эдмонтон", "Флорида Пантерз": "Флорида",
    "Лос-Анджелес Кингз": "Лос-Анджелес", "Миннесота Уайлд": "Миннесота",
    "Монреаль Канадиенс": "Монреаль", "Нэшвилл Предаторз": "Нэшвилл",
    "Нью-Джерси Девилз": "Нью-Джерси", "Нью-Йорк Айлендерс": "Айлендерс",
    "Нью-Йорк Рейнджерс": "Рейнджерс", "Оттава Сенаторз": "Оттава",
    "Филадельфия Флайерз": "Филадельфия", "Питтсбург Пингвинз": "Питтсбург",
    "Сан-Хосе Шаркс": "Сан-Хосе", "Сиэтл Кракен": "Сиэтл",
    "Сент-Луис Блюз": "Сент-Луис", "Тампа-Бэй Лайтнинг": "Тампа-Бэй",
    "Торонто Мейпл Лифс": "Торонто", "Ванкувер Кэнакс": "Ванкувер",
    "Вегас Голден Найтс": "Вегас", "Вашингтон Кэпиталз": "Вашингтон",
    "Виннипег Джетс": "Виннипег", "Юта Маммот": "Юта",
    "Юта Хоккей Клаб": "Юта",
    # КХЛ
    "Ак Барс": "Ак Барс", "Авангард": "Авангард", "ЦСКА": "ЦСКА",
    "СКА": "СКА", "Металлург Магнитогорск": "Металлург Мг",
    "Локомотив": "Локомотив", "Спартак": "Спартак",
    "Динамо Москва": "Динамо Москва", "Динамо Минск": "Динамо Минск",
    "Трактор": "Трактор", "Нефтехимик": "Нефтехимик",
    "Сибирь": "Сибирь", "Салават Юлаев": "Салават Юлаев",
    "Северсталь": "Северсталь", "Торпедо НН": "Торпедо НН",
}

# Лиги которые нас интересуют
TARGET_LEAGUES = {
    "нхл": "nhl",
    "nhl": "nhl",
    "кхл": "khl",
    "khl": "khl",
}

SIDE_MARKET_PATTERNS = [
    r"\(бр\)",
    r"\(видеопросмотр",
    r"\(выиг\.?\s*вбрасыван",
    r"\(голы\s*в\s*бол",
    r"\(штр\)",
    r"\(силов",
    r"\(блокир",
    r"\(броск",
    r"\(сейв",
]

def normalize(name):
    name = name.strip()
    name = re.sub(r"\s+", " ", name)
    name = name.replace("Юта Маммот", "Юта").replace("Юта Мэммот", "Юта").replace("Юта Хоккей Клаб", "Юта")
    name = name.replace("Ак Барс Казань", "Ак Барс").replace("Трактор Челябинск", "Трактор")
    return TEAM_MAP.get(name, name)


def is_side_market(team_name: str) -> bool:
    s = team_name.lower()
    return any(re.search(p, s) for p in SIDE_MARKET_PATTERNS)

def parse_score_reg(score_text):
    """Парсим счёт основного времени из строки типа '4:4 (0:1, 1:0, 3:3)(ОТ 0:0, бул. 2:1)'"""
    is_ot = bool(re.search(r"ОТ|от\b|OT\b|бул\.", score_text, re.I))
    
    if is_ot:
        # Берём счёт по периодам и суммируем (основное время)
        periods = re.findall(r"(\d+):(\d+)", score_text)
        if len(periods) >= 4:  # итог + 3 периода
            # periods[1], periods[2], periods[3] — периоды
            hs = sum(int(p[0]) for p in periods[1:4])
            as_ = sum(int(p[1]) for p in periods[1:4])
            return hs, as_, 1
        elif len(periods) >= 2:
            # Просто берём итог и считаем ОТ
            hs, as_ = int(periods[0][0]), int(periods[0][1])
            # В ОТ победитель забил на 1 больше — отнимаем
            if hs > as_:
                return hs - 1, as_, 1
            else:
                return hs, as_ - 1, 1
    else:
        m = re.search(r"^(\d+):(\d+)", score_text.strip())
        if m:
            return int(m.group(1)), int(m.group(2)), 0
    return None, None, 0

def fetch(url, session):
    for attempt in range(3):
        try:
            r = session.get(url, timeout=20)
            r.raise_for_status()
            return r.text
        except Exception as e:
            if attempt < 2:
                time.sleep(2)
            else:
                log.warning(f"Ошибка {url}: {e}")
    return ""

def save_result(conn, league, match_date, home, away, hs, as_, is_ot):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        conn.execute("""
            INSERT INTO results_raw 
            (league, match_date, home_team, away_team, home_score, away_score, 
             is_overtime, is_finished, source, updated_at)
            VALUES (?,?,?,?,?,?,?,1,'betz.su',?)
            ON CONFLICT(league, match_date, home_team, away_team)
            DO UPDATE SET home_score=excluded.home_score,
                          away_score=excluded.away_score,
                          is_overtime=excluded.is_overtime,
                          is_finished=1,
                          updated_at=excluded.updated_at
        """, (league, match_date, home, away, hs, as_, is_ot, now))
        conn.commit()
        return True
    except Exception as e:
        log.warning(f"DB error: {e}")
        return False

def parse_date(date_str):
    """YYYY-MM-DD → DD.MM.YYYY для betz.su"""
    d = datetime.strptime(date_str, "%Y-%m-%d")
    return d.strftime("%d.%m.%Y")

def process_date(session, conn, date_str, target):
    """Парсим один день с betz.su и сохраняем только основные матчи."""
    betz_date = parse_date(date_str)
    url = f"https://betz.su/res/result.php?date={betz_date}&sport=Хоккей"
    html = fetch(url, session)
    if not html:
        return 0

    soup = BeautifulSoup(html, "html.parser")
    saved = 0
    parsed_main = 0
    skipped_side = 0
    current_league_name = None

    for div in soup.find_all("div", class_=re.compile(r"open_all")):
        prev = div.find_previous("div")
        if prev:
            prev_text = prev.get_text(" ", strip=True).lower()
            current_league_name = None
            for key, name in TARGET_LEAGUES.items():
                if key in prev_text:
                    current_league_name = name
                    break

        if not current_league_name:
            continue

        links = div.find_all("a")
        scores = div.find_all("u")

        for link, score_tag in zip(links, scores):
            match_text = link.get_text(" ", strip=True)
            score_text = score_tag.get_text(" ", strip=True)

            if " - " not in match_text:
                continue

            home_raw, away_raw = [x.strip() for x in match_text.split(" - ", 1)]

            if is_side_market(home_raw) or is_side_market(away_raw):
                skipped_side += 1
                continue

            home = normalize(home_raw)
            away = normalize(away_raw)

            hs, as_, is_ot = parse_score_reg(score_text)
            if hs is None:
                continue

            parsed_main += 1
            if save_result(conn, current_league_name, date_str, home, away, hs, as_, is_ot):
                log.info(f"  ✅ {home} {hs}:{as_} {away} {'(OT)' if is_ot else ''} [{current_league_name}]")
                saved += 1

    log.info(f"  ℹ️ {date_str}: main={parsed_main}, saved={saved}, skipped_side={skipped_side}")
    return saved

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date-from", default=(datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d"))
    ap.add_argument("--date-to", default=datetime.now().strftime("%Y-%m-%d"))
    ap.add_argument("--db", default="betagent.db")
    args = ap.parse_args()

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row

    # Ensure schema
    conn.execute("""
        CREATE TABLE IF NOT EXISTS results_raw (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            league TEXT, match_date TEXT,
            home_team TEXT, away_team TEXT,
            home_score INTEGER, away_score INTEGER,
            is_overtime INTEGER DEFAULT 0,
            is_finished INTEGER DEFAULT 0,
            source TEXT, updated_at TEXT,
            UNIQUE(league, match_date, home_team, away_team)
        )
    """)
    conn.commit()

    session = requests.Session()
    session.headers.update(HEADERS)

    d = datetime.strptime(args.date_from, "%Y-%m-%d")
    d_to = datetime.strptime(args.date_to, "%Y-%m-%d")
    total = 0

    while d <= d_to:
        date_str = d.strftime("%Y-%m-%d")
        log.info(f"Парсим {date_str}...")
        saved = process_date(session, conn, date_str, "nhl")
        total += saved
        time.sleep(0.5)
        d += timedelta(days=1)

    conn.close()
    log.info(f"\n✅ Всего сохранено: {total}")

if __name__ == "__main__":
    main()
