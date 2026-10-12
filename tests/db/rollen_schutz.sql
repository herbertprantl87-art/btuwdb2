-- BTUWDB2: Rollen- und Gebietsschutz für profiles (Stand 12.10.2026, live in Supabase)
-- Diese Datei ist die Vorlage für die Tests. Wird der Schutz in Supabase geändert,
-- muss diese Datei mitgeändert werden, sonst prüfen die Tests den falschen Stand.
-- Wiederholbar. Im Supabase SQL-Editor komplett ausführen.
--
-- Regeln, wenn die Seite (anon/authenticated) schreibt:
--  * Rolle fehlt oder ist unbekannt -> mitarbeiter
--  * Leitungskonten (gebietsleiter/superadmin/carmelo) behalten Rolle und Gebiet,
--    die Seite kann sie weder ändern noch herabstufen
--  * gebietsleiter nur für ein GL-Gebiet und nur, wenn dieses Gebiet noch keinen GL hat
--  * superadmin und carmelo kann die Seite nie neu vergeben, nur der SQL-Editor
--  * NEU: Jedes andere Profil braucht ein gültiges Mitarbeiter-Gebiet. Fehlt es,
--    bleibt das bisherige Gebiet stehen; gibt es keins, wird das Speichern abgelehnt.
-- Im SQL-Editor (Rolle postgres) gilt nichts davon.

create or replace function public.btu_rollen_schutz()
returns trigger
language plpgsql
security invoker
set search_path = public
as $$
declare
  alt record;
  gl_gebiete text[] := array['Bayern-Roman','Bayern-Szabolcs','Berlin-Chris','Berlin-Alem'];
  ma_gebiete text[] := array['NRW/Hessen-MA','Bayern-Roman','Bayern-Szabolcs','Berlin-Chris','Berlin-Alem'];
begin
  if current_user not in ('anon', 'authenticated') then
    return new;
  end if;

  select role, gebiet into alt from public.profiles where id = new.id;

  -- Bestehende Leitungskonten: Rolle und Gebiet bleiben, wie sie sind
  if alt.role in ('gebietsleiter','superadmin','carmelo') then
    new.role := alt.role;
    new.gebiet := alt.gebiet;
    return new;
  end if;

  -- Gebiet prüfen: nur gültige Mitarbeiter-Gebiete
  if new.gebiet is null or not (new.gebiet = any(ma_gebiete)) then
    if alt.gebiet = any(ma_gebiete) then
      new.gebiet := alt.gebiet;
    else
      raise exception 'Profil ohne gültiges Gebiet: %', new.id
        using errcode = '23514', hint = 'Bitte Gebiet auswählen';
    end if;
  end if;

  -- Rolle: neu vergeben darf die Seite nur gebietsleiter (freies GL-Gebiet), sonst mitarbeiter
  if new.role = 'gebietsleiter'
     and new.gebiet = any(gl_gebiete)
     and not exists (select 1 from public.profiles p
                     where p.role = 'gebietsleiter' and p.gebiet = new.gebiet and p.id <> new.id) then
    return new;
  end if;

  new.role := 'mitarbeiter';
  return new;
end;
$$;

drop trigger if exists btu_rollen_schutz on public.profiles;
create trigger btu_rollen_schutz
  before insert or update on public.profiles
  for each row execute function public.btu_rollen_schutz();
