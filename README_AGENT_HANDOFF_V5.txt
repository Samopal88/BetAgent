agent_handoff_v5.py

Что изменено:
- LLM больше не считает:
  - EV
  - Kelly
  - probability рынка
  - stake_pct
- Всё это считает Python-код

LLM теперь возвращает только:
- рынок
- нашу вероятность
- market_error
- confirmed_facts
- unconfirmed
- confidence / signal_type / decision

Запуск:
  python agent_handoff_v5.py --dry-run --sport hockey --limit 5
