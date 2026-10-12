// Lädt den Block mit den Rollenregeln aus der index.html, ohne die ganze Seite zu starten.
// Der Block beginnt bei "var GEBIETE = [" und endet am Kommentar "ENDE ROLLENREGELN".
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import vm from "node:vm";

const HTML = fileURLToPath(new URL("../../index.html", import.meta.url));

export function regelnLaden(pfad = process.env.BTU_INDEX || HTML) {
  const html = readFileSync(pfad, "utf8");
  const start = html.indexOf("var GEBIETE = [");
  if (start === -1) throw new Error("Rollenregeln nicht gefunden: 'var GEBIETE = [' fehlt in index.html");
  let ende = html.indexOf("// ── ENDE ROLLENREGELN", start);
  if (ende === -1) {
    // ältere Fassungen ohne Endmarke: bis zur letzten bekannten Rollenfunktion laden
    const letzte = html.indexOf("function canReviewAnswers", start);
    if (letzte === -1) throw new Error("Ende der Rollenregeln nicht gefunden");
    ende = html.indexOf("\n", letzte);
  }
  const code = html.slice(start, ende);
  const ctx = {};
  vm.createContext(ctx);
  vm.runInContext(code, ctx, { filename: "index.html (Rollenregeln)" });
  return ctx;
}
