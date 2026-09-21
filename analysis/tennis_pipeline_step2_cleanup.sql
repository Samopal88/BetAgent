ALTER TABLE tennis_signals ADD COLUMN source_match_id TEXT;
ALTER TABLE tennis_signals ADD COLUMN live_identity TEXT;
ALTER TABLE tennis_signals ADD COLUMN bet_id INTEGER;
ALTER TABLE tennis_signals ADD COLUMN signal_key TEXT;

UPDATE tennis_signals
SET live_identity = CASE
    WHEN TRIM(COALESCE(source_match_id, '')) <> '' THEN
        'tennis_live:' || TRIM(source_match_id) || ':' || market
    ELSE
        'tennis_live_fallback:' ||
        lower(replace(replace(trim(player1), '.', ''), 'Ё', 'Е')) || ':' ||
        lower(replace(replace(trim(player2), '.', ''), 'Ё', 'Е')) || ':' ||
        substr(match_date, 1, 10) || ':' || market
END
WHERE live_identity IS NULL OR TRIM(live_identity) = '';

UPDATE tennis_signals
SET signal_key = live_identity
WHERE signal_key IS NULL OR TRIM(signal_key) = '';

WITH
signal_ranked AS (
    SELECT
        id AS signal_id,
        substr(match_date, 1, 10) AS match_date_key,
        market,
        lower(replace(replace(trim(player1), '.', ''), 'Ё', 'Е')) AS p1n,
        lower(replace(replace(trim(player2), '.', ''), 'Ё', 'Е')) AS p2n,
        ROW_NUMBER() OVER (
            PARTITION BY substr(match_date, 1, 10), market,
                         lower(replace(replace(trim(player1), '.', ''), 'Ё', 'Е')),
                         lower(replace(replace(trim(player2), '.', ''), 'Ё', 'Е'))
            ORDER BY datetime(created_at), id
        ) AS rn
    FROM tennis_signals
),
bet_ranked AS (
    SELECT
        b.id AS bet_id,
        substr(m.match_date, 1, 10) AS match_date_key,
        b.market,
        lower(replace(replace(trim(m.home_team), '.', ''), 'Ё', 'Е')) AS p1n,
        lower(replace(replace(trim(m.away_team), '.', ''), 'Ё', 'Е')) AS p2n,
        ROW_NUMBER() OVER (
            PARTITION BY substr(m.match_date, 1, 10), b.market,
                         lower(replace(replace(trim(m.home_team), '.', ''), 'Ё', 'Е')),
                         lower(replace(replace(trim(m.away_team), '.', ''), 'Ё', 'Е'))
            ORDER BY datetime(b.created_at), b.id
        ) AS rn
    FROM bets b
    JOIN matches m ON m.id = b.match_id
    WHERE m.sport = 'tennis'
),
paired AS (
    SELECT sr.signal_id, br.bet_id
    FROM signal_ranked sr
    JOIN bet_ranked br
      ON br.match_date_key = sr.match_date_key
     AND br.market = sr.market
     AND br.p1n = sr.p1n
     AND br.p2n = sr.p2n
     AND br.rn = sr.rn
)
UPDATE tennis_signals
SET bet_id = (
    SELECT paired.bet_id
    FROM paired
    WHERE paired.signal_id = tennis_signals.id
)
WHERE id IN (SELECT signal_id FROM paired);

UPDATE tennis_signals
SET status = CASE
        WHEN COALESCE(NULLIF(TRIM(result), ''), 'pending') = 'pending' THEN 'pending'
        ELSE result
    END
WHERE COALESCE(status, 'pending') = 'pending'
  AND COALESCE(NULLIF(TRIM(result), ''), 'pending') != 'pending';

UPDATE tennis_signals
SET status = (
        SELECT CASE WHEN COALESCE(b.result, 'pending') = 'pending' THEN 'pending' ELSE b.result END
        FROM bets b
        WHERE b.id = tennis_signals.bet_id
    ),
    result = (
        SELECT b.result FROM bets b WHERE b.id = tennis_signals.bet_id
    ),
    profit = (
        SELECT b.profit FROM bets b WHERE b.id = tennis_signals.bet_id
    ),
    settled_at = (
        SELECT b.settled_at FROM bets b WHERE b.id = tennis_signals.bet_id
    )
WHERE bet_id IS NOT NULL;

WITH duplicate_groups AS (
    SELECT
        substr(match_date, 1, 10) AS match_date_key,
        market,
        lower(replace(replace(trim(player1), '.', ''), 'Ё', 'Е')) AS p1n,
        lower(replace(replace(trim(player2), '.', ''), 'Ё', 'Е')) AS p2n
    FROM tennis_signals
    GROUP BY 1,2,3,4
    HAVING COUNT(*) > 1
)
UPDATE tennis_signals
SET status = 'archived_duplicate'
WHERE bet_id IS NULL
  AND (substr(match_date, 1, 10), market,
       lower(replace(replace(trim(player1), '.', ''), 'Ё', 'Е')),
       lower(replace(replace(trim(player2), '.', ''), 'Ё', 'Е')))
      IN (SELECT match_date_key, market, p1n, p2n FROM duplicate_groups);

CREATE UNIQUE INDEX IF NOT EXISTS idx_tennis_signals_signal_key_pending
ON tennis_signals(signal_key)
WHERE signal_key IS NOT NULL
  AND TRIM(signal_key) <> ''
  AND COALESCE(NULLIF(TRIM(result), ''), 'pending') = 'pending'
  AND COALESCE(status, 'pending') = 'pending';
