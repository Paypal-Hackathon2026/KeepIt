-- profiles
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
    check (status in ('open', 'active', 'settling', 'settled', 'cancelled')),
  join_deadline timestamptz not null,
  proof_deadline timestamptz not null,
  check (proof_deadline > join_deadline)
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

--payouts
create table if not exists payouts (
  id uuid primary key default gen_random_uuid(),
  challenge_id uuid not null,
  user_id uuid not null,
  amount_minor integer not null check (amount_minor > 0),
  paypal_item_id text unique,
  status text not null default 'pending'
    check (status in ('pending', 'success', 'failed')),
  foreign key (challenge_id, user_id) references participants (challenge_id, user_id),
  unique (challenge_id, user_id)
);

alter table payouts enable row level security;

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

alter table payments enable row level security;

--evidence
create table if not exists evidence (
  id uuid primary key default gen_random_uuid(),
  challenge_id uuid not null,
  user_id uuid not null,
  attempt integer not null check (attempt between 1 and 3),
  storage_path text not null,
  status text not null default 'pending'
    check (status in ('pending', 'auto_approved', 'needs_vote', 'approved', 'rejected')),
  foreign key (challenge_id, user_id) references participants (challenge_id, user_id),
  unique (challenge_id, user_id, attempt),
  unique (id, challenge_id)
);

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