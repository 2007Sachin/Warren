-- Phase 3 paper-trading schema. Run in Supabase SQL editor or via supabase CLI.

create table if not exists paper_orders (
  id              uuid primary key default gen_random_uuid(),
  client_tag      text unique not null,
  created_at      timestamptz not null default now(),
  symbol          text not null,
  side            text not null check (side in ('BUY','SELL')),
  qty             integer not null,
  limit_price     numeric not null,
  status          text not null default 'PENDING',
  signal_date     date not null,
  fill_date       date,
  fill_price      numeric,
  costs_breakdown jsonb
);

create table if not exists paper_positions (
  symbol          text not null primary key,
  qty             integer not null default 0,
  avg_price       numeric,
  stop_price      numeric,
  opened_at       date,
  client_tag      text
);

create table if not exists paper_daily_pnl (
  date            date primary key,
  realized        numeric not null default 0,
  unrealized      numeric not null default 0,
  equity          numeric not null,
  drawdown        numeric not null default 0
);

create table if not exists advisor_votes (
  id              bigint generated always as identity primary key,
  ts              timestamptz not null default now(),
  advisor         text not null,
  vote_type       text not null,
  payload         jsonb,
  acted_on        boolean not null default false
);
revoke delete, update on advisor_votes from authenticated, anon;
