#!/usr/bin/env python3
import sqlite3
from collections import defaultdict
from typing import Dict, List, Tuple, Any, Optional
import os
import argparse
import csv
from datetime import datetime

def get_conn(db_path: Optional[str] = None) -> sqlite3.Connection:
    """
    Get a connection to the database.
    
    Args:
        db_path: Optional path to the database file. If None, uses the default path.
        
    Returns:
        A connection to the database.
    """
    if db_path is None:
        # Default to project's main database
        db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "betagent.db")
    
    return sqlite3.connect(db_path)

def check_table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    """
    Check if a table exists in the database.
    
    Args:
        conn: Database connection
        table_name: Name of the table to check
        
    Returns:
        True if the table exists, False otherwise
    """
    cursor = conn.cursor()
    cursor.execute("""
        SELECT name FROM sqlite_master 
        WHERE type='table' AND name=?
    """, (table_name,))
    return cursor.fetchone() is not None

def fetch_backtest_matches(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    """Fetch matches from the backtest_matches table."""
    cursor = conn.cursor()
    
    # Check if the table exists
    if not check_table_exists(conn, "backtest_matches"):
        db_path = conn.execute("PRAGMA database_list").fetchone()[2]  # Get actual DB path
        raise ValueError(f"Table 'backtest_matches' does not exist in database: {db_path}")
    
    query = """
    SELECT 
        id, league, season, match_date, 
        home_team, away_team, home_score, away_score,
        odds_over_2_5, odds_under_2_5, odds_btts_yes, odds_btts_no
    FROM backtest_matches
    WHERE home_score IS NOT NULL 
      AND away_score IS NOT NULL
    ORDER BY match_date
    """
    cursor.execute(query)
    
    columns = [col[0] for col in cursor.description]
    results = []
    
    for row in cursor.fetchall():
        results.append(dict(zip(columns, row)))
    
    return results

def is_over_2_5(home_score: int, away_score: int) -> bool:
    """Check if the total goals is over 2.5."""
    return (home_score + away_score) > 2

def is_under_2_5(home_score: int, away_score: int) -> bool:
    """Check if the total goals is under 2.5."""
    return (home_score + away_score) < 3

def is_btts_yes(home_score: int, away_score: int) -> bool:
    """Check if both teams scored."""
    return home_score > 0 and away_score > 0

def is_btts_no(home_score: int, away_score: int) -> bool:
    """Check if at least one team didn't score."""
    return home_score == 0 or away_score == 0

def get_odds_bucket(odds: float) -> Optional[str]:
    """Get the odds bucket for the given odds."""
    if odds is None:
        return None
    if 1.50 <= odds < 1.80:
        return "1.50-1.79"
    elif 1.80 <= odds < 2.10:
        return "1.80-2.09"
    elif odds >= 2.10:
        return "2.10+"
    return None

def ensure_reports_dir(reports_dir: str) -> None:
    """Ensure the reports directory exists."""
    if not os.path.exists(reports_dir):
        os.makedirs(reports_dir)
        print(f"Created reports directory: {reports_dir}")

def calculate_metrics(results: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Calculate metrics for each market."""
    markets = {
        "OVER_2_5": {"odds_field": "odds_over_2_5", "check_func": is_over_2_5},
        "UNDER_2_5": {"odds_field": "odds_under_2_5", "check_func": is_under_2_5},
        "BTTS_YES": {"odds_field": "odds_btts_yes", "check_func": is_btts_yes},
        "BTTS_NO": {"odds_field": "odds_btts_no", "check_func": is_btts_no}
    }
    
    # Initialize metrics dictionaries
    metrics = {
        "overall": defaultdict(lambda: {
            "bets": 0, "wins": 0, "losses": 0, "profit": 0, "total_odds": 0
        }),
        "by_league": defaultdict(lambda: defaultdict(lambda: {
            "bets": 0, "wins": 0, "losses": 0, "profit": 0, "total_odds": 0
        })),
        "by_season": defaultdict(lambda: defaultdict(lambda: {
            "bets": 0, "wins": 0, "losses": 0, "profit": 0, "total_odds": 0
        })),
        "by_odds_bucket": defaultdict(lambda: defaultdict(lambda: {
            "bets": 0, "wins": 0, "losses": 0, "profit": 0, "total_odds": 0
        }))
    }
    
    # Process each match
    for match in results:
        home_score = match.get("home_score")
        away_score = match.get("away_score")
        
        if home_score is None or away_score is None:
            continue
        
        home_score = int(home_score)
        away_score = int(away_score)
        league = match.get("league", "Unknown")
        season = match.get("season", "Unknown")
        
        # Process each market
        for market_name, market_info in markets.items():
            odds_field = market_info["odds_field"]
            check_func = market_info["check_func"]
            odds = match.get(odds_field)
            
            if odds is None:
                continue
                
            odds = float(odds)
            odds_bucket = get_odds_bucket(odds)
            if odds_bucket is None:
                continue
                
            is_win = check_func(home_score, away_score)
            profit = odds - 1 if is_win else -1
            
            # Update overall metrics
            metrics["overall"][market_name]["bets"] += 1
            metrics["overall"][market_name]["wins"] += 1 if is_win else 0
            metrics["overall"][market_name]["losses"] += 0 if is_win else 1
            metrics["overall"][market_name]["profit"] += profit
            metrics["overall"][market_name]["total_odds"] += odds
            
            # Update by league metrics
            metrics["by_league"][league][market_name]["bets"] += 1
            metrics["by_league"][league][market_name]["wins"] += 1 if is_win else 0
            metrics["by_league"][league][market_name]["losses"] += 0 if is_win else 1
            metrics["by_league"][league][market_name]["profit"] += profit
            metrics["by_league"][league][market_name]["total_odds"] += odds
            
            # Update by season metrics
            metrics["by_season"][season][market_name]["bets"] += 1
            metrics["by_season"][season][market_name]["wins"] += 1 if is_win else 0
            metrics["by_season"][season][market_name]["losses"] += 0 if is_win else 1
            metrics["by_season"][season][market_name]["profit"] += profit
            metrics["by_season"][season][market_name]["total_odds"] += odds
            
            # Update by odds bucket metrics
            metrics["by_odds_bucket"][odds_bucket][market_name]["bets"] += 1
            metrics["by_odds_bucket"][odds_bucket][market_name]["wins"] += 1 if is_win else 0
            metrics["by_odds_bucket"][odds_bucket][market_name]["losses"] += 0 if is_win else 1
            metrics["by_odds_bucket"][odds_bucket][market_name]["profit"] += profit
            metrics["by_odds_bucket"][odds_bucket][market_name]["total_odds"] += odds
    
    return metrics

def enrich_metrics(metrics: Dict[str, Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """Enrich metrics with calculated fields and convert to sortable lists."""
    enriched = {
        "overall": [],
        "by_league": [],
        "by_season": [],
        "by_odds_bucket": []
    }
    
    # Process overall metrics
    for market, data in metrics["overall"].items():
        if data["bets"] > 0:
            hit_rate = data["wins"] / data["bets"] if data["bets"] > 0 else 0
            avg_odds = data["total_odds"] / data["bets"] if data["bets"] > 0 else 0
            roi = data["profit"] / data["bets"] if data["bets"] > 0 else 0
            
            enriched["overall"].append({
                "market": market,
                "bets": data["bets"],
                "wins": data["wins"],
                "losses": data["losses"],
                "hit_rate": hit_rate,
                "avg_odds": avg_odds,
                "profit": data["profit"],
                "roi": roi
            })
    
    # Process by league metrics
    for league, markets in metrics["by_league"].items():
        for market, data in markets.items():
            if data["bets"] > 0:
                hit_rate = data["wins"] / data["bets"] if data["bets"] > 0 else 0
                avg_odds = data["total_odds"] / data["bets"] if data["bets"] > 0 else 0
                roi = data["profit"] / data["bets"] if data["bets"] > 0 else 0
                
                enriched["by_league"].append({
                    "league": league,
                    "market": market,
                    "bets": data["bets"],
                    "wins": data["wins"],
                    "losses": data["losses"],
                    "hit_rate": hit_rate,
                    "avg_odds": avg_odds,
                    "profit": data["profit"],
                    "roi": roi
                })
    
    # Process by season metrics
    for season, markets in metrics["by_season"].items():
        for market, data in markets.items():
            if data["bets"] > 0:
                hit_rate = data["wins"] / data["bets"] if data["bets"] > 0 else 0
                avg_odds = data["total_odds"] / data["bets"] if data["bets"] > 0 else 0
                roi = data["profit"] / data["bets"] if data["bets"] > 0 else 0
                
                enriched["by_season"].append({
                    "season": season,
                    "market": market,
                    "bets": data["bets"],
                    "wins": data["wins"],
                    "losses": data["losses"],
                    "hit_rate": hit_rate,
                    "avg_odds": avg_odds,
                    "profit": data["profit"],
                    "roi": roi
                })
    
    # Process by odds bucket metrics
    for bucket, markets in metrics["by_odds_bucket"].items():
        for market, data in markets.items():
            if data["bets"] > 0:
                hit_rate = data["wins"] / data["bets"] if data["bets"] > 0 else 0
                avg_odds = data["total_odds"] / data["bets"] if data["bets"] > 0 else 0
                roi = data["profit"] / data["bets"] if data["bets"] > 0 else 0
                
                enriched["by_odds_bucket"].append({
                    "odds_bucket": bucket,
                    "market": market,
                    "bets": data["bets"],
                    "wins": data["wins"],
                    "losses": data["losses"],
                    "hit_rate": hit_rate,
                    "avg_odds": avg_odds,
                    "profit": data["profit"],
                    "roi": roi
                })
    
    # Sort all lists by ROI descending
    for key in enriched:
        enriched[key] = sorted(enriched[key], key=lambda x: x["roi"], reverse=True)
    
    return enriched

def print_metrics_table(title: str, data: List[Dict[str, Any]], columns: List[Tuple[str, str, int]]):
    """Print a formatted table of metrics."""
    print(f"\n{title}")
    print("-" * 100)
    
    # Print header
    header_parts = []
    for col_name, _, col_width in columns:
        header_parts.append(col_name.ljust(col_width))
    print(" | ".join(header_parts))
    print("-" * 100)
    
    # Print rows
    for row in data:
        row_parts = []
        for col_key, col_format, col_width in columns:
            value = row.get(col_key, "")
            if isinstance(value, (int, float)) and col_format:
                formatted_value = col_format.format(value)
            else:
                formatted_value = str(value)
            row_parts.append(formatted_value.ljust(col_width))
        print(" | ".join(row_parts))
    
    print("-" * 100)
    print(f"Total rows: {len(data)}")

def save_metrics_to_csv(data: List[Dict[str, Any]], file_path: str, columns: List[Tuple[str, str, int]]) -> None:
    """Save metrics to a CSV file."""
    with open(file_path, 'w', newline='') as csvfile:
        fieldnames = [col[0] for col in columns]
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        
        # Write header
        writer.writeheader()
        
        # Write rows
        for row in data:
            # Format values
            formatted_row = {}
            for col_key, col_format, _ in columns:
                value = row.get(col_key, "")
                if isinstance(value, (int, float)) and col_format:
                    formatted_row[col_key] = col_format.format(value)
                else:
                    formatted_row[col_key] = value
            writer.writerow(formatted_row)

def generate_markdown_summary(
    timestamp: str,
    db_path: str,
    match_count: int,
    overall_metrics: List[Dict[str, Any]],
    league_metrics: List[Dict[str, Any]],
    season_metrics: List[Dict[str, Any]],
    odds_bucket_metrics: List[Dict[str, Any]],
    file_path: str
) -> None:
    """Generate a markdown summary of the backtest results."""
    with open(file_path, 'w') as f:
        f.write(f"# Totals Backtest Summary\n\n")
        f.write(f"**Run timestamp:** {timestamp}\n\n")
        f.write(f"**Database:** {db_path}\n\n")
        f.write(f"**Total matches analyzed:** {match_count}\n\n")
        
        # Top markets by ROI
        f.write("## Top Markets by ROI\n\n")
        f.write("| Market | Bets | Win Rate | Avg Odds | Profit | ROI |\n")
        f.write("|--------|------|----------|----------|--------|-----|\n")
        for row in overall_metrics[:5]:  # Top 5
            f.write(f"| {row['market']} | {row['bets']} | {row['hit_rate']:.2%} | {row['avg_odds']:.2f} | {row['profit']:.2f} | {row['roi']:.2%} |\n")
        f.write("\n")
        
        # Top league+market combinations by ROI
        f.write("## Top League+Market Combinations by ROI\n\n")
        f.write("| League | Market | Bets | Win Rate | Avg Odds | Profit | ROI |\n")
        f.write("|--------|--------|------|----------|----------|--------|-----|\n")
        for row in league_metrics[:10]:  # Top 10
            f.write(f"| {row['league']} | {row['market']} | {row['bets']} | {row['hit_rate']:.2%} | {row['avg_odds']:.2f} | {row['profit']:.2f} | {row['roi']:.2%} |\n")
        f.write("\n")
        
        # Top season+market combinations by ROI
        f.write("## Top Season+Market Combinations by ROI\n\n")
        f.write("| Season | Market | Bets | Win Rate | Avg Odds | Profit | ROI |\n")
        f.write("|--------|--------|------|----------|----------|--------|-----|\n")
        for row in season_metrics[:10]:  # Top 10
            f.write(f"| {row['season']} | {row['market']} | {row['bets']} | {row['hit_rate']:.2%} | {row['avg_odds']:.2f} | {row['profit']:.2f} | {row['roi']:.2%} |\n")
        f.write("\n")
        
        # Top odds bucket+market combinations by ROI
        f.write("## Top Odds Bucket+Market Combinations by ROI\n\n")
        f.write("| Odds Bucket | Market | Bets | Win Rate | Avg Odds | Profit | ROI |\n")
        f.write("|------------|--------|------|----------|----------|--------|-----|\n")
        for row in odds_bucket_metrics[:10]:  # Top 10
            f.write(f"| {row['odds_bucket']} | {row['market']} | {row['bets']} | {row['hit_rate']:.2%} | {row['avg_odds']:.2f} | {row['profit']:.2f} | {row['roi']:.2%} |\n")

def main():
    """Main function to run the backtest."""
    # Parse command line arguments
    parser = argparse.ArgumentParser(description="Run backtest for totals and BTTS markets")
    parser.add_argument("--db", type=str, help="Path to the database file")
    parser.add_argument("--reports-dir", type=str, default="/root/betagent/reports", 
                        help="Directory to save reports (default: /root/betagent/reports)")
    args = parser.parse_args()
    
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    run_timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    print(f"Starting totals backtest at {run_timestamp}")
    
    try:
        conn = get_conn(args.db)
        db_path = conn.execute("PRAGMA database_list").fetchone()[2]  # Get actual DB path
        print(f"Using database: {db_path}")
        
        matches = fetch_backtest_matches(conn)
        print(f"Loaded {len(matches)} matches from database")
    except Exception as e:
        print(f"Error: {e}")
        return 1
    
    metrics = calculate_metrics(matches)
    enriched_metrics = enrich_metrics(metrics)
    
    # Define column formats for different tables
    overall_columns = [
        ("Market", "", 10),
        ("Bets", "", 6),
        ("Wins", "", 6),
        ("Losses", "", 6),
        ("Hit Rate", "{:.2%}", 10),
        ("Avg Odds", "{:.2f}", 10),
        ("Profit", "{:.2f}", 10),
        ("ROI", "{:.2%}", 10)
    ]
    
    league_columns = [
        ("League", "", 20),
        ("Market", "", 10),
        ("Bets", "", 6),
        ("Wins", "", 6),
        ("Losses", "", 6),
        ("Hit Rate", "{:.2%}", 10),
        ("Avg Odds", "{:.2f}", 10),
        ("Profit", "{:.2f}", 10),
        ("ROI", "{:.2%}", 10)
    ]
    
    season_columns = [
        ("Season", "", 10),
        ("Market", "", 10),
        ("Bets", "", 6),
        ("Wins", "", 6),
        ("Losses", "", 6),
        ("Hit Rate", "{:.2%}", 10),
        ("Avg Odds", "{:.2f}", 10),
        ("Profit", "{:.2f}", 10),
        ("ROI", "{:.2%}", 10)
    ]
    
    odds_bucket_columns = [
        ("Odds Bucket", "", 12),
        ("Market", "", 10),
        ("Bets", "", 6),
        ("Wins", "", 6),
        ("Losses", "", 6),
        ("Hit Rate", "{:.2%}", 10),
        ("Avg Odds", "{:.2f}", 10),
        ("Profit", "{:.2f}", 10),
        ("ROI", "{:.2%}", 10)
    ]
    
    # Print tables
    print_metrics_table("OVERALL METRICS BY MARKET", enriched_metrics["overall"], overall_columns)
    print_metrics_table("METRICS BY LEAGUE AND MARKET", enriched_metrics["by_league"], league_columns)
    print_metrics_table("METRICS BY SEASON AND MARKET", enriched_metrics["by_season"], season_columns)
    print_metrics_table("METRICS BY ODDS BUCKET AND MARKET", enriched_metrics["by_odds_bucket"], odds_bucket_columns)
    
    # Save reports
    ensure_reports_dir(args.reports_dir)
    
    # Define file paths
    overall_csv = os.path.join(args.reports_dir, f"totals_backtest_overall_{timestamp}.csv")
    league_csv = os.path.join(args.reports_dir, f"totals_backtest_league_{timestamp}.csv")
    season_csv = os.path.join(args.reports_dir, f"totals_backtest_season_{timestamp}.csv")
    odds_bucket_csv = os.path.join(args.reports_dir, f"totals_backtest_odds_bucket_{timestamp}.csv")
    summary_md = os.path.join(args.reports_dir, f"totals_backtest_summary_{timestamp}.md")
    
    # Save CSV files
    save_metrics_to_csv(enriched_metrics["overall"], overall_csv, overall_columns)
    save_metrics_to_csv(enriched_metrics["by_league"], league_csv, league_columns)
    save_metrics_to_csv(enriched_metrics["by_season"], season_csv, season_columns)
    save_metrics_to_csv(enriched_metrics["by_odds_bucket"], odds_bucket_csv, odds_bucket_columns)
    
    # Generate markdown summary
    generate_markdown_summary(
        run_timestamp,
        db_path,
        len(matches),
        enriched_metrics["overall"],
        enriched_metrics["by_league"],
        enriched_metrics["by_season"],
        enriched_metrics["by_odds_bucket"],
        summary_md
    )
    
    # Print file paths
    print("\nReports saved to:")
    print(f"  - {overall_csv}")
    print(f"  - {league_csv}")
    print(f"  - {season_csv}")
    print(f"  - {odds_bucket_csv}")
    print(f"  - {summary_md}")
    
    conn.close()
    print(f"\nBacktest completed at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

if __name__ == "__main__":
    main()
