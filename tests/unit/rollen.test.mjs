// Unit-Tests: einzelne Regeln zu Rollen, Gebieten und Sichtbarkeit.
// Start: node --test tests/unit
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { regelnLaden } from "./regeln-laden.mjs";

const R = regelnLaden();
const MA_GEBIETE = R.GEBIETE.filter(g => !g.glOnly).map(g => g.value);
const GL_GEBIETE = R.GEBIETE.filter(g => g.glOnly && g.role === "gebietsleiter").map(g => g.value);

function brauche(name) {
  assert.equal(typeof R[name], "function", `Funktion ${name} fehlt in index.html`);
  return R[name];
}

test("Registrierung über GL-Anmeldung ergibt GL-Rolle (Szabi-Fall)", () => {
  const rolle = brauche("rolleBeiRegistrierung");
  for (const g of GL_GEBIETE) {
    assert.equal(rolle(g, true), "gebietsleiter", `GL-Anmeldung ${g}`);
  }
});

test("Registrierung über normale Anmeldung ergibt immer Mitarbeiter", () => {
  const rolle = brauche("rolleBeiRegistrierung");
  for (const g of [...MA_GEBIETE, "Alle Gebiete", "NRW/Hessen-Herbert", "Schulungsleiter", ""]) {
    assert.equal(rolle(g, false), "mitarbeiter", `normale Anmeldung ${g || "(leer)"}`);
  }
});

test("Superadmin und Schulungsleiter nur über ihre eigenen Gebiete", () => {
  const rolle = brauche("rolleBeiRegistrierung");
  assert.equal(rolle("Alle Gebiete", true), "superadmin");
  assert.equal(rolle("NRW/Hessen-Herbert", true), "superadmin");
  assert.equal(rolle("Schulungsleiter", true), "carmelo");
  assert.equal(rolle("Gibt es nicht", true), "mitarbeiter");
});

test("Superadmin sieht alle Nutzer", () => {
  const sieht = brauche("canSeeUser");
  const richard = { username: "richard", role: "superadmin", gebiet: "Alle Gebiete" };
  for (const g of [...MA_GEBIETE, ""]) assert.equal(sieht(richard, g, "x"), true, g);
});

test("GL sieht nur sein exaktes Gebiet", () => {
  const sieht = brauche("canSeeUser");
  const szabi = { username: "szabi remenyi", role: "gebietsleiter", gebiet: "Bayern-Szabolcs" };
  assert.equal(sieht(szabi, "Bayern-Szabolcs", "jakob"), true);
  assert.equal(sieht(szabi, "Bayern-Roman", "simona"), false, "fremdes GL-Gebiet derselben Region");
  assert.equal(sieht(szabi, "NRW/Hessen-MA", "emily"), false);
  assert.equal(sieht(szabi, "", "ohne"), false);
  assert.equal(sieht(szabi, "Bayern-Szabolcs", "szabi remenyi"), true, "sich selbst");
});

test("GL ohne Gebiet sieht niemanden außer sich", () => {
  const sieht = brauche("canSeeUser");
  const gl = { username: "gl", role: "gebietsleiter", gebiet: "" };
  assert.equal(sieht(gl, "", "andere"), false);
  assert.equal(sieht(gl, "", "gl"), true);
});

test("Mitarbeiter und Schulungsleiter sehen nur sich selbst", () => {
  const sieht = brauche("canSeeUser");
  for (const v of [
    { username: "jakob", role: "mitarbeiter", gebiet: "Bayern-Szabolcs" },
    { username: "carmelo casullo", role: "carmelo", gebiet: "Schulungsleiter" },
    { username: "ohne", role: undefined, gebiet: "NRW/Hessen-MA" },
  ]) {
    assert.equal(sieht(v, v.gebiet, "jemand anders"), false, v.username);
    assert.equal(sieht(v, v.gebiet, v.username), true, v.username + " sich selbst");
  }
  assert.equal(sieht(null, "NRW/Hessen-MA", "x"), false, "ohne Anmeldung");
});

test("Gültige Mitarbeiter-Gebiete", () => {
  const ok = brauche("isValidMaGebiet");
  for (const g of MA_GEBIETE) assert.equal(ok(g), true, g);
  for (const g of ["", null, undefined, "Alle Gebiete", "NRW/Hessen-Herbert", "Schulungsleiter", "Bayern"]) {
    assert.equal(ok(g), false, String(g));
  }
});

test("Leitungsrollen", () => {
  const leit = brauche("isLeaderRole");
  for (const r of ["gebietsleiter", "superadmin", "carmelo"]) assert.equal(leit(r), true, r);
  for (const r of ["mitarbeiter", "", null, undefined, "admin"]) assert.equal(leit(r), false, String(r));
});

test("Gebietslisten in Seite und Datenbank-Schutz stimmen überein", () => {
  const sql = readFileSync(new URL("../db/rollen_schutz.sql", import.meta.url), "utf8");
  const liste = name => {
    const m = sql.match(new RegExp(name + "\\s+text\\[\\]\\s*:=\\s*array\\[([^\\]]*)\\]"));
    assert.ok(m, `${name} fehlt in rollen_schutz.sql`);
    return m[1].split(",").map(s => s.trim().replace(/^'|'$/g, "")).sort();
  };
  assert.deepEqual(liste("ma_gebiete"), [...MA_GEBIETE].sort(),
    "Mitarbeiter-Gebiete in index.html und rollen_schutz.sql weichen ab");
  assert.deepEqual(liste("gl_gebiete"), [...GL_GEBIETE].sort(),
    "GL-Gebiete in index.html und rollen_schutz.sql weichen ab");
});
