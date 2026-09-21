# Как использовать agent_handoff.py

## 1. Положи файлы рядом с parser.py
- parser.py
- agent_handoff.py
- validator.py
- AGENT_RULES.md

## 2. Установи зависимости
```bash
pip install requests
```

## 3. Задай ENV для LLM
OpenAI-compatible endpoint:
```bash
set LLM_API_URL=https://api.openai.com/v1/chat/completions
set LLM_API_KEY=<REDACTED>
set LLM_MODEL=gpt-4o-mini
```

Linux/macOS:
```bash
export LLM_API_URL=https://api.openai.com/v1/chat/completions
export LLM_API_KEY=<REDACTED>
export LLM_MODEL=gpt-4o-mini
```

## 4. Сначала обнови базу матчей
```bash
python parser.py
```

## 5. Сухой прогон
```bash
python agent_handoff.py --dry-run --limit 10
```

## 6. Запись рекомендаций в bets
```bash
python agent_handoff.py --limit 10
```

## 7. По одному спорту
```bash
python agent_handoff.py --sport hockey --limit 10
python agent_handoff.py --sport football --limit 10
```

## Что делает validator.py
- проверяет EV >= 0.03
- проверяет Kelly > 0
- проверяет коэффициентную зону
- режет размер при 3 проигрышах подряд за 72ч в этом виде спорта
- не даёт Strong без данных по составам
- не даёт ставку без объяснения ошибки рынка и подтверждённых фактов
