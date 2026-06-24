-- Sutura Genomics — demo / contact form backend.
-- Run this in the Supabase dashboard: SQL Editor → New query → paste → Run.
-- Safe to re-run (idempotent).

create table if not exists public.demo_requests (
  id           uuid        primary key default gen_random_uuid(),
  created_at   timestamptz not null    default now(),
  full_name    text        not null,
  email        text        not null,
  company      text        not null,
  role         text,
  company_size text        not null,
  looking_for  text        not null,
  source       text
);

-- Row Level Security: lock the table down, then grant ONLY anonymous inserts.
-- The public site uses the anon key, so it can submit leads but cannot read,
-- edit, or delete them. View submissions from the Supabase dashboard (Table
-- editor) or with the service_role key — never expose that key to the browser.
alter table public.demo_requests enable row level security;

-- Insert-only, no select/update/delete policy, so the public site can submit but
-- never read leads back. NOTE: do NOT request the inserted row back from the
-- client (supabase-js: don't chain .select() after .insert()) — a RETURNING
-- clause needs read access this policy intentionally withholds, which surfaces as
-- a misleading "violates row-level security policy" error.
drop policy if exists "anon can insert demo requests"   on public.demo_requests;
drop policy if exists "public can insert demo requests" on public.demo_requests;
create policy "public can insert demo requests"
  on public.demo_requests
  for insert
  to public
  with check (true);
