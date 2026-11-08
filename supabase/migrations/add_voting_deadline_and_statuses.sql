-- Migration: Add voting_deadline and new challenge statuses (open, active, voting, closed, settling, settled, cancelled)

-- 1. Add voting_deadline column if it doesn't exist
ALTER TABLE challenges ADD COLUMN IF NOT EXISTS voting_deadline timestamptz;

-- 2. Populate voting_deadline for existing records if null
UPDATE challenges SET voting_deadline = proof_deadline + interval '1 day' WHERE voting_deadline IS NULL;

-- 3. Set not null
ALTER TABLE challenges ALTER COLUMN voting_deadline SET NOT NULL;

-- 4. Update check constraint on status
ALTER TABLE challenges DROP CONSTRAINT IF EXISTS challenges_status_check;
ALTER TABLE challenges ADD CONSTRAINT challenges_status_check CHECK (status IN ('open', 'active', 'voting', 'closed', 'settling', 'settled', 'cancelled'));

-- 5. Add check constraint on voting_deadline > proof_deadline
ALTER TABLE challenges DROP CONSTRAINT IF EXISTS challenges_voting_deadline_check;
ALTER TABLE challenges ADD CONSTRAINT challenges_voting_deadline_check CHECK (voting_deadline > proof_deadline);

-- 6. Update function create_challenge_with_participant
DROP FUNCTION IF EXISTS create_challenge_with_participant(uuid, text, text, integer, text, timestamptz, timestamptz, text);
DROP FUNCTION IF EXISTS create_challenge_with_participant(uuid, text, text, integer, text, timestamptz, timestamptz, text, timestamptz);

CREATE OR REPLACE FUNCTION create_challenge_with_participant(
    p_creator_id   uuid,
    p_title        text,
    p_criteria     text,
    p_entry_fee_minor integer,
    p_proof_code   text,
    p_join_deadline  timestamptz,
    p_proof_deadline timestamptz,
    p_verification_mode text DEFAULT 'ai',
    p_voting_deadline timestamptz DEFAULT null
)
RETURNS json
LANGUAGE plpgsql
AS $$
DECLARE
    new_challenge challenges%rowtype;
    v_voting_dl timestamptz;
BEGIN
    v_voting_dl := coalesce(p_voting_deadline, p_proof_deadline + interval '1 day');

    INSERT INTO challenges (creator_id, title, criteria, entry_fee_minor, proof_code, join_deadline, proof_deadline, voting_deadline, verification_mode)
    VALUES (p_creator_id, p_title, p_criteria, p_entry_fee_minor, p_proof_code, p_join_deadline, p_proof_deadline, v_voting_dl, p_verification_mode)
    RETURNING * INTO new_challenge;

    INSERT INTO participants (challenge_id, user_id)
    VALUES (new_challenge.id, p_creator_id);

    RETURN row_to_json(new_challenge);
END;
$$;
