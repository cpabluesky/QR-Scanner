-- Public access: no visitor login. Run in the Supabase SQL Editor.
-- Also migrates the previous staff-only setup without resetting admissions.
begin;

create table if not exists public.checkins (
  bar_code text primary key,
  status text not null default 'pending',
  checked_in_at timestamptz,
  constraint valid_bar_code check (bar_code <> '' and bar_code = btrim(bar_code)),
  constraint valid_checkin_state check (
    (status = 'pending' and checked_in_at is null) or
    (status = 'checked_in' and checked_in_at is not null)
  )
);

alter table public.checkins enable row level security;
revoke all on public.checkins from anon, authenticated;
grant usage on schema public to anon, authenticated;
grant select on public.checkins to anon, authenticated;

drop policy if exists "Staff can read checkins" on public.checkins;
drop policy if exists "Public can read checkins" on public.checkins;
create policy "Public can read checkins" on public.checkins
  for select to anon, authenticated using (true);

create or replace function public.check_in(p_bar_code text)
returns jsonb language plpgsql security definer set search_path = ''
as $$
declare
  v_row public.checkins%rowtype;
begin
  update public.checkins
    set status = 'checked_in', checked_in_at = now()
    where bar_code = btrim(p_bar_code) and status = 'pending'
    returning * into v_row;

  if found then
    return jsonb_build_object('success', true, 'found', true,
      'alreadyCheckedIn', false, 'checkInTime', v_row.checked_in_at);
  end if;

  select * into v_row from public.checkins where bar_code = btrim(p_bar_code);
  if not found then
    return jsonb_build_object('success', true, 'found', false);
  end if;
  return jsonb_build_object('success', true, 'found', true,
    'alreadyCheckedIn', true, 'checkInTime', v_row.checked_in_at);
end;
$$;

revoke execute on function public.check_in(text) from public, anon, authenticated;
grant execute on function public.check_in(text) to anon, authenticated;
commit;
