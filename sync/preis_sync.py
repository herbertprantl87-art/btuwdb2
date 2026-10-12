#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BTUWDB2 Preis-Sync v17 — Preise synchronisieren + neue Shop-Produkte aufnehmen
Neu in v18 (12.10.2026): Produktliste UNSERE auf den Stand der index.html
gebracht (vorher Stand vor dem 21.08.2026, dadurch liefen 35 Packungsgrößen
#413-#448 ohne Preisabgleich). MAPPING um 39 geprüfte Zuordnungen ergänzt,
6 Einträge zu entfernten Dubletten und 3 veraltete Ausnahmen gelöscht. Die Tests in tests/sync prüfen
künftig, dass UNSERE und MAPPING zur index.html passen.
Neu in v17 (Nachpflege Beschreibungen): fest eingebaute, zugeordnete Produkte
ohne Beschreibung bekommen die Shop-Beschreibung nachgetragen — notes (Kurz-
fassung), keyIngredients, Dosierung, wo vorhanden auch kcal/Protein pro Portion.
Es werden nur leere Felder gefüllt ("", "–", Dosierung "Laut Produktetikett");
vorhandene Handpflege und bestehende Overrides bleiben unangetastet. Der Schritt
läuft bei jedem Lauf mit und ist idempotent.
Neue Shop-Produkte werden vor der Übernahme geprüft:
  - Limited Edition (auch Collector's Edition) -> eigenes Produkt "Name (Limited Edition)"
  - nur ein neuer Geschmack zu einem bestehenden Produkt (gleicher Name, gleiche
    Größe) -> kein neues Produkt, der Geschmack wird beim bestehenden ergänzt
  - nur eine neue Packungsgröße (gleicher Name, andere Größe) -> kein neues
    Produkt, die Größe wird beim bestehenden ergänzt ("454 g / 2270 g")
  - sonst -> neues eigenes Produkt wie bisher
Ergänzt wird in den Feldern flavors und packageSize; bei fest eingebauten
Produkten über Overrides (die Seite kennt diese Felder seit Commit ba7ddee9).
Bereits automatisch übernommene Limited Editions werden beim nächsten Lauf
nachträglich umbenannt, sofern ihr Name noch unverändert ist.
Merkt sich in shop_bekannt.json, welche Shop-Produkte schon bekannt sind.
Beim allerersten Lauf wird nur der Ist-Stand als Basis gespeichert (keine Flut
von Alt-Produkten); ab dem zweiten Lauf gelten neu hinzugekommene Shop-Produkte
als "neu" und werden mit --write als eigene Produkte in die Datenbank übernommen.
Nutzung:
  python preis_sync.py                       -> Trockenlauf (zeigt nur an)
  python preis_sync.py --write               -> Änderungen in die Datenbank schreiben
  python preis_sync.py --vergiss "Text"      -> TEST: ein Shop-Produkt vergessen,
                                                es gilt dann als "neu" (mit --write
                                                kombinierbar, um die Übernahme zu testen)
"""
import json, re, sys, time, urllib.request, urllib.error

class _Tee:
    def __init__(self, f): self.f=f; self.stdout=sys.stdout
    def write(self,x): self.stdout.write(x); self.f.write(x)
    def flush(self): self.stdout.flush(); self.f.flush()
sys.stdout=_Tee(open("preis_sync_report.txt","w",encoding="utf-8"))

SHOP="https://shop.biotechusa.de"
UA={"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Accept":"application/json,text/html;q=0.9,*/*;q=0.8",
    "Accept-Language":"de-DE,de;q=0.9"}
SB_BASE="https://mejwpbahcmlkwajkymnj.supabase.co/rest/v1"
SB_KEY="eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Im1landwYmFoY21sa3dhamt5bW5qIiwicm9sZSI6ImFub24iLCJpYXQiOjE3Nzc4MzQ2OTAsImV4cCI6MjA5MzQxMDY5MH0.rzt-EiWxy8poy0vs00eEVvs-GYab9VOoiTAsrEScCrE"
SB_H={"apikey":SB_KEY,"Authorization":"Bearer "+SB_KEY,"Content-Type":"application/json"}

def http_json(url,headers=None,data=None,method="GET"):
    req=urllib.request.Request(url,headers=headers or UA,data=data,method=method)
    with urllib.request.urlopen(req,timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))

def load_shop():
    out={}; page=1
    while True:
        d=None
        for versuch in range(3):
            try:
                d=http_json(f"{SHOP}/products.json?limit=250&page={page}")
                break
            except urllib.error.HTTPError as e:
                if e.code in (403,429,503) and versuch<2:
                    print(f"  Shop antwortet mit HTTP {e.code} — warte 90 s und versuche es erneut ({versuch+2}/3)...")
                    time.sleep(90)
                else:
                    print(f"FEHLER: Shop antwortet mit HTTP {e.code}."); sys.exit(1)
        prods=d.get("products",[])
        if not prods: break
        for p in prods: out[p["id"]]=p
        print(f"  Seite {page}: {len(prods)} Produkte")
        page+=1; time.sleep(1.5)
    return out

UNSERE=json.loads('[{"id": 1, "name": "Iso Whey Zero", "price": 31, "packageSize": "454 g"}, {"id": 2, "name": "Iso Whey Zero Black", "price": 95.9, "packageSize": "1816 g"}, {"id": 3, "name": "Iso Whey Zero Clear", "price": 30.9, "packageSize": "400 g"}, {"id": 4, "name": "Protein Power", "price": 31.9, "packageSize": "500 g"}, {"id": 5, "name": "100% Pure Whey", "price": 47.9, "packageSize": "2000 g"}, {"id": 6, "name": "Beef Protein", "price": 26.9, "packageSize": "500 g"}, {"id": 7, "name": "Zero Bar", "price": 2.6, "packageSize": "1 Stk. (50 g)"}, {"id": 8, "name": "Protein Bar", "price": 2.6, "packageSize": "1 Stk. (70 g)"}, {"id": 9, "name": "100% Creatine Monohydrate", "price": 21.9, "packageSize": "300 g"}, {"id": 10, "name": "EAA ZERO", "price": 29.9, "packageSize": "350 g"}, {"id": 12, "name": "BCAA ZERO", "price": 29.9, "packageSize": "700 g"}, {"id": 13, "name": "BCAA 6000", "price": 21.5, "packageSize": "100 Tbl"}, {"id": 14, "name": "BCAA+B6", "price": 30.99, "packageSize": null}, {"id": 15, "name": "After", "price": 29.9, "packageSize": "420 g"}, {"id": 16, "name": "100% L-Glutamine", "price": 31.9, "packageSize": "500 g"}, {"id": 17, "name": "100% Instant L-Leucine", "price": 21.5, "packageSize": "277 g"}, {"id": 18, "name": "L-Carnitine 3000 Ampulle", "price": 2.7, "packageSize": "1 Amp. (25 ml)"}, {"id": 19, "name": "L-Carnitine 100.000 Liquid", "price": 34.9, "packageSize": "500 ml"}, {"id": 20, "name": "ALC", "price": 24.9, "packageSize": "60 Kapseln"}, {"id": 21, "name": "Black Blood CAF+", "price": 40.5, "packageSize": "300 g"}, {"id": 22, "name": "Black Blood NOX+", "price": 42.5, "packageSize": "340 g"}, {"id": 23, "name": "Amino Energy Zero with electrolytes", "price": 34.9, "packageSize": "360 g"}, {"id": 24, "name": "AAKG 1000", "price": 14.49, "packageSize": null}, {"id": 25, "name": "Beta Alanine", "price": 29.9, "packageSize": "300 g"}, {"id": 26, "name": "Citrulline Malate", "price": 28.9, "packageSize": "300 g"}, {"id": 27, "name": "Black Burn", "price": 40.5, "packageSize": "90 Kapseln"}, {"id": 28, "name": "Black Burn Getr\\u00e4nkepulver", "price": 45.9, "packageSize": "210 g"}, {"id": 29, "name": "Arthro Forte Gelenkschutz", "price": 36.5, "packageSize": "120 Tbl"}, {"id": 30, "name": "Arthro Forte Pack", "price": 45.9, "packageSize": null}, {"id": 31, "name": "Arthro Forte Getr\\u00e4nkepulver", "price": 37.9, "packageSize": "340 g"}, {"id": 32, "name": "Arthro Forte Liquid", "price": 37.5, "packageSize": "500 ml"}, {"id": 33, "name": "Marine Collagen Getr\\u00e4nkepulver", "price": 39.9, "packageSize": "240 g"}, {"id": 34, "name": "Collagen Pulver", "price": 31.9, "packageSize": "300 g"}, {"id": 35, "name": "Collagen Liquid", "price": 39.9, "packageSize": "1000 ml"}, {"id": 36, "name": "Clear Collagen Professional", "price": 39.9, "packageSize": "350 g"}, {"id": 37, "name": "One A Day-Multivitamin", "price": 21.5, "packageSize": "100 Tbl"}, {"id": 38, "name": "One-A-Day Professional", "price": 26.9, "packageSize": "240 g"}, {"id": 39, "name": "Multivitamin for Men", "price": 22.9, "packageSize": "60 Tbl"}, {"id": 40, "name": "Daily Pack", "price": 47.9, "packageSize": null}, {"id": 41, "name": "Active Woman", "price": 24.9, "packageSize": null}, {"id": 42, "name": "B-Complex", "price": 21.5, "packageSize": null}, {"id": 43, "name": "Ashwagandha", "price": 17.9, "packageSize": null}, {"id": 44, "name": "Ashwagandha KSM-66\\u00ae", "price": 22.9, "packageSize": null}, {"id": 45, "name": "Brutal Anadrol", "price": 32.9, "packageSize": null}, {"id": 46, "name": "Black Test", "price": 40.5, "packageSize": null}, {"id": 48, "name": "Hyper Mass", "price": 26.9, "packageSize": "1000 g"}, {"id": 49, "name": "Vegan Protein", "price": 26.9, "packageSize": "500 g"}, {"id": 50, "name": "Hydro Whey Zero", "price": 33.9, "packageSize": "454 g"}, {"id": 52, "name": "Super Burn", "price": 29.9, "packageSize": "120 Tbl"}, {"id": 53, "name": "Mega Burner", "price": 26.9, "packageSize": null}, {"id": 54, "name": "Liquid Amino", "price": 28.9, "packageSize": "1000 ml"}, {"id": 55, "name": "Mega Omega 3", "price": 29.9, "packageSize": "180 Softgels"}, {"id": 56, "name": "Ca D3 K2", "price": 15.9, "packageSize": "90 Kapseln"}, {"id": 57, "name": "Multivitamin For Men from organic sources", "price": 28.9, "packageSize": "60 Tbl"}, {"id": 58, "name": "Diet Shake", "price": 40.5, "packageSize": "720 g"}, {"id": 60, "name": "Iso Whey Platinum", "price": 44.9, "packageSize": "908 g"}, {"id": 61, "name": "Juicy Isolate", "price": 39.9, "packageSize": "500 g"}, {"id": 62, "name": "100% Pure Whey Natural", "price": 37.5, "packageSize": "1000 g"}, {"id": 63, "name": "Chunky Protein Bar", "price": 2.7, "packageSize": "1 Stk. (50 g)"}, {"id": 64, "name": "Crush Bar", "price": 3.7, "packageSize": "1 Stk. (64 g)"}, {"id": 65, "name": "Oat & Fruits", "price": 2, "packageSize": "1 Stk. (70 g)"}, {"id": 66, "name": "Vegan Protein Bar", "price": 2.7, "packageSize": "1 Stk. (50 g)"}, {"id": 67, "name": "Creatine pH-X", "price": 16.9, "packageSize": "90 Kapseln"}, {"id": 68, "name": "Tri Creatine Malate", "price": 26.9, "packageSize": "300 g"}, {"id": 69, "name": "CreaTor", "price": 24.9, "packageSize": "120 Kapseln"}, {"id": 70, "name": "Crea Zero", "price": 27.9, "packageSize": "320 g"}, {"id": 71, "name": "Mega Creatine", "price": 31.9, "packageSize": "306 g"}, {"id": 72, "name": "BCAA + Glutamine Zero", "price": 38.9, "packageSize": "480 g"}, {"id": 73, "name": "BCAA 8:1:1 ZERO", "price": 29.9, "packageSize": "250 g"}, {"id": 74, "name": "EAA", "price": 22.9, "packageSize": "200 Kapseln"}, {"id": 75, "name": "Mega Amino", "price": 22.9, "packageSize": null}, {"id": 76, "name": "Glutamine Zero", "price": 25.9, "packageSize": "300 g"}, {"id": 77, "name": "L-Tyrosine", "price": 22.9, "packageSize": null}, {"id": 78, "name": "L-Tryptophan", "price": 22.9, "packageSize": null}, {"id": 79, "name": "L-Lysine", "price": 22.9, "packageSize": null}, {"id": 80, "name": "ZMB6", "price": 15.9, "packageSize": null}, {"id": 81, "name": "Vitamin C 1000", "price": 15.9, "packageSize": "100 Tabletten"}, {"id": 82, "name": "Calcium Zinc Magnesium", "price": 15.9, "packageSize": null}, {"id": 83, "name": "Tribooster", "price": 22.9, "packageSize": null}, {"id": 84, "name": "Super Lipo", "price": 22.9, "packageSize": null}, {"id": 85, "name": "Hyaluronic & Collagen", "price": 26.9, "packageSize": null}, {"id": 86, "name": "Chondroitin Glucosamine", "price": 22.9, "packageSize": null}, {"id": 87, "name": "MSM + Vitamin C", "price": 14.9, "packageSize": "150 g"}, {"id": 88, "name": "Muscle Mass", "price": 25.9, "packageSize": "1000 g"}, {"id": 89, "name": "Carbox", "price": 14.9, "packageSize": "1000 g"}, {"id": 90, "name": "Cyclic Dextrin", "price": 29.9, "packageSize": "1000 g"}, {"id": 91, "name": "Supernova", "price": 31.9, "packageSize": "282 g"}, {"id": 92, "name": "IsoTonic", "price": 23.9, "packageSize": "600 g"}, {"id": 93, "name": "Fat-X", "price": 23.9, "packageSize": null}, {"id": 94, "name": "Thermo Drine", "price": 22.9, "packageSize": null}, {"id": 95, "name": "Thermo Drine Liquid", "price": 24.5, "packageSize": "500 ml"}, {"id": 96, "name": "Synephrine", "price": 22.9, "packageSize": null}, {"id": 97, "name": "HCA", "price": 22.9, "packageSize": null}, {"id": 98, "name": "Fiber Complex", "price": 22.9, "packageSize": null}, {"id": 99, "name": "Vegan Multivitamin", "price": 21.9, "packageSize": null}, {"id": 100, "name": "Multivitamin Brausetablette", "price": 22.9, "packageSize": null}, {"id": 101, "name": "L-Carnitine 1000", "price": 22.9, "packageSize": "60 Tabletten"}, {"id": 102, "name": "Peanut Butter", "price": 10.9, "packageSize": "400 g"}, {"id": 103, "name": "Protein Cream", "price": 13.9, "packageSize": "400 g"}, {"id": 104, "name": "Protein Pancake", "price": 31.9, "packageSize": "1000 g"}, {"id": 105, "name": "Zero Drops", "price": 8.5, "packageSize": "50 ml"}, {"id": 106, "name": "Taurine", "price": 22.9, "packageSize": null}, {"id": 107, "name": "HMB", "price": 22.9, "packageSize": null}, {"id": 108, "name": "Crispy Protein Bar", "price": 2.4, "packageSize": "1 Stk. (40 g)"}, {"id": 216, "name": "Protein Bar", "price": 1.7, "packageSize": "1 Stk. (35 g)"}, {"id": 217, "name": "Protein Max", "price": 1.8, "packageSize": "1 Stk. (45 g)"}, {"id": 218, "name": "BCAA Shot", "price": 3.1, "packageSize": "60 ml (1 Ampulle)"}, {"id": 219, "name": "Liquid BCAA", "price": 29.9, "packageSize": "1000 ml (33 Portionen)"}, {"id": 220, "name": "Glutamine Peptide", "price": 27.9, "packageSize": "180 Mega-Kapseln (20 Portionen)"}, {"id": 221, "name": "CA-HMB 3000", "price": 39.9, "packageSize": "270 g (90 Portionen)"}, {"id": 222, "name": "NAC", "price": 21.5, "packageSize": "60 Tabletten (60 Portionen)"}, {"id": 223, "name": "AAKG Shock", "price": 38.9, "packageSize": "1000 ml (105 Portionen)"}, {"id": 224, "name": "Thermo Shot", "price": 3.2, "packageSize": "60 ml (2 Portionen)"}, {"id": 225, "name": "Desert", "price": 26.9, "packageSize": "100 Kapseln (33 Portionen)"}, {"id": 226, "name": "Pyruvate", "price": 17.9, "packageSize": "90 Kapseln (30 Portionen)"}, {"id": 227, "name": "Chromium Picolinate", "price": 12.9, "packageSize": "60 Tabletten (60 Portionen)"}, {"id": 228, "name": "Glucomannan + Chromium", "price": 32.9, "packageSize": "225 g (30 Portionen)"}, {"id": 229, "name": "L-Carnitine Effervescent", "price": 6.7, "packageSize": "20 Brausetabletten (20 Portionen)"}, {"id": 230, "name": "L-Carnitine + Chrome Liquid", "price": 22.5, "packageSize": "500 ml (33 Portionen)"}, {"id": 231, "name": "L-Carnitine + Chrome Caps", "price": 17.9, "packageSize": "60 Kapseln (30 Portionen)"}, {"id": 232, "name": "Eggshell Membrane", "price": 29.9, "packageSize": "60 Mega-Kapseln (60 Portionen)"}, {"id": 233, "name": "MSM Chondroitin Glucosamine", "price": 22.5, "packageSize": "60 Tabletten (30 Portionen)"}, {"id": 234, "name": "GH", "price": 24.5, "packageSize": "120 Kapseln (30 Portionen)"}, {"id": 235, "name": "Panax Ginseng", "price": 17.9, "packageSize": "60 Kapseln (60 Portionen)"}, {"id": 236, "name": "Saw Palmetto", "price": 21.5, "packageSize": "60 Mega-Kapseln (30 Portionen)"}, {"id": 237, "name": "Fenugreek", "price": 14.9, "packageSize": "60 Mega-Kapseln (30 Portionen)"}, {"id": 238, "name": "Aquamin Calcium", "price": 22.9, "packageSize": "240 g"}, {"id": 239, "name": "Omega-3 Triglycerides", "price": 15.9, "packageSize": "60 Softgelkapseln (30 Portionen)"}, {"id": 240, "name": "One-A-Day Kids", "price": 17.9, "packageSize": "90 Kautabletten (90 Portionen)"}, {"id": 241, "name": "Vitabolic", "price": 13.9, "packageSize": "30 Tabletten (30 Portionen)"}, {"id": 242, "name": "Vitamin Complex", "price": 11.9, "packageSize": "60 Kapseln (60 Portionen)"}, {"id": 243, "name": "Vitamin C 500", "price": 14.9, "packageSize": "120 Kautabletten (120 Portionen)"}, {"id": 244, "name": "Vitamin C Effervescent", "price": 6.9, "packageSize": "20 Brausetabletten"}, {"id": 245, "name": "Magnesium+Chelate", "price": 11.9, "packageSize": "60 Kapseln (60 Portionen)"}, {"id": 246, "name": "Neuro", "price": 23.9, "packageSize": "60 Kapseln (30 Portionen)"}, {"id": 247, "name": "Men\'s Arginine", "price": 22.9, "packageSize": "90 Kapseln (15 Portionen)"}, {"id": 248, "name": "Valeriana Forte", "price": 19.5, "packageSize": "60 Tabletten (20\\u201330 Portionen)"}, {"id": 249, "name": "Vitamin E", "price": 17.9, "packageSize": "100 Softgelkapseln (100 Portionen)"}, {"id": 250, "name": "Night", "price": 21.5, "packageSize": "60 Kapseln (30 Portionen)"}, {"id": 251, "name": "Q10 Coenzyme", "price": 23.5, "packageSize": "60 Kapseln (60 Portionen)"}, {"id": 252, "name": "H2O Q10", "price": 19.5, "packageSize": "60 Kapseln (60 Portionen)"}, {"id": 253, "name": "Digestion & Metabolism", "price": 12.9, "packageSize": "60 Tabletten (30 Portionen)"}, {"id": 254, "name": "Pumpkin Seed Oil", "price": 12.9, "packageSize": "60 Softgelkapseln (60 Portionen)"}, {"id": 255, "name": "Immune+Biotiq", "price": 25.5, "packageSize": "36 Kapseln (18 Portionen)"}, {"id": 256, "name": "Biotiq C", "price": 28.9, "packageSize": "36 Kapseln (36 Portionen)"}, {"id": 257, "name": "Ginkgo Biloba", "price": 21.5, "packageSize": "90 Tabletten (90 Portionen)"}, {"id": 258, "name": "Green Coffee", "price": 22.9, "packageSize": "120 Kapseln (60 Portionen)"}, {"id": 259, "name": "Resveratrol", "price": 28.9, "packageSize": "60 Kapseln (60 Portionen)"}, {"id": 260, "name": "Spirulina", "price": 10.5, "packageSize": "100 Tabletten (12 Portionen)"}, {"id": 261, "name": "Cranberry Complex", "price": 23.9, "packageSize": "60 Tabletten (30 Portionen)"}, {"id": 262, "name": "Clear Collagen", "price": 31.9, "packageSize": "308 g (28 Portionen)"}, {"id": 263, "name": "Collagen & Hyaluronic Powder", "price": 22.9, "packageSize": "300 g (20 Portionen)"}, {"id": 264, "name": "Collagen & Hyaluronic Caps", "price": 10.9, "packageSize": "30 Kapseln (30 Portionen)"}, {"id": 265, "name": "Protein Muesli Bar", "price": 1.3, "packageSize": "1 Stk. (30 g)"}, {"id": 266, "name": "Nuts & Fruits Bar", "price": 1.5, "packageSize": "1 Stk. (40 g)"}, {"id": 267, "name": "Nuts & Honey Bar", "price": 1.5, "packageSize": "1 Stk. (35 g)"}, {"id": 268, "name": "Oat & Nuts Bar", "price": 2, "packageSize": "1 Stk. (70 g)"}, {"id": 269, "name": "Protein Tortilla Chips", "price": 3.5, "packageSize": "50 g"}, {"id": 270, "name": "Protein Crispies", "price": 34.9, "packageSize": "450 g (15 Portionen)"}, {"id": 271, "name": "Fiber Mix", "price": 17.9, "packageSize": "225 g (15 Portionen)"}, {"id": 272, "name": "Instant Oats", "price": 10.9, "packageSize": "1000 g (10 Portionen)"}, {"id": 273, "name": "Protein Brownie", "price": 21.9, "packageSize": "600 g (5 Portionen)"}, {"id": 274, "name": "Protein Ice Cream", "price": 20.5, "packageSize": "500 g (10 Portionen)"}, {"id": 275, "name": "Hot Chocolate", "price": 22.9, "packageSize": "450 g (15 Portionen)"}, {"id": 276, "name": "Multi Hypotonic", "price": 28.9, "packageSize": "1000 ml (100 Portionen)"}, {"id": 277, "name": "Energy Gel", "price": 2.2, "packageSize": "40 g (1 Portion)"}, {"id": 278, "name": "Energy Shot", "price": 2.2, "packageSize": "25 ml Ampulle (1 Portion)"}, {"id": 279, "name": "Recovery Gel", "price": 2.2, "packageSize": "40 g (1 Portion)"}, {"id": 280, "name": "Protein Coffee", "price": 14.9, "packageSize": "450 g (15 Portionen)"}, {"id": 109, "name": "Vitamin D3", "price": 14.9, "packageSize": "60 Tabletten"}, {"id": 110, "name": "Magnesium Bisglycinate", "price": 15.9, "packageSize": null}, {"id": 111, "name": "Liposomal Vitamin C", "price": 13.9, "packageSize": null}, {"id": 112, "name": "Hair, Skin & Nails", "price": 21.9, "packageSize": null}, {"id": 113, "name": "Rhodiola", "price": 26.9, "packageSize": null}, {"id": 114, "name": "Mushroom Complex", "price": 16.9, "packageSize": null}, {"id": 115, "name": "Milk Thistle", "price": 22.9, "packageSize": null}, {"id": 116, "name": "Zenaya", "price": 21.5, "packageSize": null}, {"id": 117, "name": "Liquid Curcuma", "price": 21.5, "packageSize": "30 Kapseln"}, {"id": 118, "name": "Maca", "price": 19.9, "packageSize": null}, {"id": 119, "name": "L-Arginin", "price": 22.9, "packageSize": "90 Megakapseln"}, {"id": 201, "name": "Anabole Androgene Steroide (AAS)", "price": 22.9, "packageSize": null}, {"id": 202, "name": "SARMs (Selective Androgen Receptor Modulators)", "price": 22.9, "packageSize": null}, {"id": 203, "name": "Peptid-Hormone (EPO, HCG, LH, Insulin)", "price": 22.9, "packageSize": null}, {"id": 204, "name": "Clenbuterol & Verbotene Beta-2-Agonisten", "price": 22.9, "packageSize": null}, {"id": 205, "name": "Diuretika & Maskierungsmittel", "price": 22.9, "packageSize": null}, {"id": 206, "name": "Verbotene Stimulanzien (WADA S6)", "price": 22.9, "packageSize": null}, {"id": 211, "name": "HGH / Somatotropin (Wachstumshormon)", "price": 22.9, "packageSize": null}, {"id": 212, "name": "GH-Releasing-Peptide (GHRP & GHRH-Analoga)", "price": 22.9, "packageSize": null}, {"id": 213, "name": "MK-677 / Ibutamoren (Orales GH-Sekretagogum)", "price": 22.9, "packageSize": null}, {"id": 214, "name": "IGF-1, Mechano-Wachstumsfaktoren & Analoga", "price": 22.9, "packageSize": null}, {"id": 215, "name": "Legale Alternativen \\u2013 Was BTU f\\u00fcr GH & Testosteron bietet", "price": 22.9, "packageSize": null}, {"id": 121, "name": "Pump Caffeine Free", "price": 30.9, "packageSize": "330 g"}, {"id": 123, "name": "Black Blood Shot", "price": 3.1, "packageSize": "1 Amp. (60 ml)"}, {"id": 124, "name": "Caffeine + Taurine", "price": 22.9, "packageSize": null}, {"id": 125, "name": "Creatine Candy", "price": 27.9, "packageSize": "240 Stk."}, {"id": 126, "name": "Creatine Zero Effervescent", "price": 22.9, "packageSize": null}, {"id": 129, "name": "TST + GH", "price": 34.9, "packageSize": null}, {"id": 130, "name": "Tribulus Maximus", "price": 28.9, "packageSize": null}, {"id": 131, "name": "Zinc Duo", "price": 10.5, "packageSize": null}, {"id": 132, "name": "Multi Mineral Complex", "price": 13.9, "packageSize": null}, {"id": 133, "name": "Multivitamin For Women", "price": 22.9, "packageSize": null}, {"id": 134, "name": "One-A-Day 50+ For Men", "price": 22.9, "packageSize": null}, {"id": 135, "name": "Iron Professional", "price": 22.9, "packageSize": null}, {"id": 136, "name": "Lifelong 360\\u00b0", "price": 37.5, "packageSize": null}, {"id": 137, "name": "MultiSalt", "price": 22.9, "packageSize": null}, {"id": 138, "name": "CLA 400", "price": 14.9, "packageSize": null}, {"id": 139, "name": "Carni Elite", "price": 29.9, "packageSize": "10 Amp. \\u00d7 25 ml"}, {"id": 140, "name": "L-Carnitine Drink Powder", "price": 30.9, "packageSize": "150 g"}, {"id": 141, "name": "Liver Aid", "price": 22.9, "packageSize": null}, {"id": 142, "name": "Shilajit", "price": 22.9, "packageSize": null}, {"id": 143, "name": "GABA", "price": 22.9, "packageSize": null}, {"id": 144, "name": "Zero Sauce", "price": 8.5, "packageSize": "350 ml"}, {"id": 145, "name": "Zero Syrup", "price": 8.5, "packageSize": "320 ml"}, {"id": 146, "name": "Flavour Power", "price": 16.9, "packageSize": "160 g"}, {"id": 147, "name": "Rice Pudding", "price": 16.9, "packageSize": "1000 g"}, {"id": 148, "name": "Protein Oatmeal", "price": 21.9, "packageSize": "1000 g"}, {"id": 149, "name": "Oat & Fruits Zero", "price": 2, "packageSize": "1 Stk. (70 g)"}, {"id": 150, "name": "Energy Gel PRO", "price": 2.4, "packageSize": "1 Stk. (40 g)"}, {"id": 151, "name": "AAKG 7800", "price": 2.7, "packageSize": "25 ml"}, {"id": 152, "name": "Ashwa+", "price": 22.9, "packageSize": null}, {"id": 153, "name": "GH Hormon Regulator", "price": 22.9, "packageSize": null}, {"id": 154, "name": "Magna Shot", "price": 2.7, "packageSize": "1 Amp. (25 ml)"}, {"id": 155, "name": "Whey Shake", "price": 31.9, "packageSize": "1000 g"}, {"id": 157, "name": "100% Creatine Monohydrate Yuzu", "price": 23.9, "packageSize": "300 g"}, {"id": 161, "name": "Wave Shaker", "price": 6.3, "packageSize": null}, {"id": 162, "name": "Wave Plus Shaker", "price": 10.9, "packageSize": null}, {"id": 163, "name": "Wave Plus Compact Shaker", "price": 8.9, "packageSize": null}, {"id": 164, "name": "Wave+ Nano Shaker", "price": 6.3, "packageSize": null}, {"id": 165, "name": "Gallon 2200 ml", "price": 12.9, "packageSize": null}, {"id": 158, "name": "Iso Whey Zero Natural", "price": 51.9, "packageSize": "908 g"}, {"id": 159, "name": "Micellar Casein", "price": 40.9, "packageSize": "908 g"}, {"id": 281, "name": "Mug Cake", "price": 8.19, "packageSize": "7x45 g"}, {"id": 283, "name": "MagnaShot", "price": 23.4, "packageSize": "20x25 ml"}, {"id": 291, "name": "ALA Alpha Lipoic Acid", "price": 16.9, "packageSize": "50 caps"}, {"id": 295, "name": "Immune + Biotiq", "price": 25.5, "packageSize": "36 caps"}, {"id": 296, "name": "Melatonin", "price": 13.9, "packageSize": "90 tbl"}, {"id": 306, "name": "Bottle BioTech 750ml", "price": 6.9, "packageSize": "750 ml"}, {"id": 307, "name": "Shaker FC Barcelona", "price": 6.3, "packageSize": "600 ml"}, {"id": 308, "name": "NEU! Shaker Dubai Chocolate", "price": 6.3, "packageSize": "600 ml"}, {"id": 309, "name": "NEU! Shaker Menta Lime", "price": 6.3, "packageSize": "600 ml"}, {"id": 310, "name": "AMY women leggings", "price": null, "packageSize": "\\u2013"}, {"id": 311, "name": "ASA men tank top", "price": null, "packageSize": "\\u2013"}, {"id": 312, "name": "AVA women knitted top", "price": null, "packageSize": "\\u2013"}, {"id": 313, "name": "BLOOM women long-sleeve t-shirt", "price": null, "packageSize": "\\u2013"}, {"id": 314, "name": "ARENA women jogger", "price": null, "packageSize": "\\u2013"}, {"id": 315, "name": "BACKLESS MEDIUM SUPPORT SPORTS BRA", "price": null, "packageSize": "\\u2013"}, {"id": 316, "name": "BELLA female sports bra with cross strap", "price": null, "packageSize": "\\u2013"}, {"id": 317, "name": "BOOTY BOOST SCRUNCH LEGGINGS", "price": null, "packageSize": "\\u2013"}, {"id": 318, "name": "BOW women bra", "price": null, "packageSize": "\\u2013"}, {"id": 319, "name": "Body adapt women long jumpsuit", "price": null, "packageSize": "\\u2013"}, {"id": 320, "name": "CLARA female sports bra with mesh", "price": null, "packageSize": "\\u2013"}, {"id": 321, "name": "CLARA women top", "price": null, "packageSize": "\\u2013"}, {"id": 322, "name": "COURT women sportsbra", "price": null, "packageSize": "\\u2013"}, {"id": 323, "name": "CROSSOVER SEAMLESS LIFT UP LEGGINGS", "price": null, "packageSize": "\\u2013"}, {"id": 324, "name": "Crossover women shorts", "price": null, "packageSize": "\\u2013"}, {"id": 325, "name": "DERBY men sweater", "price": null, "packageSize": "\\u2013"}, {"id": 326, "name": "DEUCE women short", "price": null, "packageSize": "\\u2013"}, {"id": 327, "name": "DORA women tank top", "price": null, "packageSize": "\\u2013"}, {"id": 328, "name": "DWAYNE men sweater", "price": null, "packageSize": "\\u2013"}, {"id": 329, "name": "BioTechUSA Face Mask", "price": null, "packageSize": "\\u2013"}, {"id": 330, "name": "GARY men t-shirt", "price": null, "packageSize": "\\u2013"}, {"id": 331, "name": "GEAR women tank top", "price": null, "packageSize": "\\u2013"}, {"id": 332, "name": "GLADYS women sweater", "price": null, "packageSize": "\\u2013"}, {"id": 333, "name": "GRANDSLAM women top", "price": null, "packageSize": "\\u2013"}, {"id": 334, "name": "HURDLE women sportsbra", "price": null, "packageSize": "\\u2013"}, {"id": 335, "name": "JOHNNY male bodybuilding tank top", "price": null, "packageSize": "\\u2013"}, {"id": 336, "name": "KENJI men short", "price": null, "packageSize": "\\u2013"}, {"id": 337, "name": "LACROSSE women leggings", "price": null, "packageSize": "\\u2013"}, {"id": 338, "name": "LANE women short", "price": null, "packageSize": "\\u2013"}, {"id": 339, "name": "LAYLA women sweater", "price": null, "packageSize": "\\u2013"}, {"id": 340, "name": "LEAGUE women crop-sweater", "price": null, "packageSize": "\\u2013"}, {"id": 341, "name": "LUCY women full-zip hoodie", "price": null, "packageSize": "\\u2013"}, {"id": 342, "name": "MATHEO men sweater", "price": null, "packageSize": "\\u2013"}, {"id": 343, "name": "MEDIUM SUPPORT PADDED TOP", "price": null, "packageSize": "\\u2013"}, {"id": 344, "name": "MELANIE female leggings", "price": null, "packageSize": "\\u2013"}, {"id": 345, "name": "RUSH men knitted t-shirt", "price": null, "packageSize": "\\u2013"}, {"id": 346, "name": "SEAMLESS LONG-SLEEVE CROP TOP", "price": null, "packageSize": "\\u2013"}, {"id": 347, "name": "SHANIQUE women hoodie", "price": null, "packageSize": "\\u2013"}, {"id": 348, "name": "SHAPING SEAMLESS LIFT UP LEGGINGS", "price": null, "packageSize": "\\u2013"}, {"id": 349, "name": "SIDEBACK men leggings", "price": null, "packageSize": "\\u2013"}, {"id": 350, "name": "SMASH women jacket", "price": null, "packageSize": "\\u2013"}, {"id": 351, "name": "Seamless shaping women short jumpsuit", "price": null, "packageSize": "\\u2013"}, {"id": 352, "name": "Shaping women biker shorts", "price": null, "packageSize": "\\u2013"}, {"id": 353, "name": "TERRY men sweater", "price": null, "packageSize": "\\u2013"}, {"id": 354, "name": "THOMAS men jacket", "price": null, "packageSize": "\\u2013"}, {"id": 355, "name": "ZANE men jogger", "price": null, "packageSize": "\\u2013"}, {"id": 356, "name": "basic oversized men\'s t-shirt", "price": null, "packageSize": "\\u2013"}, {"id": 357, "name": "women OVERSIZED t-shirt", "price": null, "packageSize": "\\u2013"}, {"id": 358, "name": "BODYBUILDING leather belt", "price": 28.9, "packageSize": "\\u2013"}, {"id": 359, "name": "FITNESS belt with velcro", "price": 19.9, "packageSize": "\\u2013"}, {"id": 360, "name": "JAKE uniszex gloves", "price": 17.9, "packageSize": "\\u2013"}, {"id": 361, "name": "KYLE uniszex leather gloves with wrist grip", "price": 25.9, "packageSize": "\\u2013"}, {"id": 362, "name": "MARY women\'s leather gloves with wrist grip", "price": 19.9, "packageSize": "\\u2013"}, {"id": 363, "name": "POWERLIFTING leather belt", "price": 36.9, "packageSize": "\\u2013"}, {"id": 364, "name": "ROY men gloves", "price": 10.9, "packageSize": "\\u2013"}, {"id": 365, "name": "TORONTO uniszex leather gloves", "price": 20.9, "packageSize": "\\u2013"}, {"id": 366, "name": "TRACY women\'s gloves", "price": 15.9, "packageSize": "\\u2013"}, {"id": 367, "name": "Uniszex Grip pad", "price": 12.9, "packageSize": "\\u2013"}, {"id": 368, "name": "Uniszex Knee wraps", "price": 15.9, "packageSize": "200 cm"}, {"id": 369, "name": "Uniszex Lifting straps", "price": 8.9, "packageSize": "\\u2013"}, {"id": 370, "name": "Uniszex Wrist wraps with velcro", "price": 10.9, "packageSize": "\\u2013"}, {"id": 371, "name": "Pillbox Biotech", "price": 4.1, "packageSize": "\\u2013"}, {"id": 372, "name": "Towel BioTech", "price": 11.9, "packageSize": "100\\u00d750 cm"}, {"id": 373, "name": "Iso Whey Zero Clear", "price": 2.99, "packageSize": "25 g (Sachet)"}, {"id": 374, "name": "Iso Whey Zero", "price": 1.33, "packageSize": "25 g (Sachet)"}, {"id": 375, "name": "Iso Whey Zero", "price": 90.9, "packageSize": "1816 g"}, {"id": 379, "name": "Hydro Whey Zero", "price": 63.5, "packageSize": "1816 g"}, {"id": 380, "name": "Iso Whey Platinum", "price": 1.28, "packageSize": "22,5 g (Sachet)"}, {"id": 381, "name": "Iso Whey Platinum", "price": 61.9, "packageSize": "1816 g"}, {"id": 382, "name": "Vegan Protein", "price": 1.17, "packageSize": "25 g (Sachet)"}, {"id": 383, "name": "Vegan Protein", "price": 74.9, "packageSize": "2000 g"}, {"id": 384, "name": "Protein Power", "price": 31.9, "packageSize": "1000 g"}, {"id": 385, "name": "Protein Power", "price": 84.9, "packageSize": "4000 g"}, {"id": 386, "name": "Micellar Casein", "price": 74.9, "packageSize": "2270 g"}, {"id": 387, "name": "Beef Protein", "price": 1.28, "packageSize": "30 g (Sachet)"}, {"id": 388, "name": "Beef Protein", "price": 79.9, "packageSize": "1816 g"}, {"id": 389, "name": "Hyper Mass", "price": 56.9, "packageSize": "2270 g"}, {"id": 390, "name": "Muscle Mass", "price": 69.9, "packageSize": "4000 g"}, {"id": 391, "name": "100% Creatine Monohydrate", "price": 31.9, "packageSize": "500 g"}, {"id": 413, "name": "100% Creatine Monohydrate", "price": 22.5, "packageSize": "300 g aromatisiert"}, {"id": 392, "name": "100% Creatine Monohydrate", "price": 64.9, "packageSize": "1000 g"}, {"id": 393, "name": "Creatine pH-X", "price": 28.9, "packageSize": "210 Kapseln"}, {"id": 394, "name": "Mega Creatine", "price": 59.9, "packageSize": "120 Kapseln"}, {"id": 395, "name": "BCAA ZERO", "price": 29.9, "packageSize": "360 g"}, {"id": 396, "name": "EAA ZERO", "price": 1.17, "packageSize": "14 g (Sachet)"}, {"id": 397, "name": "EAA ZERO", "price": 19.9, "packageSize": "182 g"}, {"id": 398, "name": "Black Blood CAF+", "price": 1.25, "packageSize": "15 g (Sachet)"}, {"id": 399, "name": "Black Blood NOX+", "price": 1.33, "packageSize": "20 g (Sachet)"}, {"id": 400, "name": "Nitrox Therapy", "price": 1.17, "packageSize": "17 g (Sachet)"}, {"id": 401, "name": "Pump Caffeine Free", "price": 1.28, "packageSize": "11 g (Sachet)"}, {"id": 402, "name": "IsoTonic", "price": 0.8, "packageSize": "30 g (Sachet)"}, {"id": 404, "name": "Diet Shake", "price": 1.28, "packageSize": "30 g (Sachet)"}, {"id": 405, "name": "Protein Pancake", "price": 2.99, "packageSize": "40 g (Sachet)"}, {"id": 408, "name": "Iso Whey Zero", "price": 51.9, "packageSize": "908 g"}, {"id": 409, "name": "Nitrox Therapy", "price": 29.9, "packageSize": "340 g"}, {"id": 410, "name": "Iso Whey Platinum", "price": 17.9, "packageSize": "454 g"}, {"id": 414, "name": "Iso Whey Zero Black", "price": 3.2, "packageSize": "30 g (Sachet)"}, {"id": 415, "name": "Iso Whey Zero Black", "price": 56.5, "packageSize": "908 g"}, {"id": 416, "name": "100% Pure Whey", "price": 18.9, "packageSize": "400 g"}, {"id": 417, "name": "100% Pure Whey", "price": 36.9, "packageSize": "900 g"}, {"id": 419, "name": "100% Pure Whey", "price": 2.7, "packageSize": "28 g (Sachet)"}, {"id": 420, "name": "BCAA ZERO", "price": 2.7, "packageSize": "9 g (Sachet)"}, {"id": 421, "name": "BCAA+B6", "price": 16.9, "packageSize": "100 Tabletten"}, {"id": 422, "name": "BCAA+B6", "price": 28.9, "packageSize": "200 Tabletten"}, {"id": 423, "name": "100% L-Glutamine", "price": 21.5, "packageSize": "240 g"}, {"id": 424, "name": "Citrulline Malate", "price": 24.9, "packageSize": "90 Megakapseln"}, {"id": 425, "name": "Clear Collagen Professional", "price": 2.7, "packageSize": "25 g (Sachet)"}, {"id": 426, "name": "Hyper Mass", "price": 2.7, "packageSize": "65 g (Sachet)"}, {"id": 427, "name": "Hyper Mass", "price": 83.9, "packageSize": "4000 g"}, {"id": 428, "name": "Hyper Mass", "price": 129.9, "packageSize": "6800 g"}, {"id": 429, "name": "Liquid Amino", "price": 1.9, "packageSize": "25 ml (Ampulle)"}, {"id": 430, "name": "Mega Omega 3", "price": 19.5, "packageSize": "90 Softgel-Kapseln"}, {"id": 431, "name": "100% Pure Whey Natural", "price": 18.9, "packageSize": "400 g"}, {"id": 432, "name": "100% Pure Whey Natural", "price": 36.9, "packageSize": "900 g"}, {"id": 433, "name": "100% Pure Whey Natural", "price": 72.9, "packageSize": "2000 g"}, {"id": 434, "name": "Mega Amino", "price": 13.9, "packageSize": "100 Tabletten"}, {"id": 435, "name": "Mega Amino", "price": 30.9, "packageSize": "300 Tabletten"}, {"id": 436, "name": "Vitamin C 1000", "price": 9.5, "packageSize": "30 Tabletten"}, {"id": 437, "name": "Vitamin C 1000", "price": 33.9, "packageSize": "250 Tabletten"}, {"id": 438, "name": "L-Carnitine 1000", "price": 16.9, "packageSize": "30 Tabletten"}, {"id": 439, "name": "Peanut Butter", "price": 15.9, "packageSize": "1000 g"}, {"id": 440, "name": "Protein Cream", "price": 10.9, "packageSize": "200 g"}, {"id": 441, "name": "Vitamin D3", "price": 22.9, "packageSize": "120 Tabletten"}, {"id": 443, "name": "L-Arginin", "price": 33.9, "packageSize": "300 g"}, {"id": 444, "name": "Carni Elite", "price": 29.9, "packageSize": "90 Megakapseln"}, {"id": 445, "name": "Rice Pudding", "price": 33.9, "packageSize": "3000 g"}, {"id": 446, "name": "Whey Shake", "price": 16.9, "packageSize": "500 g"}, {"id": 447, "name": "Whey Shake", "price": 1.9, "packageSize": "25 g (Sachet)"}, {"id": 448, "name": "Nitrox Therapy", "price": 46.9, "packageSize": "680 g"}]')
MAPPING=json.loads('{"1": {"shop_product_id": 15029251637574, "shop_title": "Iso Whey Zero Proteinpulver - 454 g"}, "2": {"shop_product_id": 15020049760582, "shop_title": "Iso Whey Zero Black Getr\\u00e4nkepulver auf Basis von Molkeproteinisolat - 1816 g"}, "3": {"shop_product_id": 15402146824518, "shop_title": "Iso Whey Clear - 400 g"}, "4": {"shop_product_id": 7312247980205, "shop_title": "Protein Power - 500 g"}, "5": {"shop_product_id": 15406794670406, "shop_title": "100% Pure Whey - 2000 g"}, "6": {"shop_product_id": 487100907562, "shop_title": "Beef Protein - 500 g"}, "7": {"shop_product_id": 487103070250, "shop_title": "Zero Bar - 50 g"}, "8": {"shop_product_id": 4423745306666, "shop_title": "Protein Bar Protein-Riegel - 70 g"}, "9": {"shop_product_id": 487074201642, "shop_title": "100% Creatine Monohydrate - 300 g Ohne Geschmack"}, "10": {"shop_product_id": 15536573514054, "shop_title": "EAA ZERO - 350 g Mint-Lime"}, "12": {"shop_product_id": 1970338529322, "shop_title": "BCAA ZERO Aminos\\u00e4uren Pulver - 700 g"}, "13": {"shop_product_id": 487080460330, "shop_title": "BCAA 6000 - 100 Tabletten"}, "14": {"shop_product_id": 487070040106, "shop_title": "BCAA+B6 - 340 Tabletten"}, "15": {"shop_product_id": 1970335678506, "shop_title": "After - 420 g"}, "16": {"shop_product_id": 487071219754, "shop_title": "100% L-Glutamine - 500 g"}, "17": {"shop_product_id": 7168336363693, "shop_title": "100% Instant L-Leucine - 277 g"}, "19": {"shop_product_id": 487080493098, "shop_title": "L-Carnitine 100.000 - 500 ml"}, "20": {"shop_product_id": 487108804650, "shop_title": "ALC - 60 Kapseln"}, "21": {"shop_product_id": 15309522403654, "shop_title": "Black Blood CAF+ - 300 g"}, "22": {"shop_product_id": 487110246442, "shop_title": "Black Blood NOX+ - 340 g"}, "23": {"shop_product_id": 4378983792682, "shop_title": "Amino Energy Zero with electrolytes - 360 g"}, "24": {"shop_product_id": 487069646890, "shop_title": "AAKG 1000 - 100 Tabletten"}, "25": {"shop_product_id": 487085146154, "shop_title": "Beta Alanine - 300 g"}, "26": {"shop_product_id": 8901910987078, "shop_title": "Citrulline Malate - 300 g unaromatisiert"}, "27": {"shop_product_id": 4344681988138, "shop_title": "Black Burn - 90 Megakapseln"}, "28": {"shop_product_id": 4497400660010, "shop_title": "Black Burn Getr\\u00e4nkepulver - 210 g"}, "29": {"shop_product_id": 7157157462189, "shop_title": "Arthro Forte Gelenkschutz - 120 Tabletten"}, "30": {"shop_product_id": 487065681962, "shop_title": "Arthro Forte Pack - 30 Pakete"}, "31": {"shop_product_id": 7157155168429, "shop_title": "Arthro Forte Getr\\u00e4nkepulver - 340 g Pulver"}, "32": {"shop_product_id": 7157156610221, "shop_title": "Arthro Forte Liquid - 500 ml"}, "33": {"shop_product_id": 8363747836230, "shop_title": "Marine Collagen Getr\\u00e4nkepulver - 240 g"}, "34": {"shop_product_id": 1970334302250, "shop_title": "Collagen - aromatisiertes Pulver - 300g"}, "35": {"shop_product_id": 4555961106474, "shop_title": "Collagen Liquid - 1000 ml"}, "36": {"shop_product_id": 7331417915565, "shop_title": "Clear Collagen Professional Getr\\u00e4nkepulver - 350 g"}, "37": {"shop_product_id": 487095795754, "shop_title": "One A Day-Multivitamin - 100 Tabletten"}, "38": {"shop_product_id": 6934995796141, "shop_title": "One-A-Day Professional Getr\\u00e4nkepulver - 240 g"}, "39": {"shop_product_id": 487075315754, "shop_title": "Multivitamin for Men - 60 Tabletten"}, "40": {"shop_product_id": 487070629930, "shop_title": "Daily Pack - 30 P\\u00e4ckchen"}, "41": {"shop_product_id": 487111098410, "shop_title": "Active Woman - 60 Tabletten"}, "42": {"shop_product_id": 4331712544810, "shop_title": "B-Complex - 60 Kapseln"}, "43": {"shop_product_id": 4381245866026, "shop_title": "Ashwagandha - 60 Kapseln"}, "44": {"shop_product_id": 15429122785606, "shop_title": "Ashwagandha KSM-66\\u00ae - 60 Kapseln"}, "45": {"shop_product_id": 487096025130, "shop_title": "Brutal Anadrol - Neue Formel \\u2013 90 Megakapseln"}, "46": {"shop_product_id": 1970334859306, "shop_title": "Black Test - 90 Megakapseln"}, "48": {"shop_product_id": 487116079146, "shop_title": "Hyper Mass - 1000 g"}, "49": {"shop_product_id": 1970334433322, "shop_title": "Vegan Protein - 500 g"}, "50": {"shop_product_id": 1970338365482, "shop_title": "Hydro Whey Zero - 454 g"}, "52": {"shop_product_id": 15099565048134, "shop_title": "Super Burn - 120 Tabletten"}, "53": {"shop_product_id": 487109525546, "shop_title": "Mega Burner - 90 Kapseln"}, "54": {"shop_product_id": 487078920234, "shop_title": "Liquid Amino - 1000 ml"}, "55": {"shop_product_id": 4339161038890, "shop_title": "Mega Omega 3 - 180 Softgel Kapseln"}, "56": {"shop_product_id": 4540259762218, "shop_title": "Ca D3 K2 - 90 Kapseln"}, "57": {"shop_product_id": 14974052008262, "shop_title": "Multivitamin For Men from organic sources - 60 Tabletten"}, "58": {"shop_product_id": 6899333267629, "shop_title": "Diet Shake - 720 g"}, "60": {"shop_product_id": 15250843664710, "shop_title": "Iso Whey Platinum - 908 g"}, "61": {"shop_product_id": 7124561821869, "shop_title": "Juicy Isolate erfrischendes Getr\\u00e4nkepulver - 500 g"}, "63": {"shop_product_id": 15087356805446, "shop_title": "Chunky Protein Proteinriegel - 50 g"}, "64": {"shop_product_id": 1970334924842, "shop_title": "Crush Bar - 64 g"}, "65": {"shop_product_id": 1970346688554, "shop_title": "Oat&Fruit Haferriegel - 70 g"}, "66": {"shop_product_id": 6260553285805, "shop_title": "Vegan Protein Bar Proteinriegel - 50 g"}, "67": {"shop_product_id": 487069319210, "shop_title": "Creatine pH-X - 90 Kapseln"}, "68": {"shop_product_id": 487069253674, "shop_title": "Tri Creatine Malate - 300 g"}, "69": {"shop_product_id": 487070302250, "shop_title": "CreaTor, creatine komplex - 120 Kapseln"}, "70": {"shop_product_id": 1970339676202, "shop_title": "Crea Zero - 320 g"}, "71": {"shop_product_id": 15053161791814, "shop_title": "Mega Creatine - 306 g ohne geschmack"}, "72": {"shop_product_id": 3931856994346, "shop_title": "BCAA + Glutamine Zero - 480 g"}, "73": {"shop_product_id": 487109165098, "shop_title": "BCAA 8:1:1 ZERO - 250 g"}, "74": {"shop_product_id": 6124762431661, "shop_title": "EAA - 200 Megakapseln"}, "75": {"shop_product_id": 6122928177325, "shop_title": "Mega Amino - 500 Tabletten"}, "76": {"shop_product_id": 487115915306, "shop_title": "Glutamine Zero - 300 g"}, "77": {"shop_product_id": 487078264874, "shop_title": "L-Tyrosine - 100 Kapseln"}, "78": {"shop_product_id": 4382051729450, "shop_title": "L\\u2013Tryptophan - 60 Megakapseln"}, "79": {"shop_product_id": 4377682346026, "shop_title": "L\\u2013Lysine - 90 Kapseln"}, "80": {"shop_product_id": 487096451114, "shop_title": "ZMB - 60 Kapseln"}, "81": {"shop_product_id": 487065518122, "shop_title": "Vitamin C 1000 Bioflavonoids - 100 Tabletten"}, "82": {"shop_product_id": 3961968558122, "shop_title": "Calcium Zinc Magnesium - 100 Tabletten"}, "83": {"shop_product_id": 487109853226, "shop_title": "Tribooster - 60 Tabletten"}, "85": {"shop_product_id": 6269220913325, "shop_title": "Hyaluronic & Collagen - 120 Kapseln"}, "86": {"shop_product_id": 487096516650, "shop_title": "Chondroitin Glucosamine - 60 Kapseln"}, "87": {"shop_product_id": 487084818474, "shop_title": "MSM+Vitamin C Getr\\u00e4nkepulver - 150 g"}, "88": {"shop_product_id": 487115587626, "shop_title": "Muscle Mass kohlenhydrat- und eiwei\\u00dfhaltiges Getr\\u00e4nkepulver - 1000 g"}, "89": {"shop_product_id": 1970344296490, "shop_title": "Carbox - 1000 g nicht aromatisiert"}, "90": {"shop_product_id": 7267115925677, "shop_title": "Cyclic Dextrin Getr\\u00e4nkepulver - 1000 g"}, "91": {"shop_product_id": 1970345967658, "shop_title": "SuperNova - 282 g"}, "92": {"shop_product_id": 4382065098794, "shop_title": "IsoTonic - 600 g"}, "93": {"shop_product_id": 487085965354, "shop_title": "Fat-X - 60 Tabletten"}, "94": {"shop_product_id": 487069909034, "shop_title": "Thermo Drine - 60 Kapseln"}, "95": {"shop_product_id": 487070892074, "shop_title": "Thermo Drine Liquid - 500 ml"}, "96": {"shop_product_id": 4378464354346, "shop_title": "Synephrine - 60 Kapseln"}, "97": {"shop_product_id": 487089373226, "shop_title": "HCA - 100 Kapseln"}, "98": {"shop_product_id": 487110672426, "shop_title": "Fiber Complex - 120 Kautabletten"}, "99": {"shop_product_id": 6670013530285, "shop_title": "Vegan Multivitamintabletten - 60 St\\u00fcck Tablette"}, "100": {"shop_product_id": 4399140044842, "shop_title": "Multivitamin Brausetablette - 20 Stk. Tabletten"}, "101": {"shop_product_id": 1970338463786, "shop_title": "L-Carnitine - 60 Tabletten"}, "102": {"shop_product_id": 4404888731690, "shop_title": "Peanut Butter Erdnussbutter - 400 g"}, "103": {"shop_product_id": 4389890326570, "shop_title": "Protein Cream - 400 g"}, "104": {"shop_product_id": 4497790205994, "shop_title": "Protein Pancake Pulver - 1000 g"}, "105": {"shop_product_id": 4402747899946, "shop_title": "Zero Drops Geschmackstropfen - 50 ml"}, "107": {"shop_product_id": 6563782852781, "shop_title": "HMB - 150 Megakapseln"}, "108": {"shop_product_id": 8846811300166, "shop_title": "Crispy Protein Bar Proteinriegel - 40 g Milch"}, "109": {"shop_product_id": 487085408298, "shop_title": "Vitamin D3 - 60 Tabletten"}, "110": {"shop_product_id": 15049912484166, "shop_title": "Magnesium Bisglycinate - 90 Kapseln"}, "111": {"shop_product_id": 15049886138694, "shop_title": "Liposomal Vitamin C - 30 Kapseln"}, "112": {"shop_product_id": 7312176545965, "shop_title": "Hair, Skin & Nails - 54 Kapseln"}, "113": {"shop_product_id": 15295885443398, "shop_title": "Rhodiola - 60 Kapseln"}, "114": {"shop_product_id": 15145195667782, "shop_title": "Mushroom Complex - 60 Kapseln"}, "115": {"shop_product_id": 4555898945578, "shop_title": "Milk Thistle - 60 Kapseln"}, "116": {"shop_product_id": 15242770612550, "shop_title": "Zenaya - 60 Kapseln"}, "117": {"shop_product_id": 6622877515949, "shop_title": "Liquid Curcuma - 30\\u202fKapseln"}, "118": {"shop_product_id": 4378308149290, "shop_title": "Maca - 60 Megakapseln"}, "119": {"shop_product_id": 487084752938, "shop_title": "L-Arginine - 90 Megakapseln"}, "121": {"shop_product_id": 7175244677293, "shop_title": "Pump Caffeine Free Getr\\u00e4nkepulver - 330 g"}, "123": {"shop_product_id": 6222513406125, "shop_title": "Black Blood Shot - 60 ml Ampulle"}, "124": {"shop_product_id": 487075676202, "shop_title": "Caffeine + Taurine - 60 Kapseln"}, "125": {"shop_product_id": 15108491379014, "shop_title": "Creatine Candy - 240 Kautablette"}, "126": {"shop_product_id": 6684718334125, "shop_title": "Creatine Zero Effervescent  - 18 Tabletten"}, "129": {"shop_product_id": 487109394474, "shop_title": "TST + GH Hormonoptimierung - 300 g"}, "130": {"shop_product_id": 6566718210221, "shop_title": "Tribulus Maximus - 90 Kapseln"}, "131": {"shop_product_id": 3936657997866, "shop_title": "Zinc Duo - 60 Tabletten"}, "132": {"shop_product_id": 487090225194, "shop_title": "Multi Mineral Complex - 100 Tabletten"}, "133": {"shop_product_id": 487069057066, "shop_title": "Multivitamin For Women Tabletten - 60 St\\u00fcck Tabletten"}, "134": {"shop_product_id": 7294136352941, "shop_title": "One-A-Day 50+ For Men - 30 P\\u00e4ckchen"}, "135": {"shop_product_id": 8718799569222, "shop_title": "Iron Professional - 60 Tabletten"}, "136": {"shop_product_id": 15088056893766, "shop_title": "Lifelong 360\\u00b0 - 60 Kapseln"}, "137": {"shop_product_id": 487078395946, "shop_title": "MultiSalt - 60 Kapseln"}, "138": {"shop_product_id": 487074496554, "shop_title": "CLA 400 - 80 Softgel-Kapseln"}, "141": {"shop_product_id": 487089700906, "shop_title": "Liver Aid - 60 Tabletten"}, "142": {"shop_product_id": 15311875670342, "shop_title": "Shilajit - 60 Kapseln"}, "143": {"shop_product_id": 7231276417197, "shop_title": "GABA - 60 Kapseln"}, "144": {"shop_product_id": 4404991295530, "shop_title": "Zero Sauce - 350 ml"}, "145": {"shop_product_id": 4407015800874, "shop_title": "Zero Syrup - 320 ml"}, "146": {"shop_product_id": 7200167100589, "shop_title": "Flavour Power Aromapulver - 160 g"}, "147": {"shop_product_id": 8394564206918, "shop_title": "Rice Pudding - 1000 g"}, "148": {"shop_product_id": 4603801108522, "shop_title": "Protein Oatmeal - 1000g"}, "150": {"shop_product_id": 487074693162, "shop_title": "Energy Gel PRO - 40 g"}, "151": {"shop_product_id": 487075545130, "shop_title": "AAKG 7800 - 25 ml"}, "152": {"shop_product_id": 8583543783750, "shop_title": "Ashwa+ - 30 Megakapseln"}, "154": {"shop_product_id": 487066271786, "shop_title": "Magna Shot - 25 ml"}, "155": {"shop_product_id": 15475309281606, "shop_title": "Whey Shake - 1000 g"}, "157": {"shop_product_id": 15465198289222, "shop_title": "100% Creatine Monohydrate - 300 g yuzu"}, "158": {"shop_product_id": 15040822116678, "shop_title": "Iso Whey Zero Natural - 908 g"}, "159": {"shop_product_id": 4325810208810, "shop_title": "Micellar Casein - 908 g"}, "161": {"shop_product_id": 1970338070570, "shop_title": "Wave Shaker BioTechUSA, BPA frei  - 600 ml"}, "162": {"shop_product_id": 1970338037802, "shop_title": "BioTechUSA Wave+ Shaker 600ml(+200ml+150ml)"}, "165": {"shop_product_id": 1970338496554, "shop_title": "Gallon BioTechUSA - 2200 ml"}, "216": {"shop_product_id": 4493626540074, "shop_title": "Protein Bar Protein-Riegel - 35 g"}, "217": {"shop_product_id": 15270533300550, "shop_title": "Protein Max - 45 g"}, "218": {"shop_product_id": 487085015082, "shop_title": "BCAA Shot - 60 ml"}, "219": {"shop_product_id": 4365435011114, "shop_title": "Liquid BCAA - 1000 ml"}, "220": {"shop_product_id": 4345102893098, "shop_title": "Glutamine Peptide - 180 Megakapseln"}, "221": {"shop_product_id": 1971389530154, "shop_title": "CA-HMB 3000 - 270 g"}, "222": {"shop_product_id": 15241560031558, "shop_title": "NAC - 60 Tabletten"}, "223": {"shop_product_id": 487078428714, "shop_title": "AAKG Shock - 1000 ml"}, "224": {"shop_product_id": 6223972237485, "shop_title": "Thermo Shot - 60 ml"}, "225": {"shop_product_id": 487071580202, "shop_title": "Desert - 100 Megakapseln"}, "226": {"shop_product_id": 9015742005574, "shop_title": "Pyruvate - 90 Kapseln"}, "227": {"shop_product_id": 8660554481990, "shop_title": "Chromium Picolinate - 60 Tabletten"}, "228": {"shop_product_id": 7136267010221, "shop_title": "Glucomannan + Chromium - 225 g"}, "229": {"shop_product_id": 487104970794, "shop_title": "L-Carnitine Effervescent - 20 Tabletten"}, "230": {"shop_product_id": 487074594858, "shop_title": "L-Carnitine + Chrome - 500 ml"}, "231": {"shop_product_id": 487109722154, "shop_title": "L-Carnitine + Chrome - 60 Kapseln"}, "232": {"shop_product_id": 6623062393005, "shop_title": "Eggshell membrane Kapseln - 60 Megakapseln"}, "233": {"shop_product_id": 487078854698, "shop_title": "MSM Chondroitin Glucosamine - 60 Tabletten"}, "234": {"shop_product_id": 487076036650, "shop_title": "GH Hormone Regulator - 120 Kapseln"}, "235": {"shop_product_id": 4603927887914, "shop_title": "Panax Ginseng - 60 Kapseln"}, "236": {"shop_product_id": 6551995809965, "shop_title": "Saw Palmetto - 60 Megakapseln"}, "237": {"shop_product_id": 4377700171818, "shop_title": "Fenugreek - 60 Megakapseln"}, "238": {"shop_product_id": 15310594244934, "shop_title": "Aquamin Calcium - 240 g"}, "239": {"shop_product_id": 15444148355398, "shop_title": "Omega-3 Triglycerides  - 60 Softgel Kapseln"}, "240": {"shop_product_id": 15417561088326, "shop_title": "One-A-Day Kids - 90 Kautabletten"}, "241": {"shop_product_id": 487075872810, "shop_title": "Vitabolic - 30 Tabletten"}, "242": {"shop_product_id": 1970336694314, "shop_title": "Vitamin Complex - 60 Kapseln"}, "243": {"shop_product_id": 487070662698, "shop_title": "Vitamin C 500 - 120 Kautablette"}, "244": {"shop_product_id": 4399089582122, "shop_title": "Vitamin C Brausetablette - 20 Stk."}, "245": {"shop_product_id": 3936652787754, "shop_title": "Magnesium + Chelate - 60 Kapseln"}, "246": {"shop_product_id": 7132287991981, "shop_title": "Neuro - 60 Kapseln"}, "247": {"shop_product_id": 1970336399402, "shop_title": "Men\\u2019s Arginine - 90 Kapseln"}, "248": {"shop_product_id": 7175653851309, "shop_title": "Valeriana Forte - 60 Tabletten"}, "249": {"shop_product_id": 487085768746, "shop_title": "Vitamin E - 100 Softgel-Kapseln"}, "250": {"shop_product_id": 487075840042, "shop_title": "Night - 60 Kapseln"}, "251": {"shop_product_id": 487078789162, "shop_title": "Q10 Coenzyme 100 mg - 60 Kapseln"}, "252": {"shop_product_id": 487080067114, "shop_title": "H2O Q10 - 60 Kapseln"}, "253": {"shop_product_id": 7331420537005, "shop_title": "Digestion & Metabolism - 60 Tabletten"}, "254": {"shop_product_id": 6938999226541, "shop_title": "Pumpkin Seed Oil - 60 St\\u00fcck Weichgelatinekapseln"}, "255": {"shop_product_id": 6674434883757, "shop_title": "Immune+Biotiq - 36 Kapseln"}, "256": {"shop_product_id": 7323280375981, "shop_title": "Biotiq C - 36 Kapseln"}, "257": {"shop_product_id": 487089635370, "shop_title": "Ginkgo Biloba - 90 Tabletten"}, "258": {"shop_product_id": 487110475818, "shop_title": "Green Coffee - 120 Kapseln"}, "259": {"shop_product_id": 15058511036742, "shop_title": "Resveratrol - 60 Kapseln"}, "260": {"shop_product_id": 487080362026, "shop_title": "Spirulina - 100 Tabletten"}, "261": {"shop_product_id": 15136179978566, "shop_title": "Cranberry Complex - 60 Tabletten"}, "262": {"shop_product_id": 7331406905517, "shop_title": "Clear Collagen Getr\\u00e4nkepulver - 308 g"}, "264": {"shop_product_id": 9296235856198, "shop_title": "Collagen & Hyaluronic - 30 Kapseln"}, "265": {"shop_product_id": 1970337775658, "shop_title": "Protein Muesli - 30 g"}, "266": {"shop_product_id": 1970337841194, "shop_title": "Nuts & Fruits - 40 g"}, "267": {"shop_product_id": 1970337808426, "shop_title": "Nuts & Honey - 35 g"}, "268": {"shop_product_id": 1970346655786, "shop_title": "OAT & Nuts - 70 g"}, "269": {"shop_product_id": 8586014654790, "shop_title": "Protein Tortilla Chips - 50\\u202fg"}, "270": {"shop_product_id": 8690823987526, "shop_title": "Protein Crispies - 450 g"}, "271": {"shop_product_id": 7202061156525, "shop_title": "Getr\\u00e4nkepulver Fiber Mix - 225 g"}, "272": {"shop_product_id": 4506096140330, "shop_title": "Instant Oats - 1000 g"}, "273": {"shop_product_id": 6741518319789, "shop_title": "Protein Brownie Basispulver - 600 g"}, "274": {"shop_product_id": 3855254159402, "shop_title": "Protein Ice Cream - 500 g"}, "275": {"shop_product_id": 6948370481325, "shop_title": "Hot Chocolate Eiwei\\u00dfgetr\\u00e4nkepulver - 450 g"}, "276": {"shop_product_id": 487100973098, "shop_title": "Multi Hypotonic Drink - 1000 ml"}, "277": {"shop_product_id": 487084884010, "shop_title": "Energy Gel - 40 g"}, "278": {"shop_product_id": 487085572138, "shop_title": "Energy Shot - 25 ml"}, "279": {"shop_product_id": 487089274922, "shop_title": "Recovery Gel - 40 g"}, "280": {"shop_product_id": 15531517215046, "shop_title": "Protein Coffee - 450 g"}, "291": {"shop_product_id": 487084720170, "shop_title": "ALA - 50 Kapseln"}, "295": {"shop_product_id": 6674434883757, "shop_title": "Immune+Biotiq - 36 Kapseln"}, "296": {"shop_product_id": 7125814313133, "shop_title": "Melatonin - 90 Tabletten"}, "315": {"shop_product_id": 14816802767174, "shop_title": "BACKLESS MEDIUM SUPPORT SPORTS BRA Damen Sport-BH"}, "343": {"shop_product_id": 14816802537798, "shop_title": "MEDIUM SUPPORT PADDED TOP Damen Sport-BH"}, "373": {"shop_product_id": 15402146857286, "shop_title": "Iso Whey Clear - 25 g"}, "374": {"shop_product_id": 487102251050, "shop_title": "Iso Whey Zero Protein Isolat Pulver  - 25 g"}, "375": {"shop_product_id": 15003696595270, "shop_title": "Iso Whey Zero Proteinpulver - 1816 g"}, "379": {"shop_product_id": 487085375530, "shop_title": "Hydro Whey Zero - 1816 g"}, "381": {"shop_product_id": 15250839306566, "shop_title": "Iso Whey Platinum - 1816 g"}, "382": {"shop_product_id": 1970334203946, "shop_title": "Vegan Protein - 25 g"}, "383": {"shop_product_id": 4389850120234, "shop_title": "Vegan Protein - 2000 g"}, "384": {"shop_product_id": 487074431018, "shop_title": "Protein Power - 1000 g"}, "385": {"shop_product_id": 487076659242, "shop_title": "Protein Power - 4000 g"}, "386": {"shop_product_id": 4325792481322, "shop_title": "Micellar Casein - 2270 g"}, "387": {"shop_product_id": 487084785706, "shop_title": "Beef Protein - 30 g"}, "388": {"shop_product_id": 487081312298, "shop_title": "Beef Protein - 1816 g"}, "389": {"shop_product_id": 3881143500842, "shop_title": "Hyper Mass - 2270 g"}, "390": {"shop_product_id": 487108935722, "shop_title": "Muscle Mass kohlenhydrat- und eiwei\\u00dfhaltiges Getr\\u00e4nkepulver - 4000 g"}, "391": {"shop_product_id": 487080689706, "shop_title": "100% Creatine Monohydrate - 500 g Ohne Geschmack"}, "392": {"shop_product_id": 15447354900806, "shop_title": "100% Creatine Monohydrate - 1000 g Ohne Geschmack"}, "393": {"shop_product_id": 487066304554, "shop_title": "Creatine pH-X - 210 Kapseln"}, "394": {"shop_product_id": 9309164077382, "shop_title": "Mega\\u00a0Creatine\\u00a0- 120\\u00a0Megakapseln"}, "395": {"shop_product_id": 1970345312298, "shop_title": "BCAA ZERO Aminos\\u00e4uren Pulver - 360 g"}, "396": {"shop_product_id": 15315137790278, "shop_title": "EAA ZERO Aminos\\u00e4uren Pulver Komplex - 14 g"}, "398": {"shop_product_id": 15309584302406, "shop_title": "Black Blood CAF+ - 15 g"}, "399": {"shop_product_id": 487078756394, "shop_title": "Black Blood NOX+ - 20 g"}, "400": {"shop_product_id": 487086719018, "shop_title": "Nitrox Therapy - 17 g"}, "401": {"shop_product_id": 7175246446765, "shop_title": "Pump Caffeine Free Getr\\u00e4nkepulver - 11 g"}, "402": {"shop_product_id": 6826615013549, "shop_title": "IsoTonic - 30 g"}, "404": {"shop_product_id": 6899333038253, "shop_title": "Diet Shake - 30 g"}, "405": {"shop_product_id": 6885015257261, "shop_title": "Protein Pancake Pulver - 40 g"}, "408": {"shop_product_id": 487081574442, "shop_title": "Iso Whey Zero Protein Isolat Pulver - 908 g"}, "409": {"shop_product_id": 487101431850, "shop_title": "Nitrox Therapy - 340 g"}, "410": {"shop_product_id": 15310574879046, "shop_title": "Iso Whey Platinum - 454 g"}, "413": {"shop_product_id": 15167315902790, "shop_title": "100% Creatine Monohydrate - 300 g"}, "414": {"shop_product_id": 15240205992262, "shop_title": "Iso Whey Zero Black Getr\\u00e4nkepulver auf Basis von Molkeproteinisolat - 30 g"}, "415": {"shop_product_id": 4456481718314, "shop_title": "Iso Whey Zero Black Getr\\u00e4nkepulver auf Basis von Molkeproteinisolat - 908 g"}, "416": {"shop_product_id": 15402223337798, "shop_title": "100% Pure Whey - 400 g"}, "417": {"shop_product_id": 15426496397638, "shop_title": "100% Pure Whey  - 900 g"}, "419": {"shop_product_id": 4578081996842, "shop_title": "100% Pure Whey - 28 g"}, "420": {"shop_product_id": 1970343051306, "shop_title": "BCAA ZERO Aminos\\u00e4uren Pulver - 9 g"}, "421": {"shop_product_id": 3821742981162, "shop_title": "BCAA+B6 - 100 Tabletten"}, "422": {"shop_product_id": 487069417514, "shop_title": "BCAA+B6 - 200 Tabletten"}, "423": {"shop_product_id": 487076102186, "shop_title": "100% L-Glutamine - 240 g"}, "424": {"shop_product_id": 487115489322, "shop_title": "Citrulline Malate - 90 Megakapseln"}, "425": {"shop_product_id": 14783931941190, "shop_title": "Clear Collagen Professional Getr\\u00e4nkepulver - 25 g"}, "426": {"shop_product_id": 4344999968810, "shop_title": "Hyper Mass - 65 g"}, "427": {"shop_product_id": 487110344746, "shop_title": "Hyper Mass - 4000 g"}, "428": {"shop_product_id": 3924400570410, "shop_title": "Hyper Mass - 6800 g"}, "429": {"shop_product_id": 487085932586, "shop_title": "Liquid Amino - 25 ml"}, "430": {"shop_product_id": 487074332714, "shop_title": "Mega Omega 3 - 90 Softgel Kapseln"}, "431": {"shop_product_id": 15402222715206, "shop_title": "100% Pure Whey Natural Molkenprotein-Konzentrat Getr\\u00e4nkepulver - 400 g"}, "432": {"shop_product_id": 15426495414598, "shop_title": "100% Pure Whey Natural Molkenprotein-Konzentrat Getr\\u00e4nkepulver - 900 g"}, "433": {"shop_product_id": 15406787789126, "shop_title": "100% Pure Whey Natural Molkenprotein-Konzentrat Getr\\u00e4nkepulver - 2000 g"}, "434": {"shop_product_id": 6046819844269, "shop_title": "Mega Amino - 100 Tabletten"}, "435": {"shop_product_id": 487075217450, "shop_title": "Mega Amino - 300 Tabletten"}, "436": {"shop_product_id": 1970345934890, "shop_title": "Vitamin C 1000 Bioflavonoids - 30 Tabletten"}, "437": {"shop_product_id": 487069712426, "shop_title": "Vitamin C 1000 Bioflavonoids - 250 Tabletten"}, "439": {"shop_product_id": 4404891942954, "shop_title": "Peanut Butter Erdnussbutter - 1000 g"}, "440": {"shop_product_id": 4394904584234, "shop_title": "Protein Cream - 200 g"}, "441": {"shop_product_id": 6971175698605, "shop_title": "Vitamin D3 - 120 Tabletten"}, "443": {"shop_product_id": 487081508906, "shop_title": "L-Arginine - 300 g"}, "444": {"shop_product_id": 6124762202285, "shop_title": "Carni Elite - 90 Megakapseln"}, "445": {"shop_product_id": 14922937237830, "shop_title": "Rice Pudding - 3000 g"}, "446": {"shop_product_id": 15618208366918, "shop_title": "Whey Shake - 500 g"}, "447": {"shop_product_id": 15530074112326, "shop_title": "Whey Shake - 25 g"}, "448": {"shop_product_id": 487075282986, "shop_title": "Nitrox Therapy - 680 g"}}')
SKIP=json.loads('{"18": "L-Carnitine 3000 Ampulle \\u2014 Shop f\\u00fchrt keine Ampullen", "139": "Carni Elite Ampullen \\u2014 Shop f\\u00fchrt nur Megakapseln", "140": "L-Carnitine Drink Powder \\u2014 nicht im Shop", "62": "100% Pure Whey Natural 1000 g \\u2014 Shop hat nur 400/900/2000 g", "263": "Collagen & Hyaluronic Powder 300 g \\u2014 Shop nur Kapseln", "397": "EAA ZERO 182 g \\u2014 Gr\\u00f6\\u00dfe nicht im Shop", "380": "Iso Whey Platinum Sachet \\u2014 im Online-Feed nicht vorhanden (nur 454/908/1816 g)", "_shop_15647717982534": "100% Pure Whey 3000 g \\u2014 wird im Store nicht verkauft", "84": "Super Lipo \\u2014 nicht im Shop", "106": "Taurine \\u2014 nicht im Shop (nur Caffeine + Taurine)", "149": "Oat & Fruits Zero \\u2014 nicht im Shop", "281": "Mug Cake 7x45 g Multipack \\u2014 Shop f\\u00fchrt nur die Einzelpackung", "283": "MagnaShot 20x25 ml Karton \\u2014 Shop f\\u00fchrt nur die Einzelampulle", "438": "L-Carnitine 1000 30 Tabletten \\u2014 nicht im Shop", "153": "GH Hormon Regulator \\u2014 nicht im Shop. Der Shop-Artikel GH Hormone Regulator ist #234 GH (Arginin/Ornithin/Lysin + B6)"}')

# Shop-Kategorien, aus denen NICHTS automatisch angelegt wird.
# Bekleidung und Shaker sind fuer die Beratung ohne Wert und wuerden die
# Datenbank mit hunderten Textilartikeln fluten; "Pakete" sind Kombi-Angebote
# und laufen ueber aktionspreise.py.
IGNORE_TYPES = {
    "BiotechUSA Apparel", "Kleidung und Accessoires", "Shirts",
    "Shaker/Trinkflaschen", "Pakete", "BFTEST",
}

TYPE_TO_CAT = {
    "Protein": "Protein", "Creatine": "Kreatin", "Aminosäuren": "Aminosäuren",
    "Vitamine": "Vitamine & Mineralien", "Nitrox und Energizer": "Pre-Workout",
    "Lipotrope und thermogene Rezepturen": "Fettverbrenner",
    "L-Carnitine Formeln": "L-Carnitin",
    "Glucosamin und Chondroitin": "Gelenke & Kollagen",
    "Collagen Produkt": "Kollagen", "TST-Booster": "Testosteron-Booster",
    "BioTechUSA Endurance Line": "Ausdauer & Energie",
    "Kohlenhydratkomplexe": "Gainer & Masseaufbau",
    "Muskelaufbau fördernde Präparate": "Gainer & Masseaufbau",
    "Riegel und Sportgetränke": "Riegel & Snacks",
    "Produkte für den gesunden Lifestyle": "Healthy Lifestyle",
    "Pflanzliche Extrakte": "Kräuter & Pflanzenextrakte",
    "Shaker/Trinkflaschen": "Shaker & Zubehör",
    "BiotechUSA Apparel": "Bekleidung", "Kleidung und Accessoires": "Bekleidung",
    "Shirts": "Bekleidung", "Beauty line": "Healthy Lifestyle",
    "BioTechUSA For Her": "Healthy Lifestyle", "Pakete": "Zubehör",
}

def html_to_text(h):
    """Shop-Produktbeschreibung (HTML) in lesbaren Text umwandeln."""
    if not h: return ""
    t = re.sub(r"<(br|/p|/li|/h[1-6]|/tr)[^>]*>", "\n", h, flags=re.I)
    t = re.sub(r"<li[^>]*>", "- ", t, flags=re.I)
    t = re.sub(r"<[^>]+>", " ", t)
    for a,b in [("&nbsp;"," "),("&amp;","&"),("&auml;","ä"),("&ouml;","ö"),("&uuml;","ü"),("&Auml;","Ä"),("&Ouml;","Ö"),("&Uuml;","Ü"),("&szlig;","ß"),("&quot;",'"'),("&#39;","'"),("&eacute;","é"),("&ndash;","–"),("&mdash;","—"),("&euro;","€"),("&deg;","°"),("&reg;","®"),("&trade;","™"),("&percnt;","%")]:
        t = t.replace(a,b)
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r"\n\s*\n+", "\n", t)
    t = t.strip()
    return t[:1500] + ("…" if len(t) > 1500 else "")

def fmt_num(x):
    return ("%.1f" % x).rstrip("0").rstrip(".").replace(".", ",")

def parse_desc(h, tg=None):
    """Naehrwerte, Portion, Dosierung, Highlights aus der Shop-Beschreibung ziehen."""
    out = {}
    if not h: return out
    st = lambda t: html_to_text(t).replace(chr(10), " ").strip()
    m = re.search(r"1\s*Portion:?\s*([\d.,]+\s*(?:g|ml|Tropfen|Tabletten?|Kapseln?|Kautabletten?|Softgel[a-z\u00e4]*|St\u00fcck|Messl\u00f6ffel))", h, re.I)
    if m: out["portionSize"] = st(m.group(1))
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", h, re.S | re.I)
    raw = {}; ncols = None
    for rh in rows:
        cells = [st(c) for c in re.findall(r"<td[^>]*>(.*?)</td>", rh, re.S | re.I)]
        if not cells: continue
        head = cells[0].lower()
        if "n\u00e4hrwerte" in head and ncols is None: ncols = len(cells)
        if len(cells) < 2: continue
        val = cells[-1]
        def num(sx, unit):
            mm = re.search(r"([\d.,]+)\s*" + unit, sx)
            return float(mm.group(1).replace(",", ".")) if mm else None
        if re.match(r"(energie|brennwert)", head) and "kcal" not in raw:
            v = num(val, "kcal")
            if v is not None: raw["kcal"] = v
        elif re.match(r"(eiwei\u00df|protein)\b", head) and "protein" not in raw:
            v = num(val, "g")
            if v is not None: raw["protein"] = v
        elif head.startswith("fett") and "davon" not in head and "fat" not in raw:
            v = num(val, "g")
            if v is not None: raw["fat"] = v
        elif head.startswith("kohlenhydrate") and "carbs" not in raw:
            v = num(val, "g")
            if v is not None: raw["carbs"] = v
    if raw:
        factor = 1.0; ok = True
        if ncols is not None and ncols <= 2:
            g = None
            pm = re.match(r"([\d.,]+)\s*g", out.get("portionSize", ""))
            if pm: g = float(pm.group(1).replace(",", "."))
            elif tg and tg <= 120: g = tg
            if g: factor = g / 100.0
            else: ok = False
        if ok:
            if "kcal" in raw: out["kcalPortion"] = round(raw["kcal"] * factor)
            for k, f in [("protein", "proteinPortion"), ("fat", "fatPortion"), ("carbs", "carbsPortion")]:
                if k in raw: out[f] = fmt_num(raw[k] * factor) + " g"
    kand = []
    for m in re.finditer(r"\b(Verzehr(?:s)?empfehlung|Anwendungsempfehlung|Empfohlene\s+(?:t\u00e4gliche\s+)?(?:Verzehr|Tages|Einnahme)[a-z\u00e4\u00f6\u00fc]*|Dosierung)\s*:?", h, re.I):
        seg = re.split(r"<h|</div|<table|Zutaten", h[m.end():m.end()+600])[0]
        txt = st(re.split(r"HINWEIS", seg)[0])
        if len(txt) > 15: kand.append(txt[:300])
    # Anweisung unter einer Frage-Überschrift ("Wie ist ... einzunehmen?")
    for m in re.finditer(r"<h\d[^>]*>(.*?)</h\d>", h, re.S | re.I):
        kopf = st(m.group(1))
        if not re.search(r"einzunehmen|einnehmen|nehmen|verwenden|Anwendung|Verzehr|Dosierung", kopf, re.I): continue
        seg = re.split(r"<h\d|<table", h[m.end():m.end()+800])[0]
        txt = st(re.split(r"HINWEIS", seg)[0])
        if len(txt) > 15: kand.append(txt[:300])
    if kand:
        gut = [t for t in kand if re.search(r"\d|Kapsel|Tablette|Beutel|Portion|[Nn]imm|nehmen|einnehmen", t)]
        satz = [t for t in gut if re.match(r"^[A-Z\u00c4\u00d6\u00dc]", t) and not re.match(r"^(Die|Das|Der)\b", t)]
        out["dosage"] = (satz or gut or kand)[0]
    # Wirkstoff-Tabelle (z. B. Vitamine/Mineralstoffe): Zeilen "Name | Menge | NRV%".
    # Nur wenn keine Nährwerttabelle da ist (Kapseln/Tabletten) — bei Pulvern/Riegeln
    # würde sonst das Aminogramm zu Schlüssel-Inhaltsstoffen.
    NON_ING = re.compile(r"^[-\u2013\u2022\s]*(energie|brennwert|eiwei\u00df|protein|fett|kohlenhydrate|davon|salz|zucker|ballaststoffe|tagesdosis|n\u00e4hrwert|durchschnittliche|\*|nrv)", re.I)
    wirkstoffe = []
    if "kcal" not in raw:
        for rh in rows:
            cells = [st(c) for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", rh, re.S | re.I)]
            if len(cells) < 2: continue
            name_c, menge = cells[0], cells[1]
            if not name_c or name_c[:1] in "-\u2013\u2022" or NON_ING.match(name_c): continue
            if not re.match(r"^[\d.,]+\s*(\u00b5g|\u03bcg|mg|g|IE|IU|Mrd\.?|KBE)\b", menge): continue
            if len(name_c) > 60: continue
            wirkstoffe.append(f"{name_c} ({menge})")
    if wirkstoffe:
        out["keyIngredients"] = wirkstoffe[:24]
    ul = re.search(r"<ul[^>]*>(.*?)</ul>", h, re.S | re.I)
    if ul and "keyIngredients" not in out:
        lis = [st(x) for x in re.findall(r"<li[^>]*>(.*?)</li>", ul.group(1), re.S | re.I)]
        lis = [x for x in lis if 3 < len(x) < 90][:6]
        if lis: out["keyIngredients"] = lis
    t = html_to_text(h)
    if re.search(r"\bvegan\b", t, re.I) and not re.search(r"nicht\s+vegan", t, re.I):
        out["vegan"] = True
    return out

def short_desc(h, limit=350, name=""):
    """Erster sinnvoller Beschreibungsabsatz, an Satzgrenze gekappt.
    Bevorzugt Absätze, die das Produkt (oder einen Nährstoff) tatsächlich erwähnen."""
    if not h: return ""
    tokens = [w for w in re.split(r"[^A-Za-z0-9ÄÖÜäöüß]+", name or "") if len(w) > 1]
    paras = []
    for m in re.finditer(r"<p[^>]*>(.*?)</p>", h, re.S | re.I):
        t = html_to_text(m.group(1)).replace(chr(10), " ").strip()
        if len(t) < 40 or t.endswith("?"): continue
        paras.append(t)
    def cap(t):
        if len(t) <= limit: return t
        cut = t[:limit]
        i = max(cut.rfind(". "), cut.rfind("! "))
        return (cut[:i+1] if i > 60 else cut.rstrip() + "…")
    for t in paras[:5]:
        if any(tok.lower() in t.lower() for tok in tokens):
            return cap(t)
    return cap(paras[0]) if paras else html_to_text(h).replace(chr(10), " ").strip()[:limit]

def title_grams(t):
    m = re.search(r"-\s*([\d.,]+)\s*g\b", t or "")
    return float(m.group(1).replace(",", ".")) if m else None

def price_range(p):
    return "€" if p < 15 else ("€€" if p < 35 else "€€€")

def split_title(t):
    m = __import__("re").match(r"^(.*?)[\s\u00a0]*[-–—][\s\u00a0]*(\d[\d.,]*\s*\S*.*)$", t)
    if m: return m.group(1).strip(), m.group(2).strip()
    return t.strip(), "–"

LIMITED_RE = re.compile(r"limited\s*edition|collector.?s\s*edition|limitiert", re.I)

def is_limited(p):
    """Erkennt Limited Editions am Shop-Titel oder an der Beschreibung."""
    return bool(LIMITED_RE.search((p.get("title") or "") + " " + (p.get("body_html") or "")))

def norm_name(n):
    return re.sub(r"\s+", " ", (n or "")).strip().lower()

def variant_flavors(p, limit=3):
    fl = [v.get("title") or "" for v in (p.get("variants") or [])[:limit]]
    return [f for f in fl if f and f.lower() != "default title"]

def final_name(p, base_name, taken=()):
    """Name für ein automatisch übernommenes Produkt.
    Limited Editions bekommen den Zusatz "(Limited Edition)". Andere Namen, die
    es bei uns schon gibt, bekommen den Geschmack angehängt, damit im Katalog
    nicht zweimal derselbe Name steht."""
    if is_limited(p):
        return base_name + " (Limited Edition)"
    if norm_name(base_name) in taken:
        extra = ", ".join(variant_flavors(p)) or split_title(p.get("title") or "")[1]
        if extra and extra != "–":
            return f"{base_name} ({extra})"
    return base_name

SIZE_RE = re.compile(r"^([\d.,]+\s*(?:g|kg|ml|l|Kapseln|Tabletten|Stück|Portionen|Riegel|Beutel|Sachets?|Ampullen)?)\s*(.*)$", re.I)

def parse_size_flavor(rest):
    """Trennt "1000 g Pfirsich-Joghurt" in Größe und Geschmack."""
    rest = (rest or "").strip()
    if rest in ("", "–"): return "–", ""
    m = SIZE_RE.match(rest)
    if not m: return rest, ""
    return m.group(1).strip(), m.group(2).strip()

def norm_size(s):
    return re.sub(r"\s+", "", (s or "").replace(",", ".")).lower()

INDEX_URL = "https://raw.githubusercontent.com/herbertprantl87-art/btuwdb2/main/index.html"
_BASIS = None
_BASIS_FRESH = False

def load_index_products():
    """Basisdaten (name, packageSize, flavors, notes) der fest eingebauten
    Produkte aus der ausgelieferten index.html. Ergebnis wird lokal
    zwischengespeichert, damit ein Ausfall von GitHub den Lauf nicht blockiert."""
    global _BASIS, _BASIS_FRESH
    if _BASIS is not None: return _BASIS
    txt = None
    try:
        req = urllib.request.Request(INDEX_URL, headers=UA)
        with urllib.request.urlopen(req, timeout=60) as r:
            txt = r.read().decode("utf-8", "replace")
    except Exception as e:
        print("  Warnung: index.html nicht ladbar:", e)
    if txt:
        d = {}
        for m in re.finditer(r"\n    id: (\d+),(.*?)\n  \},", txt, re.S):
            blk = m.group(2)
            def fld(k):
                mm = re.search(k + r':\s*"((?:[^"\\]|\\.)*)"', blk)
                return mm.group(1).replace('\\"', '"') if mm else ""
            def raw(k):
                mm = re.search(k + r':\s*([^,\n]+)', blk)
                return mm.group(1).strip().strip('"') if mm else ""
            d[m.group(1)] = {"name": fld("name"), "packageSize": fld("packageSize"),
                             "flavors": fld("flavors"), "notes": fld("notes"),
                             "dosage": fld("dosage"),
                             "kcalPortion": raw("kcalPortion"), "proteinPortion": raw("proteinPortion"),
                             "hasKeyIngredients": bool(re.search(r"keyIngredients:\s*\[\s*[\"']", blk))}
        if d:
            _BASIS_FRESH = True
            _BASIS = d
            try:
                with open("produkte_basis.json", "w", encoding="utf-8") as f:
                    json.dump(d, f, ensure_ascii=False)
            except Exception: pass
            return _BASIS
    try:
        with open("produkte_basis.json", encoding="utf-8") as f:
            _BASIS = json.load(f)
        print("  Hinweis: Basisdaten aus der lokalen Zwischenspeicherung.")
        return _BASIS
    except Exception:
        return None

FORM_WORDS = ("molkenprotein-konzentrat", "molkenproteinkonzentrat",
              "auf basis von molkeproteinisolat", "aminosäuren pulver komplex",
              "aminosäuren pulver", "proteinpulver", "getränkepulver", "getränkpulver",
              "protein isolat pulver", "isolat pulver", "getränk", "pulver", "powder", "drink")

# Darreichungsform ist kein Geschmack ("90 Softgel Kapseln" -> Groesse 90, kein Aroma)
FORM_NICHT_GESCHMACK = ("kapsel", "megakapsel", "softgel", "tablette", "kautablette",
                        "stück", "stk", "beutel", "sachet", "ampulle", "päckchen", "pakete")

def ist_form(txt):
    t = norm_name(txt)
    return bool(t) and all(
        any(f in teil for f in FORM_NICHT_GESCHMACK)
        for teil in [x.strip() for x in t.split(",") if x.strip()])

def base_key(n):
    """Vergleichsschlüssel für Produktnamen: Klein-, Zusatzwörter des Shops raus."""
    k = norm_name(n)
    for w in FORM_WORDS:
        k = k.replace(w, " ")
    k = re.sub(r"[^0-9a-zäöüß%+ ]", " ", k)
    k = re.sub(r"\s+", " ", k).strip()
    # englische Schreibweise auf die deutsche ziehen: arginine -> arginin
    k = re.sub(r"\b(arginin|glutamin|carnitin|kreatin|citrullin|tyrosin|lysin|leucin|taurin)e\b", r"\1", k)
    return k

def plane_neuzugaenge(new_products, unsere, custom_read):
    """Entscheidet je neuem Shop-Produkt: anlegen, oder nur als neuer Geschmack
    beim bestehenden Produkt ergänzen. Limited Editions werden immer angelegt."""
    taken = {norm_name(u["name"]) for u in unsere.values()} | {norm_name(c.get("name")) for c in custom_read}
    # bekannte Shop-Schreibweisen aus der verifizierten Zuordnungstabelle
    shop_titel_index = {}
    for uid, m in MAPPING.items():
        shop_titel_index.setdefault(base_key(split_title(m["shop_title"])[0]), []).append(str(uid))
    anlegen = []; geschmack = []; groessen = []; ignoriert = []
    schon_da = {str(c.get("id")) for c in custom_read}
    for p in new_products:
        if ("shop-" + str(p["id"])) in schon_da: continue
        base_name, rest = split_title(p["title"])
        size, flavor_titel = parse_size_flavor(rest)
        if is_limited(p):
            name = base_name + " (Limited Edition)"
            taken.add(norm_name(name)); anlegen.append((p, name)); continue
        schluessel = base_key(base_name)
        fl = ", ".join(variant_flavors(p, 10)) or flavor_titel
        kandidaten = []
        for uid in shop_titel_index.get(schluessel, []):
            if uid in unsere:
                u = unsere[uid]; kandidaten.append(("builtin", str(uid), u["name"], u.get("packageSize")))
        for uid2, u in unsere.items():
            if base_key(u["name"]) == schluessel and not any(k[1] == str(uid2) for k in kandidaten):
                kandidaten.append(("builtin", str(uid2), u["name"], u.get("packageSize")))
        for c in custom_read:
            if base_key(c.get("name")) == schluessel:
                kandidaten.append(("custom", str(c.get("id")), c.get("name"), c.get("packageSize")))
        # Hauptprodukt zuerst: fest eingebaute vor eigenen, kleinere Produkt-ID vor größerer
        kandidaten.sort(key=lambda k: (k[0] != "builtin", int(k[1]) if k[1].isdigit() else 10**9))
        treffer = next((k for k in kandidaten if norm_size(k[3]) == norm_size(size)), None)
        if treffer:
            if fl:
                geschmack.append({"art": treffer[0], "ziel": treffer[1], "zielname": treffer[2],
                                  "geschmack": fl, "shop_id": p["id"], "titel": p["title"]})
            else:
                ignoriert.append((p, f"gleiches Produkt wie {treffer[2]}, kein neuer Geschmack erkennbar"))
            continue
        if kandidaten and size and size != "–":
            k = kandidaten[0]
            groessen.append({"art": k[0], "ziel": k[1], "zielname": k[2], "groesse": size,
                             "geschmack": fl, "shop_id": p["id"], "titel": p["title"]})
            continue
        if norm_name(base_name) in taken:
            name = f"{base_name} ({size})" if size and size != "–" else final_name(p, base_name, taken)
        else:
            name = base_name
        taken.add(norm_name(name)); anlegen.append((p, name))
    return anlegen, geschmack, groessen, ignoriert

def _leer(v, extra=()):
    """Gilt ein Feldwert als 'nicht gepflegt'?"""
    if v is None: return True
    s = str(v).strip()
    return s in ("", "–", "-", "—") or s.lower() in tuple(x.lower() for x in extra)

def plane_nachpflege(shop, ov):
    """Fest eingebaute, zugeordnete Produkte ohne Beschreibung: fehlende Felder
    (notes, keyIngredients, dosage, ggf. kcal/Protein) aus der Shop-Beschreibung
    ziehen. Nur leere Felder werden gefüllt; bestehende Overrides und in der
    index.html gepflegte Werte bleiben unangetastet."""
    basis = load_index_products()
    if not basis or not _BASIS_FRESH:
        print("\nNachpflege Beschreibungen übersprungen: index.html nicht frisch ladbar")
        print("(Zwischenspeicher reicht dafür nicht — beim nächsten Lauf erneut).")
        return {}
    pflege = {}
    for uid, m in MAPPING.items():
        b = basis.get(uid)
        if not b: continue  # kein fest eingebautes Produkt
        p = shop.get(m["shop_product_id"])
        body = p.get("body_html") if p else None
        if not body: continue
        o = ov.get(uid) or {}
        info = parse_desc(body, title_grams(p["title"]))
        entry = {}
        if _leer(o["notes"] if "notes" in o else b.get("notes")):
            sd = short_desc(body, name=b.get("name", ""))
            if len(sd) > 40: entry["notes"] = sd
        if ("keyIngredients" not in o) and not b.get("hasKeyIngredients") and info.get("keyIngredients"):
            entry["keyIngredients"] = info["keyIngredients"]
        if _leer(o["dosage"] if "dosage" in o else b.get("dosage"),
                 extra=("Laut Produktetikett",)) and info.get("dosage"):
            entry["dosage"] = info["dosage"]
        for k in ("kcalPortion", "proteinPortion"):
            if k not in o and _leer(b.get(k)) and info.get(k) is not None:
                entry[k] = info[k]
        if entry: pflege[uid] = entry
    return pflege

def ergaenze_feld(entry, feld, basiswert, neue, trenner=", "):
    """Hängt neue Werte an ein Feld an, ohne Vorhandenes zu verlieren.
    Gibt die tatsächlich ergänzten Werte zurück (leer = nichts zu tun)."""
    eff = entry.get(feld)
    if eff is None: eff = basiswert
    vorhanden = [x.strip() for x in re.split(r"[/,]", str(eff or "")) if x.strip() and x.strip() != "–"]
    add = [n.strip() for n in neue if n.strip() and n.strip().lower() not in [v.lower() for v in vorhanden]]
    if not add: return []
    entry[feld] = trenner.join(vorhanden + add)
    return add

def load_known():
    try:
        with open("shop_bekannt.json", encoding="utf-8") as f: return json.load(f)
    except Exception: return None

def save_known(d):
    with open("shop_bekannt.json", "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)

def main():
    write="--write" in sys.argv
    vergiss=None
    if "--vergiss" in sys.argv:
        i=sys.argv.index("--vergiss")
        if i+1 < len(sys.argv): vergiss=sys.argv[i+1]
        else:
            print("Bitte Suchtext angeben:  --vergiss \"Churros\""); return
    unsere={str(u["id"]):u for u in UNSERE}
    print(f"Feste Zuordnungen: {len(MAPPING)} | Bewusst ausgenommen: {len(SKIP)}")
    print("Lade Shop-Produkte...")
    shop=load_shop()
    print(f"Shop: {len(shop)} Produkte\n")

    ov={}
    try:
        rows=http_json(SB_BASE+"/app_config?key=eq.product_overrides&select=value",headers=SB_H)
        if rows and rows[0].get("value"): ov=rows[0]["value"]
    except Exception as e:
        print("Warnung: Overrides nicht ladbar:",e)

    custom_read=[]
    try:
        rows=http_json(SB_BASE+"/app_config?key=eq.custom_products&select=value",headers=SB_H)
        if rows and rows[0].get("value") and isinstance(rows[0]["value"],list): custom_read=rows[0]["value"]
    except Exception as e:
        print("Warnung: eigene Produkte nicht ladbar:",e)

    diffs=[]; missing=[]
    for uid,m in MAPPING.items():
        u=unsere.get(uid)
        if not u: continue
        p=shop.get(m["shop_product_id"])
        if not p or not p.get("variants"):
            missing.append((uid,u["name"],m["shop_title"])); continue
        shop_price=float(p["variants"][0]["price"])
        o=ov.get(uid) or {}
        eff=o.get("price",u.get("price"))
        try: eff=float(str(eff).replace(",","."))
        except Exception: eff=None
        if eff is None or abs(eff-shop_price)>=0.01:
            diffs.append((int(uid),u["name"],u.get("packageSize"),eff,shop_price))

    diffs.sort()
    print(f"Abweichungen: {len(diffs)}\n")
    if diffs:
        print(f'{"ID":>4}  {"Produkt":<44} {"Größe":<22} {"Bei uns":>9} {"Im Shop":>9}')
        for pid,name,size,eff,sp in diffs:
            eff_s=(f"{eff:.2f}".replace(".",",") if eff is not None else "?")
            print(f"{pid:>4}  {name[:44]:<44} {(size or "")[:22]:<22} {eff_s:>9} {f'{sp:.2f}'.replace('.',','):>9}")
    if missing:
        print("\nZugeordnete Produkte, die der Shop-Feed gerade nicht liefert:")
        for uid,name,st in missing: print(f"  #{uid} {name}  (erwartet: {st})")
    print("\nBewusst nicht synchronisiert:")
    for uid,reason in SKIP.items(): print(f"  #{uid} {reason}")

    # ── Neue Shop-Produkte erkennen ──
    known = load_known()
    mapped_ids = set(m["shop_product_id"] for m in MAPPING.values())
    if "--nachholen" in sys.argv and known is not None:
        # Beim allerersten Lauf wurde der komplette Shop als "bekannt" gespeichert.
        # Damit fehlen bis heute alle Artikel, die damals schon im Shop standen und
        # nicht in MAPPING sind. --nachholen behandelt sie einmalig als neu.
        print("\nNACHHOLEN: alle nicht zugeordneten Shop-Produkte werden als neu behandelt.")
        known["ids"] = []
    first_run = known is None
    if first_run:
        known = {"ids": sorted(shop.keys()), "added": {}}
        new_products = []
        print("\nErster Lauf: aktueller Shop-Stand wird als Basis gespeichert.")
        print("Ab dem nächsten Lauf werden neu hinzugekommene Shop-Produkte erkannt.")
    else:
        known_ids = set(known.get("ids", []))
        if vergiss:
            hits=[p for pid,p in shop.items() if vergiss.lower() in p["title"].lower() and pid not in mapped_ids]
            if not hits:
                print(f"\nTEST: kein unzugeordnetes Shop-Produkt passt auf '{vergiss}'.")
            else:
                p=hits[0]
                known_ids.discard(p["id"])
                print(f"\nTEST: '{p['title']}' wird für diesen Lauf als neu behandelt.")
                if len(hits)>1:
                    print(f"      ({len(hits)} Treffer, verwendet wird der erste)")
        new_products = [p for pid,p in shop.items() if pid not in known_ids and pid not in mapped_ids]
    new_products = [p for p in new_products if (p.get("product_type") or "") not in IGNORE_TYPES]
    anlegen, geschmack, groessen, ignoriert = plane_neuzugaenge(new_products, unsere, custom_read)
    if new_products:
        print(f"\nNeue Produkte im Shop ({len(new_products)}):")
        for p in new_products:
            print(f"  + {p['title']}  ({p['variants'][0]['price']} EUR, Typ: {p.get('product_type') or '?'})")
        if anlegen:
            print("\nWird als eigenes Produkt angelegt:")
            for p, name in anlegen: print(f"  {name}   (aus: {p['title']})")
        if geschmack:
            print("\nNur neuer Geschmack — wird beim bestehenden Produkt ergänzt:")
            for g in geschmack:
                ziel = ("#" + g["ziel"]) if g["art"] == "builtin" else g["ziel"]
                print(f"  {g['geschmack']}  ->  {g['zielname']} ({ziel})")
        if groessen:
            print("\nNur neue Packungsgröße — wird beim bestehenden Produkt ergänzt:")
            for g in groessen:
                ziel = ("#" + g["ziel"]) if g["art"] == "builtin" else g["ziel"]
                zus = f" + Geschmack {g['geschmack']}" if g["geschmack"] else ""
                print(f"  {g['groesse']}{zus}  ->  {g['zielname']} ({ziel})")
        if ignoriert:
            print("\nÜbersprungen:")
            for p, grund in ignoriert: print(f"  {p['title']} — {grund}")
        if not write:
            print("\nMit --write werden diese Änderungen übernommen.")

    # Preis- und Namenspflege für früher automatisch übernommene Produkte.
    # Quelle sind nicht nur die selbst angelegten (known["added"]), sondern alle
    # eigenen Produkte mit einer Shop-ID im Schlüssel — auch von Hand eingepflegte.
    auto_updates = []
    gesehen = set()
    quellen = dict(known.get("added") or {})
    try:
        _rows = http_json(SB_BASE + "/app_config?key=eq.custom_products&select=value", headers=SB_H)
        _cur = _rows[0]["value"] if _rows and _rows[0].get("value") else []
        if isinstance(_cur, list):
            for c in _cur:
                cid = str(c.get("id") or "")
                if cid.startswith("shop-") and cid[5:].isdigit():
                    quellen.setdefault(cid[5:], cid)
    except Exception as e:
        print("Hinweis: eigene Produkte für die Preispflege nicht lesbar (%s)" % e)
    for spid, cid in quellen.items():
        if cid in gesehen: continue
        gesehen.add(cid)
        p = shop.get(int(spid))
        if p and p.get("variants"):
            auto_updates.append((cid, p))

    # ── Nachpflege: Beschreibungen für Bestandsprodukte ──
    pflege = plane_nachpflege(shop, ov)
    if pflege:
        print(f"\nNachpflege Beschreibungen ({len(pflege)} Produkte ohne gepflegte Felder):")
        for uid in sorted(pflege, key=int):
            felder = ", ".join(sorted(pflege[uid].keys()))
            print(f"  #{uid} {unsere.get(uid, {}).get('name', '?')}: {felder}")
        if not write:
            print("Mit --write werden diese Felder aus der Shop-Beschreibung gefüllt.")

    if not write:
        if first_run: save_known(known)
        print("\nTrockenlauf beendet — es wurde NICHTS in die Datenbank geschrieben.")
        print("Zum Übernehmen:  python preis_sync.py --write")
        return
    unerledigt = set()
    builtin_add = [g for g in geschmack + groessen if g["art"] == "builtin"]
    if diffs or builtin_add or pflege:
        print("\nSchreibe Overrides nach Supabase...")
        rows=http_json(SB_BASE+"/app_config?key=eq.product_overrides&select=value",headers=SB_H)
        base=rows[0]["value"] if rows and rows[0].get("value") else {}
        for pid,name,size,eff,sp in diffs:
            entry=dict(base.get(str(pid)) or {})
            entry["price"]=round(sp,2)
            base[str(pid)]=entry
        npf=0
        for uid, felder in pflege.items():
            entry=dict(base.get(uid) or {})
            neu={k:v for k,v in felder.items() if k not in entry}
            if not neu: continue
            entry.update(neu)
            base[uid]=entry
            print(f"  #{uid}: {', '.join(sorted(neu))} nachgetragen")
            npf+=1
        erg=0
        for g in builtin_add:
            basis=(load_index_products() or {}).get(g["ziel"])
            entry=dict(base.get(g["ziel"]) or {})
            if basis is None and ("flavors" not in entry or "packageSize" not in entry):
                print(f"  Basisdaten fehlen — #{g['ziel']} wird beim nächsten Lauf nachgeholt.")
                unerledigt.add(g["shop_id"]); continue
            basis = basis or {}
            gemacht=[]
            if g.get("groesse"):
                neu=ergaenze_feld(entry,"packageSize",basis.get("packageSize"),[g["groesse"]]," / ")
                if neu: gemacht.append("Größe "+", ".join(neu))
            if g.get("geschmack"):
                neu=ergaenze_feld(entry,"flavors",basis.get("flavors"),g["geschmack"].split(","))
                if neu: gemacht.append("Geschmack "+", ".join(neu))
            if not gemacht: continue
            base[g["ziel"]]=entry
            print(f"  #{g['ziel']} {g['zielname']}: {'; '.join(gemacht)} ergänzt")
            erg+=1
        payload=json.dumps({"key":"product_overrides","value":base,
            "updated_at":time.strftime("%Y-%m-%dT%H:%M:%SZ",time.gmtime())}).encode()
        req=urllib.request.Request(SB_BASE+"/app_config",data=payload,method="POST",
            headers={**SB_H,"Prefer":"resolution=merge-duplicates,return=minimal"})
        urllib.request.urlopen(req,timeout=30)
        if diffs: print(f"Fertig: {len(diffs)} Preise aktualisiert.")
        if erg: print(f"Bestehende Produkte ergänzt: {erg}.")
        if npf: print(f"Beschreibungen nachgetragen: {npf}.")
    else:
        print("\nKeine Preisabweichungen.")

    # ── Neue Produkte als custom_products übernehmen (merge-basiert) ──
    custom_add = [g for g in geschmack + groessen if g["art"] == "custom"]
    if anlegen or auto_updates or custom_add:
        rows = http_json(SB_BASE + "/app_config?key=eq.custom_products&select=value", headers=SB_H)
        cur = rows[0]["value"] if rows and rows[0].get("value") else []
        if not isinstance(cur, list): cur = []
        by_id = {str(c.get("id")): c for c in cur}
        taken = {norm_name(u["name"]) for u in UNSERE} | {norm_name(c.get("name")) for c in cur}
        added_now = 0
        for p, name in anlegen:
            cid = "shop-" + str(p["id"])
            if cid in by_id: continue
            base_name, size = split_title(p["title"])
            taken.add(norm_name(name))
            pr = float(p["variants"][0]["price"])
            flavors = ", ".join(variant_flavors(p, 10)) or "–"
            info = parse_desc(p.get("body_html"), title_grams(p["title"]))
            cur.append({
                "id": cid, "custom": True,
                "name": name, "category": TYPE_TO_CAT.get(p.get("product_type") or "", "Zubehör"),
                "subcategory": p.get("product_type") or "",
                "price": pr, "priceRange": price_range(pr),
                "packageSize": size, "portionSize": info.get("portionSize", "–"), "kcalPortion": info.get("kcalPortion", "–"),
                "proteinPortion": info.get("proteinPortion", "–"), "fatPortion": info.get("fatPortion", "–"), "carbsPortion": info.get("carbsPortion", "–"),
                "vegan": bool(info.get("vegan")), "freeFrom": [], "keyIngredients": info.get("keyIngredients", []),
                "flavors": flavors, "dosage": info.get("dosage", "–"),
                # Der Hinweistext gehoert NICHT in notes: notes wird in der Seite
                # angezeigt und im Quiz als Antwortoption verwendet.
                "notes": short_desc(p.get("body_html"), name=base_name).strip(),
                "autoImport": time.strftime("%Y-%m-%d"),
                "studies": [],
            })
            known["added"][str(p["id"])] = cid
            added_now += 1
        # Neue Geschmäcker und Größen bei bereits vorhandenen eigenen Produkten
        fl_upd = 0
        for g in custom_add:
            c = by_id.get(g["ziel"])
            if not c:
                unerledigt.add(g["shop_id"]); continue
            gemacht = []
            if g.get("groesse"):
                neu = ergaenze_feld(c, "packageSize", c.get("packageSize"), [g["groesse"]], " / ")
                if neu: gemacht.append("Größe " + ", ".join(neu))
            if g.get("geschmack"):
                neu = ergaenze_feld(c, "flavors", c.get("flavors"), g["geschmack"].split(","))
                if neu: gemacht.append("Geschmack " + ", ".join(neu))
            if not gemacht: continue
            print(f"  {c.get('name')}: {'; '.join(gemacht)} ergänzt")
            fl_upd += 1

        # Preise früher übernommener Produkte aktuell halten,
        # Limited-Edition-Kennzeichnung nachziehen
        upd = 0; renamed = 0
        for cid, p in auto_updates:
            c = by_id.get(cid)
            if not c: continue
            pr = float(p["variants"][0]["price"])
            if abs(float(c.get("price") or 0) - pr) >= 0.01:
                c["price"] = pr; c["priceRange"] = price_range(pr); upd += 1
            base_name = split_title(p["title"])[0]
            soll = final_name(p, base_name, taken - {norm_name(c.get("name"))})
            # nur nachbessern, solange der Name noch der automatisch vergebene ist
            if norm_name(c.get("name")) == norm_name(base_name) and soll != c.get("name"):
                print(f"  Umbenannt: {c.get('name')} -> {soll}")
                c["name"] = soll; renamed += 1
            # Geschmack aus der Packungsgröße lösen ("300 g Drachenfrucht-Litschi")
            g_size, g_flavor = parse_size_flavor(c.get("packageSize"))
            if g_flavor:
                c["packageSize"] = g_size
                alt_fl = (c.get("flavors") or "").strip()
                if not alt_fl or alt_fl == "–": c["flavors"] = g_flavor
                elif g_flavor.lower() not in alt_fl.lower(): c["flavors"] = alt_fl + ", " + g_flavor
                print(f"  Packungsgröße bereinigt bei {c.get('name')}: {g_size} | Geschmack: {c['flavors']}")
                renamed += 1
        payload = json.dumps({"key": "custom_products", "value": cur,
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}).encode()
        req = urllib.request.Request(SB_BASE + "/app_config", data=payload, method="POST",
            headers={**SB_H, "Prefer": "resolution=merge-duplicates,return=minimal"})
        urllib.request.urlopen(req, timeout=30)
        if added_now: print(f"Neu in die Datenbank aufgenommen: {added_now} Produkte.")
        if upd: print(f"Preise automatisch übernommener Produkte aktualisiert: {upd}.")
        if renamed: print(f"Namen nachträglich gekennzeichnet: {renamed}.")
        if fl_upd: print(f"Eigene Produkte ergänzt: {fl_upd}.")
    # Basis aktualisieren: alles, was der Shop jetzt führt, gilt als bekannt.
    # Nicht erledigte Fälle bleiben offen und kommen beim nächsten Lauf wieder.
    known["ids"] = sorted(pid for pid in shop.keys() if pid not in unerledigt)
    save_known(known)
    print("Die Seite übernimmt alles innerhalb von 10 Sekunden.")

if __name__=="__main__":
    main()
