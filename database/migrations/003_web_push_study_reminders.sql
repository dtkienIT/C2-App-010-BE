create table if not exists web_push_subscriptions (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references profiles(id) on delete cascade,
  installation_id text not null,
  endpoint text not null,
  p256dh_key text not null,
  auth_key text not null,
  content_encoding text,
  user_agent text,
  platform text not null default 'web',
  is_active boolean not null default true,
  last_seen_at timestamptz not null default now(),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  revoked_at timestamptz,
  constraint web_push_subscriptions_installation_id_check check (char_length(installation_id) between 8 and 128),
  constraint web_push_subscriptions_endpoint_check check (char_length(endpoint) between 16 and 4096),
  constraint web_push_subscriptions_p256dh_check check (char_length(p256dh_key) between 16 and 512),
  constraint web_push_subscriptions_auth_check check (char_length(auth_key) between 8 and 256),
  unique (endpoint),
  unique (user_id, installation_id)
);

create index if not exists web_push_subscriptions_user_active_idx on web_push_subscriptions(user_id, is_active);
create index if not exists web_push_subscriptions_last_seen_at_idx on web_push_subscriptions(last_seen_at);

create table if not exists study_reminders (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references profiles(id) on delete cascade,
  reminder_time time not null,
  days_of_week smallint[] not null,
  timezone text not null,
  is_enabled boolean not null default true,
  next_run_at timestamptz not null,
  last_sent_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint study_reminders_days_not_empty check (cardinality(days_of_week) > 0),
  constraint study_reminders_days_valid check (days_of_week <@ array[1,2,3,4,5,6,7]::smallint[])
);

create index if not exists study_reminders_enabled_next_run_idx on study_reminders(is_enabled, next_run_at);
create index if not exists study_reminders_user_idx on study_reminders(user_id);

create table if not exists notification_outbox (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references profiles(id) on delete cascade,
  reminder_id uuid references study_reminders(id) on delete set null,
  event_type text not null,
  scheduled_at timestamptz not null,
  status text not null,
  attempts integer not null default 0,
  next_attempt_at timestamptz,
  locked_at timestamptz,
  worker_id text,
  payload jsonb not null,
  dedupe_key text not null unique,
  last_error_code text,
  last_error_message text,
  processed_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint notification_outbox_status_check check (
    status in ('pending', 'processing', 'sent', 'partial', 'failed', 'skipped', 'cancelled')
  ),
  constraint notification_outbox_event_type_check check (event_type in ('DAILY_STUDY_REMINDER')),
  constraint notification_outbox_dedupe_key_check check (char_length(dedupe_key) between 8 and 256)
);

create index if not exists notification_outbox_due_idx
  on notification_outbox(status, scheduled_at, next_attempt_at)
  where status = 'pending';
create index if not exists notification_outbox_user_idx on notification_outbox(user_id);
create index if not exists notification_outbox_reminder_idx on notification_outbox(reminder_id);

create table if not exists notification_deliveries (
  id uuid primary key default gen_random_uuid(),
  outbox_id uuid not null references notification_outbox(id) on delete cascade,
  subscription_id uuid not null references web_push_subscriptions(id) on delete cascade,
  status text not null,
  attempts integer not null default 0,
  error_code text,
  error_message text,
  sent_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint notification_deliveries_status_check check (
    status in ('pending', 'sent', 'failed', 'permanent_failure', 'transient_failure', 'skipped')
  ),
  unique (outbox_id, subscription_id)
);

create index if not exists notification_deliveries_outbox_idx on notification_deliveries(outbox_id);
create index if not exists notification_deliveries_subscription_idx on notification_deliveries(subscription_id);
