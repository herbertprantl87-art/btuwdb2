# Tests für BTUWDB2

Die Tests laufen bei jeder Änderung auf GitHub automatisch (Reiter "Actions").
Schlägt ein Test fehl, schickt GitHub eine E-Mail. Die echte Supabase-Datenbank
wird dabei nie benutzt.

| Ebene | Ordner | Was wird geprüft |
|---|---|---|
| Unit | `unit/` | Einzelne Regeln aus der index.html: Rollenvergabe, wer wen sehen darf, gültige Gebiete |
| Datenbank | `db/` | Der Rollen- und Gebietsschutz in einer nachgebauten PostgreSQL-Datenbank |
| Browser | `e2e/` | Registrierung und Anmeldung komplett im Browser, mit nachgebauter Supabase |

## Wichtig bei Änderungen

- `db/rollen_schutz.sql` ist die Vorlage des Schutzes, der live in Supabase läuft.
  Wird der Schutz dort geändert, muss diese Datei mitgeändert werden.
- Kommt ein neues Gebiet oder ein neuer GL dazu, müssen `GEBIETE` in der index.html
  und die Listen in `db/rollen_schutz.sql` zusammenpassen. Ein Test prüft das.
- Die Unit-Tests laden den Block zwischen `var GEBIETE = [` und
  `// ── ENDE ROLLENREGELN` aus der index.html. Diese Marke nicht entfernen.

## Lokal ausführen

```
cd tests
npm ci
npx playwright install chromium
npm run unit
PGHOST=localhost PGUSER=postgres PGPASSWORD=... npm run db
npm run e2e
```
