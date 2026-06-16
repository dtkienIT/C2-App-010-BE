create table if not exists user_unlocked_companion_models (
  user_id uuid not null references profiles(id) on delete cascade,
  model_id text not null references companion_models(id) on delete cascade,
  unlocked_at timestamptz not null default now(),
  primary key (user_id, model_id)
);

create table if not exists user_unlocked_room_backgrounds (
  user_id uuid not null references profiles(id) on delete cascade,
  background_id text not null references room_backgrounds(id) on delete cascade,
  unlocked_at timestamptz not null default now(),
  primary key (user_id, background_id)
);

update user_stats
set coins = 0,
    updated_at = now();

update companion_models
set price = case when source = 'shop' then 1 else price end;

update room_backgrounds
set price = 1;

update user_companion_settings
set equipped_model_id = null,
    buddy_3d_enabled = false,
    updated_at = now();
