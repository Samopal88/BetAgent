-- cleanup_pending_duplicates.sql
-- Keeps the earliest pending bet for each match_id + market + created_by
DELETE FROM bets
WHERE id IN (
    SELECT id FROM (
        SELECT id,
               ROW_NUMBER() OVER (
                   PARTITION BY match_id, market, created_by, result
                   ORDER BY id ASC
               ) AS rn
        FROM bets
        WHERE result = 'pending'
          AND created_by = 'agent_handoff_v7.py'
    )
    WHERE rn > 1
);
