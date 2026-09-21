from .football import (
    FOOTBALL_LEAGUE_STAKING,
    BACKTEST_LEAGUE_NAME_MAP,
    detect_football_league_key,
    normalize_rule_league_name,
    is_rpl_league,
    is_pd_league,
    is_epl_league,
    is_fl1_league,
    is_bundesliga_league,
    is_serie_a_league,
    is_ligue1_league,
    is_nla_league,
    is_mls_league,
)
from .hockey import (
    HOCKEY_LEAGUE_CONFIG,
    detect_league_key,
    get_hockey_features,
    validate_hockey_recommendation,
    process_hockey_match,
    _set_dependencies,
)

__all__ = [
    # football
    "FOOTBALL_LEAGUE_STAKING",
    "BACKTEST_LEAGUE_NAME_MAP",
    "detect_football_league_key",
    "normalize_rule_league_name",
    "is_rpl_league",
    "is_pd_league",
    "is_epl_league",
    "is_fl1_league",
    "is_bundesliga_league",
    "is_serie_a_league",
    "is_ligue1_league",
    "is_nla_league",
    "is_mls_league",
    # hockey
    "HOCKEY_LEAGUE_CONFIG",
    "detect_league_key",
    "get_hockey_features",
    "validate_hockey_recommendation",
    "process_hockey_match",
    "_set_dependencies",
]
