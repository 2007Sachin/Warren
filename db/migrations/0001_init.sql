-- Phase 0 operational schema. Idempotent. Apply on the direct (unpooled) URL.

create table if not exists schema_migrations (
  name text primary key,
  applied_at timestamptz not null default now()
);

create table if not exists orders_intent (
  id            uuid primary key default gen_random_uuid(),
  client_tag    text unique not null,
  created_at    timestamptz not null default now(),
  symbol_token  text not null,
  exchange      text not null,
  side          text not null check (side in ('BUY','SELL')),
  order_type    text not null default 'LIMIT',
  qty           integer not null,
  limit_price   numeric not null,
  status        text not null default 'PENDING'
);

create table if not exists orders (
  id            bigint generated always as identity primary key,
  intent_tag    text references orders_intent(client_tag),
  broker_order_id text,
  placed_at     timestamptz,
  status        text,
  avg_price     numeric,
  filled_qty    integer,
  raw           jsonb
);

create table if not exists positions (
  symbol_token  text not null,
  exchange      text not null,
  qty           integer not null default 0,
  avg_price     numeric,
  updated_at    timestamptz not null default now(),
  primary key (symbol_token, exchange)
);

create table if not exists daily_pnl (
  date          date primary key,
  realized      numeric not null default 0,
  unrealized    numeric not null default 0,
  notes         text
);

create table if not exists kill_switch_state (
  id            integer primary key default 1 check (id = 1),
  halted        boolean not null default false,
  reason        text,
  tripped_at    timestamptz,
  reset_by      text
);
insert into kill_switch_state (id) values (1) on conflict do nothing;

create table if not exists audit_log (
  id            bigint generated always as identity primary key,
  at            timestamptz not null default now(),
  actor         text not null,
  action        text not null,
  payload       jsonb
);

do $$
begin
  if exists (select 1 from pg_roles where rolname = 'authenticated') then
    execute 'revoke delete, update on audit_log from authenticated';
  end if;
  if exists (select 1 from pg_roles where rolname = 'anon') then
    execute 'revoke delete, update on audit_log from anon';
  end if;
end $$;
revoke delete, update on audit_log from public;
