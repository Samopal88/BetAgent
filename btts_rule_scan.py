#!/usr/bin/env python3
import sqlite3
import os
import argparse
import csv
from collections import defaultdict
from typing import Dict, List, Tuple, Any, Optional
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

def ensure_reports_dir(reports_dir: str) -> None:
    """Ensure the reports directory exists."""
    if not os.path.exists(reports_dir):
        os.makedirs(reports_dir)
        print(f"Created reports directory: {reports_dir}")

def fetch_matches(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
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
        odds_btts_yes
    FROM backtest_matches
    WHERE home_score IS NOT NULL 
      AND away_score IS NOT NULL
      AND odds_btts_yes IS NOT NULL
    ORDER BY match_date
    """
    cursor.execute(query)
    
    columns = [col[0] for col in cursor.description]
    results = []
    
    for row in cursor.fetchall():
        results.append(dict(zip(columns, row)))
    
    return results

def prepare_data(matches: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Prepare data for analysis by adding BTTS result and form features.
    
    Args:
        matches: List of match dictionaries
        
    Returns:
        List of enriched match dictionaries
    """
    # Sort matches by date to ensure proper order for form calculation
    matches = sorted(matches, key=lambda x: x.get('match_date', ''))
    
    # Add BTTS result
    for match in matches:
        home_score = int(match.get('home_score', 0))
        away_score = int(match.get('away_score', 0))
        match['result_btts'] = 1 if home_score > 0 and away_score > 0 else 0
    
    # Create team history dictionaries
    team_history = defaultdict(list)
    
    # First pass: collect team history
    for match in matches:
        home_team = match.get('home_team')
        away_team = match.get('away_team')
        home_score = int(match.get('home_score', 0))
        away_score = int(match.get('away_score', 0))
        match_date = match.get('match_date')
        
        # Add to home team history
        team_history[home_team].append({
            'date': match_date,
            'is_home': True,
            'goals_scored': home_score,
            'goals_conceded': away_score,
            'opponent': away_team
        })
        
        # Add to away team history
        team_history[away_team].append({
            'date': match_date,
            'is_home': False,
            'goals_scored': away_score,
            'goals_conceded': home_score,
            'opponent': home_team
        })
    
    # Second pass: calculate form features
    for match in matches:
        home_team = match.get('home_team')
        away_team = match.get('away_team')
        match_date = match.get('match_date')
        
        # Get previous matches for each team
        home_prev = [m for m in team_history[home_team] if m['date'] < match_date]
        away_prev = [m for m in team_history[away_team] if m['date'] < match_date]
        
        # Calculate form features using last 5 matches
        home_prev = home_prev[-5:] if len(home_prev) >= 5 else home_prev
        away_prev = away_prev[-5:] if len(away_prev) >= 5 else away_prev
        
        # Calculate averages
        match['avg_goals_scored_last5_home'] = sum(m['goals_scored'] for m in home_prev) / len(home_prev) if home_prev else 0
        match['avg_goals_conceded_last5_home'] = sum(m['goals_conceded'] for m in home_prev) / len(home_prev) if home_prev else 0
        match['avg_goals_scored_last5_away'] = sum(m['goals_scored'] for m in away_prev) / len(away_prev) if away_prev else 0
        match['avg_goals_conceded_last5_away'] = sum(m['goals_conceded'] for m in away_prev) / len(away_prev) if away_prev else 0
        
        # Optional: total goals average
        match['total_goals_avg_last5'] = (
            (sum(m['goals_scored'] + m['goals_conceded'] for m in home_prev) + 
             sum(m['goals_scored'] + m['goals_conceded'] for m in away_prev)) / 
            (len(home_prev) + len(away_prev))
        ) if home_prev and away_prev else 0
    
    return matches

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

def backtest_rules(
    matches: List[Dict[str, Any]], 
    min_bets: int = 100, 
    min_roi: float = 3.0
) -> List[Dict[str, Any]]:
    """
    Backtest rule combinations and return profitable ones.
    
    Args:
        matches: List of enriched match dictionaries
        min_bets: Minimum number of bets for a rule to be considered
        min_roi: Minimum ROI percentage for a rule to be considered
        
    Returns:
        List of rule results sorted by ROI
    """
    # Define rule parameters
    leagues = ['EPL', 'BL1', 'SA', 'PD', 'FL1']
    form_scored_thresholds = [1.0, 1.2, 1.5]
    form_conceded_thresholds = [0.8, 1.0, 1.2]
    
    results = []
    
    # Test each combination
    for league in leagues:
        # Filter matches by league
        league_matches = [m for m in matches if m.get('league') == league]
        
        # Skip if not enough matches
        if len(league_matches) < min_bets:
            continue
        
        for form_scored in form_scored_thresholds:
            for form_conceded in form_conceded_thresholds:
                # Test each odds bucket separately
                for odds_min, odds_max, bucket_name in [
                    (1.5, 1.8, "1.50-1.79"),
                    (1.8, 2.1, "1.80-2.09"),
                    (2.1, 100, "2.10+")
                ]:
                    # Apply rule filters
                    rule_matches = [
                        m for m in league_matches 
                        if (
                            odds_min <= float(m.get('odds_btts_yes', 0)) < odds_max and
                            m.get('avg_goals_scored_last5_home', 0) >= form_scored and
                            m.get('avg_goals_scored_last5_away', 0) >= form_scored and
                            m.get('avg_goals_conceded_last5_home', 0) >= form_conceded and
                            m.get('avg_goals_conceded_last5_away', 0) >= form_conceded
                        )
                    ]
                    
                    # Skip if not enough bets
                    if len(rule_matches) < min_bets:
                        continue
                    
                    # Calculate metrics
                    bets = len(rule_matches)
                    wins = sum(1 for m in rule_matches if m.get('result_btts') == 1)
                    losses = bets - wins
                    hit_rate = wins / bets if bets > 0 else 0
                    avg_odds = sum(float(m.get('odds_btts_yes', 0)) for m in rule_matches) / bets if bets > 0 else 0
                    profit = sum((float(m.get('odds_btts_yes', 0)) - 1) if m.get('result_btts') == 1 else -1 for m in rule_matches)
                    roi = (profit / bets) * 100 if bets > 0 else 0
                    
                    # Check if rule meets criteria
                    if roi > min_roi:
                        results.append({
                            'league': league,
                            'odds_bucket': bucket_name,
                            'form_scored_threshold': form_scored,
                            'form_conceded_threshold': form_conceded,
                            'bets': bets,
                            'wins': wins,
                            'losses': losses,
                            'hit_rate': hit_rate,
                            'avg_odds': avg_odds,
                            'profit': profit,
                            'roi': roi
                        })
    
    # Sort by ROI descending, then by bets descending
    results.sort(key=lambda x: (-x['roi'], -x['bets']))
    
    return results

def print_results(results: List[Dict[str, Any]], limit: int = 20):
    """Print top rule results."""
    print(f"\nTOP {min(limit, len(results))} BTTS RULES BY ROI")
    print("-" * 100)
    
    # Print header
    header = "League | Odds Bucket | Form Scored | Form Conceded | Bets | Hit Rate | Avg Odds | Profit | ROI"
    print(header)
    print("-" * 100)
    
    # Print rows
    for i, rule in enumerate(results[:limit], 1):
        row = (
            f"{rule['league']:<6} | "
            f"{rule['odds_bucket']:<11} | "
            f"{rule['form_scored_threshold']:<11} | "
            f"{rule['form_conceded_threshold']:<13} | "
            f"{rule['bets']:<4} | "
            f"{rule['hit_rate']:.2%} | "
            f"{rule['avg_odds']:.2f} | "
            f"{rule['profit']:.2f} | "
            f"{rule['roi']:.2%}"
        )
        print(row)
    
    print("-" * 100)
    print(f"Total rules found: {len(results)}")

def save_results_to_csv(results: List[Dict[str, Any]], file_path: str):
    """Save rule results to a CSV file."""
    with open(file_path, 'w', newline='') as csvfile:
        fieldnames = [
            'league', 'odds_bucket', 'form_scored_threshold', 'form_conceded_threshold',
            'bets', 'wins', 'losses', 'hit_rate', 'avg_odds', 'profit', 'roi'
        ]
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        
        writer.writeheader()
        for rule in results:
            # Format values
            formatted_rule = rule.copy()
            formatted_rule['hit_rate'] = f"{rule['hit_rate']:.2%}"
            formatted_rule['avg_odds'] = f"{rule['avg_odds']:.2f}"
            formatted_rule['profit'] = f"{rule['profit']:.2f}"
            formatted_rule['roi'] = f"{rule['roi']:.2%}"
            writer.writerow(formatted_rule)

def generate_markdown_summary(
    timestamp: str,
    db_path: str,
    match_count: int,
    results: List[Dict[str, Any]],
    file_path: str
):
    """Generate a markdown summary of the rule scan results."""
    with open(file_path, 'w') as f:
        f.write(f"# BTTS Rule Scan Summary\n\n")
        f.write(f"**Run timestamp:** {timestamp}\n\n")
        f.write(f"**Database:** {db_path}\n\n")
        f.write(f"**Total matches analyzed:** {match_count}\n\n")
        f.write(f"**Total profitable rules found:** {len(results)}\n\n")
        
        # Top rules by ROI
        f.write("## Top 20 BTTS Rules by ROI\n\n")
        f.write("| League | Odds Bucket | Form Scored | Form Conceded | Bets | Hit Rate | Avg Odds | Profit | ROI |\n")
        f.write("|--------|-------------|------------|--------------|------|----------|----------|--------|-----|\n")
        
        for rule in results[:20]:
            f.write(
                f"| {rule['league']} | "
                f"{rule['odds_bucket']} | "
                f"{rule['form_scored_threshold']} | "
                f"{rule['form_conceded_threshold']} | "
                f"{rule['bets']} | "
                f"{rule['hit_rate']:.2%} | "
                f"{rule['avg_odds']:.2f} | "
                f"{rule['profit']:.2f} | "
                f"{rule['roi']:.2%} |\n"
            )
        
        # League breakdown
        f.write("\n## Rules by League\n\n")
        league_counts = {}
        for rule in results:
            league = rule['league']
            league_counts[league] = league_counts.get(league, 0) + 1
        
        f.write("| League | Rule Count |\n")
        f.write("|--------|------------|\n")
        for league, count in sorted(league_counts.items(), key=lambda x: -x[1]):
            f.write(f"| {league} | {count} |\n")
        
        # Odds bucket breakdown
        f.write("\n## Rules by Odds Bucket\n\n")
        bucket_counts = {}
        for rule in results:
            bucket = rule['odds_bucket']
            bucket_counts[bucket] = bucket_counts.get(bucket, 0) + 1
        
        f.write("| Odds Bucket | Rule Count |\n")
        f.write("|-------------|------------|\n")
        for bucket, count in sorted(bucket_counts.items(), key=lambda x: -x[1]):
            f.write(f"| {bucket} | {count} |\n")

def main():
    """Main function to run the BTTS rule scan."""
    # Parse command line arguments
    parser = argparse.ArgumentParser(description="Scan for profitable BTTS rules")
    parser.add_argument("--db", type=str, help="Path to the database file")
    parser.add_argument("--reports-dir", type=str, default="/root/betagent/reports", 
                        help="Directory to save reports (default: /root/betagent/reports)")
    parser.add_argument("--min-bets", type=int, default=100,
                        help="Minimum number of bets for a rule (default: 100)")
    parser.add_argument("--min-roi", type=float, default=3.0,
                        help="Minimum ROI percentage for a rule (default: 3.0)")
    args = parser.parse_args()
    
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    run_timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    print(f"Starting BTTS rule scan at {run_timestamp}")
    
    try:
        conn = get_conn(args.db)
        db_path = conn.execute("PRAGMA database_list").fetchone()[2]  # Get actual DB path
        print(f"Using database: {db_path}")
        
        # Step 1: Fetch and prepare data
        print("Fetching matches...")
        matches = fetch_matches(conn)
        print(f"Loaded {len(matches)} matches from database")
        
        print("Preparing data and calculating form features...")
        enriched_matches = prepare_data(matches)
        print(f"Data preparation complete")
        
        # Step 2 & 3: Define rules and backtest
        print(f"Backtesting rule combinations (min bets: {args.min_bets}, min ROI: {args.min_roi}%)...")
        rule_results = backtest_rules(enriched_matches, args.min_bets, args.min_roi)
        print(f"Found {len(rule_results)} profitable rules")
        
        # Step 4 & 5: Print and save results
        print_results(rule_results)
        
        # Save reports
        ensure_reports_dir(args.reports_dir)
        
        # Define file paths
        csv_path = os.path.join(args.reports_dir, f"btts_rule_scan_{timestamp}.csv")
        md_path = os.path.join(args.reports_dir, f"btts_rule_scan_{timestamp}.md")
        
        # Save CSV file
        save_results_to_csv(rule_results, csv_path)
        
        # Generate markdown summary
        generate_markdown_summary(
            run_timestamp,
            db_path,
            len(matches),
            rule_results,
            md_path
        )
        
        # Print file paths
        print("\nReports saved to:")
        print(f"  - {csv_path}")
        print(f"  - {md_path}")
        
    except Exception as e:
        print(f"Error: {e}")
        return 1
    
    conn.close()
    print(f"\nBTTS rule scan completed at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

if __name__ == "__main__":
    main()
