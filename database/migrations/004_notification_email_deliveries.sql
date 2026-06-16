create table if not exists notification_email_deliveries (
  id uuid primary key default gen_random_uuid(),
  outbox_id uuid not null references notification_outbox(id) on delete cascade,
  user_id uuid not null references profiles(id) on delete cascade,
  email text not null,
  status text not null,
  attempts integer not null default 0,
  error_code text,
  error_message text,
  sent_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint notification_email_deliveries_status_check check (
    status in ('pending', 'sent', 'failed', 'permanent_failure', 'transient_failure', 'skipped')
  ),
  unique (outbox_id, user_id)
);

create index if not exists notification_email_deliveries_outbox_idx on notification_email_deliveries(outbox_id);
create index if not exists notification_email_deliveries_user_idx on notification_email_deliveries(user_id);
