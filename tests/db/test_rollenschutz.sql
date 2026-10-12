-- Datenbank-Tests für den Rollen- und Gebietsschutz.
-- Läuft gegen eine leere Test-Datenbank, nie gegen Supabase. Start: tests/db/run.sh
\set ON_ERROR_STOP on
set client_min_messages = warning;

do $$ begin
  if not exists (select 1 from pg_roles where rolname = 'anon') then create role anon nologin; end if;
  if not exists (select 1 from pg_roles where rolname = 'authenticated') then create role authenticated nologin; end if;
end $$;

-- Nachbau der Tabelle profiles mit den Spalten, die die Seite schreibt
create table public.profiles(
  id text primary key, name text, first_name text, last_name text,
  gebiet text, role text, store text, is_online boolean, last_seen timestamptz
);
grant select, insert, update, delete on public.profiles to anon, authenticated;

-- Ausgangslage wie live
insert into public.profiles(id, gebiet, role) values
  ('herbert prantl',    'NRW/Hessen-Herbert', 'superadmin'),
  ('richard',           'Alle Gebiete',       'superadmin'),
  ('carmelo casullo',   'Schulungsleiter',    'carmelo'),
  ('roman sergienko',   'Bayern-Roman',       'gebietsleiter'),
  ('alem hublic',       'Berlin-Alem',        'gebietsleiter'),
  ('christoph neumann', 'Berlin-Chris',       'gebietsleiter'),
  ('jakob',             'Bayern-Szabolcs',    'mitarbeiter'),
  ('emily',             'NRW/Hessen-MA',      'mitarbeiter');

\ir rollen_schutz.sql

-- Hilfsfunktionen für die Prüfungen
create function pg_temp.soll(name text, ist text, erwartet text) returns void language plpgsql as $$
begin
  if ist is distinct from erwartet then
    raise exception 'FEHLER  %: erwartet "%", ist "%"', name, erwartet, ist;
  end if;
  raise warning 'ok  %', name;
end $$;
create function pg_temp.rolle(p text) returns text language sql as $$ select role from public.profiles where id = p $$;
create function pg_temp.gebiet(p text) returns text language sql as $$ select gebiet from public.profiles where id = p $$;
-- Führt SQL als Seite (anon) aus und meldet, ob die Datenbank es abgelehnt hat
create function pg_temp.als_seite(sql text) returns text language plpgsql as $$
begin
  execute 'set local role anon';
  execute sql;
  execute 'reset role';
  return 'gespeichert';
exception when others then
  return 'abgelehnt';
end $$;

\o /dev/null

-- 1. Normaler Login: die Seite schreibt das Profil mit Rolle und Gebiet zurück
select pg_temp.als_seite($q$insert into profiles(id,gebiet,role,is_online) values ('herbert prantl','NRW/Hessen-Herbert','superadmin',true)
  on conflict(id) do update set gebiet=excluded.gebiet, role=excluded.role, is_online=excluded.is_online$q$);
select pg_temp.soll('Login Superadmin behält Rolle', pg_temp.rolle('herbert prantl'), 'superadmin');
select pg_temp.als_seite($q$insert into profiles(id,gebiet,role) values ('roman sergienko','Bayern-Roman','gebietsleiter')
  on conflict(id) do update set gebiet=excluded.gebiet, role=excluded.role$q$);
select pg_temp.soll('Login GL behält Rolle', pg_temp.rolle('roman sergienko'), 'gebietsleiter');

-- 2. Neuer GL in einem Gebiet ohne GL (Szabi-Fall)
select pg_temp.als_seite($q$insert into profiles(id,gebiet,role) values ('szabi remenyi','Bayern-Szabolcs','gebietsleiter')$q$);
select pg_temp.soll('Neuer GL in freiem Gebiet wird GL', pg_temp.rolle('szabi remenyi'), 'gebietsleiter');

-- 3. Mitarbeiter registriert sich über die GL-Anmeldung in einem besetzten Gebiet
select pg_temp.als_seite($q$insert into profiles(id,gebiet,role) values ('nikita krech','Berlin-Alem','gebietsleiter')$q$);
select pg_temp.soll('Zweiter GL im Gebiet wird Mitarbeiter', pg_temp.rolle('nikita krech'), 'mitarbeiter');

-- 4. Superadmin oder Schulungsleiter über die Seite anlegen
select pg_temp.soll('Neuer Superadmin über die Seite abgelehnt',
  pg_temp.als_seite($q$insert into profiles(id,gebiet,role) values ('fake boss','Alle Gebiete','superadmin')$q$), 'abgelehnt');
select pg_temp.als_seite($q$insert into profiles(id,gebiet,role) values ('fake chef','NRW/Hessen-MA','superadmin')$q$);
select pg_temp.soll('Superadmin-Rolle in MA-Gebiet wird Mitarbeiter', pg_temp.rolle('fake chef'), 'mitarbeiter');
select pg_temp.als_seite($q$insert into profiles(id,gebiet,role) values ('fake carmelo','NRW/Hessen-MA','carmelo')$q$);
select pg_temp.soll('Carmelo-Rolle über die Seite wird Mitarbeiter', pg_temp.rolle('fake carmelo'), 'mitarbeiter');

-- 5. Bestehender Mitarbeiter versucht sich hochzustufen
select pg_temp.als_seite($q$update profiles set role='superadmin' where id='jakob'$q$);
select pg_temp.soll('Mitarbeiter kann sich nicht zum Superadmin machen', pg_temp.rolle('jakob'), 'mitarbeiter');
select pg_temp.als_seite($q$update profiles set role='gebietsleiter', gebiet='Berlin-Chris' where id='jakob'$q$);
select pg_temp.soll('Mitarbeiter kann sich nicht zum GL machen', pg_temp.rolle('jakob'), 'mitarbeiter');

-- 6. Leitungskonten können über die Seite nicht verändert werden
select pg_temp.als_seite($q$update profiles set role='mitarbeiter' where id='herbert prantl'$q$);
select pg_temp.soll('Superadmin nicht herabstufbar', pg_temp.rolle('herbert prantl'), 'superadmin');
select pg_temp.als_seite($q$update profiles set gebiet='Bayern-Roman' where id='alem hublic'$q$);
select pg_temp.soll('GL-Gebiet nicht änderbar', pg_temp.gebiet('alem hublic'), 'Berlin-Alem');

-- 7. Gebiet ist Pflicht
select pg_temp.soll('Neues Profil ohne Gebiet abgelehnt',
  pg_temp.als_seite($q$insert into profiles(id,gebiet,role) values ('ohne1','','mitarbeiter')$q$), 'abgelehnt');
select pg_temp.soll('Neues Profil mit Gebiet NULL abgelehnt',
  pg_temp.als_seite($q$insert into profiles(id,role) values ('ohne2','mitarbeiter')$q$), 'abgelehnt');
select pg_temp.soll('Neues Profil nur mit Namen abgelehnt (alter Umbenennen-Fehler)',
  pg_temp.als_seite($q$insert into profiles(id,first_name) values ('nurname','X') on conflict(id) do update set first_name=excluded.first_name$q$), 'abgelehnt');
select pg_temp.soll('Mitarbeiter in Leitungs-Gebiet abgelehnt',
  pg_temp.als_seite($q$insert into profiles(id,gebiet,role) values ('ma2','Alle Gebiete','mitarbeiter')$q$), 'abgelehnt');
select pg_temp.als_seite($q$insert into profiles(id,gebiet,role) values ('emily','','mitarbeiter')
  on conflict(id) do update set gebiet=excluded.gebiet, role=excluded.role$q$);
select pg_temp.soll('Leeres Gebiet überschreibt bestehendes nicht', pg_temp.gebiet('emily'), 'NRW/Hessen-MA');

-- 8. Normale Vorgänge der Seite laufen weiter
select pg_temp.soll('Normale Mitarbeiter-Registrierung',
  pg_temp.als_seite($q$insert into profiles(id,gebiet,role,first_name) values ('neu','Berlin-Chris','mitarbeiter','Neu')$q$), 'gespeichert');
select pg_temp.soll('Rolle fehlt wird Mitarbeiter',
  pg_temp.als_seite($q$insert into profiles(id,gebiet) values ('ohnerolle','NRW/Hessen-MA')$q$), 'gespeichert');
select pg_temp.soll('... und zwar Mitarbeiter', pg_temp.rolle('ohnerolle'), 'mitarbeiter');
select pg_temp.soll('Online-Status aktualisieren',
  pg_temp.als_seite($q$update profiles set is_online=false, last_seen=now() where id='emily'$q$), 'gespeichert');
select pg_temp.soll('Umbenennen (neues Profil mit Gebiet)',
  pg_temp.als_seite($q$insert into profiles(id,first_name,last_name,gebiet,role) values ('emily_neu','Emily','Neu','NRW/Hessen-MA','mitarbeiter')$q$), 'gespeichert');
select pg_temp.soll('Profil löschen',
  pg_temp.als_seite($q$delete from profiles where id='emily'$q$), 'gespeichert');
select pg_temp.soll('... ist gelöscht', (select count(*)::text from profiles where id='emily'), '0');

-- 9. Im SQL-Editor (nicht über die Seite) darf Herbert alles setzen
update public.profiles set role = 'gebietsleiter' where id = 'nikita krech';
select pg_temp.soll('SQL-Editor kann Rollen setzen', pg_temp.rolle('nikita krech'), 'gebietsleiter');

-- 10. Endkontrolle: kein Mitarbeiter ohne gültiges Gebiet
select pg_temp.soll('Kein Mitarbeiterprofil ohne gültiges Gebiet',
  (select count(*)::text from profiles where role not in ('gebietsleiter','superadmin','carmelo')
     and coalesce(gebiet,'') not in ('NRW/Hessen-MA','Bayern-Roman','Bayern-Szabolcs','Berlin-Chris','Berlin-Alem')), '0');

\o
\echo ALLE DATENBANK-TESTS BESTANDEN
