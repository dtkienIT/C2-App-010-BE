create table if not exists user_buddy_states (
  user_id uuid not null references profiles(id) on delete cascade,
  buddy_id text not null references buddies(id) on delete cascade,
  joy integer not null default 84,
  energy integer not null default 76,
  focus integer not null default 68,
  mood text not null default 'focus',
  updated_at timestamptz not null default now(),
  primary key (user_id, buddy_id)
);

create index if not exists user_buddy_states_user_id_idx on user_buddy_states(user_id);
