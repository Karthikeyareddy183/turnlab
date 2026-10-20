-- Apply to your own Supabase project. The local backend is the sole data client.
create table if not exists public.turnlab_runs (
  workspace text not null check (length(workspace) between 1 and 100),
  id uuid not null,
  mode text not null,
  status text not null,
  created_at timestamptz not null,
  source_updated_at timestamptz not null,
  fingerprint text not null,
  metadata jsonb not null default '{}'::jsonb,
  incidents jsonb not null default '[]'::jsonb,
  primary key (workspace, id)
);
create index if not exists turnlab_runs_recent on public.turnlab_runs (workspace, source_updated_at desc);
alter table public.turnlab_runs enable row level security;
revoke all on public.turnlab_runs from anon, authenticated;
grant select, insert, update on public.turnlab_runs to service_role;

-- Prevent an older backend snapshot from replacing newer metadata.
create or replace function public.turnlab_keep_newest_snapshot()
returns trigger language plpgsql set search_path = '' as $$
begin
  if new.source_updated_at < old.source_updated_at then
    return null;
  end if;
  return new;
end;
$$;
drop trigger if exists turnlab_keep_newest_snapshot on public.turnlab_runs;
create trigger turnlab_keep_newest_snapshot before update on public.turnlab_runs
for each row execute function public.turnlab_keep_newest_snapshot();
