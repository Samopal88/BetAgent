Как использовать debug_payload_match.py

Вариант 1:
  python debug_payload_match.py --match-id 290

Вариант 2:
  python debug_payload_match.py --sport hockey --home "Салават Юлаев" --away "Динамо Москва"

Что покажет:
1) матч и коэффициенты
2) payload, который уходит в модель
3) raw content ответа модели
4) parsed JSON
5) результат validator

Это нужно, чтобы понять:
- действительно ли payload наполнен фактами
- не врёт ли модель в трактовке формы/мотивации
- где именно рождается PASS / BET
