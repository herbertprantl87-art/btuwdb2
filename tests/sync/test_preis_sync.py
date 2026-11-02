"""Unit-Tests fuer einzelne Regeln aus preis_sync.py (Faelle aus Juli/August 2026)."""
import io
import unittest
import urllib.request

import laden

ps = laden.skript("preis_sync")


class Zahlen(unittest.TestCase):
    def test_zahlformat_ohne_abgeschnittene_null(self):
        # Fehler Juli 2026: rstrip("0") machte aus "40 g" "4 g"
        self.assertEqual(ps.fmt_num(40.0), "40")
        self.assertEqual(ps.fmt_num(100.0), "100")
        self.assertEqual(ps.fmt_num(4.5), "4,5")
        self.assertEqual(ps.fmt_num(21.04), "21")

    def test_preisklasse(self):
        self.assertEqual(ps.price_range(2.7), "€")
        self.assertEqual(ps.price_range(15), "€€")
        self.assertEqual(ps.price_range(34.99), "€€")
        self.assertEqual(ps.price_range(35), "€€€")


class Titel(unittest.TestCase):
    def test_titel_trennen(self):
        self.assertEqual(ps.split_title("Iso Whey Zero - 454 g"), ("Iso Whey Zero", "454 g"))
        self.assertEqual(ps.split_title("Black Burn"), ("Black Burn", "–"))

    def test_groesse_und_geschmack_trennen(self):
        # v16: "300 g Drachenfrucht-Litschi" gehoert in packageSize + flavors
        self.assertEqual(ps.parse_size_flavor("300 g Drachenfrucht-Litschi"), ("300 g", "Drachenfrucht-Litschi"))
        self.assertEqual(ps.parse_size_flavor("1000 g"), ("1000 g", ""))
        self.assertEqual(ps.parse_size_flavor("–"), ("–", ""))
        self.assertEqual(ps.parse_size_flavor(""), ("–", ""))

    def test_gramm_aus_titel(self):
        self.assertEqual(ps.title_grams("Iso Whey Zero - 454 g"), 454.0)
        self.assertIsNone(ps.title_grams("Black Burn - 90 Megakapseln"))


class LimitedEdition(unittest.TestCase):
    def test_erkennung(self):
        self.assertTrue(ps.is_limited({"title": "Whey Shake - 1000 g", "body_html": "Collector's Edition"}))
        self.assertTrue(ps.is_limited({"title": "Beef Protein Limited Edition - 900 g"}))
        self.assertTrue(ps.is_limited({"title": "X", "body_html": "<p>Limitiert verfügbar</p>"}))
        self.assertFalse(ps.is_limited({"title": "Iso Whey Zero - 454 g", "body_html": ""}))

    def test_name_mit_zusatz(self):
        p = {"title": "Whey Shake - 1000 g", "body_html": "limited edition", "variants": [{"title": "Pfirsich-Joghurt"}]}
        self.assertEqual(ps.final_name(p, "Whey Shake", {"whey shake"}), "Whey Shake (Limited Edition)")

    def test_doppelter_name_bekommt_geschmack_ohne_default_title(self):
        p = {"title": "Go Energy - 40 g", "variants": [{"title": "Default Title"}]}
        self.assertEqual(ps.final_name(p, "Go Energy", {"go energy"}), "Go Energy (40 g)")
        p2 = {"title": "Go Energy - 40 g", "variants": [{"title": "Erdbeere"}]}
        self.assertEqual(ps.final_name(p2, "Go Energy", {"go energy"}), "Go Energy (Erdbeere)")
        self.assertEqual(ps.final_name(p2, "Go Energy", set()), "Go Energy")


class FelderErgaenzen(unittest.TestCase):
    def test_groesse_wird_angehaengt_und_nur_einmal(self):
        e = {}
        self.assertEqual(ps.ergaenze_feld(e, "packageSize", "454 g", ["2270 g"], " / "), ["2270 g"])
        self.assertEqual(e["packageSize"], "454 g / 2270 g")
        # zweiter Lauf: nichts mehr zu tun (idempotent)
        self.assertEqual(ps.ergaenze_feld(e, "packageSize", "454 g", ["2270 g"], " / "), [])
        self.assertEqual(e["packageSize"], "454 g / 2270 g")

    def test_geschmack_gross_klein_egal(self):
        e = {"flavors": "Vanille, Schoko"}
        self.assertEqual(ps.ergaenze_feld(e, "flavors", "", ["schoko", "Mango"]), ["Mango"])
        self.assertEqual(e["flavors"], "Vanille, Schoko, Mango")

    def test_platzhalter_zaehlt_als_leer(self):
        e = {}
        ps.ergaenze_feld(e, "flavors", "–", ["Erdbeere"])
        self.assertEqual(e["flavors"], "Erdbeere")
        self.assertTrue(ps._leer("Laut Produktetikett", extra=("Laut Produktetikett",)))
        self.assertTrue(ps._leer(" – "))
        self.assertFalse(ps._leer("2 Kapseln täglich"))


class Beschreibung(unittest.TestCase):
    NAEHRWERT_100G = (
        "<p>1 Portion: 30 g</p><table>"
        "<tr><td>Nährwerte</td><td>100 g</td></tr>"
        "<tr><td>Energie</td><td>1590 kJ / 376 kcal</td></tr>"
        "<tr><td>Fett</td><td>2 g</td></tr>"
        "<tr><td>Kohlenhydrate</td><td>3,3 g</td></tr>"
        "<tr><td>Eiweiß</td><td>80 g</td></tr></table>"
        "<h3>Verzehrempfehlung</h3><p>Täglich 1 Portion (30 g) in 300 ml Wasser einrühren.</p>")

    def test_naehrwerte_werden_auf_portion_umgerechnet(self):
        d = ps.parse_desc(self.NAEHRWERT_100G)
        self.assertEqual(d["portionSize"], "30 g")
        self.assertEqual(d["kcalPortion"], 113)
        self.assertEqual(d["proteinPortion"], "24 g")
        self.assertEqual(d["fatPortion"], "0,6 g")

    def test_dosierung_wird_gefunden(self):
        d = ps.parse_desc(self.NAEHRWERT_100G)
        self.assertIn("1 Portion", d["dosage"])

    def test_wirkstoffe_nur_ohne_naehrwerttabelle(self):
        vit = ("<table><tr><th>Wirkstoff</th><th>Menge</th></tr>"
               "<tr><td>Vitamin C</td><td>1000 mg</td><td>1250%</td></tr>"
               "<tr><td>Bioflavonoide</td><td>50 mg</td><td>*</td></tr></table>")
        self.assertEqual(ps.parse_desc(vit)["keyIngredients"], ["Vitamin C (1000 mg)", "Bioflavonoide (50 mg)"])
        self.assertNotIn("keyIngredients", ps.parse_desc(self.NAEHRWERT_100G),
                         "bei Pulvern darf das Aminogramm nicht zu Inhaltsstoffen werden")

    def test_vegan(self):
        self.assertTrue(ps.parse_desc("<p>Vegan und laktosefrei.</p>").get("vegan"))
        self.assertNotIn("vegan", ps.parse_desc("<p>Dieses Produkt ist nicht vegan.</p>"))

    def test_kurzbeschreibung_kappt_an_satzgrenze(self):
        satz = "Iso Whey Zero ist ein Isolat mit hohem Eiweißgehalt und wenig Zucker. "
        h = "<p>" + satz * 10 + "</p>"
        k = ps.short_desc(h, limit=350, name="Iso Whey Zero")
        self.assertLessEqual(len(k), 350)
        self.assertTrue(k.endswith("."))


def basis_aus_lokaler_index():
    """Basisdaten der index.html ohne Netz laden (plane_neuzugaenge braucht sie)."""
    if ps._BASIS is not None:
        return
    html = laden.index_html().encode()

    class Antwort(io.BytesIO):
        def __enter__(self): return self
        def __exit__(self, *a): return False

    alt = urllib.request.urlopen
    urllib.request.urlopen = lambda req, timeout=None: Antwort(html)
    ps.open = lambda *a, **k: io.StringIO()   # Zwischenspeicher nicht schreiben
    try:
        ps.load_index_products()
    finally:
        urllib.request.urlopen = alt
        del ps.open


class Groessen(unittest.TestCase):
    def test_groessenkern(self):
        self.assertEqual(ps.size_kern("22,5 g (Sachet)"), ps.size_kern("22,5 g"))
        self.assertEqual(ps.size_kern("1 Stk. (64 g)"), "64g")
        self.assertEqual(ps.size_kern("100 Tbl"), ps.size_kern("100 Tabletten"))
        self.assertNotEqual(ps.size_kern("60 Tabletten"), ps.size_kern("120 Tabletten"))


class NeueShopProdukte(unittest.TestCase):
    """Regeln von Herbert (03.08.2026): neuer Geschmack oder neue Groesse wird beim
    bestehenden Produkt ergaenzt, Limited Editions werden eigene Produkte."""

    @classmethod
    def setUpClass(cls):
        cls.unsere = {str(u["id"]): u for u in ps.UNSERE}
        basis_aus_lokaler_index()

    def plane(self, titel, varianten=("Vanille",), body=""):
        p = {"id": 999000001, "title": titel, "body_html": body,
             "variants": [{"title": v} for v in varianten]}
        return ps.plane_neuzugaenge([p], self.unsere, [])

    def test_neuer_geschmack_geht_ans_hauptprodukt(self):
        anlegen, geschmack, groessen, _, _ = self.plane("Iso Whey Zero Proteinpulver - 454 g", ["Mango-Lassi"])
        self.assertEqual(anlegen, [])
        self.assertEqual(len(geschmack), 1)
        self.assertEqual(geschmack[0]["ziel"], "1", "nicht an das Sachet #374, sondern an #1")
        self.assertEqual(geschmack[0]["geschmack"], "Mango-Lassi")

    def test_neue_groesse_wird_eigene_groesse_statt_neu_angelegt(self):
        anlegen, geschmack, groessen, _, _ = self.plane("Iso Whey Zero Proteinpulver - 5000 g")
        self.assertEqual(anlegen, [])
        self.assertEqual([(g["ziel"], g["groesse"]) for g in groessen], [("1", "5000 g")])

    def test_limited_edition_wird_eigenes_produkt(self):
        anlegen, geschmack, groessen, _, _ = self.plane("Iso Whey Zero - 454 g", ["Lebkuchen"], "Limited Edition")
        self.assertEqual([n for _, n in anlegen], ["Iso Whey Zero (Limited Edition)"])
        self.assertEqual(geschmack, [])

    def test_unbekanntes_produkt_wird_angelegt(self):
        anlegen, geschmack, groessen, _, _ = self.plane("Voellig Neues Produkt XY - 60 Kapseln")
        self.assertEqual([n for _, n in anlegen], ["Voellig Neues Produkt XY"])

    def test_neue_groesse_haengt_am_hauptprodukt_nicht_an_einer_variante(self):
        # Iso Whey Platinum: Hauptprodukt #60 (908 g), Varianten 454 g, 1816 g, Sachet
        _, _, groessen, _, _ = self.plane("Iso Whey Platinum - 3000 g")
        self.assertEqual([(g["ziel"], g["groesse"]) for g in groessen], [("60", "3000 g")])

    def test_vorhandene_groesse_ohne_zuordnung_wird_verknuepft(self):
        # #438 L-Carnitine 1000 30 Tabletten gibt es, aber ohne Shop-Zuordnung
        anlegen, geschmack, groessen, _, zuordnen = self.plane("L-Carnitine 1000 - 30 Tabletten", ["Default Title"])
        self.assertEqual((anlegen, groessen), ([], []))
        self.assertEqual([z["ziel"] for z in zuordnen], ["438"])

    def test_fehlende_groesse_kommt_aus_dem_shop_titel(self):
        # Tribooster hat in der index.html keine Packungsgroesse; zugeordnet ist 60 Tabletten.
        # Dieselbe Groesse darf deshalb keine neue Variante werden.
        _, _, groessen, ignoriert, _ = self.plane("Tribooster - 60 Tabletten", ["Default Title"])
        self.assertEqual(groessen, [])
        self.assertEqual(len(ignoriert), 1)


if __name__ == "__main__":
    unittest.main()
