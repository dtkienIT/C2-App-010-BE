create table if not exists user_notifications (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references profiles(id) on delete cascade,
  event_type text not null,
  status text not null default 'stored',
  payload jsonb not null,
  expires_at timestamptz not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint user_notifications_status_check check (status in ('stored'))
);

create index if not exists user_notifications_user_created_idx
  on user_notifications(user_id, created_at desc);

create index if not exists user_notifications_expires_at_idx
  on user_notifications(expires_at);
