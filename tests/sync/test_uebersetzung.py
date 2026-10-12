"""Der Uebersetzungs-Nachlauf (Python) muss dieselben Schluessel bilden wie die
Seite (JavaScript, i18nHash in der index.html). Weicht das ab, bleiben neue
Texte unbemerkt deutsch."""
import json
import re
import shutil
import subprocess
import unittest

import laden

TEXTE = ["Iso Whey Zero", "Kräuter & Pflanzenextrakte", "Größe: 454 g",
         "\U0001F3F7️ Monatsangebote Oktober", "مرحبا",
         "  Leerzeichen  ", "", "60 Kapseln", "Laut Produktetikett",
         "Calcium Zinc Magnesium from organic sources", "1€ – 50%"]


def js_schluessel(texte):
    html = laden.index_html()
    m = re.search(r"function i18nHash\(s\) \{.*?\n\}", html, re.S)
    assert m, "i18nHash nicht in index.html gefunden"
    code = m.group(0) + "\nconsole.log(JSON.stringify(%s.map(i18nHash)));" % json.dumps(texte)
    out = subprocess.run(["node", "-e", code], capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


@unittest.skipUnless(shutil.which("node"), "node fehlt")
class Uebersetzungsschluessel(unittest.TestCase):
    def test_python_und_javascript_gleich(self):
        nl = laden.skript("uebersetzung_nachlauf")
        self.assertEqual([nl.schluessel_fuer(t) for t in TEXTE], js_schluessel(TEXTE))

    def test_schutzbegriffe_kommen_unveraendert_zurueck(self):
        nl = laden.skript("uebersetzung_nachlauf")
        muster = nl.schutzmuster(["Iso Whey Zero", "from organic sources"])
        text = "Iso Whey Zero ist ein Protein. Calcium from organic sources."
        geschuetzt, marken = nl.schuetzen(text, muster)
        self.assertNotIn("Iso Whey Zero", geschuetzt)
        self.assertEqual(nl.zurueck(geschuetzt, marken), text)


if __name__ == "__main__":
    unittest.main()
