// Nachbau von Supabase für die Browser-Tests.
// Alle Anfragen an die echte Datenbank werden abgefangen und im Speicher beantwortet.
// So entstehen nie Testprofile bei den echten Mitarbeitern.
import { readFileSync } from "node:fs";
import { createHash } from "node:crypto";
import { fileURLToPath } from "node:url";

const INDEX = process.env.BTU_INDEX || fileURLToPath(new URL("../../index.html", import.meta.url));
// localhost, damit der Browser crypto.subtle (Passwort-Hash) wie auf der echten https-Seite anbietet
export const SEITE = "http://localhost:4173/";

export const hash = pw => createHash("sha256").update(pw).digest("hex");

const SCHLUESSEL = { profiles: "id", app_config: "key", favorites: "profile_id", quiz_results: "profile_id", advisor_sessions: "id" };

function passt(row, params) {
  for (const [k, v] of params) {
    if (["select", "order", "limit", "offset", "on_conflict"].includes(k)) continue;
    const m = /^eq\.(.*)$/.exec(v);
    if (m && String(row[k] ?? "") !== m[1]) return false;
  }
  return true;
}

export async function seiteMitNachbau(page, daten = {}) {
  const db = { profiles: [], app_config: [], ...structuredClone(daten) };
  const html = readFileSync(INDEX, "utf8");

  // Echtzeit-Verbindung zu Supabase nie aufbauen
  await page.routeWebSocket(/.*/, ws => ws.close());
  // Schriften und Update-Prüfung nicht laden
  await page.route(/fonts\.(googleapis|gstatic)\.com/, r => r.abort());
  await page.route(/github\.io\/btuwdb2\/version\.json/, r => r.fulfill({ status: 404, body: "" }));
  // Die Seite selbst aus der lokalen Datei
  await page.route(SEITE + "**", r => r.fulfill({ status: 200, contentType: "text/html; charset=utf-8", body: html }));

  // Supabase-REST nachbauen, alles andere von supabase.co blockieren
  await page.route(/supabase\.co/, async route => {
    const req = route.request();
    const url = new URL(req.url());
    const m = /\/rest\/v1\/([^/?]+)/.exec(url.pathname);
    if (!m) return route.abort();
    const tab = decodeURIComponent(m[1]);
    const rows = (db[tab] ||= []);
    const params = [...url.searchParams.entries()];
    const methode = req.method();
    const json = body => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });

    if (methode === "GET") return json(rows.filter(r => passt(r, params)));
    if (methode === "POST") {
      const daten = JSON.parse(req.postData() || "[]");
      const schl = SCHLUESSEL[tab];
      for (const neu of [].concat(daten)) {
        const alt = schl && rows.find(r => r[schl] === neu[schl]);
        if (alt) Object.assign(alt, neu); else rows.push({ ...neu });
      }
      return route.fulfill({ status: 201, body: "" });
    }
    if (methode === "PATCH") {
      const daten = JSON.parse(req.postData() || "{}");
      rows.filter(r => passt(r, params)).forEach(r => Object.assign(r, daten));
      return route.fulfill({ status: 204, body: "" });
    }
    if (methode === "DELETE") {
      db[tab] = rows.filter(r => !passt(r, params));
      return route.fulfill({ status: 204, body: "" });
    }
    return json([]);
  });

  return db;
}
