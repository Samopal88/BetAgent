Как использовать debug_payload_match_v2.py

По id:
  python debug_payload_match_v2.py --match-id 290

По названию матча:
  python debug_payload_match_v2.py --sport hockey --home "Салават Юлаев" --away "Динамо Москва"

Что исправлено:
- поиск по названиям теперь сначала выбирает матч с коэффициентами
- то есть для одинаковых пар команд приоритет у Fonbet/upcoming/odds != NULL
- TheSports берётся только как fallback
