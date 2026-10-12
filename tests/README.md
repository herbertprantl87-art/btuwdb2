# Tests für BTUWDB2

Die Tests laufen bei jeder Änderung auf GitHub automatisch (Reiter "Actions").
Schlägt ein Test fehl, schickt GitHub eine E-Mail. Die echte Supabase-Datenbank
wird dabei nie benutzt.

| Ebene | Ordner | Was wird geprüft |
|---|---|---|
| Unit | `unit/` | Einzelne Regeln aus der index.html: Rollenvergabe, wer wen sehen darf, gültige Gebiete |
| Datenbank | `db/` | Der Rollen- und Gebietsschutz in einer nachgebauten PostgreSQL-Datenbank |
| Browser | `e2e/` | Registrierung und Anmeldung komplett im Browser, mit nachgebauter Supabase |
| Sync | `sync/` | Preis-Sync, Aktionspreise und Übersetzungs-Nachlauf: einzelne Regeln, Abbruch bei Shop-Sperre, Abgleich mit der index.html |

## Wichtig bei Änderungen

- `db/rollen_schutz.sql` ist die Vorlage des Schutzes, der live in Supabase läuft.
  Wird der Schutz dort geändert, muss diese Datei mitgeändert werden.
- Kommt ein neues Gebiet oder ein neuer GL dazu, müssen `GEBIETE` in der index.html
  und die Listen in `db/rollen_schutz.sql` zusammenpassen. Ein Test prüft das.
- Die Unit-Tests laden den Block zwischen `var GEBIETE = [` und
  `// ── ENDE ROLLENREGELN` aus der index.html. Diese Marke nicht entfernen.

- Die Sync-Skripte liegen als Kopie im Ordner `sync/`. Sie laufen täglich auf Herberts
  Rechner (Ordner PriesSync, `sync_start.bat`). Die Fassung im Repo ist die Vorlage:
  Wird ein Skript geändert, kommt die neue Fassung erst hierher (Tests laufen), dann
  in den PriesSync-Ordner.
- Wird ein Produkt in der index.html ergänzt oder entfernt, schlagen die Sync-Tests an,
  bis `UNSERE`, `MAPPING` und `SKIP` in `sync/preis_sync.py` nachgezogen sind. Das ist
  gewollt: so bekommt kein Produkt still keinen Preisabgleich mehr.

## Lokal ausführen

```
cd tests
npm ci
npx playwright install chromium
npm run unit
PGHOST=localhost PGUSER=postgres PGPASSWORD=... npm run db
npm run e2e
cd sync && python3 -m unittest -v
```
