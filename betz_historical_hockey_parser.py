import argparse
import logging
import re
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable, Optional
from urllib.parse import urlencode

import requests
from bs4 import BeautifulSoup

DB_PATH = "betagent.db"
BASE_URL = "https://betz.su/line/"
SPORT_NAME = "Хоккей"
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)

# Главная 1X2-линия обычно имеет p1 / xx / p2.
# На странице также есть статистические рынки вида "голы в большинстве", "штрафное время",
# "броски в створ" и т.д. Их лучше исключить, иначе база загрязняется не-матчевыми сущностями.
LEAGUE_EXCLUDE_KEYWORDS = (
    "статистика игрового дня",
    "голы в большинстве",
    "броски в створ",
    "штрафное время",
    "выигранные вбрасывания",
    "видеопросмотры",
    "статистика серии",
)
TEAM_EXCLUDE_PATTERNS = (
    "(голы",
    "(бр",
    "(штр",
    "(выиг.",
    "(видеопросмотры",
    "(серия)",
)


@dataclass
class MatchRow:
    league: str
    match_date: str
    match_time: Optional[str]
    home_team: str
    away_team: str
    home_score: Optional[int]
    away_score: Optional[int]
    odds_home: Optional[float]
    odds_draw: Optional[float]
    odds_away: Optional[float]
    source_url: Optional[str]
    source_event_id: Optional[str]
    raw_score: Optional[str]


CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS backtest_hockey_matches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    league TEXT,
    match_date TEXT,
    match_time TEXT,
    home_team TEXT,
    away_team TEXT,
    home_score INTEGER,
    away_score INTEGER,
    odds_home REAL,
    odds_draw REAL,
    odds_away REAL,
    source_url TEXT,
    source_event_id TEXT,
    raw_score TEXT,
    created_at TEXT,
    UNIQUE(match_date, home_team, away_team)
)
"""


class BetzHockeyParser:
    def __init__(
        self,
        db_path: str = DB_PATH,
        delay: float = 0.6,
        timeout: int = 20,
        retries: int = 3,
        session: Optional[requests.Session] = None,
    ) -> None:
        self.db_path = db_path
        self.delay = delay
        self.timeout = timeout
        self.retries = retries
        self.session = session or requests.Session()
        self.session.headers.update(
            {
                "User-Agent": USER_AGENT,
                "Accept-Language": "ru,en;q=0.9",
                "Referer": "https://betz.su/",
            }
        )

    def create_table(self) -> None:
        conn = sqlite3.connect(self.db_path)
        try:
            cur = conn.cursor()
            cur.execute(CREATE_TABLE_SQL)
            conn.commit()
        finally:
            conn.close()

    def fetch_html(self, date_str: str, page: int = 0) -> str:
        params = {
            "mode": "started",
            "date": date_str,
            "sport": SPORT_NAME,
        }
        if page > 0:
            params["p"] = page

        url = f"{BASE_URL}?{urlencode(params)}"
        last_error: Optional[Exception] = None

        for attempt in range(1, self.retries + 1):
            try:
                response = self.session.get(url, timeout=self.timeout)
                response.raise_for_status()
                response.encoding = response.encoding or "utf-8"
                return response.text
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                if attempt < self.retries:
                    time.sleep(min(2 * attempt, 5))
                else:
                    raise RuntimeError(f"fetch failed: {url} -> {exc}") from exc

        raise RuntimeError(f"fetch failed: {url} -> {last_error}")

    def parse_matches(self, html: str, requested_date: Optional[str] = None) -> list[MatchRow]:
        soup = BeautifulSoup(html, "html.parser")
        sport_line = soup.select_one("ul.sport_line")
        if not sport_line:
            return []

        rows: list[MatchRow] = []
        current_league: Optional[str] = None
        current_date: Optional[str] = requested_date

        for li in sport_line.find_all("li", recursive=False):
            classes = set(li.get("class", []))

            if "sport_info" in classes:
                value = li.get_text(" ", strip=True)
                if re.fullmatch(r"\d{2}\.\d{2}\.\d{4}", value):
                    current_date = value
                continue

            if "sport_info_2" in classes:
                current_league = self._clean_text(li.get_text(" ", strip=True))
                continue

            if li.get("itemscope") is None:
                continue

            match = self._parse_match_li(li, current_league=current_league, current_date=current_date)
            if match:
                rows.append(match)

        return rows

    def _parse_match_li(
        self,
        li,
        current_league: Optional[str],
        current_date: Optional[str],
    ) -> Optional[MatchRow]:
        league = self._clean_text(current_league)
        if not league or self._should_skip_league(league):
            return None

        teams_text = self._clean_text(li.select_one("span.sport_ha").get_text(" ", strip=True) if li.select_one("span.sport_ha") else "")
        if " - " not in teams_text:
            return None

        home_team, away_team = [self._clean_text(x) for x in teams_text.split(" - ", 1)]
        if self._should_skip_teams(home_team, away_team):
            return None

        score_text = self._clean_text(li.select_one("span.sport_res").get_text(" ", strip=True) if li.select_one("span.sport_res") else "")
        home_score, away_score = self._extract_score(score_text)

        date_text, time_text = self._extract_date_time(li, fallback_date=current_date)
        if not date_text:
            return None

        odds_home = self._extract_odds(li, "span.p1")
        odds_draw = self._extract_odds(li, "span.xx")
        odds_away = self._extract_odds(li, "span.p2")

        detail_link = li.select_one('a[href*="detail="]')
        source_url = None
        source_event_id = None
        if detail_link and detail_link.get("href"):
            href = detail_link["href"]
            source_url = href if href.startswith("http") else f"https://betz.su{href}"
            event_match = re.search(r"detail=(\d+)", href)
            if event_match:
                source_event_id = event_match.group(1)

        return MatchRow(
            league=league,
            match_date=date_text,
            match_time=time_text,
            home_team=home_team,
            away_team=away_team,
            home_score=home_score,
            away_score=away_score,
            odds_home=odds_home,
            odds_draw=odds_draw,
            odds_away=odds_away,
            source_url=source_url,
            source_event_id=source_event_id,
            raw_score=score_text or None,
        )

    @staticmethod
    def _clean_text(value: Optional[str]) -> str:
        return re.sub(r"\s+", " ", (value or "")).strip()

    @staticmethod
    def _extract_score(score_text: str) -> tuple[Optional[int], Optional[int]]:
        match = re.match(r"(\d+)\s*:\s*(\d+)", score_text)
        if not match:
            return None, None
        return int(match.group(1)), int(match.group(2))

    @staticmethod
    def _extract_odds(li, selector: str) -> Optional[float]:
        node = li.select_one(selector)
        if not node:
            return None
        text = node.get_text(" ", strip=True)
        match = re.search(r"-\s*([0-9]+(?:[.,][0-9]+)?)\s*$", text)
        if not match:
            bold = node.find("b")
            if bold:
                raw = bold.get_text(strip=True)
            else:
                return None
        else:
            raw = match.group(1)
        raw = raw.replace(",", ".")
        try:
            return float(raw)
        except ValueError:
            return None

    @staticmethod
    def _extract_date_time(li, fallback_date: Optional[str]) -> tuple[Optional[str], Optional[str]]:
        date_node = li.select_one("span.sport_date")
        if not date_node:
            return fallback_date, None

        time_text = None
        bold = date_node.find("b")
        if bold:
            raw_time = bold.get_text(strip=True)
            if re.fullmatch(r"\d{1,2}:\d{2}", raw_time):
                time_text = raw_time

        anchor = date_node.find("a")
        date_text = anchor.get_text(strip=True) if anchor else fallback_date
        if date_text and re.fullmatch(r"\d{2}\.\d{2}\.\d{4}", date_text):
            return date_text, time_text
        return fallback_date, time_text

    @staticmethod
    def _should_skip_league(league: str) -> bool:
        lower = league.lower()
        return any(keyword in lower for keyword in LEAGUE_EXCLUDE_KEYWORDS)

    @staticmethod
    def _should_skip_teams(home_team: str, away_team: str) -> bool:
        joined = f"{home_team} | {away_team}".lower()
        return any(pattern in joined for pattern in TEAM_EXCLUDE_PATTERNS)

    def save_matches(self, matches: Iterable[MatchRow]) -> tuple[int, int]:
        conn = sqlite3.connect(self.db_path)
        inserted = 0
        skipped = 0
        now_iso = datetime.now().isoformat(timespec="seconds")

        try:
            cur = conn.cursor()
            for m in matches:
                try:
                    cur.execute(
                        """
                        INSERT INTO backtest_hockey_matches (
                            league,
                            match_date,
                            match_time,
                            home_team,
                            away_team,
                            home_score,
                            away_score,
                            odds_home,
                            odds_draw,
                            odds_away,
                            source_url,
                            source_event_id,
                            raw_score,
                            created_at
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            m.league,
                            m.match_date,
                            m.match_time,
                            m.home_team,
                            m.away_team,
                            m.home_score,
                            m.away_score,
                            m.odds_home,
                            m.odds_draw,
                            m.odds_away,
                            m.source_url,
                            m.source_event_id,
                            m.raw_score,
                            now_iso,
                        ),
                    )
                    inserted += 1
                except sqlite3.IntegrityError:
                    skipped += 1
            conn.commit()
        finally:
            conn.close()

        return inserted, skipped

    def discover_page_count(self, html: str) -> int:
        soup = BeautifulSoup(html, "html.parser")
        pages = {1}
        for nav_link in soup.select("nav a[href]"):
            text = nav_link.get_text(strip=True)
            if text.isdigit():
                pages.add(int(text))
        return max(pages)

    def run(self, date_from: datetime, date_to: datetime, include_pagination: bool = True) -> None:
        self.create_table()
        total_inserted = 0
        total_skipped = 0

        for current_date in daterange(date_from, date_to):
            date_str = current_date.strftime("%d.%m.%Y")
            logging.info("Processing %s", date_str)

            try:
                first_html = self.fetch_html(date_str, page=0)
                page_count = self.discover_page_count(first_html) if include_pagination else 1
                daily_matches: list[MatchRow] = self.parse_matches(first_html, requested_date=date_str)

                if include_pagination and page_count > 1:
                    for page_idx in range(1, page_count):
                        time.sleep(self.delay)
                        html = self.fetch_html(date_str, page=page_idx)
                        daily_matches.extend(self.parse_matches(html, requested_date=date_str))

                logging.info("Found valid hockey matches: %s", len(daily_matches))
                inserted, skipped = self.save_matches(daily_matches)
                total_inserted += inserted
                total_skipped += skipped
                logging.info("Inserted: %s, skipped: %s", inserted, skipped)
            except Exception as exc:  # noqa: BLE001
                logging.exception("Error on %s: %s", date_str, exc)

            time.sleep(self.delay)

        logging.info("TOTAL INSERTED: %s", total_inserted)
        logging.info("TOTAL SKIPPED: %s", total_skipped)


def daterange(start_date: datetime, end_date: datetime):
    current = start_date
    while current <= end_date:
        yield current
        current += timedelta(days=1)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Парсер исторических хоккейных матчей с betz.su")
    parser.add_argument("--db", default=DB_PATH, help="Путь к SQLite базе")
    parser.add_argument("--date-from", default="2023-03-01", help="Дата начала в формате YYYY-MM-DD")
    parser.add_argument("--date-to", default="2023-03-10", help="Дата конца в формате YYYY-MM-DD")
    parser.add_argument("--delay", type=float, default=0.6, help="Пауза между запросами")
    parser.add_argument("--timeout", type=int, default=20, help="Таймаут HTTP")
    parser.add_argument("--retries", type=int, default=3, help="Количество ретраев")
    parser.add_argument(
        "--no-pagination",
        action="store_true",
        help="Не ходить по страницам пагинации",
    )
    parser.add_argument(
        "--test-html",
        help="Локальный HTML-файл для тестового парсинга без HTTP-запросов",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

    parser = BetzHockeyParser(
        db_path=args.db,
        delay=args.delay,
        timeout=args.timeout,
        retries=args.retries,
    )

    if args.test_html:
        parser.create_table()
        with open(args.test_html, "r", encoding="utf-8") as f:
            html = f.read()
        matches = parser.parse_matches(html)
        inserted, skipped = parser.save_matches(matches)
        logging.info("TEST HTML -> parsed: %s, inserted: %s, skipped: %s", len(matches), inserted, skipped)
        return

    date_from = datetime.strptime(args.date_from, "%Y-%m-%d")
    date_to = datetime.strptime(args.date_to, "%Y-%m-%d")
    parser.run(date_from, date_to, include_pagination=not args.no_pagination)


if __name__ == "__main__":
    main()
