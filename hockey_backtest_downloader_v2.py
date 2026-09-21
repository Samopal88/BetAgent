#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import logging
import re
import sqlite3
import time
from dataclasses import dataclass, asdict
from datetime import date, datetime, timedelta
from typing import Iterable, Optional
from urllib.parse import urlencode, urljoin

import requests
from bs4 import BeautifulSoup, Tag

BASE_URL = "https://betz.su"
LIST_PATH = "/line/"
DEFAULT_DB = "betagent.db"
DEFAULT_SPORT = "Хоккей"
DEFAULT_SOURCE = "betz.su"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0 Safari/537.36"
    ),
    "Accept-Language": "ru,en;q=0.9",
    "Referer": "https://betz.su/",
}

EXOTIC_NAME_PATTERNS = [
    r"\(голы в бол\.\)",
    r"\(штр\)",
    r"\(бр\)",
    r"\(серия\)",
    r"\(видеопросмотры\)",
    r"\(выиг\. вбрасывания\)",
    r"\(голы\)",
]

EXOTIC_LEAGUE_PATTERNS = [
    r"статистика игрового дня",
    r"голы в большинстве",
    r"броски в створ",
    r"броски в створ ворот",
    r"штрафное время",
    r"выигранные вбрасывания",
    r"видеопросмотры",
    r"статистика серии",
]

SCORE_RE = re.compile(r"^\s*(\d+):(\d+)")
PERIODS_RE = re.compile(r"\((.*?)\)")
FLOAT_RE = re.compile(r"(\d+(?:\.\d+)?)")
DATE_RU_RE = re.compile(r"\b\d{2}\.\d{2}\.\d{4}\b")
TIME_RE = re.compile(r"\b\d{1,2}:\d{2}\b")


@dataclass
class MatchRow:
    source: str
    source_match_id: str
    detail_url: str
    league: str
    season: Optional[str]
    country: Optional[str]
    competition: Optional[str]
    stage: Optional[str]
    sport: str
    match_date: str
    match_time: str
    home_team: str
    away_team: str
    home_score: Optional[int]
    away_score: Optional[int]
    result_raw: str
    periods_raw: Optional[str]
    result_type: Optional[str]
    odds_home: Optional[float]
    odds_draw: Optional[float]
    odds_away: Optional[float]
    odds_total_over: Optional[float]
    odds_total_under: Optional[float]
    total_line: Optional[float]
    odds_handicap_home: Optional[float]
    odds_handicap_away: Optional[float]
    handicap_line_home: Optional[float]
    handicap_line_away: Optional[float]
    source_url: str
    page_date: str
    page_num: int
    fetched_at: str
    rt_home_score: Optional[int] = None
    rt_away_score: Optional[int] = None
    went_ot_or_so: int = 0


def setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
    )


def ensure_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS backtest_hockey_matches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT NOT NULL,
            source_match_id TEXT NOT NULL,
            detail_url TEXT,
            league TEXT,
            season TEXT,
            country TEXT,
            competition TEXT,
            stage TEXT,
            sport TEXT NOT NULL,
            match_date TEXT NOT NULL,
            match_time TEXT,
            home_team TEXT NOT NULL,
            away_team TEXT NOT NULL,
            home_score INTEGER,
            away_score INTEGER,
            result_raw TEXT,
            periods_raw TEXT,
            result_type TEXT,
            odds_home REAL,
            odds_draw REAL,
            odds_away REAL,
            odds_total_over REAL,
            odds_total_under REAL,
            total_line REAL,
            odds_handicap_home REAL,
            odds_handicap_away REAL,
            handicap_line_home REAL,
            handicap_line_away REAL,
            source_url TEXT,
            page_date TEXT NOT NULL,
            page_num INTEGER NOT NULL DEFAULT 0,
            fetched_at TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(source, source_match_id)
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_bhm_date ON backtest_hockey_matches(match_date)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_bhm_league_season ON backtest_hockey_matches(league, season)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_bhm_teams ON backtest_hockey_matches(home_team, away_team)")
    conn.commit()


def daterange(start_dt: date, end_dt: date) -> Iterable[date]:
    current = start_dt
    while current <= end_dt:
        yield current
        current += timedelta(days=1)


def build_list_url(dt: date, page_num: int = 0, sport: str = DEFAULT_SPORT) -> str:
    params = {
        "mode": "started",
        "date": dt.strftime("%d.%m.%Y"),
        "sport": sport,
    }
    if page_num > 0:
        params["p"] = str(page_num)
    return f"{BASE_URL}{LIST_PATH}?{urlencode(params)}"


class Downloader:
    def __init__(self, timeout: int, retries: int, delay: float):
        self.timeout = timeout
        self.retries = retries
        self.delay = delay
        self.session = requests.Session()
        self.session.headers.update(HEADERS)

    def fetch_html(self, url: str) -> str:
        last_error: Optional[Exception] = None
        for attempt in range(1, self.retries + 1):
            try:
                resp = self.session.get(url, timeout=self.timeout)
                resp.raise_for_status()
                resp.encoding = resp.encoding or "utf-8"
                return resp.text
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                if attempt < self.retries:
                    sleep_for = min(2 * attempt, 5)
                    logging.warning("Fetch failed attempt %s/%s for %s: %s", attempt, self.retries, url, exc)
                    time.sleep(sleep_for)
                else:
                    raise RuntimeError(f"fetch failed: {url} -> {exc}") from exc
        raise RuntimeError(f"fetch failed: {url} -> {last_error}")


def extract_match_id(detail_url: str) -> str:
    match = re.search(r"detail=(\d+)", detail_url)
    return match.group(1) if match else detail_url


def extract_float(text: str) -> Optional[float]:
    text = text.replace(",", ".")
    # Берём последнее число — это коэффициент (не номер исхода П1/П2)
    matches = FLOAT_RE.findall(text)
    if not matches:
        return None
    try:
        return float(matches[-1])
    except ValueError:
        return None


def extract_line_from_text(text: str) -> Optional[float]:
    match = re.search(r"\(([+-]?\d+(?:[\.,]\d+)?)\)", text.replace(",", "."))
    if not match:
        return None
    try:
        return float(match.group(1))
    except ValueError:
        return None


def normalize_league_parts(league: str) -> tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
    parts = [p.strip(" .") for p in league.split(".") if p.strip(" .")]
    country = parts[1] if len(parts) > 1 else None
    competition = parts[2] if len(parts) > 2 else None
    stage = ". ".join(parts[3:]) if len(parts) > 3 else None
    season = None
    match = re.search(r"(Сезон\s+\d{2}/\d{2})", league, re.IGNORECASE)
    if match:
        season = match.group(1)
    return country, competition, stage, season


def is_exotic_match(league: str, home_team: str, away_team: str) -> bool:
    low_league = league.lower()
    if any(re.search(pat, low_league, re.IGNORECASE) for pat in EXOTIC_LEAGUE_PATTERNS):
        return True
    joined = f"{home_team} {away_team}".lower()
    return any(re.search(pat, joined, re.IGNORECASE) for pat in EXOTIC_NAME_PATTERNS)


def parse_score_and_periods(result_text: str) -> tuple[Optional[int], Optional[int], str, Optional[str], Optional[str], Optional[int], Optional[int], int]:
    result_text = " ".join(result_text.split())
    score_match = SCORE_RE.search(result_text)
    home_score = away_score = None
    if score_match:
        home_score = int(score_match.group(1))
        away_score = int(score_match.group(2))
    periods_match = PERIODS_RE.search(result_text)
    periods = periods_match.group(1) if periods_match else None
    result_type = None
    lowered = result_text.lower()
    if "бул" in lowered:
        result_type = "so"
    elif "от" in lowered:
        result_type = "ot"
    elif score_match:
        result_type = "regular"
    # Compute RT (regulation) score from first 3 periods
    rt_home = rt_away = None
    went_ot = 1 if result_type in ("so", "ot") else 0
    if periods:
        parts = [p.strip() for p in periods.split(",")]
        reg = []
        for p in parts:
            if "ОТ" in p or "бул" in p.lower():
                break
            if ":" in p:
                reg.append(p)
        if len(reg) >= 3:
            try:
                pairs = [tuple(map(int, x.split(":"))) for x in reg[:3]]
                rt_home = sum(h for h, _ in pairs)
                rt_away = sum(a for _, a in pairs)
            except Exception:
                pass
    if rt_home is None and result_type == "regular":
        rt_home, rt_away = home_score, away_score
    return home_score, away_score, result_text, periods, result_type, rt_home, rt_away, went_ot


def parse_market_spans(container: Tag) -> dict[str, Optional[float]]:
    values: dict[str, Optional[float]] = {
        "odds_home": None,
        "odds_draw": None,
        "odds_away": None,
        "odds_total_over": None,
        "odds_total_under": None,
        "total_line": None,
        "odds_handicap_home": None,
        "odds_handicap_away": None,
        "handicap_line_home": None,
        "handicap_line_away": None,
    }

    for span in container.find_all("span", recursive=False):
        classes = span.get("class", [])
        text = " ".join(span.stripped_strings)
        if "p1" in classes:
            values["odds_home"] = extract_float(text)
        elif "xx" in classes:
            values["odds_draw"] = extract_float(text)
        elif "p2" in classes:
            values["odds_away"] = extract_float(text)
        elif "tm" in classes:
            values["odds_total_under"] = extract_float(text)
            values["total_line"] = values["total_line"] or extract_line_from_text(text)
        elif "tb" in classes:
            values["odds_total_over"] = extract_float(text)
            values["total_line"] = values["total_line"] or extract_line_from_text(text)
        elif "f1" in classes:
            values["odds_handicap_home"] = extract_float(text)
            values["handicap_line_home"] = extract_line_from_text(text)
        elif "f2" in classes:
            values["odds_handicap_away"] = extract_float(text)
            values["handicap_line_away"] = extract_line_from_text(text)

    return values


def _extract_match_datetime(li: Tag, requested_dt: date) -> tuple[str, str]:
    date_span = li.find("span", class_="sport_date")
    if date_span is None:
        return requested_dt.isoformat(), "00:00"

    text = " ".join(date_span.stripped_strings)
    date_match = DATE_RU_RE.search(text)
    time_match = TIME_RE.search(text)

    match_date = requested_dt
    if date_match:
        try:
            match_date = datetime.strptime(date_match.group(0), "%d.%m.%Y").date()
        except ValueError:
            pass
    match_time = time_match.group(0) if time_match else "00:00"
    return match_date.isoformat(), match_time


def parse_page(html: str, requested_dt: date, page_num: int, page_url: str) -> tuple[list[MatchRow], bool]:
    soup = BeautifulSoup(html, "html.parser")
    root = soup.find("ul", class_="sport_line")
    if root is None:
        logging.warning("Не найден ul.sport_line на %s", page_url)
        return [], False

    rows: list[MatchRow] = []
    current_league: Optional[str] = None
    fetched_at = datetime.utcnow().isoformat(timespec="seconds")

    for li in root.find_all("li", recursive=False):
        classes = li.get("class", [])
        if "sport_info_2" in classes:
            current_league = " ".join(li.stripped_strings)
            continue
        if li.get("itemscope") is None:
            continue

        ha_span = li.find("span", class_="sport_ha")
        res_span = li.find("span", class_="sport_res")
        line_div = li.find("div", class_=re.compile(r"^sport_l\b"))
        if not (current_league and ha_span and res_span and line_div):
            continue

        link = ha_span.find("a")
        if not link:
            continue
        teams_text = " ".join(link.stripped_strings)
        if " - " not in teams_text:
            continue

        home_team, away_team = [x.strip() for x in teams_text.split(" - ", 1)]
        if is_exotic_match(current_league, home_team, away_team):
            continue

        detail_url = urljoin(BASE_URL, link.get("href", ""))
        source_match_id = extract_match_id(detail_url)

        result_text = " ".join(res_span.stripped_strings)
        home_score, away_score, result_raw, periods_raw, result_type, rt_home_score, rt_away_score, went_ot_or_so = parse_score_and_periods(result_text)
        match_date, match_time = _extract_match_datetime(li, requested_dt)
        market_values = parse_market_spans(line_div)
        country, competition, stage, season = normalize_league_parts(current_league)

        rows.append(
            MatchRow(
                source=DEFAULT_SOURCE,
                source_match_id=source_match_id,
                detail_url=detail_url,
                league=current_league,
                season=season,
                country=country,
                competition=competition,
                stage=stage,
                sport=DEFAULT_SPORT,
                match_date=match_date,
                match_time=match_time,
                home_team=home_team,
                away_team=away_team,
                home_score=home_score,
                away_score=away_score,
                result_raw=result_raw,
                periods_raw=periods_raw,
                result_type=result_type,
                odds_home=market_values["odds_home"],
                odds_draw=market_values["odds_draw"],
                odds_away=market_values["odds_away"],
                odds_total_over=market_values["odds_total_over"],
                odds_total_under=market_values["odds_total_under"],
                total_line=market_values["total_line"],
                odds_handicap_home=market_values["odds_handicap_home"],
                odds_handicap_away=market_values["odds_handicap_away"],
                handicap_line_home=market_values["handicap_line_home"],
                handicap_line_away=market_values["handicap_line_away"],
                source_url=page_url,
                page_date=requested_dt.isoformat(),
                page_num=page_num,
                fetched_at=fetched_at,
                rt_home_score=rt_home_score,
                rt_away_score=rt_away_score,
                went_ot_or_so=went_ot_or_so,
            )
        )

    has_next_page = False
    nav = soup.find("nav")
    if nav:
        for a in nav.find_all("a", href=True):
            href = a["href"]
            match = re.search(r"[?&]p=(\d+)", href)
            if match and int(match.group(1)) >= page_num + 1:
                has_next_page = True
                break

    return rows, has_next_page


def upsert_rows(conn: sqlite3.Connection, rows: list[MatchRow]) -> tuple[int, int, int]:
    inserted = 0
    updated = 0
    skipped = 0

    sql = """
    INSERT INTO backtest_hockey_matches (
        source, source_match_id, detail_url,
        league, season, country, competition, stage,
        sport, match_date, match_time,
        home_team, away_team, home_score, away_score,
        result_raw, periods_raw, result_type,
        odds_home, odds_draw, odds_away,
        odds_total_over, odds_total_under, total_line,
        odds_handicap_home, odds_handicap_away,
        handicap_line_home, handicap_line_away,
        source_url, page_date, page_num, fetched_at, updated_at,
        rt_home_score, rt_away_score, went_ot_or_so
    )
    VALUES (
        :source, :source_match_id, :detail_url,
        :league, :season, :country, :competition, :stage,
        :sport, :match_date, :match_time,
        :home_team, :away_team, :home_score, :away_score,
        :result_raw, :periods_raw, :result_type,
        :odds_home, :odds_draw, :odds_away,
        :odds_total_over, :odds_total_under, :total_line,
        :odds_handicap_home, :odds_handicap_away,
        :handicap_line_home, :handicap_line_away,
        :source_url, :page_date, :page_num, :fetched_at, CURRENT_TIMESTAMP,
        :rt_home_score, :rt_away_score, :went_ot_or_so
    )
    ON CONFLICT(source, source_match_id) DO UPDATE SET
        detail_url=excluded.detail_url,
        league=excluded.league,
        season=excluded.season,
        country=excluded.country,
        competition=excluded.competition,
        stage=excluded.stage,
        sport=excluded.sport,
        match_date=excluded.match_date,
        match_time=excluded.match_time,
        home_team=excluded.home_team,
        away_team=excluded.away_team,
        home_score=excluded.home_score,
        away_score=excluded.away_score,
        result_raw=excluded.result_raw,
        periods_raw=excluded.periods_raw,
        result_type=excluded.result_type,
        odds_home=excluded.odds_home,
        odds_draw=excluded.odds_draw,
        odds_away=excluded.odds_away,
        odds_total_over=excluded.odds_total_over,
        odds_total_under=excluded.odds_total_under,
        total_line=excluded.total_line,
        odds_handicap_home=excluded.odds_handicap_home,
        odds_handicap_away=excluded.odds_handicap_away,
        handicap_line_home=excluded.handicap_line_home,
        handicap_line_away=excluded.handicap_line_away,
        source_url=excluded.source_url,
        page_date=excluded.page_date,
        page_num=excluded.page_num,
        fetched_at=excluded.fetched_at,
        rt_home_score=excluded.rt_home_score,
        rt_away_score=excluded.rt_away_score,
        went_ot_or_so=excluded.went_ot_or_so,
        updated_at=CURRENT_TIMESTAMP
    """

    for row in rows:
        existed = conn.execute(
            "SELECT 1 FROM backtest_hockey_matches WHERE source=? AND source_match_id=?",
            (row.source, row.source_match_id),
        ).fetchone() is not None
        before = conn.total_changes
        try:
            conn.execute(sql, asdict(row))
        except Exception:
            pass
        after = conn.total_changes
        if existed:
            if after > before:
                updated += 1
            else:
                skipped += 1
        else:
            inserted += 1

    conn.commit()
    return inserted, updated, skipped


def process_date(downloader: Downloader, conn: sqlite3.Connection, dt: date, max_pages: int, test_html: Optional[str] = None) -> tuple[int, int, int, int]:
    total_found = total_inserted = total_updated = total_skipped = 0
    page_num = 0

    while True:
        if test_html:
            with open(test_html, "r", encoding="utf-8") as fh:
                html = fh.read()
            url = f"file://{test_html}"
        else:
            url = build_list_url(dt, page_num=page_num, sport=DEFAULT_SPORT)
            logging.info("Дата %s | страница %s | %s", dt.isoformat(), page_num + 1, url)
            html = downloader.fetch_html(url)

        rows, has_next = parse_page(html, dt, page_num, url)
        logging.info("Дата %s | страница %s | найдено матчей: %s", dt.isoformat(), page_num + 1, len(rows))
        if not rows and page_num == 0:
            break

        inserted, updated, skipped = upsert_rows(conn, rows)
        total_found += len(rows)
        total_inserted += inserted
        total_updated += updated
        total_skipped += skipped

        if test_html or not has_next:
            break
        page_num += 1
        if page_num >= max_pages:
            logging.warning("Достигнут max_pages=%s, остановка", max_pages)
            break
        time.sleep(downloader.delay)

    return total_found, total_inserted, total_updated, total_skipped


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Загрузка исторических хоккейных матчей с betz.su")
    parser.add_argument("--db", default=DEFAULT_DB, help="Путь к SQLite базе")
    parser.add_argument("--date-from", required=False, help="Начальная дата YYYY-MM-DD")
    parser.add_argument("--date-to", required=False, help="Конечная дата YYYY-MM-DD")
    parser.add_argument("--delay", type=float, default=0.8, help="Пауза между запросами страниц")
    parser.add_argument("--max-pages", type=int, default=20, help="Макс. число страниц на дату")
    parser.add_argument("--timeout", type=int, default=20, help="HTTP timeout")
    parser.add_argument("--retries", type=int, default=3, help="Количество ретраев")
    parser.add_argument("--verbose", action="store_true", help="Подробный лог")
    parser.add_argument("--test-html", help="Локальный HTML-файл для тестового парсинга")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    setup_logging(args.verbose)

    if not args.test_html and (not args.date_from or not args.date_to):
        raise SystemExit("Нужны --date-from и --date-to, либо --test-html")

    downloader = Downloader(timeout=args.timeout, retries=args.retries, delay=args.delay)
    conn = sqlite3.connect(args.db)
    ensure_table(conn)

    total_dates = total_found = total_inserted = total_updated = total_skipped = 0

    try:
        if args.test_html:
            today = date.today()
            found, inserted, updated, skipped = process_date(downloader, conn, today, args.max_pages, test_html=args.test_html)
            total_dates = 1
            total_found = found
            total_inserted = inserted
            total_updated = updated
            total_skipped = skipped
        else:
            start_dt = datetime.strptime(args.date_from, "%Y-%m-%d").date()
            end_dt = datetime.strptime(args.date_to, "%Y-%m-%d").date()
            if end_dt < start_dt:
                raise SystemExit("date-to не может быть раньше date-from")

            for dt in daterange(start_dt, end_dt):
                total_dates += 1
                found, inserted, updated, skipped = process_date(downloader, conn, dt, args.max_pages)
                total_found += found
                total_inserted += inserted
                total_updated += updated
                total_skipped += skipped
                time.sleep(args.delay)
    finally:
        conn.close()

    logging.info("Download completed")
    logging.info("Total dates processed: %s", total_dates)
    logging.info("Total matches found: %s", total_found)
    logging.info("Total inserted: %s", total_inserted)
    logging.info("Total updated: %s", total_updated)
    logging.info("Total skipped: %s", total_skipped)


if __name__ == "__main__":
    main()
