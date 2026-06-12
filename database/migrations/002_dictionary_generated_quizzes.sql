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

alter table quiz_attempt_answers drop constraint if exists quiz_attempt_answers_question_id_fkey;
alter table quiz_attempt_answers drop constraint if exists quiz_attempt_answers_selected_option_id_fkey;
alter table quiz_attempts drop constraint if exists quiz_attempts_quiz_id_fkey;
alter table quiz_attempts alter column quiz_id drop not null;
