#!/usr/bin/env bash
# Datenbank-Tests: legt eine frische Test-Datenbank an und spielt die Prüfungen ein.
# Nutzt die üblichen PG-Umgebungsvariablen (PGHOST, PGUSER, PGPASSWORD ...).
# Nie gegen Supabase ausführen.
set -euo pipefail
cd "$(dirname "$0")"
DB="btu_test_$$"
psql -qX -v ON_ERROR_STOP=1 -d postgres -c "create database $DB" >/dev/null
trap 'psql -qX -d postgres -c "drop database if exists $DB" >/dev/null 2>&1 || true' EXIT
psql -qX -v ON_ERROR_STOP=1 -d "$DB" -f test_rollenschutz.sql 2>&1 | sed 's/^psql:[^ ]* WARNING:  /  /'
