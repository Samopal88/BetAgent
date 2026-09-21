enricher_football_rpl.py

Что делает:
- тянет TheSports results page по РПЛ
- парсит standings
- парсит results / fixtures
- пишет standings и results_raw
- синхронизирует match_facts на upcoming Fonbet матчи РПЛ

Что считает:
- форма последних 5
- средние голы за/против
- H2H
- позиции, очки, мотивацию

Запуск:
  python enricher_football_rpl.py

Потом:
  python agent_handoff_v7.py --dry-run --sport football --limit 10
