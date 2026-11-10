
ALTER TABLE evidence ADD COLUMN IF NOT EXISTS created_at timestamptz NOT NULL DEFAULT now();

UPDATE evidence e
SET created_at = v.created_at
FROM verdicts v
WHERE v.evidence_id = e.id;

UPDATE evidence e
SET created_at = sub.earliest_vote
FROM (
  SELECT evidence_id, MIN(created_at) AS earliest_vote
  FROM votes
  GROUP BY evidence_id
) sub
WHERE sub.evidence_id = e.id
  AND sub.earliest_vote < e.created_at;

CREATE INDEX IF NOT EXISTS idx_evidence_challenge_created_at ON evidence (challenge_id, created_at);
