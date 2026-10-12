"""Integrationstests: passen Preis-Sync, Aktionspreise und index.html zusammen?

Hintergrund: Am 20./21.08.2026 wurden in der index.html Dubletten entfernt und
35 Packungsgroessen ergaenzt. Der Preis-Sync wurde nicht nachgezogen, dadurch
liefen die neuen Groessen bis 12.10.2026 ohne Preisabgleich. Diese Tests
schlagen an, sobald index.html und Preis-Sync wieder auseinanderlaufen.
"""
import io
import re
import unittest

import laden

# Kategorien ohne Preisabgleich: Bekleidung, Zubehoer und Infoseiten
# Bekannte, bewusst offene Abweichungen. Jeder Eintrag braucht einen Grund und ein Datum.
BEKANNTE_GROESSEN_ABWEICHUNG = {
    "91": "Supernova: Katalog 300 g, Shop 282 g, gleicher Preis. Frage an Herbert offen (12.10.2026)",
}
STUECK = {"kaps", "tbl", "st\u00fcck"}

OHNE_ABGLEICH = {"Bekleidung", "Zubehör", "Shaker & Zubehör",
                 "⚠️ Verbotene Substanzen (WADA)",
                 "⚠️ Wachstumshormone & GH-Peptide"}


def katalog():
    """id -> {name, size, price, refOnly, category} aus der index.html"""
    html = laden.index_html()
    s = html.find("var PRODUCTS = [")
    e = html.find("\n];", s)
    body = html[s:e]
    out = {}
    for m in re.finditer(r'\n    id: (\d+),(.{0,900}?)\n    category: "([^"]*)"', body, re.S):
        chunk = m.group(2)
        nm = re.search(r'name: "((?:[^"\\]|\\.)*)"', chunk)
        sz = re.search(r'packageSize: "((?:[^"\\]|\\.)*)"', chunk)
        pr = re.search(r'price: ([\d.]+)', chunk)
        out[m.group(1)] = {"name": nm.group(1) if nm else "", "size": sz.group(1) if sz else "",
                           "price": float(pr.group(1)) if pr else None,
                           "refOnly": "refOnly: true" in chunk, "category": m.group(3)}
    return out


class KatalogAbgleich(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ps = laden.skript("preis_sync")
        cls.ak = laden.skript("aktionspreise")
        cls.ak.log = lambda *a, **k: None
        cls.kat = katalog()
        cls.ids = set(laden.index_produkt_ids())

    def test_katalog_wird_vollstaendig_gelesen(self):
        self.assertGreater(len(self.ids), 300)
        self.assertEqual(set(self.kat), self.ids,
                         "Kategorie fehlt bei: %s" % sorted(self.ids - set(self.kat)))

    def test_zuordnungen_zeigen_auf_vorhandene_produkte(self):
        tot = sorted((k for k in self.ps.MAPPING if k not in self.ids), key=int)
        self.assertEqual(tot, [], "MAPPING in preis_sync.py zeigt auf Produkte, die es in der "
                                  "index.html nicht mehr gibt: %s" % tot)

    def test_ausnahmen_zeigen_auf_vorhandene_produkte(self):
        tot = [k for k in self.ps.SKIP if k.isdigit() and k not in self.ids]
        self.assertEqual(tot, [], "SKIP nennt Produkte, die es nicht mehr gibt: %s" % tot)

    def test_kein_produkt_zugleich_zugeordnet_und_ausgenommen(self):
        beides = sorted(set(self.ps.MAPPING) & set(self.ps.SKIP))
        self.assertEqual(beides, [], "Produkte stehen in MAPPING und SKIP: %s" % beides)

    def test_jedes_produkt_hat_preisabgleich_oder_begruendung(self):
        ohne = sorted((i for i, p in self.kat.items()
                       if p["category"] not in OHNE_ABGLEICH
                       and i not in self.ps.MAPPING and i not in self.ps.SKIP), key=int)
        self.assertEqual(ohne, [], "Diese Produkte haben weder eine Shop-Zuordnung (MAPPING) "
                                   "noch eine Begründung (SKIP) in preis_sync.py: %s"
                         % ["#%s %s %s" % (i, self.kat[i]["name"], self.kat[i]["size"]) for i in ohne])

    def test_produktliste_im_preis_sync_entspricht_der_seite(self):
        """UNSERE wird beim Preisabgleich benutzt. Fehlt dort ein Produkt,
        wird es stillschweigend uebersprungen (Fall #413 bis #448)."""
        unsere = {str(u["id"]): u for u in self.ps.UNSERE}
        self.assertEqual(sorted(set(unsere) - self.ids, key=int), [],
                         "UNSERE enthält entfernte Produkte")
        self.assertEqual(sorted(self.ids - set(unsere), key=int), [],
                         "UNSERE fehlen Produkte der index.html, sie bekommen keinen Preisabgleich")
        abw = [(i, unsere[i]["name"], self.kat[i]["name"]) for i in self.ids
               if unsere[i]["name"] != self.kat[i]["name"]
               or (unsere[i].get("packageSize") or "") != self.kat[i]["size"]]
        self.assertEqual(abw, [], "Name oder Größe in UNSERE weicht von der index.html ab")

    def test_zuordnung_passt_zur_packungsgroesse(self):
        """Shop-Titel und unsere Packungsgroesse duerfen sich nicht widersprechen
        (Fehler wie Sachet 25 g gegen 28 g)."""
        falsch = []
        for k, m in self.ps.MAPPING.items():
            p = self.kat.get(k)
            if not p:
                continue
            sg = self.ak.groesse(m["shop_title"])
            pg = self.ak.groesse(p["size"] or "")
            if k in BEKANNTE_GROESSEN_ABWEICHUNG:
                continue
            if sg and pg and sg[1] in STUECK and pg[1] in STUECK:
                sg, pg = sg[0], pg[0]          # 60 Softgelkapseln = 60 Stueck
            if sg and pg and sg != pg:
                falsch.append("#%s %s %s <-> %s" % (k, p["name"], p["size"], m["shop_title"]))
        self.assertEqual(falsch, [], "Größe passt nicht zur Shop-Zuordnung")

    def test_aktionspreise_liest_dieselbe_zuordnung(self):
        rev = self.ak.lade_mapping()
        anzahl = sum(len(v) for v in rev.values())
        self.assertEqual(anzahl, len(self.ps.MAPPING),
                         "aktionspreise.py liest MAPPING aus preis_sync.py nicht vollständig")

    def test_aktionspreise_erkennt_alle_produkte_der_seite(self):
        prods = self.ak._produkte_parsen(laden.index_html())
        self.assertEqual({p["id"] for p in prods}, self.ids)
        for p in prods:
            k = self.kat[p["id"]]
            self.assertEqual((p["name"], p["size"], p["refOnly"]), (k["name"], k["size"], k["refOnly"]), p["id"])

    def test_preis_sync_erkennt_alle_produkte_der_seite(self):
        """load_index_products liest die index.html mit einem Muster. Aendert sich
        die Formatierung, darf das nicht stillschweigend leer laufen."""
        html = laden.index_html().encode()

        class Antwort(io.BytesIO):
            def __enter__(self): return self
            def __exit__(self, *a): return False

        ps = laden.skript("preis_sync")
        ps.urllib.request.urlopen = lambda req, timeout=None: Antwort(html)
        alt_open = ps.__dict__.get("open")
        ps.open = lambda *a, **k: io.StringIO()   # Zwischenspeicher nicht auf die Platte schreiben
        try:
            basis = ps.load_index_products()
        finally:
            if alt_open is None:
                del ps.open
        self.assertTrue(ps._BASIS_FRESH)
        self.assertEqual(set(basis), self.ids)
        self.assertEqual(basis["1"]["name"], "Iso Whey Zero")


if __name__ == "__main__":
    unittest.main()
