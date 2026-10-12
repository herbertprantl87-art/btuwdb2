"""Tests fuer aktionspreise.py: Zuordnung, Kombis, Rabatte und der Schutz bei Shop-Sperre."""
import json
import unittest

import laden

ak = laden.skript("aktionspreise")
ak.log = lambda *a, **k: None
PRODS = ak._produkte_parsen(laden.index_html())
# eigene Produkte, wie sie der echte Lauf zusaetzlich aus Supabase laedt
EIGENE = [
    {"id": "shop-14976809632070", "name": "Calcium Zinc Magnesium from organic sources",
     "size": "90 Tabletten", "price": 22.5, "refOnly": False},
    {"id": "shop-14969802391878", "name": "Multivitamin For Women from organic sources",
     "size": "60 Tabletten", "price": 28.9, "refOnly": False},
]


class Kombis(unittest.TestCase):
    def test_kombi_erkennung(self):
        for t in ["1 db One-a-day 100 tabs + 1 db One-a-day Kids 90 tabs 50%-ért",
                  "IsoTonic + Cyclic Dextrin -10%", "Protein Bar 3+1",
                  "Iso Whey Zero Sample Bundle - 17*25 g"]:
            self.assertTrue(ak.ist_kombi(t), t)
        for t in ["Iso Whey Zero - 454 g", "BCAA 8:1:1 ZERO - 250 g", "Vitamin C 1000 Bioflavonoids - 100 Tabletten",
                  "100% Creatine Monohydrate - 300 g"]:
            self.assertFalse(ak.ist_kombi(t), t)

    def kombi(self, titel, prods=PRODS):
        b, offen = ak.kombi_bauen(1, titel, 10.0, 20.0, None, prods)
        return b, offen

    def test_one_a_day_kombi_aus_herberts_beispiel(self):
        b, _ = self.kombi("1 db One-a-day 100 tabs + 1 db One-a-day Kids 90 tabs 50%-ért")
        self.assertEqual(b["produkte"], [37, 240])

    def test_zwei_produkte(self):
        self.assertEqual(self.kombi("IsoTonic + Cyclic Dextrin -10%")[0]["produkte"], [92, 90])
        self.assertEqual(self.kombi("Beef Protein 500 g + 100% Creatine Monohydrate 300 g -20%")[0]["produkte"], [6, 9])

    def test_mengenangebot(self):
        b, _ = self.kombi("Protein Bar 3+1")
        self.assertEqual((b["menge"], b["gratis"]), (4, 1))
        b, _ = self.kombi("Iso Whey Zero Sample Bundle - 17*25 g")
        self.assertEqual((b["menge"], b["gratis"]), (17, None))

    def test_organic_paket_nimmt_organic_varianten(self):
        b, _ = self.kombi("Multivitamin For Men + Calcium Zinc Magnesium + Liposomal Vitamin C from organic sources",
                          PRODS + EIGENE)
        self.assertIn("shop-14976809632070", b["produkte"], "organic-Variante statt #82")
        self.assertNotIn(82, b["produkte"])

    def test_unklare_kombi_wird_gemeldet_statt_geraten(self):
        b, offen = self.kombi("Voellig Unbekannt + Auch Unbekannt -10%")
        self.assertIsNone(b)
        self.assertTrue(offen)


class Rabatte(unittest.TestCase):
    def test_prozent_und_normalpreis_kommen_vom_shop(self):
        # Vorgabe Herbert 18.08.2026: Badge und Normalpreis wie im Shop
        rev = ak.lade_mapping()
        sid = int(next(s for s, ids in rev.items() if "92" in ids))
        neu = ak.sale_prices_bauen({sid: {"aktion": 19.10, "name": "IsoTonic", "pct": 15}},
                                   {sid: {"titel": "IsoTonic - 600 g", "preis": 23.90}}, PRODS, rev)
        self.assertEqual(neu["92"]["pct"], 15)
        self.assertEqual(neu["92"]["normal"], 23.90)

    def test_kein_aktionspreis_ueber_normalpreis(self):
        rev = ak.lade_mapping()
        sid = int(next(s for s, ids in rev.items() if "92" in ids))
        neu = ak.sale_prices_bauen({sid: {"aktion": 25.0, "name": "IsoTonic", "pct": None}},
                                   {sid: {"titel": "IsoTonic - 600 g", "preis": 23.90}}, PRODS, rev)
        self.assertEqual(neu, {})

    def test_produkt_ids_als_zahl_oder_text(self):
        self.assertEqual(ak.pid_out("37"), 37)
        self.assertEqual(ak.pid_out("shop-123"), "shop-123")


class Monatskategorie(unittest.TestCase):
    def test_hand_gepflegte_kombis_bleiben(self):
        hand = {"id": "h1", "produkte": [37, 240], "text": "Hand", "preis": 21.5, "quelle": "hand"}
        alt_shop = {"id": "shop-1", "produkte": [92, 90], "quelle": "shop"}
        neu_shop = {"id": "shop-2", "produkte": [6, 9], "quelle": "shop", "text": "neu"}
        doppel = {"id": "shop-3", "produkte": [240, 37], "quelle": "shop", "text": "doppelt"}
        ergebnis = ak.bundles_mischen([hand, alt_shop], [neu_shop, doppel])
        self.assertEqual([b["id"] for b in ergebnis], ["h1", "shop-2"])

    def test_monatsname(self):
        self.assertEqual(ak.monatsname("Oktober"), "Oktober")
        self.assertEqual(len(ak.MONATE), 12)


class ShopSperre(unittest.TestCase):
    """Luecke vom 18.08.2026: blockt der Shop, darf nichts geschrieben werden,
    sonst verschwinden alle Angebote aus der App."""

    def setUp(self):
        self.m = laden.skript("aktionspreise")
        self.m.log = lambda *a, **k: None
        self.schreiben = []
        self.m.sb = lambda method, query, body=None: (self.schreiben.append(method) if method != "GET" else []) or []
        self.m.wdb_produkte = lambda: PRODS
        self.m.lade_mapping = lambda: {}

    def lauf(self, *argv):
        import sys
        alt = sys.argv
        sys.argv = ["aktionspreise.py"] + list(argv)
        try:
            return self.m.main()
        finally:
            sys.argv = alt

    def test_shop_gesperrt_bricht_ab_und_schreibt_nichts(self):
        def gesperrt(url, tries=3, warten=20):
            raise RuntimeError("HTTP Error 429: Too Many Requests")
        self.m.fetch = gesperrt
        self.assertEqual(self.lauf("--write"), 1)
        self.assertEqual(self.schreiben, [])

    def test_eine_seite_gesperrt_reicht_fuer_abbruch(self):
        def halb(url, tries=3, warten=20):
            if "aktionsprodukte" in url:
                raise RuntimeError("HTTP Error 503")
            return "<html></html>"
        self.m.fetch = halb
        self.assertEqual(self.lauf("--write"), 1)
        self.assertEqual(self.schreiben, [])

    def test_probelauf_schreibt_nie(self):
        self.m.fetch = lambda url, tries=3, warten=20: "<html></html>"
        self.m.sb_config = lambda key: {"92": {"price": 1}}
        self.assertEqual(self.lauf(), 0)
        self.assertEqual(self.schreiben, [])


if __name__ == "__main__":
    unittest.main()
