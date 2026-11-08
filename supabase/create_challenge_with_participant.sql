-- Atomic function: create a challenge and register the creator as participant.
-- Called via supabase.rpc("create_challenge_with_participant", {...})
create or replace function create_challenge_with_participant(
    p_creator_id   uuid,
    p_title        text,
    p_criteria     text,
    p_entry_fee_minor integer,
    p_proof_code   text,
    p_join_deadline  timestamptz,
    p_proof_deadline timestamptz,
    p_verification_mode text default 'ai',
    p_voting_deadline timestamptz default null
)
returns json
language plpgsql
as $$
declare
    new_challenge challenges%rowtype;
    v_voting_dl timestamptz;
begin
    v_voting_dl := coalesce(p_voting_deadline, p_proof_deadline + interval '1 day');

    insert into challenges (creator_id, title, criteria, entry_fee_minor, proof_code, join_deadline, proof_deadline, voting_deadline, verification_mode)
    values (p_creator_id, p_title, p_criteria, p_entry_fee_minor, p_proof_code, p_join_deadline, p_proof_deadline, v_voting_dl, p_verification_mode)
    returning * into new_challenge;

    insert into participants (challenge_id, user_id)
    values (new_challenge.id, p_creator_id);

    return row_to_json(new_challenge);
end;
$$;

