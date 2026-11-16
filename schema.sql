-- TTOPULO: run ONCE in Supabase SQL Editor.
-- Only authenticated users can interact with data; each row belongs to its owner.
create extension if not exists pgcrypto;
create table if not exists public.quiz_books (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null references auth.users(id) on delete cascade,
  title text not null,
  filename text not null default '',
  source_hash text not null,
  created_at timestamptz not null default now(),
  unique(owner_id, source_hash),
  unique(id, owner_id)
);
create table if not exists public.quiz_questions (
  id uuid primary key default gen_random_uuid(),
  book_id uuid not null,
  owner_id uuid not null,
  section text not null default '미분류',
  number integer not null,
  page integer not null default 1,
  prompt text not null,
  options jsonb not null default '[]'::jsonb,
  answer_text text not null default '',
  answer_indices jsonb not null default '[]'::jsonb,
  explanation text not null default '',
  notes text not null default '',
  needs_review boolean not null default false,
  foreign key(book_id, owner_id) references public.quiz_books(id, owner_id) on delete cascade,
  unique(id, book_id, owner_id)
);
create table if not exists public.quiz_progress (
  owner_id uuid not null,
  book_id uuid not null,
  question_id uuid not null,
  learned boolean not null default false,
  submitted_answer text,
  is_correct boolean,
  updated_at timestamptz not null default now(),
  primary key(owner_id,question_id),
  foreign key(question_id,book_id,owner_id)
    references public.quiz_questions(id,book_id,owner_id) on delete cascade
);

alter table public.quiz_books enable row level security;
alter table public.quiz_questions enable row level security;
alter table public.quiz_progress enable row level security;

-- Explicit privileges + separate RLS policies for each operation.
revoke all on public.quiz_books, public.quiz_questions, public.quiz_progress from anon;
revoke all on public.quiz_books, public.quiz_questions, public.quiz_progress from authenticated;
grant select,insert,update,delete on public.quiz_books,public.quiz_questions,public.quiz_progress to authenticated;

do $$
declare t text;
begin
  foreach t in array array['quiz_books','quiz_questions','quiz_progress'] loop
    execute format('drop policy if exists %I on public.%I',t||'_select',t);
    execute format('drop policy if exists %I on public.%I',t||'_insert',t);
    execute format('drop policy if exists %I on public.%I',t||'_update',t);
    execute format('drop policy if exists %I on public.%I',t||'_delete',t);
    execute format('create policy %I on public.%I for select to authenticated using ((select auth.uid())=owner_id)', t||'_select',t);
    execute format('create policy %I on public.%I for insert to authenticated with check ((select auth.uid())=owner_id)', t||'_insert',t);
    execute format('create policy %I on public.%I for update to authenticated using ((select auth.uid())=owner_id) with check ((select auth.uid())=owner_id)', t||'_update',t);
    execute format('create policy %I on public.%I for delete to authenticated using ((select auth.uid())=owner_id)', t||'_delete',t);
  end loop;
end $$;
