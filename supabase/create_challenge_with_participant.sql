-- Atomic function: create a challenge and register the creator as participant.
-- Called via supabase.rpc("create_challenge_with_participant", {...})
create or replace function create_challenge_with_participant(
    p_creator_id   uuid,
    p_title        text,
    p_criteria     text,
    p_entry_fee_minor integer,
    p_proof_code   text,
    p_join_deadline  timestamptz,
    p_proof_deadline timestamptz
)
returns json
language plpgsql
as $$
declare
    new_challenge challenges%rowtype;
begin
    insert into challenges (creator_id, title, criteria, entry_fee_minor, proof_code, join_deadline, proof_deadline)
    values (p_creator_id, p_title, p_criteria, p_entry_fee_minor, p_proof_code, p_join_deadline, p_proof_deadline)
    returning * into new_challenge;

    insert into participants (challenge_id, user_id)
    values (new_challenge.id, p_creator_id);

    return row_to_json(new_challenge);
end;
$$;

