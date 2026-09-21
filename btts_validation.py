#!/usr/bin/env python3
import sqlite3
import os
import argparse
import csv
from collections import defaultdict
from typing import Dict, List, Tuple, Any, Optional
from datetime import datetime
import itertools
import sys

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
      AND league IN ('BL1', 'EPL', 'FL1')
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
        
        # Extract year from match date for train/test split
        if match_date:
            match['year'] = match_date[:4]  # Assuming format YYYY-MM-DD
    
    return matches

def simulate_bankroll(
    matches: List[Dict[str, Any]], 
    starting_bankroll: float, 
    flat_stake: float = None,
    pct_stake: float = None,
    mode: str = "flat_1000"
) -> Dict[str, Any]:
    """
    Simulate bankroll evolution for a series of bets.
    
    Args:
        matches: List of match dictionaries with results
        starting_bankroll: Initial bankroll amount
        flat_stake: Fixed stake amount per bet (if using flat staking)
        pct_stake: Percentage of bankroll to stake per bet (if using percentage staking)
        mode: Staking mode identifier
        
    Returns:
        Dictionary with bankroll metrics
    """
    bankroll = starting_bankroll
    bankroll_history = [bankroll]
    result_sequence = []
    current_streak = {'type': None, 'length': 0}
    max_winning_streak = 0
    max_losing_streak = 0
    total_staked = 0
    
    # Sort matches by date
    sorted_matches = sorted(matches, key=lambda x: x.get('match_date', ''))
    
    # For monthly analysis
    monthly_data = []
    current_month = None
    month_start_bankroll = bankroll
    month_bets = 0
    month_wins = 0
    month_profit = 0
    month_peak = bankroll
    month_min = bankroll
    
    for match in sorted_matches:
        is_win = match.get('result_btts') == 1
        odds = float(match.get('odds_btts_yes', 0))
        match_date = match.get('match_date', '')
        match_month = match_date[:7] if match_date else ''  # YYYY-MM
        
        # Check if we're in a new month
        if match_month and match_month != current_month:
            if current_month:  # Save previous month data
                monthly_data.append({
                    'month': current_month,
                    'bankroll_start': month_start_bankroll,
                    'bankroll_end': bankroll,
                    'bets': month_bets,
                    'wins': month_wins,
                    'losses': month_bets - month_wins,
                    'profit': month_profit,
                    'roi': (month_profit / month_bets) * 100 if month_bets > 0 else 0,
                    'drawdown_currency': month_peak - month_min,
                    'drawdown_percent': ((month_peak - month_min) / month_peak) * 100 if month_peak > 0 else 0
                })
            
            # Reset for new month
            current_month = match_month
            month_start_bankroll = bankroll
            month_bets = 0
            month_wins = 0
            month_profit = 0
            month_peak = bankroll
            month_min = bankroll
        
        # Determine stake based on mode
        if pct_stake is not None:
            stake = bankroll * pct_stake / 100
        else:
            stake = flat_stake
        
        total_staked += stake
        
        # Update bankroll
        if is_win:
            profit = stake * (odds - 1)
            bankroll += profit
            result_sequence.append(1)
            month_profit += profit
            month_wins += 1
            
            # Update streak
            if current_streak['type'] == 'win':
                current_streak['length'] += 1
            else:
                current_streak = {'type': 'win', 'length': 1}
            
            max_winning_streak = max(max_winning_streak, current_streak['length'])
        else:
            bankroll -= stake
            result_sequence.append(-1)
            month_profit -= stake
            
            # Update streak
            if current_streak['type'] == 'loss':
                current_streak['length'] += 1
            else:
                current_streak = {'type': 'loss', 'length': 1}
            
            max_losing_streak = max(max_losing_streak, current_streak['length'])
        
        bankroll_history.append(bankroll)
        month_bets += 1
        month_peak = max(month_peak, bankroll)
        month_min = min(month_min, bankroll)
        
        # Add bankroll to match for analysis
        match['bankroll'] = bankroll
    
    # Add the last month if there was any data
    if current_month:
        monthly_data.append({
            'month': current_month,
            'bankroll_start': month_start_bankroll,
            'bankroll_end': bankroll,
            'bets': month_bets,
            'wins': month_wins,
            'losses': month_bets - month_wins,
            'profit': month_profit,
            'roi': (month_profit / month_bets) * 100 if month_bets > 0 else 0,
            'drawdown_currency': month_peak - month_min,
            'drawdown_percent': ((month_peak - month_min) / month_peak) * 100 if month_peak > 0 else 0
        })
    
    # Calculate drawdown
    peak = starting_bankroll
    drawdowns = []
    current_drawdown = 0
    
    for value in bankroll_history:
        if value > peak:
            peak = value
            current_drawdown = 0
        else:
            current_drawdown = peak - value
            drawdowns.append(current_drawdown)
    
    max_drawdown_currency = max(drawdowns) if drawdowns else 0
    max_drawdown_percent = (max_drawdown_currency / peak) * 100 if peak > 0 else 0
    
    # Find best and worst months
    if monthly_data:
        worst_month = min(monthly_data, key=lambda x: x['profit'])
        best_month = max(monthly_data, key=lambda x: x['profit'])
        worst_month_profit = worst_month['profit']
        best_month_profit = best_month['profit']
    else:
        worst_month_profit = 0
        best_month_profit = 0
    
    # Calculate yield
    yield_pct = (bankroll - starting_bankroll) / total_staked * 100 if total_staked > 0 else 0
    
    return {
        'mode': mode,
        'starting_bankroll': starting_bankroll,
        'ending_bankroll': bankroll,
        'net_profit_currency': bankroll - starting_bankroll,
        'bankroll_history': bankroll_history,
        'max_drawdown_currency': max_drawdown_currency,
        'max_drawdown_percent': max_drawdown_percent,
        'max_winning_streak': max_winning_streak,
        'max_losing_streak': max_losing_streak,
        'monthly_data': monthly_data,
        'worst_month_profit': worst_month_profit,
        'best_month_profit': best_month_profit,
        'total_staked': total_staked,
        'yield_pct': yield_pct
    }

def simulate_multiple_staking_modes(
    matches: List[Dict[str, Any]], 
    starting_bankroll: float = 100000,
    flat_stake: float = 1000
) -> Dict[str, Dict[str, Any]]:
    """
    Simulate multiple staking modes on the same matches.
    
    Args:
        matches: List of match dictionaries with results
        starting_bankroll: Initial bankroll amount
        flat_stake: Fixed stake amount for flat staking mode
        
    Returns:
        Dictionary with results for each staking mode
    """
    staking_modes = {
        "flat_1000": {"type": "flat", "stake": flat_stake},
        "pct_0_75": {"type": "percentage", "stake": 0.75},
        "pct_1_00": {"type": "percentage", "stake": 1.00},
        "pct_1_25": {"type": "percentage", "stake": 1.25},
        "pct_1_50": {"type": "percentage", "stake": 1.50}
    }
    
    results = {}
    
    # Create a deep copy of matches for each mode to avoid cross-contamination
    for mode_name, mode_config in staking_modes.items():
        # Create a deep copy of matches to avoid cross-contamination between modes
        mode_matches = []
        for match in matches:
            mode_matches.append({k: v for k, v in match.items()})
            
        if mode_config["type"] == "flat":
            results[mode_name] = simulate_bankroll(
                mode_matches, 
                starting_bankroll, 
                flat_stake=mode_config["stake"],
                mode=mode_name
            )
        else:  # percentage staking
            results[mode_name] = simulate_bankroll(
                mode_matches, 
                starting_bankroll, 
                pct_stake=mode_config["stake"],
                mode=mode_name
            )
    
    return results

def get_monthly_breakdown(matches: List[Dict[str, Any]], flat_stake: float) -> List[Dict[str, Any]]:
    """
    Group matches by month and calculate metrics for each month.
    
    Args:
        matches: List of match dictionaries with results and bankroll
        flat_stake: Stake amount per bet
        
    Returns:
        List of dictionaries with monthly metrics
    """
    # This function is now handled within simulate_bankroll
    # We'll keep it for backward compatibility but it's not used for staking comparison
    
    # Sort matches by date
    sorted_matches = sorted(matches, key=lambda x: x.get('match_date', ''))
    
    # Group by month (YYYY-MM)
    monthly_data = []
    
    # Function to extract month from date string
    def get_month(match):
        date_str = match.get('match_date', '')
        if date_str and len(date_str) >= 7:
            return date_str[:7]  # YYYY-MM
        return ''
    
    # Group matches by month
    for month, month_matches in itertools.groupby(sorted_matches, key=get_month):
        month_matches = list(month_matches)
        
        if not month or not month_matches:
            continue
        
        bets = len(month_matches)
        wins = sum(1 for m in month_matches if m.get('result_btts') == 1)
        losses = bets - wins
        hit_rate = wins / bets if bets > 0 else 0
        avg_odds = sum(float(m.get('odds_btts_yes', 0)) for m in month_matches) / bets if bets > 0 else 0
        profit = sum((float(m.get('odds_btts_yes', 0)) - 1) if m.get('result_btts') == 1 else -1 for m in month_matches)
        roi = profit / bets * 100 if bets > 0 else 0
        
        # Get ending bankroll for the month
        ending_bankroll = month_matches[-1].get('bankroll', 0)
        
        # Calculate drawdown for the month
        if len(month_matches) > 1:
            start_bankroll = month_matches[0].get('bankroll', 0) - (1 if month_matches[0].get('result_btts') == 1 else -1) * flat_stake
            peak_bankroll = start_bankroll
            min_bankroll = start_bankroll
            
            for match in month_matches:
                current_bankroll = match.get('bankroll', 0)
                peak_bankroll = max(peak_bankroll, current_bankroll)
                min_bankroll = min(min_bankroll, current_bankroll)
            
            drawdown_currency = peak_bankroll - min_bankroll
            drawdown_percent = (drawdown_currency / peak_bankroll) * 100 if peak_bankroll > 0 else 0
        else:
            drawdown_currency = 0
            drawdown_percent = 0
        
        monthly_data.append({
            'month': month,
            'bets': bets,
            'wins': wins,
            'losses': losses,
            'hit_rate': hit_rate,
            'avg_odds': avg_odds,
            'profit': profit,
            'roi': roi,
            'ending_bankroll': ending_bankroll,
            'drawdown_currency': drawdown_currency,
            'drawdown_percent': drawdown_percent
        })
    
    return monthly_data

def calculate_implied_probability(odds: float) -> float:
    """
    Calculate implied probability from decimal odds.
    
    Args:
        odds: Decimal odds
        
    Returns:
        Implied probability as a float between 0 and 1
    """
    if odds <= 0:
        return 0
    return 1 / odds

def calculate_edge(our_probability: float, market_probability: float) -> float:
    """
    Calculate edge between our probability and market probability.
    
    Args:
        our_probability: Our calculated probability
        market_probability: Market implied probability
        
    Returns:
        Edge as a float
    """
    return our_probability - market_probability

def apply_btts_rule(
    matches: List[Dict[str, Any]], 
    starting_bankroll: float = 100000, 
    flat_stake: float = 1000,
    min_edge: float = 0.0
) -> Dict[str, Dict[str, Any]]:
    """
    Apply the simplified BTTS rule to the matches.
    
    Rule:
    - leagues: BL1, EPL, FL1
    - odds: 1.80–2.10
    - form scored >= 1.0
    - form conceded >= 0.8
    - edge vs market >= min_edge
    
    Args:
        matches: List of enriched match dictionaries
        starting_bankroll: Initial bankroll amount
        flat_stake: Stake amount per bet
        min_edge: Minimum edge vs market probability
        
    Returns:
        Dictionary with train and test results
    """
    # Split data into train (2021-2023) and test (2024)
    train_years = ['2021', '2022', '2023']
    test_years = ['2024']
    
    train_matches = [m for m in matches if m.get('year') in train_years]
    test_matches = [m for m in matches if m.get('year') in test_years]
    
    print(f"Train set: {len(train_matches)} matches from {', '.join(train_years)}")
    print(f"Test set: {len(test_matches)} matches from {', '.join(test_years)}")
    
    # Calculate our BTTS probability based on form
    for match in train_matches + test_matches:
        # Simple model: average of form metrics
        home_scored = match.get('avg_goals_scored_last5_home', 0)
        away_scored = match.get('avg_goals_scored_last5_away', 0)
        home_conceded = match.get('avg_goals_conceded_last5_home', 0)
        away_conceded = match.get('avg_goals_conceded_last5_away', 0)
        
        # Calculate probability factors (simplified model)
        home_scores_prob = min(0.9, home_scored * 0.3 + away_conceded * 0.2)
        away_scores_prob = min(0.9, away_scored * 0.3 + home_conceded * 0.2)
        
        # Combined probability of both teams scoring
        our_btts_prob = home_scores_prob * away_scores_prob
        match['our_btts_prob'] = our_btts_prob
        
        # Calculate market implied probability
        odds_btts = float(match.get('odds_btts_yes', 0))
        market_prob = calculate_implied_probability(odds_btts)
        match['market_btts_prob'] = market_prob
        
        # Calculate edge
        edge = calculate_edge(our_btts_prob, market_prob)
        match['btts_edge'] = edge
    
    # Apply rule to train set
    train_rule_matches = [
        m for m in train_matches 
        if (
            1.80 <= float(m.get('odds_btts_yes', 0)) <= 2.10 and
            m.get('avg_goals_scored_last5_home', 0) >= 1.0 and
            m.get('avg_goals_scored_last5_away', 0) >= 1.0 and
            m.get('avg_goals_conceded_last5_home', 0) >= 0.8 and
            m.get('avg_goals_conceded_last5_away', 0) >= 0.8 and
            m.get('btts_edge', 0) >= min_edge
        )
    ]
    
    # Apply rule to test set
    test_rule_matches = [
        m for m in test_matches 
        if (
            1.80 <= float(m.get('odds_btts_yes', 0)) <= 2.10 and
            m.get('avg_goals_scored_last5_home', 0) >= 1.0 and
            m.get('avg_goals_scored_last5_away', 0) >= 1.0 and
            m.get('avg_goals_conceded_last5_home', 0) >= 0.8 and
            m.get('avg_goals_conceded_last5_away', 0) >= 0.8 and
            m.get('btts_edge', 0) >= min_edge
        )
    ]
    
    # Calculate metrics for train set
    train_bets = len(train_rule_matches)
    train_wins = sum(1 for m in train_rule_matches if m.get('result_btts') == 1)
    train_hit_rate = train_wins / train_bets if train_bets > 0 else 0
    train_avg_odds = sum(float(m.get('odds_btts_yes', 0)) for m in train_rule_matches) / train_bets if train_bets > 0 else 0
    train_profit = sum((float(m.get('odds_btts_yes', 0)) - 1) if m.get('result_btts') == 1 else -1 for m in train_rule_matches)
    train_roi = train_profit / train_bets * 100 if train_bets > 0 else 0
    
    # Calculate metrics for test set
    test_bets = len(test_rule_matches)
    test_wins = sum(1 for m in test_rule_matches if m.get('result_btts') == 1)
    test_hit_rate = test_wins / test_bets if test_bets > 0 else 0
    test_avg_odds = sum(float(m.get('odds_btts_yes', 0)) for m in test_rule_matches) / test_bets if test_bets > 0 else 0
    test_profit = sum((float(m.get('odds_btts_yes', 0)) - 1) if m.get('result_btts') == 1 else -1 for m in test_rule_matches)
    test_roi = test_profit / test_bets * 100 if test_bets > 0 else 0
    
    # Calculate metrics by league for train set
    train_by_league = {}
    for league in ['BL1', 'EPL', 'FL1']:
        league_matches = [m for m in train_rule_matches if m.get('league') == league]
        bets = len(league_matches)
        if bets > 0:
            wins = sum(1 for m in league_matches if m.get('result_btts') == 1)
            hit_rate = wins / bets
            avg_odds = sum(float(m.get('odds_btts_yes', 0)) for m in league_matches) / bets
            profit = sum((float(m.get('odds_btts_yes', 0)) - 1) if m.get('result_btts') == 1 else -1 for m in league_matches)
            roi = profit / bets * 100
            train_by_league[league] = {
                'bets': bets,
                'wins': wins,
                'hit_rate': hit_rate,
                'avg_odds': avg_odds,
                'profit': profit,
                'roi': roi
            }
    
    # Calculate metrics by league for test set
    test_by_league = {}
    for league in ['BL1', 'EPL', 'FL1']:
        league_matches = [m for m in test_rule_matches if m.get('league') == league]
        bets = len(league_matches)
        if bets > 0:
            wins = sum(1 for m in league_matches if m.get('result_btts') == 1)
            hit_rate = wins / bets
            avg_odds = sum(float(m.get('odds_btts_yes', 0)) for m in league_matches) / bets
            profit = sum((float(m.get('odds_btts_yes', 0)) - 1) if m.get('result_btts') == 1 else -1 for m in league_matches)
            roi = profit / bets * 100
            test_by_league[league] = {
                'bets': bets,
                'wins': wins,
                'hit_rate': hit_rate,
                'avg_odds': avg_odds,
                'profit': profit,
                'roi': roi
            }
    
    # Simulate bankroll for train and test sets with different staking modes
    # Each set starts with the same starting bankroll for fair comparison
    train_staking_modes = simulate_multiple_staking_modes(train_rule_matches, starting_bankroll, flat_stake)
    test_staking_modes = simulate_multiple_staking_modes(test_rule_matches, starting_bankroll, flat_stake)
    
    # Combine all matches for overall analysis with different staking modes
    all_rule_matches = sorted(train_rule_matches + test_rule_matches, key=lambda x: x.get('match_date', ''))
    all_staking_modes = simulate_multiple_staking_modes(all_rule_matches, starting_bankroll, flat_stake)
    
    # Use flat staking for basic metrics and monthly breakdown
    train_bankroll = train_staking_modes["flat_1000"]
    test_bankroll = test_staking_modes["flat_1000"]
    all_bankroll = all_staking_modes["flat_1000"]
    
    # Get monthly breakdown for flat staking
    train_monthly = train_bankroll['monthly_data']
    test_monthly = test_bankroll['monthly_data']
    all_monthly = all_bankroll['monthly_data']
    
    # Perform sanity checks
    for mode in train_staking_modes:
        if train_staking_modes[mode]['ending_bankroll'] == starting_bankroll and train_bets > 0:
            print(f"WARNING: {mode} train ending bankroll unchanged despite {train_bets} bets")
    
    for mode in test_staking_modes:
        if test_staking_modes[mode]['ending_bankroll'] == starting_bankroll and test_bets > 0:
            print(f"WARNING: {mode} test ending bankroll unchanged despite {test_bets} bets")
    
    return {
        'train': {
            'overall': {
                'bets': train_bets,
                'wins': train_wins,
                'hit_rate': train_hit_rate,
                'avg_odds': train_avg_odds,
                'profit': train_profit,
                'roi': train_roi,
                'bankroll': train_bankroll,
                'monthly': train_monthly,
                'staking_modes': train_staking_modes
            },
            'by_league': train_by_league
        },
        'test': {
            'overall': {
                'bets': test_bets,
                'wins': test_wins,
                'hit_rate': test_hit_rate,
                'avg_odds': test_avg_odds,
                'profit': test_profit,
                'roi': test_roi,
                'bankroll': test_bankroll,
                'monthly': test_monthly,
                'staking_modes': test_staking_modes
            },
            'by_league': test_by_league
        },
        'all': {
            'bankroll': all_bankroll,
            'monthly': all_monthly,
            'staking_modes': all_staking_modes
        }
    }

def save_staking_comparison_to_csv(results: Dict[str, Dict[str, Any]], file_path: str):
    """Save staking comparison results to a CSV file."""
    try:
        with open(file_path, 'w', newline='') as csvfile:
            fieldnames = [
                'mode', 'split', 'starting_bankroll', 'ending_bankroll', 'net_profit_rub', 
                'roi_percent', 'yield_percent', 'bets', 'max_drawdown_rub', 'max_drawdown_percent', 
                'max_losing_streak', 'max_winning_streak', 'worst_month_profit', 'best_month_profit'
            ]
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            
            writer.writeheader()
            
            # Write train results for each staking mode
            train_bets = results['train']['overall']['bets']
            for mode, mode_results in results['train']['overall']['staking_modes'].items():
                writer.writerow({
                    'mode': mode,
                    'split': 'train',
                    'starting_bankroll': mode_results['starting_bankroll'],
                    'ending_bankroll': mode_results['ending_bankroll'],
                    'net_profit_rub': mode_results['net_profit_currency'],
                    'roi_percent': f"{(mode_results['net_profit_currency'] / mode_results['starting_bankroll']) * 100:.2f}",
                    'yield_percent': f"{mode_results.get('yield_pct', 0):.2f}",
                    'bets': train_bets,
                    'max_drawdown_rub': mode_results['max_drawdown_currency'],
                    'max_drawdown_percent': f"{mode_results['max_drawdown_percent']:.2f}",
                    'max_losing_streak': mode_results['max_losing_streak'],
                    'max_winning_streak': mode_results['max_winning_streak'],
                    'worst_month_profit': mode_results['worst_month_profit'],
                    'best_month_profit': mode_results['best_month_profit']
                })
            
            # Write test results for each staking mode
            test_bets = results['test']['overall']['bets']
            for mode, mode_results in results['test']['overall']['staking_modes'].items():
                writer.writerow({
                    'mode': mode,
                    'split': 'test',
                    'starting_bankroll': mode_results['starting_bankroll'],
                    'ending_bankroll': mode_results['ending_bankroll'],
                    'net_profit_rub': mode_results['net_profit_currency'],
                    'roi_percent': f"{(mode_results['net_profit_currency'] / mode_results['starting_bankroll']) * 100:.2f}",
                    'yield_percent': f"{mode_results.get('yield_pct', 0):.2f}",
                    'bets': test_bets,
                    'max_drawdown_rub': mode_results['max_drawdown_currency'],
                    'max_drawdown_percent': f"{mode_results['max_drawdown_percent']:.2f}",
                    'max_losing_streak': mode_results['max_losing_streak'],
                    'max_winning_streak': mode_results['max_winning_streak'],
                    'worst_month_profit': mode_results['worst_month_profit'],
                    'best_month_profit': mode_results['best_month_profit']
                })
            
            # Write overall results for each staking mode
            all_bets = train_bets + test_bets
            for mode, mode_results in results['all']['staking_modes'].items():
                writer.writerow({
                    'mode': mode,
                    'split': 'overall',
                    'starting_bankroll': mode_results['starting_bankroll'],
                    'ending_bankroll': mode_results['ending_bankroll'],
                    'net_profit_rub': mode_results['net_profit_currency'],
                    'roi_percent': f"{(mode_results['net_profit_currency'] / mode_results['starting_bankroll']) * 100:.2f}",
                    'yield_percent': f"{mode_results.get('yield_pct', 0):.2f}",
                    'bets': all_bets,
                    'max_drawdown_rub': mode_results['max_drawdown_currency'],
                    'max_drawdown_percent': f"{mode_results['max_drawdown_percent']:.2f}",
                    'max_losing_streak': mode_results['max_losing_streak'],
                    'max_winning_streak': mode_results['max_winning_streak'],
                    'worst_month_profit': mode_results['worst_month_profit'],
                    'best_month_profit': mode_results['best_month_profit']
                })
        print(f"Staking comparison saved to {file_path}")
    except Exception as e:
        print(f"Error saving staking comparison to CSV: {e}")

def save_staking_monthly_to_csv(results: Dict[str, Dict[str, Any]], file_path: str):
    """Save monthly data for each staking mode to a CSV file."""
    try:
        with open(file_path, 'w', newline='') as csvfile:
            fieldnames = [
                'mode', 'split', 'month', 'bankroll_start', 'bankroll_end', 
                'bets', 'wins', 'losses', 'profit_rub', 'roi_percent', 'drawdown_rub', 'drawdown_percent'
            ]
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            
            writer.writeheader()
            
            # Write train monthly data for each staking mode
            for mode, mode_results in results['train']['overall']['staking_modes'].items():
                for month_data in mode_results['monthly_data']:
                    writer.writerow({
                        'mode': mode,
                        'split': 'train',
                        'month': month_data['month'],
                        'bankroll_start': month_data['bankroll_start'],
                        'bankroll_end': month_data['bankroll_end'],
                        'bets': month_data['bets'],
                        'wins': month_data['wins'],
                        'losses': month_data['losses'],
                        'profit_rub': month_data['profit'],
                        'roi_percent': f"{month_data['roi']:.2f}",
                        'drawdown_rub': month_data['drawdown_currency'],
                        'drawdown_percent': f"{month_data['drawdown_percent']:.2f}"
                    })
            
            # Write test monthly data for each staking mode
            for mode, mode_results in results['test']['overall']['staking_modes'].items():
                for month_data in mode_results['monthly_data']:
                    writer.writerow({
                        'mode': mode,
                        'split': 'test',
                        'month': month_data['month'],
                        'bankroll_start': month_data['bankroll_start'],
                        'bankroll_end': month_data['bankroll_end'],
                        'bets': month_data['bets'],
                        'wins': month_data['wins'],
                        'losses': month_data['losses'],
                        'profit_rub': month_data['profit'],
                        'roi_percent': f"{month_data['roi']:.2f}",
                        'drawdown_rub': month_data['drawdown_currency'],
                        'drawdown_percent': f"{month_data['drawdown_percent']:.2f}"
                    })
                    
            # Write overall monthly data for each staking mode
            if 'all' in results and 'staking_modes' in results['all']:
                for mode, mode_results in results['all']['staking_modes'].items():
                    for month_data in mode_results['monthly_data']:
                        writer.writerow({
                            'mode': mode,
                            'split': 'overall',
                            'month': month_data['month'],
                            'bankroll_start': month_data['bankroll_start'],
                            'bankroll_end': month_data['bankroll_end'],
                            'bets': month_data['bets'],
                            'wins': month_data['wins'],
                            'losses': month_data['losses'],
                            'profit_rub': month_data['profit'],
                            'roi_percent': f"{month_data['roi']:.2f}",
                            'drawdown_rub': month_data['drawdown_currency'],
                            'drawdown_percent': f"{month_data['drawdown_percent']:.2f}"
                        })
                        
        print(f"Staking monthly data saved to {file_path}")
    except Exception as e:
        print(f"Error saving staking monthly data to CSV: {e}")

def save_results_to_csv(results: Dict[str, Dict[str, Any]], file_path: str, flat_stake: float):
    """Save validation results to a CSV file."""
    try:
        with open(file_path, 'w', newline='') as csvfile:
            fieldnames = [
                'dataset_type', 'split', 'league', 'bets', 'wins', 'losses', 'hit_rate', 
                'avg_odds', 'profit', 'roi', 'starting_bankroll', 'ending_bankroll', 
                'max_drawdown_currency', 'max_drawdown_percent', 'max_losing_streak', 'max_winning_streak'
            ]
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            
            writer.writeheader()
            
            # Write overall results
            train_overall = results['train']['overall']
            test_overall = results['test']['overall']
            
            writer.writerow({
                'dataset_type': 'overall',
                'split': 'train',
                'league': 'ALL',
                'bets': train_overall['bets'],
                'wins': train_overall['wins'],
                'losses': train_overall['bets'] - train_overall['wins'],
                'hit_rate': f"{train_overall['hit_rate']:.2%}",
                'avg_odds': f"{train_overall['avg_odds']:.2f}",
                'profit': f"{train_overall['profit']:.2f}",
                'roi': f"{train_overall['roi']:.2%}",
                'starting_bankroll': train_overall['bankroll']['starting_bankroll'],
                'ending_bankroll': train_overall['bankroll']['ending_bankroll'],
                'max_drawdown_currency': train_overall['bankroll']['max_drawdown_currency'],
                'max_drawdown_percent': f"{train_overall['bankroll']['max_drawdown_percent']:.2f}%",
                'max_losing_streak': train_overall['bankroll']['max_losing_streak'],
                'max_winning_streak': train_overall['bankroll']['max_winning_streak']
            })
            
            writer.writerow({
                'dataset_type': 'overall',
                'split': 'test',
                'league': 'ALL',
                'bets': test_overall['bets'],
                'wins': test_overall['wins'],
                'losses': test_overall['bets'] - test_overall['wins'],
                'hit_rate': f"{test_overall['hit_rate']:.2%}",
                'avg_odds': f"{test_overall['avg_odds']:.2f}",
                'profit': f"{test_overall['profit']:.2f}",
                'roi': f"{test_overall['roi']:.2%}",
                'starting_bankroll': test_overall['bankroll']['starting_bankroll'],
                'ending_bankroll': test_overall['bankroll']['ending_bankroll'],
                'max_drawdown_currency': test_overall['bankroll']['max_drawdown_currency'],
                'max_drawdown_percent': f"{test_overall['bankroll']['max_drawdown_percent']:.2f}%",
                'max_losing_streak': test_overall['bankroll']['max_losing_streak'],
                'max_winning_streak': test_overall['bankroll']['max_winning_streak']
            })
            
            # Write league results for train
            for league, metrics in results['train']['by_league'].items():
                writer.writerow({
                    'dataset_type': 'league',
                    'split': 'train',
                    'league': league,
                    'bets': metrics['bets'],
                    'wins': metrics['wins'],
                    'losses': metrics['bets'] - metrics['wins'],
                    'hit_rate': f"{metrics['hit_rate']:.2%}",
                    'avg_odds': f"{metrics['avg_odds']:.2f}",
                    'profit': f"{metrics['profit']:.2f}",
                    'roi': f"{metrics['roi']:.2%}",
                    'starting_bankroll': '',
                    'ending_bankroll': '',
                    'max_drawdown_currency': '',
                    'max_drawdown_percent': '',
                    'max_losing_streak': '',
                    'max_winning_streak': ''
                })
            
            # Write league results for test
            for league, metrics in results['test']['by_league'].items():
                writer.writerow({
                    'dataset_type': 'league',
                    'split': 'test',
                    'league': league,
                    'bets': metrics['bets'],
                    'wins': metrics['wins'],
                    'losses': metrics['bets'] - metrics['wins'],
                    'hit_rate': f"{metrics['hit_rate']:.2%}",
                    'avg_odds': f"{metrics['avg_odds']:.2f}",
                    'profit': f"{metrics['profit']:.2f}",
                    'roi': f"{metrics['roi']:.2%}",
                    'starting_bankroll': '',
                    'ending_bankroll': '',
                    'max_drawdown_currency': '',
                    'max_drawdown_percent': '',
                    'max_losing_streak': '',
                    'max_winning_streak': ''
                })
        print(f"Results saved to {file_path}")
    except Exception as e:
        print(f"Error saving results to CSV: {e}")

def save_monthly_results_to_csv(results: Dict[str, Dict[str, Any]], file_path: str):
    """Save monthly validation results to a CSV file."""
    try:
        with open(file_path, 'w', newline='') as csvfile:
            fieldnames = [
                'split', 'month', 'bets', 'wins', 'losses', 'hit_rate', 
                'avg_odds', 'profit', 'roi', 'ending_bankroll', 
                'drawdown_currency', 'drawdown_percent'
            ]
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            
            writer.writeheader()
            
            # Write train monthly data
            for month_data in results['train']['overall']['monthly']:
                writer.writerow({
                    'split': 'train',
                    'month': month_data['month'],
                    'bets': month_data['bets'],
                    'wins': month_data['wins'],
                    'losses': month_data['losses'],
                    'hit_rate': f"{month_data['hit_rate']:.2f}",
                    'avg_odds': f"{month_data['avg_odds']:.2f}",
                    'profit': f"{month_data['profit']:.2f}",
                    'roi': f"{month_data['roi']:.2f}",
                    'ending_bankroll': f"{month_data['ending_bankroll']:.2f}",
                    'drawdown_currency': f"{month_data['drawdown_currency']:.2f}",
                    'drawdown_percent': f"{month_data['drawdown_percent']:.2f}"
                })
            
            # Write test monthly data
            for month_data in results['test']['overall']['monthly']:
                writer.writerow({
                    'split': 'test',
                    'month': month_data['month'],
                    'bets': month_data['bets'],
                    'wins': month_data['wins'],
                    'losses': month_data['losses'],
                    'hit_rate': f"{month_data['hit_rate']:.2f}",
                    'avg_odds': f"{month_data['avg_odds']:.2f}",
                    'profit': f"{month_data['profit']:.2f}",
                    'roi': f"{month_data['roi']:.2f}",
                    'ending_bankroll': f"{month_data['ending_bankroll']:.2f}",
                    'drawdown_currency': f"{month_data['drawdown_currency']:.2f}",
                    'drawdown_percent': f"{month_data['drawdown_percent']:.2f}"
                })
                
            # Write overall monthly data if available
            if 'all' in results and 'monthly' in results['all']:
                for month_data in results['all']['monthly']:
                    writer.writerow({
                        'split': 'overall',
                        'month': month_data['month'],
                        'bets': month_data['bets'],
                        'wins': month_data['wins'],
                        'losses': month_data['losses'],
                        'hit_rate': f"{month_data['hit_rate']:.2f}",
                        'avg_odds': f"{month_data.get('avg_odds', 0):.2f}",
                        'profit': f"{month_data['profit']:.2f}",
                        'roi': f"{month_data['roi']:.2f}",
                        'ending_bankroll': f"{month_data['ending_bankroll']:.2f}",
                        'drawdown_currency': f"{month_data['drawdown_currency']:.2f}",
                        'drawdown_percent': f"{month_data['drawdown_percent']:.2f}"
                    })
                    
        print(f"Monthly results saved to {file_path}")
    except Exception as e:
        print(f"Error saving monthly results to CSV: {e}")

def generate_staking_comparison_markdown(
    timestamp: str,
    db_path: str,
    results: Dict[str, Dict[str, Any]],
    file_path: str,
    starting_bankroll: float,
    flat_stake: float
):
    """Generate a markdown summary of the staking comparison results."""
    try:
        with open(file_path, 'w') as f:
            f.write(f"# BTTS Staking Comparison Summary\n\n")
            f.write(f"**Run timestamp:** {timestamp}\n\n")
            f.write(f"**Database:** {db_path}\n\n")
            
            # Rule definition
            f.write("## Rule Definition\n\n")
            f.write("- Leagues: BL1, EPL, FL1\n")
            f.write("- Odds range: 1.80–2.10\n")
            f.write("- Form scored >= 1.0 (both teams)\n")
            f.write("- Form conceded >= 0.8 (both teams)\n\n")
            
            # Staking modes
            f.write("## Staking Modes Compared\n\n")
            f.write("1. **flat_1000**: Fixed stake of 1,000 RUB per bet\n")
            f.write("2. **pct_0_75**: 0.75% of current bankroll per bet\n")
            f.write("3. **pct_1_00**: 1.00% of current bankroll per bet\n")
            f.write("4. **pct_1_25**: 1.25% of current bankroll per bet\n")
            f.write("5. **pct_1_50**: 1.50% of current bankroll per bet\n\n")
            
            # Train/Test split
            f.write("## Data Split\n\n")
            f.write("- Train: 2021-2023 seasons\n")
            f.write("- Test: 2024 season\n\n")
            
            # Overall comparison
            f.write("## Overall Staking Comparison\n\n")
            f.write("### Train Set Results\n\n")
            f.write("| Mode | Starting Bankroll | Ending Bankroll | Net Profit | ROI | Yield | Max DD | Max DD % | Max Losing Streak | Max Winning Streak |\n")
            f.write("|------|------------------|-----------------|------------|-----|-------|--------|---------|-------------------|-------------------|\n")
            
            for mode, mode_results in results['train']['overall']['staking_modes'].items():
                roi_pct = (mode_results['net_profit_currency'] / mode_results['starting_bankroll']) * 100
                yield_pct = mode_results.get('yield_pct', 0)
                f.write(f"| {mode} | {mode_results['starting_bankroll']:,.2f} | {mode_results['ending_bankroll']:,.2f} | {mode_results['net_profit_currency']:,.2f} | {roi_pct:.2f}% | {yield_pct:.2f}% | {mode_results['max_drawdown_currency']:,.2f} | {mode_results['max_drawdown_percent']:.2f}% | {mode_results['max_losing_streak']} | {mode_results['max_winning_streak']} |\n")
            
            f.write("\n### Test Set Results\n\n")
            f.write("| Mode | Starting Bankroll | Ending Bankroll | Net Profit | ROI | Yield | Max DD | Max DD % | Max Losing Streak | Max Winning Streak |\n")
            f.write("|------|------------------|-----------------|------------|-----|-------|--------|---------|-------------------|-------------------|\n")
            
            for mode, mode_results in results['test']['overall']['staking_modes'].items():
                roi_pct = (mode_results['net_profit_currency'] / mode_results['starting_bankroll']) * 100
                yield_pct = mode_results.get('yield_pct', 0)
                f.write(f"| {mode} | {mode_results['starting_bankroll']:,.2f} | {mode_results['ending_bankroll']:,.2f} | {mode_results['net_profit_currency']:,.2f} | {roi_pct:.2f}% | {yield_pct:.2f}% | {mode_results['max_drawdown_currency']:,.2f} | {mode_results['max_drawdown_percent']:.2f}% | {mode_results['max_losing_streak']} | {mode_results['max_winning_streak']} |\n")
            
            f.write("\n### Overall Results (Train + Test)\n\n")
            f.write("| Mode | Starting Bankroll | Ending Bankroll | Net Profit | ROI | Yield | Max DD | Max DD % | Max Losing Streak | Max Winning Streak |\n")
            f.write("|------|------------------|-----------------|------------|-----|-------|--------|---------|-------------------|-------------------|\n")
            
            for mode, mode_results in results['all']['staking_modes'].items():
                roi_pct = (mode_results['net_profit_currency'] / mode_results['starting_bankroll']) * 100
                yield_pct = mode_results.get('yield_pct', 0)
                f.write(f"| {mode} | {mode_results['starting_bankroll']:,.2f} | {mode_results['ending_bankroll']:,.2f} | {mode_results['net_profit_currency']:,.2f} | {roi_pct:.2f}% | {yield_pct:.2f}% | {mode_results['max_drawdown_currency']:,.2f} | {mode_results['max_drawdown_percent']:.2f}% | {mode_results['max_losing_streak']} | {mode_results['max_winning_streak']} |\n")
            
            # Monthly best/worst
            f.write("\n## Monthly Performance Extremes\n\n")
            f.write("| Mode | Best Month Profit | Worst Month Profit |\n")
            f.write("|------|------------------|-------------------|\n")
            
            for mode, mode_results in results['all']['staking_modes'].items():
                f.write(f"| {mode} | {mode_results['best_month_profit']:,.2f} | {mode_results['worst_month_profit']:,.2f} |\n")
            
            # Conclusion
            f.write("\n## Conclusion\n\n")
            
            # Find best performing mode by ending bankroll
            best_mode = max(results['all']['staking_modes'].items(), key=lambda x: x[1]['ending_bankroll'])
            safest_mode = min(results['all']['staking_modes'].items(), key=lambda x: x[1]['max_drawdown_percent'])
            
            f.write(f"- Best performing staking mode: **{best_mode[0]}** with ending bankroll of {best_mode[1]['ending_bankroll']:,.2f} RUB\n")
            f.write(f"- Safest staking mode (lowest max drawdown %): **{safest_mode[0]}** with max drawdown of {safest_mode[1]['max_drawdown_percent']:.2f}%\n")
        print(f"Staking comparison markdown saved to {file_path}")
    except Exception as e:
        print(f"Error generating staking comparison markdown: {e}")

def generate_markdown_summary(
    timestamp: str,
    db_path: str,
    results: Dict[str, Dict[str, Any]],
    file_path: str,
    starting_bankroll: float,
    flat_stake: float
):
    """Generate a markdown summary of the validation results."""
    try:
        with open(file_path, 'w') as f:
            f.write(f"# BTTS Rule Validation Summary\n\n")
            f.write(f"**Run timestamp:** {timestamp}\n\n")
            f.write(f"**Database:** {db_path}\n\n")
            
            # Bankroll parameters
            f.write("## Bankroll Parameters\n\n")
            f.write(f"- Starting bankroll: {starting_bankroll:,.2f}\n")
            f.write(f"- Flat stake per bet: {flat_stake:,.2f}\n\n")
            
            # Rule definition
            f.write("## Rule Definition\n\n")
            f.write("- Leagues: BL1, EPL, FL1\n")
            f.write("- Odds range: 1.80–2.10\n")
            f.write("- Form scored >= 1.0 (both teams)\n")
            f.write("- Form conceded >= 0.8 (both teams)\n\n")
            
            # Train/Test split
            f.write("## Data Split\n\n")
            f.write("- Train: 2021-2023 seasons\n")
            f.write("- Test: 2024 season\n\n")
            
            # Overall results
            train_overall = results['train']['overall']
            test_overall = results['test']['overall']
            
            f.write("## Overall Results\n\n")
            f.write("| Dataset | Bets | Hit Rate | Avg Odds | Profit | ROI | Ending Bankroll |\n")
            f.write("|---------|------|----------|----------|--------|-----|----------------|\n")
            f.write(f"| Train | {train_overall['bets']} | {train_overall['hit_rate']:.2%} | {train_overall['avg_odds']:.2f} | {train_overall['profit']:.2f} | {train_overall['roi']:.2%} | {train_overall['bankroll']['ending_bankroll']:,.2f} |\n")
            f.write(f"| Test | {test_overall['bets']} | {test_overall['hit_rate']:.2%} | {test_overall['avg_odds']:.2f} | {test_overall['profit']:.2f} | {test_overall['roi']:.2%} | {test_overall['bankroll']['ending_bankroll']:,.2f} |\n\n")
            
            # Results by league (train)
            f.write("## Results by League (Train)\n\n")
            f.write("| League | Bets | Hit Rate | Avg Odds | Profit | ROI |\n")
            f.write("|--------|------|----------|----------|--------|-----|\n")
            
            for league, metrics in results['train']['by_league'].items():
                f.write(f"| {league} | {metrics['bets']} | {metrics['hit_rate']:.2%} | {metrics['avg_odds']:.2f} | {metrics['profit']:.2f} | {metrics['roi']:.2%} |\n")
            
            # Results by league (test)
            f.write("\n## Results by League (Test)\n\n")
            f.write("| League | Bets | Hit Rate | Avg Odds | Profit | ROI |\n")
            f.write("|--------|------|----------|----------|--------|-----|\n")
            
            for league, metrics in results['test']['by_league'].items():
                f.write(f"| {league} | {metrics['bets']} | {metrics['hit_rate']:.2%} | {metrics['avg_odds']:.2f} | {metrics['profit']:.2f} | {metrics['roi']:.2%} |\n")
            
            # Monthly summary
            f.write("\n## Monthly Performance Summary\n\n")
            f.write("| Month | Split | Bets | Hit Rate | Profit | ROI | Ending Bankroll |\n")
            f.write("|-------|-------|------|----------|--------|-----|----------------|\n")
            
            # Train monthly data
            for month_data in results['train']['overall']['monthly']:
                f.write(f"| {month_data['month']} | Train | {month_data['bets']} | {month_data['hit_rate']:.2%} | {month_data['profit']:.2f} | {month_data['roi']:.2%} | {month_data['ending_bankroll']:,.2f} |\n")
            
            # Test monthly data
            for month_data in results['test']['overall']['monthly']:
                f.write(f"| {month_data['month']} | Test | {month_data['bets']} | {month_data['hit_rate']:.2%} | {month_data['profit']:.2f} | {month_data['roi']:.2%} | {month_data['ending_bankroll']:,.2f} |\n")
            
            # Bankroll and drawdown analysis
            f.write("\n## Bankroll and Drawdown Analysis\n\n")
            
            train_bankroll = train_overall['bankroll']
            test_bankroll = test_overall['bankroll']
            all_bankroll = results['all']['bankroll']
            
            f.write("| Metric | Train | Test | Overall |\n")
            f.write("|--------|-------|------|--------|\n")
            f.write(f"| Starting Bankroll | {train_bankroll['starting_bankroll']:,.2f} | {test_bankroll['starting_bankroll']:,.2f} | {all_bankroll['starting_bankroll']:,.2f} |\n")
            f.write(f"| Ending Bankroll | {train_bankroll['ending_bankroll']:,.2f} | {test_bankroll['ending_bankroll']:,.2f} | {all_bankroll['ending_bankroll']:,.2f} |\n")
            f.write(f"| Net Profit | {train_bankroll['net_profit_currency']:,.2f} | {test_bankroll['net_profit_currency']:,.2f} | {all_bankroll['net_profit_currency']:,.2f} |\n")
            f.write(f"| Max Drawdown (Currency) | {train_bankroll['max_drawdown_currency']:,.2f} | {test_bankroll['max_drawdown_currency']:,.2f} | {all_bankroll['max_drawdown_currency']:,.2f} |\n")
            f.write(f"| Max Drawdown (%) | {train_bankroll['max_drawdown_percent']:.2f}% | {test_bankroll['max_drawdown_percent']:.2f}% | {all_bankroll['max_drawdown_percent']:.2f}% |\n")
            f.write(f"| Max Losing Streak | {train_bankroll['max_losing_streak']} | {test_bankroll['max_losing_streak']} | {all_bankroll['max_losing_streak']} |\n")
            f.write(f"| Max Winning Streak | {train_bankroll['max_winning_streak']} | {test_bankroll['max_winning_streak']} | {all_bankroll['max_winning_streak']} |\n")
            
            # Staking comparison summary
            f.write("\n## Staking Comparison Summary\n\n")
            f.write("For detailed staking comparison, see the separate staking comparison report.\n\n")
            
            # Find best performing mode by ending bankroll
            best_mode = max(results['all']['staking_modes'].items(), key=lambda x: x[1]['ending_bankroll'])
            safest_mode = min(results['all']['staking_modes'].items(), key=lambda x: x[1]['max_drawdown_percent'])
            
            f.write(f"- Best performing staking mode: **{best_mode[0]}** with ending bankroll of {best_mode[1]['ending_bankroll']:,.2f} RUB\n")
            f.write(f"- Safest staking mode (lowest max drawdown %): **{safest_mode[0]}** with max drawdown of {safest_mode[1]['max_drawdown_percent']:.2f}%\n")
        print(f"Markdown summary saved to {file_path}")
    except Exception as e:
        print(f"Error generating markdown summary: {e}")

def print_staking_comparison(results: Dict[str, Dict[str, Any]], starting_bankroll: float, flat_stake: float):
    """Print staking comparison results."""
    print("\nBTTS STAKING COMPARISON")
    print("=" * 100)
    
    print(f"Starting bankroll: {starting_bankroll:,.2f}")
    print(f"Base flat stake: {flat_stake:,.2f}")
    
    # Print overall staking comparison
    print("\nOVERALL STAKING COMPARISON")
    print("-" * 100)
    print(f"{'Mode':<10} | {'Split':<6} | {'Ending BR':<15} | {'Net Profit':<15} | {'ROI':<10} | {'Max DD':<10} | {'Max DD %':<10} | {'Max Lose':<10} | {'Max Win':<10}")
    print("-" * 100)
    
    # Train results
    for mode, mode_results in results['train']['overall']['staking_modes'].items():
        roi_pct = (mode_results['net_profit_currency'] / mode_results['starting_bankroll']) * 100
        print(f"{mode:<10} | {'Train':<6} | {mode_results['ending_bankroll']:,.2f} | {mode_results['net_profit_currency']:,.2f} | {roi_pct:.2f}% | {mode_results['max_drawdown_currency']:,.2f} | {mode_results['max_drawdown_percent']:.2f}% | {mode_results['max_losing_streak']:<10} | {mode_results['max_winning_streak']:<10}")
    
    # Test results
    for mode, mode_results in results['test']['overall']['staking_modes'].items():
        roi_pct = (mode_results['net_profit_currency'] / mode_results['starting_bankroll']) * 100
        print(f"{mode:<10} | {'Test':<6} | {mode_results['ending_bankroll']:,.2f} | {mode_results['net_profit_currency']:,.2f} | {roi_pct:.2f}% | {mode_results['max_drawdown_currency']:,.2f} | {mode_results['max_drawdown_percent']:.2f}% | {mode_results['max_losing_streak']:<10} | {mode_results['max_winning_streak']:<10}")
    
    # Overall results
    print("\nOVERALL RESULTS (TRAIN + TEST)")
    print("-" * 100)
    for mode, mode_results in results['all']['staking_modes'].items():
        roi_pct = (mode_results['net_profit_currency'] / mode_results['starting_bankroll']) * 100
        print(f"{mode:<10} | {'Overall':<6} | {mode_results['ending_bankroll']:,.2f} | {mode_results['net_profit_currency']:,.2f} | {roi_pct:.2f}% | {mode_results['max_drawdown_currency']:,.2f} | {mode_results['max_drawdown_percent']:.2f}% | {mode_results['max_losing_streak']:<10} | {mode_results['max_winning_streak']:<10}")
    
    # Find best performing mode by ending bankroll
    best_mode = max(results['all']['staking_modes'].items(), key=lambda x: x[1]['ending_bankroll'])
    safest_mode = min(results['all']['staking_modes'].items(), key=lambda x: x[1]['max_drawdown_percent'])
    
    print("\nSUMMARY:")
    print(f"- Best performing staking mode: {best_mode[0]} with ending bankroll of {best_mode[1]['ending_bankroll']:,.2f} RUB")
    print(f"- Safest staking mode (lowest max drawdown %): {safest_mode[0]} with max drawdown of {safest_mode[1]['max_drawdown_percent']:.2f}%")

def print_results(results: Dict[str, Dict[str, Any]], starting_bankroll: float, flat_stake: float):
    """Print validation results."""
    print("\nBTTS RULE VALIDATION RESULTS")
    print("=" * 100)
    
    print(f"Starting bankroll: {starting_bankroll:,.2f}")
    print(f"Flat stake per bet: {flat_stake:,.2f}")
    
    # Print overall results
    print("\nOVERALL RESULTS")
    print("-" * 100)
    print(f"{'Dataset':<10} | {'Bets':<6} | {'Hit Rate':<10} | {'Avg Odds':<10} | {'Profit':<10} | {'ROI':<10} | {'Ending Bankroll':<15}")
    print("-" * 100)
    
    train_overall = results['train']['overall']
    test_overall = results['test']['overall']
    
    print(f"{'Train':<10} | {train_overall['bets']:<6} | {train_overall['hit_rate']:.2%} | {train_overall['avg_odds']:.2f} | {train_overall['profit']:.2f} | {train_overall['roi']:.2%} | {train_overall['bankroll']['ending_bankroll']:,.2f}")
    print(f"{'Test':<10} | {test_overall['bets']:<6} | {test_overall['hit_rate']:.2%} | {test_overall['avg_odds']:.2f} | {test_overall['profit']:.2f} | {test_overall['roi']:.2%} | {test_overall['bankroll']['ending_bankroll']:,.2f}")
    
    # Print results by league
    print("\nRESULTS BY LEAGUE (TRAIN)")
    print("-" * 100)
    print(f"{'League':<10} | {'Bets':<6} | {'Hit Rate':<10} | {'Avg Odds':<10} | {'Profit':<10} | {'ROI':<10}")
    print("-" * 100)
    
    for league, metrics in results['train']['by_league'].items():
        print(f"{league:<10} | {metrics['bets']:<6} | {metrics['hit_rate']:.2%} | {metrics['avg_odds']:.2f} | {metrics['profit']:.2f} | {metrics['roi']:.2%}")
    
    print("\nRESULTS BY LEAGUE (TEST)")
    print("-" * 100)
    print(f"{'League':<10} | {'Bets':<6} | {'Hit Rate':<10} | {'Avg Odds':<10} | {'Profit':<10} | {'ROI':<10}")
    print("-" * 100)
    
    for league, metrics in results['test']['by_league'].items():
        print(f"{league:<10} | {metrics['bets']:<6} | {metrics['hit_rate']:.2%} | {metrics['avg_odds']:.2f} | {metrics['profit']:.2f} | {metrics['roi']:.2%}")
    
    # Print bankroll and drawdown analysis
    print("\nBANKROLL AND DRAWDOWN ANALYSIS")
    print("-" * 100)
    print(f"{'Metric':<20} | {'Train':<15} | {'Test':<15} | {'Overall':<15}")
    print("-" * 100)
    
    train_bankroll = train_overall['bankroll']
    test_bankroll = test_overall['bankroll']
    all_bankroll = results['all']['bankroll']
    
    print(f"{'Starting Bankroll':<20} | {train_bankroll['starting_bankroll']:,.2f} | {test_bankroll['starting_bankroll']:,.2f} | {all_bankroll['starting_bankroll']:,.2f}")
    print(f"{'Ending Bankroll':<20} | {train_bankroll['ending_bankroll']:,.2f} | {test_bankroll['ending_bankroll']:,.2f} | {all_bankroll['ending_bankroll']:,.2f}")
    print(f"{'Net Profit':<20} | {train_bankroll['net_profit_currency']:,.2f} | {test_bankroll['net_profit_currency']:,.2f} | {all_bankroll['net_profit_currency']:,.2f}")
    print(f"{'Max Drawdown (Currency)':<20} | {train_bankroll['max_drawdown_currency']:,.2f} | {test_bankroll['max_drawdown_currency']:,.2f} | {all_bankroll['max_drawdown_currency']:,.2f}")
    print(f"{'Max Drawdown (%)':<20} | {train_bankroll['max_drawdown_percent']:.2f}% | {test_bankroll['max_drawdown_percent']:.2f}% | {all_bankroll['max_drawdown_percent']:.2f}%")
    print(f"{'Max Losing Streak':<20} | {train_bankroll['max_losing_streak']} | {test_bankroll['max_losing_streak']} | {all_bankroll['max_losing_streak']}")
    print(f"{'Max Winning Streak':<20} | {train_bankroll['max_winning_streak']} | {test_bankroll['max_winning_streak']} | {all_bankroll['max_winning_streak']}")

def compare_thresholds(
    matches: List[Dict[str, Any]], 
    thresholds: List[float],
    starting_bankroll: float = 100000, 
    flat_stake: float = 1000
) -> Dict[str, Dict[str, Dict[str, Any]]]:
    """
    Compare BTTS rule performance with different edge thresholds.
    
    Args:
        matches: List of enriched match dictionaries
        thresholds: List of edge thresholds to compare
        starting_bankroll: Initial bankroll amount
        flat_stake: Stake amount per bet
        
    Returns:
        Dictionary with results for each threshold
    """
    results = {}
    
    for threshold in thresholds:
        print(f"\n{'-' * 80}")
        print(f"Applying BTTS rule with min_edge = {threshold:.3f}")
        print(f"{'-' * 80}")
        
        # Apply rule with current threshold
        threshold_results = apply_btts_rule(matches, starting_bankroll, flat_stake, threshold)
        
        # Store results
        results[f"{threshold:.3f}"] = threshold_results
    
    return results

def save_threshold_comparison_to_csv(
    results: Dict[str, Dict[str, Dict[str, Any]]], 
    file_path: str
):
    """Save threshold comparison results to a CSV file."""
    try:
        with open(file_path, 'w', newline='') as csvfile:
            fieldnames = [
                'threshold', 'split', 'bets', 'wins', 'hit_rate', 'avg_odds', 
                'profit', 'roi', 'ending_bankroll', 'max_drawdown_currency', 
                'max_drawdown_percent', 'max_losing_streak', 'max_winning_streak'
            ]
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            
            writer.writeheader()
            
            # Write results for each threshold
            for threshold, threshold_results in results.items():
                # Train results
                train_overall = threshold_results['train']['overall']
                train_bankroll = train_overall['bankroll']
                
                writer.writerow({
                    'threshold': threshold,
                    'split': 'train',
                    'bets': train_overall['bets'],
                    'wins': train_overall['wins'],
                    'hit_rate': f"{train_overall['hit_rate']:.2%}",
                    'avg_odds': f"{train_overall['avg_odds']:.2f}",
                    'profit': f"{train_overall['profit']:.2f}",
                    'roi': f"{train_overall['roi']:.2%}",
                    'ending_bankroll': f"{train_bankroll['ending_bankroll']:.2f}",
                    'max_drawdown_currency': f"{train_bankroll['max_drawdown_currency']:.2f}",
                    'max_drawdown_percent': f"{train_bankroll['max_drawdown_percent']:.2f}%",
                    'max_losing_streak': train_bankroll['max_losing_streak'],
                    'max_winning_streak': train_bankroll['max_winning_streak']
                })
                
                # Test results
                test_overall = threshold_results['test']['overall']
                test_bankroll = test_overall['bankroll']
                
                writer.writerow({
                    'threshold': threshold,
                    'split': 'test',
                    'bets': test_overall['bets'],
                    'wins': test_overall['wins'],
                    'hit_rate': f"{test_overall['hit_rate']:.2%}",
                    'avg_odds': f"{test_overall['avg_odds']:.2f}",
                    'profit': f"{test_overall['profit']:.2f}",
                    'roi': f"{test_overall['roi']:.2%}",
                    'ending_bankroll': f"{test_bankroll['ending_bankroll']:.2f}",
                    'max_drawdown_currency': f"{test_bankroll['max_drawdown_currency']:.2f}",
                    'max_drawdown_percent': f"{test_bankroll['max_drawdown_percent']:.2f}%",
                    'max_losing_streak': test_bankroll['max_losing_streak'],
                    'max_winning_streak': test_bankroll['max_winning_streak']
                })
                
                # Combined results
                all_bankroll = threshold_results['all']['bankroll']
                all_bets = train_overall['bets'] + test_overall['bets']
                all_wins = train_overall['wins'] + test_overall['wins']
                all_hit_rate = all_wins / all_bets if all_bets > 0 else 0
                all_profit = train_overall['profit'] + test_overall['profit']
                all_roi = all_profit / all_bets * 100 if all_bets > 0 else 0
                
                writer.writerow({
                    'threshold': threshold,
                    'split': 'all',
                    'bets': all_bets,
                    'wins': all_wins,
                    'hit_rate': f"{all_hit_rate:.2%}",
                    'avg_odds': f"N/A",  # Would need weighted average
                    'profit': f"{all_profit:.2f}",
                    'roi': f"{all_roi:.2%}",
                    'ending_bankroll': f"{all_bankroll['ending_bankroll']:.2f}",
                    'max_drawdown_currency': f"{all_bankroll['max_drawdown_currency']:.2f}",
                    'max_drawdown_percent': f"{all_bankroll['max_drawdown_percent']:.2f}%",
                    'max_losing_streak': all_bankroll['max_losing_streak'],
                    'max_winning_streak': all_bankroll['max_winning_streak']
                })
        
        print(f"Threshold comparison saved to {file_path}")
    except Exception as e:
        print(f"Error saving threshold comparison to CSV: {e}")

def save_threshold_monthly_to_csv(
    results: Dict[str, Dict[str, Dict[str, Any]]], 
    file_path: str
):
    """Save monthly data for each threshold to a CSV file."""
    try:
        with open(file_path, 'w', newline='') as csvfile:
            fieldnames = [
                'threshold', 'split', 'month', 'bets', 'wins', 'losses', 
                'profit', 'roi', 'ending_bankroll', 'drawdown_currency', 'drawdown_percent'
            ]
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            
            writer.writeheader()
            
            # Write monthly data for each threshold
            for threshold, threshold_results in results.items():
                # Train monthly data
                for month_data in threshold_results['train']['overall']['monthly']:
                    writer.writerow({
                        'threshold': threshold,
                        'split': 'train',
                        'month': month_data['month'],
                        'bets': month_data['bets'],
                        'wins': month_data['wins'],
                        'losses': month_data['losses'],
                        'profit': f"{month_data['profit']:.2f}",
                        'roi': f"{month_data['roi']:.2f}",
                        'ending_bankroll': f"{month_data['ending_bankroll']:.2f}",
                        'drawdown_currency': f"{month_data['drawdown_currency']:.2f}",
                        'drawdown_percent': f"{month_data['drawdown_percent']:.2f}"
                    })
                
                # Test monthly data
                for month_data in threshold_results['test']['overall']['monthly']:
                    writer.writerow({
                        'threshold': threshold,
                        'split': 'test',
                        'month': month_data['month'],
                        'bets': month_data['bets'],
                        'wins': month_data['wins'],
                        'losses': month_data['losses'],
                        'profit': f"{month_data['profit']:.2f}",
                        'roi': f"{month_data['roi']:.2f}",
                        'ending_bankroll': f"{month_data['ending_bankroll']:.2f}",
                        'drawdown_currency': f"{month_data['drawdown_currency']:.2f}",
                        'drawdown_percent': f"{month_data['drawdown_percent']:.2f}"
                    })
        
        print(f"Threshold monthly data saved to {file_path}")
    except Exception as e:
        print(f"Error saving threshold monthly data to CSV: {e}")

def generate_threshold_comparison_markdown(
    timestamp: str,
    db_path: str,
    results: Dict[str, Dict[str, Dict[str, Any]]],
    file_path: str,
    starting_bankroll: float,
    flat_stake: float
):
    """Generate a markdown summary of the threshold comparison results."""
    try:
        with open(file_path, 'w') as f:
            f.write(f"# BTTS Edge Threshold Comparison\n\n")
            f.write(f"**Run timestamp:** {timestamp}\n\n")
            f.write(f"**Database:** {db_path}\n\n")
            
            # Bankroll parameters
            f.write("## Bankroll Parameters\n\n")
            f.write(f"- Starting bankroll: {starting_bankroll:,.2f}\n")
            f.write(f"- Flat stake per bet: {flat_stake:,.2f}\n\n")
            
            # Rule definition
            f.write("## Rule Definition\n\n")
            f.write("- Leagues: BL1, EPL, FL1\n")
            f.write("- Odds range: 1.80–2.10\n")
            f.write("- Form scored >= 1.0 (both teams)\n")
            f.write("- Form conceded >= 0.8 (both teams)\n")
            f.write("- Edge vs market >= [threshold]\n\n")
            
            # Train/Test split
            f.write("## Data Split\n\n")
            f.write("- Train: 2021-2023 seasons\n")
            f.write("- Test: 2024 season\n\n")
            
            # Overall comparison
            f.write("## Overall Comparison\n\n")
            f.write("### Train Set Results\n\n")
            f.write("| Threshold | Bets | Hit Rate | Avg Odds | Profit | ROI | Ending Bankroll | Max DD | Max DD % | Max Losing Streak |\n")
            f.write("|-----------|------|----------|----------|--------|-----|-----------------|--------|---------|-------------------|\n")
            
            for threshold, threshold_results in sorted(results.items(), key=lambda x: float(x[0])):
                train_overall = threshold_results['train']['overall']
                train_bankroll = train_overall['bankroll']
                
                f.write(f"| {threshold} | {train_overall['bets']} | {train_overall['hit_rate']:.2%} | {train_overall['avg_odds']:.2f} | {train_overall['profit']:.2f} | {train_overall['roi']:.2%} | {train_bankroll['ending_bankroll']:,.2f} | {train_bankroll['max_drawdown_currency']:,.2f} | {train_bankroll['max_drawdown_percent']:.2f}% | {train_bankroll['max_losing_streak']} |\n")
            
            f.write("\n### Test Set Results\n\n")
            f.write("| Threshold | Bets | Hit Rate | Avg Odds | Profit | ROI | Ending Bankroll | Max DD | Max DD % | Max Losing Streak |\n")
            f.write("|-----------|------|----------|----------|--------|-----|-----------------|--------|---------|-------------------|\n")
            
            for threshold, threshold_results in sorted(results.items(), key=lambda x: float(x[0])):
                test_overall = threshold_results['test']['overall']
                test_bankroll = test_overall['bankroll']
                
                f.write(f"| {threshold} | {test_overall['bets']} | {test_overall['hit_rate']:.2%} | {test_overall['avg_odds']:.2f} | {test_overall['profit']:.2f} | {test_overall['roi']:.2%} | {test_bankroll['ending_bankroll']:,.2f} | {test_bankroll['max_drawdown_currency']:,.2f} | {test_bankroll['max_drawdown_percent']:.2f}% | {test_bankroll['max_losing_streak']} |\n")
            
            f.write("\n### Combined Results (Train + Test)\n\n")
            f.write("| Threshold | Bets | Hit Rate | Profit | ROI | Ending Bankroll | Max DD | Max DD % | Max Losing Streak |\n")
            f.write("|-----------|------|----------|--------|-----|-----------------|--------|---------|-------------------|\n")
            
            for threshold, threshold_results in sorted(results.items(), key=lambda x: float(x[0])):
                train_overall = threshold_results['train']['overall']
                test_overall = threshold_results['test']['overall']
                all_bankroll = threshold_results['all']['bankroll']
                
                all_bets = train_overall['bets'] + test_overall['bets']
                all_wins = train_overall['wins'] + test_overall['wins']
                all_hit_rate = all_wins / all_bets if all_bets > 0 else 0
                all_profit = train_overall['profit'] + test_overall['profit']
                all_roi = all_profit / all_bets * 100 if all_bets > 0 else 0
                
                f.write(f"| {threshold} | {all_bets} | {all_hit_rate:.2%} | {all_profit:.2f} | {all_roi:.2%} | {all_bankroll['ending_bankroll']:,.2f} | {all_bankroll['max_drawdown_currency']:,.2f} | {all_bankroll['max_drawdown_percent']:.2f}% | {all_bankroll['max_losing_streak']} |\n")
            
            # Monthly comparison
            f.write("\n## Monthly Performance Highlights\n\n")
            
            # Best and worst months by threshold
            f.write("### Best and Worst Months by Threshold\n\n")
            f.write("| Threshold | Best Month | Best Profit | Worst Month | Worst Profit |\n")
            f.write("|-----------|-----------|------------|-------------|-------------|\n")
            
            for threshold, threshold_results in sorted(results.items(), key=lambda x: float(x[0])):
                # Combine train and test monthly data
                all_monthly = (
                    threshold_results['train']['overall']['monthly'] + 
                    threshold_results['test']['overall']['monthly']
                )
                
                if all_monthly:
                    best_month = max(all_monthly, key=lambda x: x['profit'])
                    worst_month = min(all_monthly, key=lambda x: x['profit'])
                    
                    f.write(f"| {threshold} | {best_month['month']} | {best_month['profit']:.2f} | {worst_month['month']} | {worst_month['profit']:.2f} |\n")
                else:
                    f.write(f"| {threshold} | N/A | N/A | N/A | N/A |\n")
            
            # Conclusion
            f.write("\n## Conclusion\n\n")
            
            # Find best performing threshold by ROI on test set
            best_threshold_roi = max(results.items(), key=lambda x: x[1]['test']['overall']['roi'])
            
            # Find best performing threshold by ending bankroll on test set
            best_threshold_bankroll = max(results.items(), key=lambda x: x[1]['test']['overall']['bankroll']['ending_bankroll'])
            
            # Find threshold with most bets on test set
            most_bets_threshold = max(results.items(), key=lambda x: x[1]['test']['overall']['bets'])
            
            f.write(f"- Best threshold by test ROI: **{best_threshold_roi[0]}** with ROI of {best_threshold_roi[1]['test']['overall']['roi']:.2%}\n")
            f.write(f"- Best threshold by test ending bankroll: **{best_threshold_bankroll[0]}** with ending bankroll of {best_threshold_bankroll[1]['test']['overall']['bankroll']['ending_bankroll']:,.2f}\n")
            f.write(f"- Threshold with most bets: **{most_bets_threshold[0]}** with {most_bets_threshold[1]['test']['overall']['bets']} bets\n")
        
        print(f"Threshold comparison markdown saved to {file_path}")
    except Exception as e:
        print(f"Error generating threshold comparison markdown: {e}")

def print_threshold_comparison(
    results: Dict[str, Dict[str, Dict[str, Any]]], 
    starting_bankroll: float, 
    flat_stake: float
):
    """Print threshold comparison results."""
    print("\nBTTS EDGE THRESHOLD COMPARISON")
    print("=" * 100)
    
    print(f"Starting bankroll: {starting_bankroll:,.2f}")
    print(f"Flat stake per bet: {flat_stake:,.2f}")
    
    # Print overall comparison
    print("\nOVERALL COMPARISON")
    print("-" * 100)
    print(f"{'Threshold':<10} | {'Split':<6} | {'Bets':<6} | {'Hit Rate':<10} | {'Avg Odds':<10} | {'Profit':<10} | {'ROI':<10} | {'Ending BR':<15} | {'Max DD':<10} | {'Max DD %':<10}")
    print("-" * 100)
    
    for threshold, threshold_results in sorted(results.items(), key=lambda x: float(x[0])):
        # Train results
        train_overall = threshold_results['train']['overall']
        train_bankroll = train_overall['bankroll']
        
        print(f"{threshold:<10} | {'Train':<6} | {train_overall['bets']:<6} | {train_overall['hit_rate']:.2%} | {train_overall['avg_odds']:.2f} | {train_overall['profit']:.2f} | {train_overall['roi']:.2%} | {train_bankroll['ending_bankroll']:,.2f} | {train_bankroll['max_drawdown_currency']:,.2f} | {train_bankroll['max_drawdown_percent']:.2f}%")
        
        # Test results
        test_overall = threshold_results['test']['overall']
        test_bankroll = test_overall['bankroll']
        
        print(f"{threshold:<10} | {'Test':<6} | {test_overall['bets']:<6} | {test_overall['hit_rate']:.2%} | {test_overall['avg_odds']:.2f} | {test_overall['profit']:.2f} | {test_overall['roi']:.2%} | {test_bankroll['ending_bankroll']:,.2f} | {test_bankroll['max_drawdown_currency']:,.2f} | {test_bankroll['max_drawdown_percent']:.2f}%")
        
        # Combined results
        all_bankroll = threshold_results['all']['bankroll']
        all_bets = train_overall['bets'] + test_overall['bets']
        all_wins = train_overall['wins'] + test_overall['wins']
        all_hit_rate = all_wins / all_bets if all_bets > 0 else 0
        all_profit = train_overall['profit'] + test_overall['profit']
        all_roi = all_profit / all_bets * 100 if all_bets > 0 else 0
        
        print(f"{threshold:<10} | {'All':<6} | {all_bets:<6} | {all_hit_rate:.2%} | {'N/A':<10} | {all_profit:.2f} | {all_roi:.2%} | {all_bankroll['ending_bankroll']:,.2f} | {all_bankroll['max_drawdown_currency']:,.2f} | {all_bankroll['max_drawdown_percent']:.2f}%")
        print("-" * 100)
    
    # Find best performing threshold by ROI on test set
    best_threshold_roi = max(results.items(), key=lambda x: x[1]['test']['overall']['roi'])
    
    # Find best performing threshold by ending bankroll on test set
    best_threshold_bankroll = max(results.items(), key=lambda x: x[1]['test']['overall']['bankroll']['ending_bankroll'])
    
    print("\nSUMMARY:")
    print(f"- Best threshold by test ROI: {best_threshold_roi[0]} with ROI of {best_threshold_roi[1]['test']['overall']['roi']:.2%}")
    print(f"- Best threshold by test ending bankroll: {best_threshold_bankroll[0]} with ending bankroll of {best_threshold_bankroll[1]['test']['overall']['bankroll']['ending_bankroll']:,.2f}")

def main():
    """Main function to run the BTTS rule validation."""
    # Parse command line arguments
    parser = argparse.ArgumentParser(description="Validate BTTS rule with train/test split")
    parser.add_argument("--db", type=str, help="Path to the database file")
    parser.add_argument("--reports-dir", type=str, default="/root/betagent/reports", 
                        help="Directory to save reports (default: /root/betagent/reports)")
    parser.add_argument("--starting-bankroll", type=float, default=100000,
                        help="Starting bankroll amount (default: 100000)")
    parser.add_argument("--flat-stake", type=float, default=1000,
                        help="Flat stake per bet (default: 1000)")
    parser.add_argument("--thresholds", type=float, nargs="+",
                        help="Edge thresholds to compare (e.g., 0.015 0.010 0.005)")
    parser.add_argument("--min-edge", type=float, default=0.0,
                        help="Minimum edge vs market probability (default: 0.0)")
    args = parser.parse_args()
    
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    run_timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    # Check if we're in threshold comparison mode
    threshold_mode = args.thresholds is not None and len(args.thresholds) > 0
    
    if threshold_mode:
        print(f"Starting BTTS threshold comparison at {run_timestamp}")
        print(f"Comparing thresholds: {', '.join([f'{t:.3f}' for t in args.thresholds])}")
    else:
        print(f"Starting BTTS rule validation at {run_timestamp}")
        print(f"Using min edge: {args.min_edge:.3f}")
    
    conn = None
    try:
        conn = get_conn(args.db)
        db_path = conn.execute("PRAGMA database_list").fetchone()[2]  # Get actual DB path
        print(f"Using database: {db_path}")
        
        # Fetch and prepare data
        print("Fetching matches...")
        matches = fetch_matches(conn)
        print(f"Loaded {len(matches)} matches from database")
        
        print("Preparing data and calculating form features...")
        enriched_matches = prepare_data(matches)
        print(f"Data preparation complete")
        
        # Save reports
        ensure_reports_dir(args.reports_dir)
        
        if threshold_mode:
            # Compare thresholds
            print("Comparing BTTS rule with different edge thresholds...")
            threshold_results = compare_thresholds(
                enriched_matches, 
                args.thresholds,
                args.starting_bankroll, 
                args.flat_stake
            )
            
            # Print threshold comparison
            print_threshold_comparison(threshold_results, args.starting_bankroll, args.flat_stake)
            
            # Define file paths for threshold comparison
            threshold_csv_path = os.path.join(args.reports_dir, f"btts_threshold_compare_{timestamp}.csv")
            threshold_monthly_csv_path = os.path.join(args.reports_dir, f"btts_threshold_compare_monthly_{timestamp}.csv")
            threshold_md_path = os.path.join(args.reports_dir, f"btts_threshold_compare_{timestamp}.md")
            
            # Save threshold comparison files
            try:
                save_threshold_comparison_to_csv(threshold_results, threshold_csv_path)
                save_threshold_monthly_to_csv(threshold_results, threshold_monthly_csv_path)
                
                generate_threshold_comparison_markdown(
                    run_timestamp,
                    db_path,
                    threshold_results,
                    threshold_md_path,
                    args.starting_bankroll,
                    args.flat_stake
                )
                
                # Print file paths
                print("\nReports saved to:")
                print(f"  - {threshold_csv_path}")
                print(f"  - {threshold_monthly_csv_path}")
                print(f"  - {threshold_md_path}")
            except Exception as e:
                print(f"Error saving threshold comparison reports: {e}")
                import traceback
                traceback.print_exc()
        else:
            # Apply rule and get results
            print(f"Applying BTTS rule with min_edge = {args.min_edge:.3f}...")
            results = apply_btts_rule(enriched_matches, args.starting_bankroll, args.flat_stake, args.min_edge)
            
            # Print results
            print_results(results, args.starting_bankroll, args.flat_stake)
            
            # Print staking comparison
            print_staking_comparison(results, args.starting_bankroll, args.flat_stake)
            
            # Define file paths
            csv_path = os.path.join(args.reports_dir, f"btts_validation_{timestamp}.csv")
            monthly_csv_path = os.path.join(args.reports_dir, f"btts_validation_monthly_{timestamp}.csv")
            md_path = os.path.join(args.reports_dir, f"btts_validation_{timestamp}.md")
            
            # Define staking comparison file paths
            staking_csv_path = os.path.join(args.reports_dir, f"btts_staking_compare_{timestamp}.csv")
            staking_monthly_csv_path = os.path.join(args.reports_dir, f"btts_staking_monthly_{timestamp}.csv")
            staking_md_path = os.path.join(args.reports_dir, f"btts_staking_compare_{timestamp}.md")
            
            # Save CSV files
            try:
                save_results_to_csv(results, csv_path, args.flat_stake)
                save_monthly_results_to_csv(results, monthly_csv_path)
                
                # Save staking comparison files
                save_staking_comparison_to_csv(results, staking_csv_path)
                save_staking_monthly_to_csv(results, staking_monthly_csv_path)
                
                # Generate markdown summaries
                generate_markdown_summary(
                    run_timestamp,
                    db_path,
                    results,
                    md_path,
                    args.starting_bankroll,
                    args.flat_stake
                )
                
                generate_staking_comparison_markdown(
                    run_timestamp,
                    db_path,
                    results,
                    staking_md_path,
                    args.starting_bankroll,
                    args.flat_stake
                )
                
                # Print file paths
                print("\nReports saved to:")
                print(f"  - {csv_path}")
                print(f"  - {monthly_csv_path}")
                print(f"  - {md_path}")
                print(f"  - {staking_csv_path}")
                print(f"  - {staking_monthly_csv_path}")
                print(f"  - {staking_md_path}")
            except Exception as e:
                print(f"Error saving reports: {e}")
                import traceback
                traceback.print_exc()
            
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        return 1
    finally:
        if conn:
            conn.close()
    
    if threshold_mode:
        print(f"\nBTTS threshold comparison completed at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    else:
        print(f"\nBTTS rule validation completed at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

if __name__ == "__main__":
    main()
