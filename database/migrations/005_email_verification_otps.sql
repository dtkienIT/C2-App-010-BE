alter table profiles
  add column if not exists is_email_verified boolean not null default false,
  add column if not exists email_verified_at timestamptz,
  add column if not exists status text not null default 'pending_verification';

update profiles
set is_email_verified = true,
    email_verified_at = coalesce(email_verified_at, now()),
    status = case when status = 'pending_verification' then 'active' else status end
where email_verified_at is null
  and is_email_verified = false;

create table if not exists email_verification_otps (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references profiles(id) on delete cascade,
  verification_session_id uuid not null unique,
  otp_hash text not null,
  expires_at timestamptz not null,
  attempt_count integer not null default 0,
  used_at timestamptz,
  locked_at timestamptz,
  last_sent_at timestamptz not null default now(),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists email_verification_otps_user_id_idx on email_verification_otps(user_id);
create index if not exists email_verification_otps_session_idx on email_verification_otps(verification_session_id);
create index if not exists email_verification_otps_expires_at_idx on email_verification_otps(expires_at);
