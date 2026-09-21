#!/usr/bin/env python3
"""
Tennis ML Enriched Dataset v3
==============================
Improves odds join coverage via name normalization.
Both tables use English names; backtest has mixed short/long formats.
Strategy: canonicalize to short format, join on names+year+tour.

Sources: backtest_tennis_players (primary) + tennis_data_odds (odds only)
"""

import sqlite3
from pathlib import Path
import numpy as np
import pandas as pd

DB_PATH = Path(__file__).resolve().parent.parent / "betagent.db"
DATA_DIR = Path(__file__).resolve().parent.parent / "data"
ANALYSIS_DIR = Path(__file__).resolve().parent
DATA_DIR.mkdir(exist_ok=True)


def to_short_name(name):
    """Normalize to 'LastName F.' format. Already-short names pass through."""
    name = name.strip()
    if not name or pd.isna(name):
        return name
    if '. ' in name or name.endswith('.'):
        return name
    parts = name.split()
    if len(parts) == 1:
        return name
    last = parts[-1]
    first_initial = parts[0][0] + '.'
    return f'{last} {first_initial}'


def build_enriched_features(history):
    """Compute rolling, surface, fatigue, H2H features (same as v2)."""
    # Rolling features
    for n in [5, 10]:
        history[f"win_pct_{n}"] = (
            history.groupby("player_name")["won"]
            .transform(lambda x: x.shift(1).rolling(n, min_periods=1).mean())
        )
        history[f"ss_pct_{n}"] = (
            history.groupby("player_name")["straight_sets"]
            .transform(lambda x: x.shift(1).rolling(n, min_periods=1).mean())
        )

    for col in ["ace", "df", "first_in"]:
        history[f"{col}_roll10"] = (
            history.groupby("player_name")[col]
            .transform(lambda x: x.shift(1).rolling(10, min_periods=1).mean())
        )

    history["first_in_shifted"] = history.groupby("player_name")["first_in"].shift(1)
    history["first_won_shifted"] = history.groupby("player_name")["first_won"].shift(1)
    history["first_won_pct_roll10"] = (
        history.groupby("player_name")["first_won_shifted"]
        .transform(lambda x: x.rolling(10, min_periods=1).sum())
    ) / (
        history.groupby("player_name")["first_in_shifted"]
        .transform(lambda x: x.rolling(10, min_periods=1).sum())
    )

    history["bp_saved_shifted"] = history.groupby("player_name")["bp_saved"].shift(1)
    history["bp_faced_shifted"] = history.groupby("player_name")["bp_faced"].shift(1)
    history["bp_saved_pct_roll10"] = (
        history.groupby("player_name")["bp_saved_shifted"]
        .transform(lambda x: x.rolling(10, min_periods=1).sum())
    ) / (
        history.groupby("player_name")["bp_faced_shifted"]
        .transform(lambda x: x.rolling(10, min_periods=1).sum())
    )

    history["minutes_roll5"] = (
        history.groupby("player_name")["minutes"]
        .transform(lambda x: x.shift(1).rolling(5, min_periods=1).mean())
    )

    history.drop(columns=[
        "first_in_shifted", "first_won_shifted",
        "bp_saved_shifted", "bp_faced_shifted"
    ], inplace=True)

    # Surface features
    surface_stats = (
        history.groupby(["player_name", "surface"])["won"]
        .transform(lambda x: x.shift(1).expanding().mean())
    )
    history["surface_win_pct"] = surface_stats
    history["surface_matches"] = history.groupby(["player_name", "surface"]).cumcount()

    for col in ["ace", "first_won", "first_in", "bp_saved", "bp_faced"]:
        history[f"{col}_surf_shifted"] = history.groupby(["player_name", "surface"])[col].shift(1)

    history["surface_ace_avg"] = (
        history.groupby(["player_name", "surface"])["ace_surf_shifted"]
        .transform(lambda x: x.rolling(10, min_periods=1).mean())
    )

    surf_fw_sum = (
        history.groupby(["player_name", "surface"])["first_won_surf_shifted"]
        .transform(lambda x: x.rolling(10, min_periods=1).sum())
    )
    surf_fi_sum = (
        history.groupby(["player_name", "surface"])["first_in_surf_shifted"]
        .transform(lambda x: x.rolling(10, min_periods=1).sum())
    )
    history["surface_1st_won_pct"] = surf_fw_sum / surf_fi_sum

    surf_bps_sum = (
        history.groupby(["player_name", "surface"])["bp_saved_surf_shifted"]
        .transform(lambda x: x.rolling(10, min_periods=1).sum())
    )
    surf_bpf_sum = (
        history.groupby(["player_name", "surface"])["bp_faced_surf_shifted"]
        .transform(lambda x: x.rolling(10, min_periods=1).sum())
    )
    history["surface_bp_saved_pct"] = surf_bps_sum / surf_bpf_sum

    history.drop(columns=[
        "ace_surf_shifted", "first_won_surf_shifted", "first_in_surf_shifted",
        "bp_saved_surf_shifted", "bp_faced_surf_shifted"
    ], inplace=True)

    # Fatigue features
    history["prev_date"] = history.groupby("player_name")["tourney_date"].shift(1)
    history["days_rest"] = (history["tourney_date"] - history["prev_date"]).dt.days

    fatigue_data = []
    for player, grp in history.groupby("player_name"):
        if len(grp) <= 1:
            fatigue_data.append(pd.DataFrame({
                "idx": grp.index,
                "matches_7d": 0,
                "matches_14d": 0,
                "minutes_14d": np.nan,
            }))
            continue

        dates = grp["tourney_date"].values
        minutes = grp["minutes"].values.astype(float)
        n = len(grp)

        m7 = np.zeros(n, dtype=int)
        m14 = np.zeros(n, dtype=int)
        min14 = np.full(n, np.nan)

        for i in range(1, n):
            d = dates[i]
            d7 = d - np.timedelta64(7, 'D')
            d14 = d - np.timedelta64(14, 'D')
            mask7 = (dates[:i] >= d7) & (dates[:i] < d)
            mask14 = (dates[:i] >= d14) & (dates[:i] < d)
            m7[i] = mask7.sum()
            m14[i] = mask14.sum()
            if mask14.any():
                min14[i] = np.nansum(minutes[:i][mask14])

        fatigue_data.append(pd.DataFrame({
            "idx": grp.index,
            "matches_7d": m7,
            "matches_14d": m14,
            "minutes_14d": min14,
        }))

    fatigue_df = pd.concat(fatigue_data, ignore_index=True)
    fatigue_df = fatigue_df.set_index("idx")
    history["matches_7d"] = fatigue_df["matches_7d"]
    history["matches_14d"] = fatigue_df["matches_14d"]
    history["minutes_14d"] = fatigue_df["minutes_14d"]
    history.drop(columns=["prev_date"], inplace=True)

    return history


def build_h2h(btp_sorted):
    """Build H2H features from backtest_tennis_players.

    Only count PRIOR encounters between the two players.
    The current match result must NOT be included in H2H features.
    For both rows of the same match, the H2H values are identical
    (just swapped between player/opponent perspective).

    BUG FIX (2026-04-12): Previously h2h_wins was incremented by 1 for every
    match regardless of winner, making w_h2h_wins == total prior meetings and
    l_h2h_wins == 0. This encoded the match outcome directly into features.
    Now we track actual wins per player in each H2H pair.
    """
    h2h_counts = {}       # key -> total prior matches
    h2h_p1_wins = {}      # key -> prior wins by alphabetically-first player

    w_h2h_wins = np.zeros(len(btp_sorted), dtype=int)
    l_h2h_wins = np.zeros(len(btp_sorted), dtype=int)
    h2h_total = np.zeros(len(btp_sorted), dtype=int)

    for i, row in btp_sorted.iterrows():
        winner, loser = row["winner_name"], row["loser_name"]
        key = tuple(sorted([winner, loser]))
        p1 = key[0]  # alphabetically-first player

        # Assign PRIOR H2H stats only (before this match)
        h2h_total[i] = h2h_counts.get(key, 0)
        prior_p1_wins = h2h_p1_wins.get(key, 0)
        prior_p2_wins = h2h_counts.get(key, 0) - prior_p1_wins

        # Map to winner/loser perspective
        if winner == p1:
            w_h2h_wins[i] = prior_p1_wins
            l_h2h_wins[i] = prior_p2_wins
        else:
            w_h2h_wins[i] = prior_p2_wins
            l_h2h_wins[i] = prior_p1_wins

        # Now update counters with this match result (for future matches)
        h2h_counts[key] = h2h_counts.get(key, 0) + 1
        if winner == p1:
            h2h_p1_wins[key] = h2h_p1_wins.get(key, 0) + 1
        else:
            h2h_p1_wins[key] = h2h_p1_wins.get(key, 0)

    btp_sorted["w_h2h_wins"] = w_h2h_wins
    btp_sorted["h2h_total"] = h2h_total
    btp_sorted["l_h2h_wins"] = l_h2h_wins
    return btp_sorted


def join_odds_v3(btp_df, odds_df):
    """
    Join odds onto backtest matches using name normalization.

    Returns btp_df with added odds columns and join_confidence flag.
    """
    # Create canonical names for both tables
    btp_df = btp_df.copy()
    btp_df["c_winner"] = btp_df["winner_name"].apply(to_short_name)
    btp_df["c_loser"] = btp_df["loser_name"].apply(to_short_name)

    odds_df = odds_df.copy()
    odds_df["c_winner"] = odds_df["winner"].apply(to_short_name)
    odds_df["c_loser"] = odds_df["loser"].apply(to_short_name)

    # Build lookup from odds: (c_winner, c_loser, year, tour) -> odds
    odds_lookup = {}
    for _, row in odds_df.iterrows():
        key = (row["c_winner"], row["c_loser"], row["year"], row["tour"])
        if key not in odds_lookup:
            odds_lookup[key] = []
        odds_lookup[key].append(row)

    # Also build reverse lookup (swapped) for cases where winner/loser might be flipped
    odds_lookup_swapped = {}
    for _, row in odds_df.iterrows():
        key = (row["c_loser"], row["c_winner"], row["year"], row["tour"])
        if key not in odds_lookup_swapped:
            odds_lookup_swapped[key] = []
        odds_lookup_swapped[key].append(row)

    # For each btp row, try to find matching odds
    btp_df["odds_player"] = np.nan
    btp_df["odds_opponent"] = np.nan
    btp_df["join_confidence"] = "unmatched"
    btp_df["join_type"] = ""

    for idx, row in btp_df.iterrows():
        key = (row["c_winner"], row["c_loser"], row["year"], row["tour"])

        if key in odds_lookup:
            matches = odds_lookup[key]
            if len(matches) == 1:
                btp_df.at[idx, "odds_player"] = matches[0]["b365_winner"]
                btp_df.at[idx, "odds_opponent"] = matches[0]["b365_loser"]
                btp_df.at[idx, "join_confidence"] = "high"
                btp_df.at[idx, "join_type"] = "exact"
            else:
                # Multiple odds matches — pick first, mark medium
                btp_df.at[idx, "odds_player"] = matches[0]["b365_winner"]
                btp_df.at[idx, "odds_opponent"] = matches[0]["b365_loser"]
                btp_df.at[idx, "join_confidence"] = "medium"
                btp_df.at[idx, "join_type"] = f"multi_odds_{len(matches)}"
        elif key in odds_lookup_swapped:
            matches = odds_lookup_swapped[key]
            btp_df.at[idx, "odds_player"] = matches[0]["b365_loser"]
            btp_df.at[idx, "odds_opponent"] = matches[0]["b365_winner"]
            btp_df.at[idx, "join_confidence"] = "suspicious"
            btp_df.at[idx, "join_type"] = "swapped"
        else:
            # Try without tour (year only)
            key_no_tour = (row["c_winner"], row["c_loser"], row["year"])
            found = False
            for okey, matches in odds_lookup.items():
                if (okey[0], okey[1], okey[2]) == key_no_tour:
                    btp_df.at[idx, "odds_player"] = matches[0]["b365_winner"]
                    btp_df.at[idx, "odds_opponent"] = matches[0]["b365_loser"]
                    btp_df.at[idx, "join_confidence"] = "medium"
                    btp_df.at[idx, "join_type"] = "year_only"
                    found = True
                    break
            if not found:
                for okey, matches in odds_lookup_swapped.items():
                    if (okey[0], okey[1], okey[2]) == key_no_tour:
                        btp_df.at[idx, "odds_player"] = matches[0]["b365_loser"]
                        btp_df.at[idx, "odds_opponent"] = matches[0]["b365_winner"]
                        btp_df.at[idx, "join_confidence"] = "suspicious"
                        btp_df.at[idx, "join_type"] = "swapped_year_only"
                        found = True
                        break

    return btp_df


def main():
    print("=" * 60)
    print("Tennis ML Enriched Dataset v3")
    print("=" * 60)

    conn = sqlite3.connect(str(DB_PATH))
    btp = pd.read_sql("SELECT * FROM backtest_tennis_players", conn)
    odds = pd.read_sql("SELECT * FROM tennis_data_odds", conn)
    conn.close()

    print(f"  backtest_tennis_players: {len(btp)} rows")
    print(f"  tennis_data_odds: {len(odds)} rows")

    # ============================================================
    # 1. Join odds with name normalization
    # ============================================================
    print("\n--- Step 1: Joining odds (name normalization) ---")

    btp_sorted = btp.sort_values("tourney_date").reset_index(drop=True)
    btp_sorted["tourney_date"] = pd.to_datetime(btp_sorted["tourney_date"])
    btp_sorted = join_odds_v3(btp_sorted, odds)

    n_high = (btp_sorted["join_confidence"] == "high").sum()
    n_medium = (btp_sorted["join_confidence"] == "medium").sum()
    n_suspicious = (btp_sorted["join_confidence"] == "suspicious").sum()
    n_unmatched = (btp_sorted["join_confidence"] == "unmatched").sum()

    print(f"  High confidence:   {n_high} ({n_high/len(btp_sorted)*100:.1f}%)")
    print(f"  Medium confidence: {n_medium} ({n_medium/len(btp_sorted)*100:.1f}%)")
    print(f"  Suspicious:        {n_suspicious} ({n_suspicious/len(btp_sorted)*100:.1f}%)")
    print(f"  Unmatched:         {n_unmatched} ({n_unmatched/len(btp_sorted)*100:.1f}%)")
    print(f"  Total with odds:   {n_high + n_medium + n_suspicious} ({(n_high+n_medium+n_suspicious)/len(btp_sorted)*100:.1f}%)")

    # ============================================================
    # 2. Build enriched features
    # ============================================================
    print("\n--- Step 2: Building enriched features ---")

    w = btp_sorted.rename(columns={
        "winner_name": "player_name", "winner_rank": "player_rank",
        "winner_rank_pts": "player_rank_pts",
        "w_ace": "ace", "w_df": "df", "w_1stIn": "first_in",
        "w_1stWon": "first_won", "w_2ndWon": "second_won",
        "w_bpSaved": "bp_saved", "w_bpFaced": "bp_faced",
        "sets_winner": "sets_won", "sets_loser": "sets_lost",
    }).assign(won=1)

    l = btp_sorted.rename(columns={
        "loser_name": "player_name", "loser_rank": "player_rank",
        "loser_rank_pts": "player_rank_pts",
        "l_ace": "ace", "l_df": "df", "l_1stIn": "first_in",
        "l_1stWon": "first_won", "l_2ndWon": "second_won",
        "l_bpSaved": "bp_saved", "l_bpFaced": "bp_faced",
        "sets_winner": "sets_won", "sets_loser": "sets_lost",
    }).assign(won=0)

    history = pd.concat([w, l], ignore_index=True)
    history["tourney_date"] = pd.to_datetime(history["tourney_date"])
    history = history.sort_values(["player_name", "tourney_date"]).reset_index(drop=True)

    print(f"  Player history: {len(history)} rows, {history['player_name'].nunique()} players")

    history = build_enriched_features(history)
    print("  Enriched features computed")

    # ============================================================
    # 3. H2H
    # ============================================================
    print("\n--- Step 3: H2H ---")
    btp_sorted = build_h2h(btp_sorted)
    n_with_h2h = (btp_sorted["h2h_total"] > 0).sum()
    print(f"  Matches with prior H2H: {n_with_h2h}")

    # ============================================================
    # 4. Merge features back to match-level
    # ============================================================
    print("\n--- Step 4: Merging features ---")

    hist_features = history[["id", "tour", "year", "tourney_name", "surface", "tourney_date",
                              "round", "player_name",
                              "win_pct_5", "win_pct_10", "ss_pct_5", "ss_pct_10",
                              "ace_roll10", "df_roll10", "first_in_roll10",
                              "first_won_pct_roll10", "bp_saved_pct_roll10",
                              "minutes_roll5",
                              "surface_win_pct", "surface_matches",
                              "surface_ace_avg", "surface_1st_won_pct", "surface_bp_saved_pct",
                              "days_rest", "matches_7d", "matches_14d", "minutes_14d"]].copy()

    w_feat = hist_features.rename(columns={
        "player_name": "winner_name",
        "win_pct_5": "w_win_pct_5", "win_pct_10": "w_win_pct_10",
        "ss_pct_5": "w_ss_pct_5", "ss_pct_10": "w_ss_pct_10",
        "ace_roll10": "w_ace_roll10", "df_roll10": "w_df_roll10",
        "first_in_roll10": "w_first_in_roll10",
        "first_won_pct_roll10": "w_first_won_pct_roll10",
        "bp_saved_pct_roll10": "w_bp_saved_pct_roll10",
        "minutes_roll5": "w_minutes_roll5",
        "surface_win_pct": "w_surface_win_pct",
        "surface_matches": "w_surface_matches",
        "surface_ace_avg": "w_surface_ace_avg",
        "surface_1st_won_pct": "w_surface_1st_won_pct",
        "surface_bp_saved_pct": "w_surface_bp_saved_pct",
        "days_rest": "w_days_rest",
        "matches_7d": "w_matches_7d",
        "matches_14d": "w_matches_14d",
        "minutes_14d": "w_minutes_14d",
    })

    l_feat = hist_features.rename(columns={
        "player_name": "loser_name",
        "win_pct_5": "l_win_pct_5", "win_pct_10": "l_win_pct_10",
        "ss_pct_5": "l_ss_pct_5", "ss_pct_10": "l_ss_pct_10",
        "ace_roll10": "l_ace_roll10", "df_roll10": "l_df_roll10",
        "first_in_roll10": "l_first_in_roll10",
        "first_won_pct_roll10": "l_first_won_pct_roll10",
        "bp_saved_pct_roll10": "l_bp_saved_pct_roll10",
        "minutes_roll5": "l_minutes_roll5",
        "surface_win_pct": "l_surface_win_pct",
        "surface_matches": "l_surface_matches",
        "surface_ace_avg": "l_surface_ace_avg",
        "surface_1st_won_pct": "l_surface_1st_won_pct",
        "surface_bp_saved_pct": "l_surface_bp_saved_pct",
        "days_rest": "l_days_rest",
        "matches_7d": "l_matches_7d",
        "matches_14d": "l_matches_14d",
        "minutes_14d": "l_minutes_14d",
    })

    merge_keys = ["id", "tour", "year", "tourney_name", "surface", "tourney_date", "round"]

    df = btp_sorted.merge(
        w_feat, on=["winner_name"] + merge_keys, how="left"
    ).merge(
        l_feat, on=["loser_name"] + merge_keys, how="left"
    )

    print(f"  Merged: {len(df)} rows, {len(df.columns)} columns")

    # ============================================================
    # 5. Build match-level rows (2 per match)
    # ============================================================
    print("\n--- Step 5: Building match-level rows ---")

    df["rank_diff"] = df["loser_rank"] - df["winner_rank"]
    df["rank_pts_diff"] = df["winner_rank_pts"] - df["loser_rank_pts"]

    def make_perspective(src, is_winner=True):
        pfx = "w" if is_winner else "l"
        opfx = "l" if is_winner else "w"
        return pd.DataFrame({
            "match_id": src["id"],
            "tour": src["tour"],
            "year": src["year"],
            "tourney_name": src["tourney_name"],
            "surface": src["surface"],
            "round": src["round"],
            "best_of": src["best_of"],
            "tourney_date": src["tourney_date"],
            "tourney_level": src["tourney_level"],
            "target": 1 if is_winner else 0,
            "odds_player": src["odds_player"],
            "odds_opponent": src["odds_opponent"],
            "player_rank": src[f"winner_rank"] if is_winner else src[f"loser_rank"],
            "opponent_rank": src[f"loser_rank"] if is_winner else src[f"winner_rank"],
            "player_rank_pts": src[f"winner_rank_pts"] if is_winner else src[f"loser_rank_pts"],
            "opponent_rank_pts": src[f"loser_rank_pts"] if is_winner else src[f"winner_rank_pts"],
            "rank_diff": src["rank_diff"] if is_winner else -src["rank_diff"],
            "rank_pts_diff": src["rank_pts_diff"] if is_winner else -src["rank_pts_diff"],
            "player_win_pct_5": src[f"{pfx}_win_pct_5"],
            "player_win_pct_10": src[f"{pfx}_win_pct_10"],
            "player_ss_pct_5": src[f"{pfx}_ss_pct_5"],
            "player_ss_pct_10": src[f"{pfx}_ss_pct_10"],
            "opponent_win_pct_5": src[f"{opfx}_win_pct_5"],
            "opponent_win_pct_10": src[f"{opfx}_win_pct_10"],
            "opponent_ss_pct_5": src[f"{opfx}_ss_pct_5"],
            "opponent_ss_pct_10": src[f"{opfx}_ss_pct_10"],
            "player_ace_avg": src[f"{pfx}_ace_roll10"],
            "player_df_avg": src[f"{pfx}_df_roll10"],
            "player_1st_in_avg": src[f"{pfx}_first_in_roll10"],
            "player_1st_won_pct": src[f"{pfx}_first_won_pct_roll10"],
            "player_bp_saved_pct": src[f"{pfx}_bp_saved_pct_roll10"],
            "player_minutes_avg": src[f"{pfx}_minutes_roll5"],
            "opponent_ace_avg": src[f"{opfx}_ace_roll10"],
            "opponent_df_avg": src[f"{opfx}_df_roll10"],
            "opponent_1st_in_avg": src[f"{opfx}_first_in_roll10"],
            "opponent_1st_won_pct": src[f"{opfx}_first_won_pct_roll10"],
            "opponent_bp_saved_pct": src[f"{opfx}_bp_saved_pct_roll10"],
            "opponent_minutes_avg": src[f"{opfx}_minutes_roll5"],
            "player_surface_win_pct": src[f"{pfx}_surface_win_pct"],
            "player_surface_matches": src[f"{pfx}_surface_matches"],
            "player_surface_ace_avg": src[f"{pfx}_surface_ace_avg"],
            "player_surface_1st_won_pct": src[f"{pfx}_surface_1st_won_pct"],
            "player_surface_bp_saved_pct": src[f"{pfx}_surface_bp_saved_pct"],
            "opponent_surface_win_pct": src[f"{opfx}_surface_win_pct"],
            "opponent_surface_matches": src[f"{opfx}_surface_matches"],
            "opponent_surface_ace_avg": src[f"{opfx}_surface_ace_avg"],
            "opponent_surface_1st_won_pct": src[f"{opfx}_surface_1st_won_pct"],
            "opponent_surface_bp_saved_pct": src[f"{opfx}_surface_bp_saved_pct"],
            "player_days_rest": src[f"{pfx}_days_rest"],
            "player_matches_7d": src[f"{pfx}_matches_7d"],
            "player_matches_14d": src[f"{pfx}_matches_14d"],
            "player_minutes_14d": src[f"{pfx}_minutes_14d"],
            "opponent_days_rest": src[f"{opfx}_days_rest"],
            "opponent_matches_7d": src[f"{opfx}_matches_7d"],
            "opponent_matches_14d": src[f"{opfx}_matches_14d"],
            "opponent_minutes_14d": src[f"{opfx}_minutes_14d"],
            "h2h_player_wins": src[f"{pfx}_h2h_wins"],
            "h2h_opponent_wins": src[f"{opfx}_h2h_wins"],
            "h2h_total": src["h2h_total"],
            "join_confidence": src["join_confidence"],
            "join_type": src["join_type"],
        })

    # Fix column names — btp_sorted has winner_rank, loser_rank (not w_rank/l_rank)
    df = df.rename(columns={
        "winner_rank": "winner_rank",
        "loser_rank": "loser_rank",
        "winner_rank_pts": "winner_rank_pts",
        "loser_rank_pts": "loser_rank_pts",
    })

    w_rows = make_perspective(df, is_winner=True)
    l_rows = make_perspective(df, is_winner=False)

    match_df = pd.concat([w_rows, l_rows], ignore_index=True)
    match_df = match_df.sample(frac=1, random_state=42).reset_index(drop=True)
    print(f"  Match-level rows: {len(match_df)} ({match_df['target'].mean():.3f} win rate)")

    # ============================================================
    # 6. Save
    # ============================================================
    csv_path = DATA_DIR / "tennis_ml_enriched_v3.csv"
    match_df.to_csv(str(csv_path), index=False)
    print(f"\nDataset saved: {csv_path}")

    # ============================================================
    # 7. Report
    # ============================================================
    generate_report(df, match_df, n_high, n_medium, n_suspicious, n_unmatched)

    print("\n" + "=" * 60)
    print("DONE")
    print("=" * 60)


def generate_report(df, match_df, n_high, n_medium, n_suspicious, n_unmatched):
    lines = []
    lines.append("# Tennis ML Enriched Dataset v3 — Coverage Report")
    lines.append("")
    lines.append("## 1. Join Coverage (v3 vs v2)")
    lines.append("")
    lines.append(f"- backtest_tennis_players total rows: {len(df)}")
    lines.append(f"- High confidence: {n_high} ({n_high/len(df)*100:.1f}%)")
    lines.append(f"- Medium confidence: {n_medium} ({n_medium/len(df)*100:.1f}%)")
    lines.append(f"- Suspicious: {n_suspicious} ({n_suspicious/len(df)*100:.1f}%)")
    lines.append(f"- Total with odds: {n_high + n_medium + n_suspicious} ({(n_high+n_medium+n_suspicious)/len(df)*100:.1f}%)")
    lines.append(f"- Unmatched: {n_unmatched} ({n_unmatched/len(df)*100:.1f}%)")
    lines.append("")
    lines.append("| Version | Odds Coverage |")
    lines.append("|---------|--------------|")
    lines.append("| v2 (exact rank) | 11.9% |")
    lines.append(f"| v3 (name norm) | {(n_high+n_medium+n_suspicious)/len(df)*100:.1f}% |")
    lines.append("")

    lines.append("## 2. Usable Rows")
    lines.append("")
    lines.append(f"- Enriched match-level rows: {len(match_df)}")
    lines.append(f"- Year range: {match_df['year'].min()} - {match_df['year'].max()}")
    lines.append(f"- Tours: {match_df['tour'].unique().tolist()}")
    lines.append(f"- Surfaces: {match_df['surface'].unique().tolist()}")
    lines.append("")

    lines.append("## 3. Confidence Distribution")
    lines.append("")
    conf_counts = match_df["join_confidence"].value_counts()
    for conf, cnt in conf_counts.items():
        lines.append(f"- {conf}: {cnt} ({cnt/len(match_df)*100:.1f}%)")
    lines.append("")

    lines.append("## 4. Missing Rates (Top 20)")
    lines.append("")
    missing = match_df.isna().mean().sort_values(ascending=False)
    lines.append("| Feature | Missing % |")
    lines.append("|---------|-----------|")
    for feat, rate in missing.head(20).items():
        if rate > 0:
            lines.append(f"| {feat} | {rate*100:.1f}% |")
    lines.append("")

    lines.append("## 5. Feature Coverage Summary")
    lines.append("")
    n_with_odds = match_df["odds_player"].notna().sum()
    n_with_serve = match_df["player_ace_avg"].notna().sum()
    n_with_surface = match_df["player_surface_win_pct"].notna().sum()
    n_with_h2h = (match_df["h2h_total"] > 0).sum()
    n_with_fatigue = match_df["player_days_rest"].notna().sum()

    lines.append(f"- Rows with odds: {n_with_odds} ({n_with_odds/len(match_df)*100:.1f}%)")
    lines.append(f"- Rows with serve stats: {n_with_serve} ({n_with_serve/len(match_df)*100:.1f}%)")
    lines.append(f"- Rows with surface stats: {n_with_surface} ({n_with_surface/len(match_df)*100:.1f}%)")
    lines.append(f"- Rows with H2H history: {n_with_h2h} ({n_with_h2h/len(match_df)*100:.1f}%)")
    lines.append(f"- Rows with fatigue data: {n_with_fatigue} ({n_with_fatigue/len(match_df)*100:.1f}%)")
    lines.append("")

    lines.append("## 6. Join Type Breakdown")
    lines.append("")
    type_counts = match_df["join_type"].value_counts()
    for jtype, cnt in type_counts.items():
        lines.append(f"- {jtype}: {cnt}")
    lines.append("")

    lines.append("## 7. Verdict")
    lines.append("")
    if n_with_odds > 10000:
        lines.append(f"- Dataset has {n_with_odds} rows with odds — **READY** for baseline ML model")
        lines.append(f"- Odds coverage improved from 11.9% (v2) to {n_with_odds/len(match_df)*100:.1f}% (v3)")
        lines.append("- Name normalization is the primary improvement driver")
        lines.append("- High confidence subset recommended for initial model training")
    else:
        lines.append(f"- Dataset has {n_with_odds} rows with odds — may need more data sources")
    lines.append("")

    report = "\n".join(lines)
    report_path = ANALYSIS_DIR / "tennis_ml_enriched_v3_report.md"
    report_path.write_text(report)
    print(f"\nReport saved: {report_path}")


if __name__ == "__main__":
    main()
