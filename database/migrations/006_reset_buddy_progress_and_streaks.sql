alter table if exists user_stats
  alter column level set default 0,
  alter column streak set default 0;

alter table if exists user_buddies
  alter column level set default 0,
  alter column xp set default 0;

update user_stats
set streak = 0,
    updated_at = now();

update user_buddies
set level = 0,
    xp = 0,
    updated_at = now();
