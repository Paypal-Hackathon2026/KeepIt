-- KeepIt database schema.
-- Run this file once in the Supabase SQL Editor on an empty project to create everything from scratch.
-- Amounts are in minor units (grosze). RLS is enabled on every table with no policies:
-- only the server talks to the database, using the secret key.

--profiles
create table if not exists profiles (
  id uuid primary key default gen_random_uuid(),
  paypal_user_id text not null unique,
  display_name text not null,
  paypal_email text not null unique,
  created_at timestamptz not null default now()
);

alter table profiles enable row level security;

--challenges
create table if not exists challenges (
  id uuid primary key default gen_random_uuid(),
  creator_id uuid not null references profiles(id),
  title text not null,
  criteria text not null,
  entry_fee_minor integer not null check (entry_fee_minor > 0),
  proof_code text not null,
  status text not null default 'open'
    check (status in ('open', 'active', 'voting', 'closed', 'settling', 'settled', 'cancelled')),
  verification_mode text not null default 'ai'
    check (verification_mode in ('ai', 'vote')),
  join_deadline timestamptz not null,
  proof_deadline timestamptz not null,
  voting_deadline timestamptz not null,
  paypal_batch_id text unique,
  check (proof_deadline > join_deadline),
  constraint challenges_voting_deadline_check check (voting_deadline > proof_deadline)
);

alter table challenges enable row level security;

--participants
create table if not exists participants (
  challenge_id uuid not null references challenges(id),
  user_id uuid not null references profiles(id),
  paid boolean not null default false,
  outcome text not null default 'pending'
    check (outcome in ('pending', 'verified', 'forfeited')),
  joined_at timestamptz not null default now(),
  primary key (challenge_id, user_id)
);

alter table participants enable row level security;

--payments
create table if not exists payments (
  id uuid primary key default gen_random_uuid(),
  challenge_id uuid not null,
  user_id uuid not null,
  amount_minor integer not null check (amount_minor > 0),
  paypal_order_id text not null unique,
  paypal_capture_id text unique,
  status text not null default 'created'
    check (status in ('created', 'captured', 'cancelled')),
  foreign key (challenge_id, user_id) references participants (challenge_id, user_id)
);

-- a participant can have only one payment in progress or completed per challenge
create unique index if not exists one_active_payment_per_participant
  on payments (challenge_id, user_id)
  where status in ('created', 'captured');

alter table payments enable row level security;

--payouts
create table if not exists payouts (
  id uuid primary key default gen_random_uuid(),
  challenge_id uuid not null,
  user_id uuid not null,
  amount_minor integer not null check (amount_minor > 0),
  paypal_item_id text unique,
  status text not null default 'pending'
    check (status in ('pending', 'success', 'failed')),
  unique (challenge_id, user_id),
  foreign key (challenge_id, user_id) references participants (challenge_id, user_id)
);

alter table payouts enable row level security;

--evidence
create table if not exists evidence (
  id uuid primary key default gen_random_uuid(),
  challenge_id uuid not null,
  user_id uuid not null,
  attempt integer not null check (attempt between 1 and 3),
  storage_path text not null,
  status text not null default 'pending'
    check (status in ('pending', 'auto_approved', 'auto_rejected', 'needs_vote', 'approved', 'rejected')),
  created_at timestamptz not null default now(),
  unique (challenge_id, user_id, attempt),
  unique (id, challenge_id),
  foreign key (challenge_id, user_id) references participants (challenge_id, user_id)
);

create index if not exists idx_evidence_challenge_created_at
  on evidence (challenge_id, created_at);

alter table evidence enable row level security;

--verdicts
create table if not exists verdicts (
  id uuid primary key default gen_random_uuid(),
  evidence_id uuid not null references evidence(id),
  model text not null,
  verified boolean not null,
  confidence numeric(3,2) not null check (confidence between 0 and 1),
  code_visible boolean not null,
  reasoning text not null,
  fraud_flags text[] not null default '{}',
  created_at timestamptz not null default now()
);

alter table verdicts enable row level security;

--votes
create table if not exists votes (
  evidence_id uuid not null,
  challenge_id uuid not null,
  voter_id uuid not null,
  approve boolean not null,
  created_at timestamptz not null default now(),
  primary key (evidence_id, voter_id),
  foreign key (evidence_id, challenge_id) references evidence (id, challenge_id),
  foreign key (challenge_id, voter_id) references participants (challenge_id, user_id)
);

alter table votes enable row level security;

--webhook events
create table if not exists webhook_events (
  event_id text primary key,
  event_type text not null,
  payload jsonb not null,
  received_at timestamptz not null default now()
);

alter table webhook_events enable row level security;

--functions
-- creates a challenge and registers the creator as its first participant in one transaction
-- called from Python via supabase.rpc("create_challenge_with_participant", {...})
create or replace function create_challenge_with_participant(
  p_creator_id uuid,
  p_title text,
  p_criteria text,
  p_entry_fee_minor integer,
  p_proof_code text,
  p_join_deadline timestamptz,
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

  insert into challenges (creator_id, title, criteria, entry_fee_minor, proof_code,
                          join_deadline, proof_deadline, voting_deadline, verification_mode)
  values (p_creator_id, p_title, p_criteria, p_entry_fee_minor, p_proof_code,
          p_join_deadline, p_proof_deadline, v_voting_dl, p_verification_mode)
  returning * into new_challenge;

  insert into participants (challenge_id, user_id)
  values (new_challenge.id, p_creator_id);

  return row_to_json(new_challenge);
end;
$$;