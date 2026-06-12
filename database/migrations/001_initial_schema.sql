create table if not exists profiles (
  id uuid primary key,
  email text unique not null,
  display_name text not null,
  avatar_url text default '',
  role text not null default 'student',
  password_hash text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists user_stats (
  user_id uuid primary key references profiles(id) on delete cascade,
  level integer not null default 1,
  xp integer not null default 0,
  coins integer not null default 0,
  streak integer not null default 0,
  total_quizzes integer not null default 0,
  total_correct_answers integer not null default 0,
  total_study_minutes integer not null default 0,
  last_active_at timestamptz,
  updated_at timestamptz not null default now()
);

create table if not exists buddies (
  id text primary key,
  name text not null,
  role text default '',
  type text default '',
  emoji text default '',
  gradient text default '',
  description text not null,
  personality text default '',
  avatar_url text default '',
  tags jsonb not null default '[]',
  skills jsonb not null default '[]',
  accent text default 'cyan',
  rarity text not null default 'common',
  default_mood text not null default 'idle',
  is_active boolean not null default true,
  created_at timestamptz not null default now()
);

create table if not exists user_buddies (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references profiles(id) on delete cascade,
  buddy_id text not null references buddies(id),
  is_selected boolean not null default false,
  level integer not null default 1,
  xp integer not null default 0,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique(user_id, buddy_id)
);

create table if not exists companion_models (
  id text primary key,
  name text not null,
  description text not null,
  model_url text not null,
  thumbnail_url text default '',
  rarity text not null default 'common',
  price integer not null default 0,
  tags jsonb not null default '[]',
  actions jsonb not null default '[]',
  accent text default 'cyan',
  source text default 'shop',
  is_active boolean not null default true,
  created_at timestamptz not null default now()
);

create table if not exists room_backgrounds (
  id text primary key,
  name text not null,
  description text default '',
  image_url text not null,
  thumbnail_url text default '',
  price integer not null default 0,
  accent text default 'cyan',
  is_active boolean not null default true,
  created_at timestamptz not null default now()
);

create table if not exists user_companion_settings (
  user_id uuid primary key references profiles(id) on delete cascade,
  active_buddy_id text references buddies(id),
  equipped_model_id text references companion_models(id),
  room_background_id text references room_backgrounds(id),
  buddy_3d_enabled boolean not null default false,
  updated_at timestamptz not null default now()
);

create table if not exists missions (
  id text primary key,
  title text not null,
  description text not null,
  type text not null,
  target_type text not null,
  target_value integer not null,
  reward_xp integer not null default 0,
  reward_coins integer not null default 0,
  is_active boolean not null default true,
  created_at timestamptz not null default now()
);

create table if not exists user_missions (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references profiles(id) on delete cascade,
  mission_id text not null references missions(id),
  progress integer not null default 0,
  is_completed boolean not null default false,
  is_claimed boolean not null default false,
  completed_at timestamptz,
  claimed_at timestamptz,
  date_scope text not null default 'global',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique(user_id, mission_id, date_scope)
);

create table if not exists quizzes (
  id text primary key,
  title text not null,
  description text default '',
  level integer not null default 1,
  topic text not null,
  reward_xp integer not null default 0,
  reward_coins integer not null default 0,
  is_active boolean not null default true,
  created_at timestamptz not null default now()
);

create table if not exists dictionary_words (
  id uuid primary key default gen_random_uuid(),
  source_id integer unique,
  word text not null,
  type text default '',
  meaning text not null,
  example text default '',
  pronunciation text default '',
  difficulty_level text not null default 'beginner',
  is_active boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique(word, meaning)
);

create index if not exists dictionary_words_word_idx on dictionary_words(word);
create index if not exists dictionary_words_type_idx on dictionary_words(type);
create index if not exists dictionary_words_difficulty_level_idx on dictionary_words(difficulty_level);
create index if not exists dictionary_words_is_active_idx on dictionary_words(is_active);

create table if not exists quiz_sessions (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references profiles(id) on delete cascade,
  title text not null,
  difficulty text not null default 'mixed',
  question_types text[] not null default '{}',
  total_questions integer not null,
  created_at timestamptz not null default now(),
  expires_at timestamptz
);

create table if not exists quiz_session_questions (
  id uuid primary key default gen_random_uuid(),
  session_id uuid not null references quiz_sessions(id) on delete cascade,
  dictionary_word_id uuid not null references dictionary_words(id),
  question_type text not null,
  question_text text not null,
  correct_answer_text text not null,
  explanation text default '',
  order_index integer not null,
  created_at timestamptz not null default now()
);

create table if not exists quiz_session_options (
  id uuid primary key default gen_random_uuid(),
  session_question_id uuid not null references quiz_session_questions(id) on delete cascade,
  option_text text not null,
  is_correct boolean not null default false,
  order_index integer not null,
  created_at timestamptz not null default now()
);

create table if not exists quiz_questions (
  id text primary key,
  quiz_id text not null references quizzes(id) on delete cascade,
  question_text text not null,
  explanation text default '',
  order_index integer not null,
  created_at timestamptz not null default now()
);

create table if not exists quiz_options (
  id text primary key,
  question_id text not null references quiz_questions(id) on delete cascade,
  option_text text not null,
  is_correct boolean not null default false,
  order_index integer not null,
  created_at timestamptz not null default now()
);

create table if not exists quiz_attempts (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references profiles(id) on delete cascade,
  quiz_id text,
  score integer not null,
  total_questions integer not null,
  correct_answers integer not null,
  earned_xp integer not null,
  earned_coins integer not null,
  percentage integer not null,
  created_at timestamptz not null default now()
);

create table if not exists quiz_attempt_answers (
  id uuid primary key default gen_random_uuid(),
  attempt_id uuid not null references quiz_attempts(id) on delete cascade,
  question_id text not null,
  selected_option_id text not null,
  is_correct boolean not null,
  created_at timestamptz not null default now()
);

create table if not exists achievements (
  id text primary key,
  title text not null,
  description text not null,
  icon text default '',
  condition_type text not null,
  condition_value integer not null,
  reward_xp integer not null default 0,
  reward_coins integer not null default 0,
  created_at timestamptz not null default now()
);

create table if not exists user_achievements (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references profiles(id) on delete cascade,
  achievement_id text not null references achievements(id),
  unlocked_at timestamptz not null default now(),
  is_claimed boolean not null default false,
  claimed_at timestamptz,
  unique(user_id, achievement_id)
);
