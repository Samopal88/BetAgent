#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Парсер угловых, ЖК и ударов в створ с betz.su (Футбол).
Восполняет пробелы: основные исходы 1X2 уже есть в backtest_matches.

Как работает:
1. Для каждой даты загружается страница результатов betz:
   https://betz.su/res/result.php?date=DD.MM.YYYY&sport=Футбол
2. Матчи ищутся по целевым лигам (РПЛ, Бундеслига, Серия А, Ла Лига, Лига 1, АПЛ).
   Для каждой лиги есть основной блок и блок ". Статистика.".
3. Из статистического блока берутся ссылки на страницы:
   — «УГЛ {home} — УГЛ {away}»
   — «ЖК {home} — ЖК {away}»
   — «{home} удары в створ — {away} удары в створ»
4. Каждая страница парсится: результат (счёт в шапке), TM/TB-коэффициенты,
   первые/последние минуты ЖК.
5. Данные сохраняются в backtest_football_stats.
"""
import argparse, logging, re, sqlite3, time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from urllib.parse import quote
import requests

from bs4 import BeautifulSoup

DB_PATH = "betagent.db"
RESULTS_URL = "https://betz.su/res/result.php"
SPORT_NAME = "Футбол"

# Целевые лиги (должны содержаться в названии блока, lower-case)
TARGET_LEAGUES_LOWER = [
    "россия. премьер-лига",
    "германия. бундеслига",
    "италия. серия a",
    "испания. примера дивизион",
    "франция. лига 1",
    "англия. премьер-лига",
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/123.0 Safari/537.36"
    ),
    "Accept-Language": "ru,en;q=0.9",
    "Referer": "https://betz.su/",
}

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS backtest_football_stats (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    league            TEXT,
    match_date        TEXT NOT NULL,
    home_team         TEXT NOT NULL,
    away_team         TEXT NOT NULL,
    -- corners
    corners_home      INTEGER,
    corners_away      INTEGER,
    corners_total     INTEGER,
    corners_h1_home   INTEGER,
    corners_h1_away   INTEGER,
    corners_odds_over REAL,
    corners_odds_under REAL,
    corners_line      REAL,
    -- yellow cards
    yc_home           INTEGER,
    yc_away           INTEGER,
    yc_total          INTEGER,
    yc_first_minute   REAL,
    yc_last_minute    REAL,
    yc_odds_over      REAL,
    yc_odds_under     REAL,
    yc_line           REAL,
    -- shots on target
    shots_home        INTEGER,
    shots_away        INTEGER,
    shots_odds_over   REAL,
    shots_odds_under  REAL,
    shots_line        REAL,

    created_at        TEXT DEFAULT (datetime('now')),
    UNIQUE(match_date, home_team, away_team)
)
"""

log = logging.getLogger(__name__)


# -----------------------------------------------------------
# helpers
# -----------------------------------------------------------

def _score_match(text: str) -> Tuple[Optional[int], Optional[int]]:
    """Extract X:Y from text, optional with HT (X:Y)."""
    m = re.search(r"(\d+)\s*:\s*(\d+)(?:\s*[(]\s*([\d:]+)\s*[)])?", text)
    if m:
        return int(m.group(1)), int(m.group(2))
    return None, None


def _ht_score(text: str) -> Tuple[Optional[int], Optional[int]]:
    m = re.search(r"[(]\s*(\d+)\s*:\s*(\d+)\s*[)]", text)
    if m:
        return int(m.group(1)), int(m.group(2))
    return None, None


def _parse_tm_tb_odds(full_text: str) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    """
    Return (over_odds, under_odds, line) from pattern like:
    ТМ (8.5) - 2.02  ТБ (8.5) - 1.74
    """
    tm = re.findall(r"ТМ\s*\(([0-9.,]+)\)\s*[-–]\s*([0-9.,]+)", full_text)
    tb = re.findall(r"ТБ\s*\(([0-9.,]+)\)\s*[-–]\s*([0-9.,]+)", full_text)
    if not tm and not tb:
        return None, None, None
    # normalise comma → dot
    tm_list = [(float(line.replace(",", ".")), float(val.replace(",", "."))) for line, val in tm]
    tb_list = [(float(line.replace(",", ".")), float(val.replace(",", "."))) for line, val in tb]
    # try to find matching pair on same line
    for t_line, t_val in tm_list:
        for o_line, o_val in tb_list:
            if abs(t_line - o_line) < 0.01:
                return o_val, t_val, t_line  # over, under, line
    # fallback — return first pair
    if tm_list and tb_list:
        return tb_list[0][1], tm_list[0][1], tm_list[0][0]
    return None, None, None


def _first_yc_minute(full_text: str) -> Optional[float]:
    m = re.search(r"Первая\s+ЖК\s*[(]мин[)]\s*[-:]\s*([0-9]+(?:[.,][0-9]+)?)", full_text)
    if not m:
        m = re.search(r"Первая[^Ж]*(?:ЖК|жёлт)[^:]*[:\s-]+(\d+)", full_text)
    if m:
        return float(m.group(1).replace(",", "."))
    return None


def _last_yc_minute(full_text: str) -> Optional[float]:
    m = re.search(r"Последняя\s+ЖК\s*[(]мин[)]\s*[-:]\s*([0-9]+(?:[.,][0-9]+)?)", full_text)
    if not m:
        m = re.search(r"Последняя[^Ж]*(?:ЖК|жёлт)[^:]*[:\s-]+(\d+)", full_text)
    if m:
        return float(m.group(1).replace(",", "."))
    return None


STAT_PREFIXES = [
    ("УГЛ ", "corners"),
    ("ЖК ", "yc"),
]

STAT_SUFFIX = " удары в створ"  # shots on target suffix

TARGET_STAT_TYPES = {"corners", "yc", "shots"}


def _classify_stat_title(title: str) -> Tuple[str, str, str]:
    """
    Classify a stat page title.
    Returns (stat_type, home_team, away_team).
    Raises ValueError if not a recognised stat page.
    """
    # Shots: "Team1 удары в створ — Team2 удары в створ"
    suffix = STAT_SUFFIX
    if suffix in title and " - " in title:
        home, away = title.split(" - ", 1)
        home = home.replace(suffix, "").strip()
        away = away.replace(suffix, "").strip()
        if home and away:
            return "shots", home, away

    # YC / Corners: "УГЛ Team1 — УГЛ Team2" or "ЖК Team1 — ЖК Team2"
    for prefix, stat_type in STAT_PREFIXES:
        if title.startswith(prefix) and " - " in title:
            home, away = title.split(" - ", 1)
            home = home.replace(prefix, "", 1).strip()
            away = away.replace(prefix, "", 1).strip()
            if home and away:
                return stat_type, home, away

    raise ValueError(f"Not a recognised stat title: {title!r}")


# -----------------------------------------------------------
# parser class
# -----------------------------------------------------------

class BetzFootballStatsParser:
    def __init__(
        self,
        db_path: str = DB_PATH,
        delay: float = 0.3,
        timeout: int = 20,
        retries: int = 3,
    ) -> None:
        self.db_path = db_path
        self.delay = delay
        self.timeout = timeout
        self.retries = retries
        self.session = requests.Session()
        self.session.headers.update(HEADERS)

    # --- HTTP ---

    def _fetch(self, url: str) -> str:
        last_err: Optional[Exception] = None
        for attempt in range(1, self.retries + 1):
            try:
                r = self.session.get(url, timeout=self.timeout)
                r.raise_for_status()
                r.encoding = r.encoding or "utf-8"
                return r.text
            except Exception as exc:
                last_err = exc
                if attempt < self.retries:
                    time.sleep(min(2 * attempt, 5))
        raise RuntimeError(f"Fetch failed: {url} -> {last_err}")

    def _fetch_page(self, date_str: str) -> Optional[str]:
        url = f"{RESULTS_URL}?date={quote(date_str)}&sport={quote(SPORT_NAME)}"
        try:
            return self._fetch(url)
        except RuntimeError as exc:
            log.warning("Failed to fetch results for %s: %s", date_str, exc)
            return None

    # --- parse main matches from a single league block ---

    def _parse_main_matches(
        self,
        matches_div,
        league_name: str,
        date_str: str,
    ) -> List[Dict]:
        """Return list of {home_team, away_team, home_score, away_score}."""
        result: List[Dict] = []
        links = matches_div.find_all("a", href=re.compile(r"detail=\d+"))
        for link in links:
            text = link.get_text(strip=True)
            if " - " not in text:
                continue
            home, away = [x.strip() for x in text.split(" - ", 1)]
            u_tag = link.find_next("u")
            score_text = u_tag.get_text(strip=True) if u_tag else ""
            h, a = _score_match(score_text)
            result.append({
                "league": league_name,
                "home_team": home,
                "away_team": away,
                "home_score": h,
                "away_score": a,
            })
        return result

    # --- parse whole results page ---

    def parse_day(
        self,
        date_str: str,
        html: str,
    ) -> Tuple[List[Dict], List[Dict]]:
        """
        Parse one day's results page.
        Returns (main_matches, stat_pages) where stat_pages are dicts with
        stat_type, home_team, away_team, score_text, and detail_url.
        """
        soup = BeautifulSoup(html, "html.parser")
        main_matches: List[Dict] = []
        stat_pages: List[Dict] = []

        # Build a map to track stat blocks by the league without ". Статистика."
        stats_map: Dict[str, Dict] = {}  # normalised_name -> matches_div
        cc_divs = soup.find_all("div", id="cc")
        for cc in cc_divs:
            raw = cc.get_text(strip=True)
            low = raw.lower()

            # Detect stat block
            if ". статистика." in low and "игрового" not in low:
                base = low.replace(". статистика.", "").rstrip(".")
                next_div = cc.find_next_sibling("div")
                if next_div:
                    stats_map[base] = next_div
                continue

        # Parse main league blocks
        for cc in cc_divs:
            raw = cc.get_text(strip=True)
            low = raw.lower()

            # Skip stat / info blocks
            if "статистика" in low or "игрового дня" in low:
                continue

            # Check if this is a target league
            if not any(kw in low for kw in TARGET_LEAGUES_LOWER):
                continue

            next_div = cc.find_next_sibling("div")
            if not next_div:
                continue

            main_matches.extend(self._parse_main_matches(next_div, raw, date_str))

        # Parse stat blocks — find links with УГЛ, ЖК, удары in створ
        for cc in cc_divs:
            raw = cc.get_text(strip=True)
            low = raw.lower()

            # Only "Статистика." blocks (not "игрового дня")
            if ". статистика." not in low or "игрового" in low:
                continue

            next_div = cc.find_next_sibling("div")
            if not next_div:
                continue

            links = next_div.find_all("a", href=re.compile(r"detail=\d+"))
            for a in links:
                title = a.get_text(strip=True)
                try:
                    stat_type, home, away = _classify_stat_title(title)
                except ValueError:
                    continue

                u_tag = a.find_next("u")
                score_text = u_tag.get_text(strip=True) if u_tag else ""

                detail_url = a.get("href", "")
                if detail_url and not detail_url.startswith("http"):
                    detail_url = f"https://betz.su{detail_url}"

                stat_pages.append({
                    "stat_type": stat_type,
                    "home_team": home,
                    "away_team": away,
                    "score_text": score_text,
                    "detail_url": detail_url,
                })

        return main_matches, stat_pages

    # --- fetch detail page and parse ---

    def _parse_corners_detail(self, html: str) -> Dict:
        soup = BeautifulSoup(html, "html.parser")
        text = soup.get_text(" ", strip=True)

        # Score from title / header
        title_el = soup.select_one("title")
        title = title_el.get_text(strip=True) if title_el else ""

        # Result score: "7:2 (5:1)" from body text
        m = re.search(r"Результат[\s\S]{0,80}?(\d+)\s*:\s*(\d+)", text)
        if m:
            home, away = int(m.group(1)), int(m.group(2))
        else:
            # fallback: parse from title after team names, e.g. "16:30 5 Апреля"
            # try generic score pattern
            m2 = re.search(r"[(\s](\d+)\s*:\s*(\d+)[)]", text)  # HT score
            if m2:
                home, away = int(m2.group(1)), int(m2.group(2))
            else:
                home, away = None, None

        # HT score
        ht = _ht_score(text)

        over, under, line = _parse_tm_tb_odds(text)

        return {
            "corners_home": home,
            "corners_away": away,
            "corners_total": (home + away) if home is not None and away is not None else None,
            "corners_h1_home": ht[0] if ht else None,
            "corners_h1_away": ht[1] if ht else None,
            "corners_odds_over": over,
            "corners_odds_under": under,
            "corners_line": line,
        }

    def _parse_yc_detail(self, html: str) -> Dict:
        soup = BeautifulSoup(html, "html.parser")
        text = soup.get_text(" ", strip=True)

        # Score
        m = re.search(r"Результат[\s\S]{0,80}?(\d+)\s*:\s*(\d+)", text)
        if m:
            home, away = int(m.group(1)), int(m.group(2))
        else:
            home, away = None, None

        ht = _ht_score(text)
        over, under, line = _parse_tm_tb_odds(text)
        first_min = _first_yc_minute(text)
        last_min = _last_yc_minute(text)

        return {
            "yc_home": home,
            "yc_away": away,
            "yc_total": (home + away) if home is not None and away is not None else None,
            "yc_h1_home": ht[0] if ht else None,
            "yc_h1_away": ht[1] if ht else None,
            "yc_first_minute": first_min,
            "yc_last_minute": last_min,
            "yc_odds_over": over,
            "yc_odds_under": under,
            "yc_line": line,
        }

    def _parse_shots_detail(self, html: str) -> Dict:
        soup = BeautifulSoup(html, "html.parser")
        text = soup.get_text(" ", strip=True)

        m = re.search(r"Результат[\s\S]{0,80}?(\d+)\s*:\s*(\d+)", text)
        if m:
            home, away = int(m.group(1)), int(m.group(2))
        else:
            home, away = None, None

        over, under, line = _parse_tm_tb_odds(text)

        return {
            "shots_home": home,
            "shots_away": away,
            "shots_odds_over": over,
            "shots_odds_under": under,
            "shots_line": line,
        }

    DETAIL_PARSERS = {
        "corners": _parse_corners_detail,
        "yc": _parse_yc_detail,
        "shots": _parse_shots_detail,
    }

    # --- main loop ---

    def run(self, date_from: datetime, date_to: datetime) -> Tuple[int, int]:
        self._create_table()
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA journal_mode=WAL")

        day = date_from
        total_inserted = 0
        total_skipped = 0

        while day <= date_to:
            date_str_req = day.strftime("%d.%m.%Y")
            log.info("Processing matches %s", date_str_req)

            html = self._fetch_page(date_str_req)
            if not html:
                day += timedelta(days=1)
                time.sleep(self.delay)
                continue

            main_matches, stat_pages = self.parse_day(date_str_req, html)
            log.info(
                "Found %d main matches, %d stat pages with score for %s",
                len(main_matches), len(stat_pages), date_str_req,
            )

            # Group stat pages by (home_team, away_team)
            stats_by_match: Dict[Tuple[str, str], Dict[str, Dict]] = {}
            for sp in stat_pages:
                key = (sp["home_team"], sp["away_team"])
                if key not in stats_by_match:
                    stats_by_match[key] = {}
                stats_by_match[key][sp["stat_type"]] = sp

            # Process each main match
            for mm in main_matches:
                match_key = (mm["home_team"], mm["away_team"])
                match_date = day.strftime("%Y-%m-%d")

                # Start a blank row for this match
                row_data: Dict[str, object] = {
                    "league": mm["league"].replace(". Статистика", "").strip(),
                    "match_date": match_date,
                    "home_team": mm["home_team"],
                    "away_team": mm["away_team"],
                }

                # Merge stats
                if match_key in stats_by_match:
                    for stat_type, sp_data in stats_by_match[match_key].items():
                        detail_url = sp_data["detail_url"]
                        if not detail_url:
                            continue
                        log.info("  Fetching %s: %s %s", stat_type, mm["home_team"], mm["away_team"])
                        time.sleep(self.delay)
                        detail_html = ""
                        try:
                            detail_html = self._fetch(detail_url)
                        except RuntimeError as exc:
                            log.warning("  Failed to fetch %s detail: %s", stat_type, exc)

                        if detail_html:
                            parser_fn = self.DETAIL_PARSERS.get(stat_type)
                            if parser_fn:
                                parsed = parser_fn(self, detail_html)
                                row_data.update(parsed)

                inserted, skipped = self._save_single(conn, row_data)
                total_inserted += inserted
                total_skipped += skipped
                if inserted:
                    log.info(
                        "  INSERTED: %s | %s | C=%s/%s YC=%s/%s SH=%s/%s",
                        match_key[0] + " - " + match_key[1],
                        row_data.get("league", ""),
                        row_data.get("corners_home"), row_data.get("corners_away"),
                        row_data.get("yc_home"), row_data.get("yc_away"),
                        row_data.get("shots_home"), row_data.get("shots_away"),
                    )

            day += timedelta(days=1)
            time.sleep(self.delay)

        conn.close()
        log.info("TOTAL: +%d new, %d skipped", total_inserted, total_skipped)
        return total_inserted, total_skipped

    def _create_table(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute(CREATE_TABLE_SQL)
        conn.commit()
        # Add missing columns if table already existed but was created earlier
        existing_cols = {
            r[1]
            for r in conn.execute("PRAGMA table_info(backtest_football_stats)").fetchall()
        }
        optional_cols = [
            ("corners_h1_home", "INTEGER"),
            ("corners_h1_away", "INTEGER"),
        ]
        for col, ctype in optional_cols:
            if col not in existing_cols:
                conn.execute(f"ALTER TABLE backtest_football_stats ADD COLUMN {col} {ctype}")
        conn.commit()
        conn.close()

    @staticmethod
    def _save_single(conn, data: Dict) -> Tuple[int, int]:
        try:
            conn.execute(
                """
                INSERT INTO backtest_football_stats (
                    league, match_date, home_team, away_team,
                    corners_home, corners_away, corners_total,
                    corners_h1_home, corners_h1_away,
                    corners_odds_over, corners_odds_under, corners_line,
                    yc_home, yc_away, yc_total,
                    yc_first_minute, yc_last_minute,
                    yc_odds_over, yc_odds_under, yc_line,
                    shots_home, shots_away,
                    shots_odds_over, shots_odds_under, shots_line
                ) VALUES (
                    ?, ?, ?, ?,
                    ?, ?, ?,
                    ?, ?,
                    ?, ?, ?,
                    ?, ?, ?,
                    ?, ?,
                    ?, ?, ?,
                    ?, ?,
                    ?, ?, ?
                )
                """,
                (
                    data.get("league"),
                    data.get("match_date"),
                    data.get("home_team"),
                    data.get("away_team"),
                    data.get("corners_home"),
                    data.get("corners_away"),
                    data.get("corners_total"),
                    data.get("corners_h1_home"),
                    data.get("corners_h1_away"),
                    data.get("corners_odds_over"),
                    data.get("corners_odds_under"),
                    data.get("corners_line"),
                    data.get("yc_home"),
                    data.get("yc_away"),
                    data.get("yc_total"),
                    data.get("yc_first_minute"),
                    data.get("yc_last_minute"),
                    data.get("yc_odds_over"),
                    data.get("yc_odds_under"),
                    data.get("yc_line"),
                    data.get("shots_home"),
                    data.get("shots_away"),
                    data.get("shots_odds_over"),
                    data.get("shots_odds_under"),
                    data.get("shots_line"),
                ),
            )
            conn.commit()
            return 1, 0
        except sqlite3.IntegrityError:
            return 0, 1


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description="Парсер статистики футбола с betz.su (угловые, ЖК, удары в створ)"
    )
    ap.add_argument("--date-from", default="2021-08-01")
    ap.add_argument("--date-to", default=datetime.now().strftime("%Y-%m-%d"))
    ap.add_argument("--db", default=DB_PATH)
    ap.add_argument("--delay", type=float, default=0.3)
    ap.add_argument("--timeout", type=int, default=20)
    ap.add_argument("--retries", type=int, default=3)
    return ap.parse_args()


def main():
    args = parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    date_from = datetime.strptime(args.date_from, "%Y-%m-%d")
    date_to = datetime.strptime(args.date_to, "%Y-%m-%d")

    parser = BetzFootballStatsParser(
        db_path=args.db,
        delay=args.delay,
        timeout=args.timeout,
        retries=args.retries,
    )
    parser.run(date_from, date_to)


if __name__ == "__main__":
    main()
