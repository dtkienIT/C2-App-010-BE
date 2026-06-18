alter table user_stats
  add column if not exists streak_count integer not null default 0,
  add column if not exists last_streak_date date,
  add column if not exists last_login_reward_date date;

update user_stats
set streak_count = greatest(0, coalesce(streak_count, streak, 0)),
    last_streak_date = coalesce(
      last_streak_date,
      case
        when coalesce(streak, 0) > 0 and last_active_at is not null then (last_active_at at time zone 'UTC')::date
        else null
      end
    ),
    last_login_reward_date = coalesce(
      last_login_reward_date,
      case
        when coalesce(streak, 0) > 0 and last_active_at is not null then (last_active_at at time zone 'UTC')::date
        else null
      end
    ),
    streak = greatest(0, coalesce(streak_count, streak, 0));
