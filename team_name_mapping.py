# Маппинг английских названий (backtest_matches) -> русские (backtest_football_stats)

# League-specific shot-to-goal conversion rates for xg proxy calculation
# Computed from avg(goals) / avg(shots) per league
CONVERSION_RATES = {
    "EPL": {"home": 0.327, "away": 0.327},
    "SA":  {"home": 0.311, "away": 0.321},
    "PD":  {"home": 0.313, "away": 0.311},
    "FL1": {"home": 0.328, "away": 0.310},
    "RPL": {"home": 0.321, "away": 0.298},
    "BL1": {"home": 0.347, "away": 0.325},
}

BL1_MAP = {
    "Augsburg": "Аугсбург",
    "Bayern Munich": "Бавария",
    "Bielefeld": "Арминия",
    "Bochum": "Бохум",
    "Darmstadt": "Дармштадт 98",
    "Dortmund": "Боруссия Дортмунд",
    "Ein Frankfurt": "Айнтрахт Франкфурт",
    "FC Koln": "Кёльн",
    "Freiburg": "Фрайбург",
    "Greuther Furth": "Фюрт",
    "Hamburg": "Гамбург",
    "Heidenheim": "Хайденхайм",
    "Hertha": "Герта",
    "Hoffenheim": "Хоффенхайм",
    "Holstein Kiel": "Киль",
    "Leverkusen": "Байер 04",
    "M'gladbach": "Боруссия Мёнхенгладбах",
    "Mainz": "Майнц 05",
    "RB Leipzig": "Лейпциг",
    "Schalke 04": "Шальке 04",
    "St Pauli": "Санкт-Паули",
    "Stuttgart": "Штутгарт",
    "Union Berlin": "Унион Берлин",
    "Werder Bremen": "Вердер",
    "Wolfsburg": "Вольфсбург",
}

EPL_MAP = {
    "Arsenal": "Арсенал",
    "Aston Villa": "Астон Вилла",
    "Bournemouth": "Борнмут",
    "Brentford": "Брентфорд",
    "Brighton": "Брайтон",
    "Burnley": "Бернли",
    "Chelsea": "Челси",
    "Crystal Palace": "Кристал Пэлас",
    "Everton": "Эвертон",
    "Fulham": "Фулхэм",
    "Ipswich": "Ипсвич",
    "Leeds": "Лидс",
    "Leicester": "Лестер",
    "Liverpool": "Ливерпуль",
    "Luton": "Лутон Таун",
    "Man City": "Манчестер Сити",
    "Man United": "Манчестер Юнайтед",
    "Newcastle": "Ньюкасл",
    "Norwich": "Норвич",
    "Nott'm Forest": "Ноттингем Форест",
    "Sheffield United": "Шеффилд Юнайтед",
    "Southampton": "Саутгемптон",
    "Sunderland": "Сандерленд",
    "Tottenham": "Тоттенхэм",
    "Watford": "Уотфорд",
    "West Ham": "Вест Хэм",
    "Wolves": "Вулверхэмптон",
}

SA_MAP = {
    "Atalanta": "Аталанта",
    "Bologna": "Болонья",
    "Cagliari": "Кальяри",
    "Como": "Комо",
    "Cremonese": "Кремонезе",
    "Empoli": "Эмполи",
    "Fiorentina": "Фиорентина",
    "Frosinone": "Фрозиноне",
    "Genoa": "Дженоа",
    "Inter": "Интер",
    "Juventus": "Ювентус",
    "Lazio": "Лацио",
    "Lecce": "Лечче",
    "Milan": "Милан",
    "Monza": "Монца",
    "Napoli": "Наполи",
    "Parma": "Парма",
    "Pisa": "Пиза",
    "Roma": "Рома",
    "Salernitana": "Салернитана",
    "Sampdoria": "Сампдория",
    "Sassuolo": "Сассуоло",
    "Spezia": "Специя",
    "Torino": "Торино",
    "Udinese": "Удинезе",
    "Venezia": "Венеция",
    "Verona": "Верона",
}

PD_MAP = {
    "Alaves": "Алавес",
    "Almeria": "Альмерия",
    "Ath Bilbao": "Атлетик Бильбао",
    "Ath Madrid": "Атлетико Мадрид",
    "Barcelona": "Барселона",
    "Betis": "Бетис",
    "Cadiz": "Кадис",
    "Celta": "Сельта",
    "Elche": "Эльче",
    "Espanol": "Эспаньол",
    "Getafe": "Хетафе",
    "Girona": "Жирона",
    "Granada": "Гранада",
    "Las Palmas": "Лас-Пальмас",
    "Leganes": "Леганес",
    "Levante": "Леванте",
    "Mallorca": "Мальорка",
    "Osasuna": "Осасуна",
    "Oviedo": "Овьедо",
    "Real Madrid": "Реал Мадрид",
    "Sevilla": "Севилья",
    "Sociedad": "Реал Сосьедад",
    "Valencia": "Валенсия",
    "Valladolid": "Вальядолид",
    "Vallecano": "Райо Вальекано",
    "Villarreal": "Вильярреал",
}

FL1_MAP = {
    "Ajaccio": "Аяччо",
    "Angers": "Анже",
    "Auxerre": "Осер",
    "Bordeaux": "Бордо",
    "Brest": "Брест",
    "Clermont": "Клермон",
    "Le Havre": "Гавр",
    "Lens": "Ланс",
    "Lille": "Лилль",
    "Lorient": "Лорьян",
    "Lyon": "Лион",
    "Marseille": "Марсель",
    "Metz": "Мец",
    "Monaco": "Монако",
    "Montpellier": "Монпелье",
    "Nantes": "Нант",
    "Nice": "Ницца",
    "Paris FC": "Париж",
    "Paris SG": "ПСЖ",
    "Reims": "Реймс",
    "Rennes": "Ренн",
    "St Etienne": "Сент-Этьен",
    "Strasbourg": "Страсбур",
    "Toulouse": "Тулуза",
    "Troyes": "Труа",
}

RPL_MAP = {
    "Akhmat": "Ахмат",
    "Akron": "Акрон Тольятти",
    "Arsenal Tula": "Арсенал Тула",
    "Baltika": "Балтика",
    "CSKA Moscow": "ЦСКА Москва",
    "Dynamo Makhachkala": "Динамо Махачкала",
    "Dynamo Moscow": "Динамо Москва",
    "Dynamo Msc": "Динамо Москва",
    "Enisey": "Енисей",
    "Fakel": "Факел",
    "Khimki": "Химки",
    "Krasnodar": "ФК Краснодар",
    "Krylya Sovetov": "Крылья Советов",
    "Lokomotiv Moscow": "Локомотив Москва",
    "Lokomotiv Msk": "Локомотив Москва",
    "Nizhny Novgorod": "Нижний Новгород",
    "Orenburg": "ФК Оренбург",
    "Rostov": "ФК Ростов",
    "Rodina Moscow": "Родина Москва",
    "Rubin Kazan": "Рубин",
    "Rubin": "Рубин",
    "SKA Khabarovsk": "СКА Хабаровск",
    "Sochi": "ФК Сочи",
    "Spartak Moscow": "Спартак Москва",
    "Spartak Msk": "Спартак Москва",
    "Torpedo Moscow": "Торпедо Москва",
    "Ufa": "ФК Уфа",
    "Ural": "Урал",
    "Zenit": "Зенит",
}

LEAGUE_MAPS = {
    "BL1": BL1_MAP,
    "EPL": EPL_MAP,
    "SA": SA_MAP,
    "PD": PD_MAP,
    "FL1": FL1_MAP,
    "RPL": RPL_MAP,
}

# Cyrillic league strings  short code
LEAGUE_CODES = {
    "Футбол. Англия. Премьер-лига.": "EPL",
    "Футбол. Италия. Серия A.": "SA",
    "Футбол. Испания. Примера Дивизион.": "PD",
    "Футбол. Франция. Лига 1.": "FL1",
    "Футбол. Германия. Бундеслига.": "BL1",
    "Футбол. Россия. Премьер-Лига.": "RPL",
}

# Reverse: English  Cyrillic
LEAGUE_NAMES_CYR = {v: k for k, v in LEAGUE_CODES.items()}


def map_team(eng_name: str, league: str = None) -> str:
    """Map English team name to Russian (betz) name.

    Args:
        eng_name: Team name from backtest_matches (e.g. 'Arsenal')
        league: League code (EPL/SA/PD/FL1/BL1/RPL).
               If None, tries all maps and returns first match.
    """
    if league:
        code = LEAGUE_CODES.get(league, league)
        m = LEAGUE_MAPS.get(code)
        if m and eng_name in m:
            return m[eng_name]
        # Fall back to searching all maps
    for m in LEAGUE_MAPS.values():
        if eng_name in m:
            return m[eng_name]
    return eng_name


def map_team_to_eng(rus_name: str, league: str = None) -> str:
    """Map Russian team name back to English.

    Args:
        rus_name: Team name from backtest_football_stats (e.g. 'Арсенал')
        league: League code or Cyrillic league string.
    """
    if league:
        code = LEAGUE_CODES.get(league, league)
        m = LEAGUE_MAPS.get(code)
        if m:
            reverse = {v: k for k, v in m.items()}
            if rus_name in reverse:
                return reverse[rus_name]
    for m in LEAGUE_MAPS.values():
        reverse = {v: k for k, v in m.items()}
        if rus_name in reverse:
            return reverse[rus_name]
    return rus_name
