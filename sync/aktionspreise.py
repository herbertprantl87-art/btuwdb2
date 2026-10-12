# -*- coding: utf-8 -*-
"""
Monatsangebote automatisch in die Wissensdatenbank uebernehmen.

Was das Skript macht
--------------------
1. Liest die Aktionsseiten des offiziellen Shops
   (shop.biotechusa.de/collections/monatsaktion und /aktionsprodukte).
   Dort stehen Shop-ID, Aktionspreis und Rabatt-Badge im HTML.
   Der Produktfeed products.json liefert nur die Normalpreise.
2. Ordnet die Aktionsprodukte unseren Produkten zu:
   zuerst ueber die verifizierte MAPPING-Tabelle aus preis_sync.py,
   dann ueber EXTRA_MAP, zuletzt ueber Name + Packungsgroesse.
3. Schreibt die Aktionspreise nach Supabase (app_config, Key "sale_prices").
   Die Seite zeigt sie nur in Kategorien mit Haken "Angebotskategorie".
4. Pflegt bei jedem Lauf die Kategorie des aktuellen Monats:
   - Kategorie "Monatsangebote <aktueller Monat>" fehlt  -> wird angelegt,
     mit den Aktionsprodukten und Haken "Angebotskategorie".
   - Kategorie ist schon vorhanden -> Produktliste bleibt unangetastet,
     nur die Preise werden aktualisiert.

Aufruf
------
python aktionspreise.py                  Probelauf, schreibt nichts
python aktionspreise.py --write          schreibt nach Supabase
python aktionspreise.py --monat Oktober  Monat fuer Tests erzwingen
"""
import ast
import datetime
import json
import os
import re
import sys
import time
import urllib.request
import uuid

# ── Einstellungen ────────────────────────────────────────────────────────
CAT_PREFIX = "Monatsangebote "   # Kategoriename = Prefix + Monat
CAT_EMOJI = "\U0001F3F7\uFE0F"   # Preisschild
CAT_GEBIET = "NRW/Hessen-Herbert"
CAT_ERSTELLER = "aktionspreise.py"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
SHOP = "https://shop.biotechusa.de"
COLLECTIONS = ["monatsaktion", "aktionsprodukte"]
INDEX_URL = "https://raw.githubusercontent.com/herbertprantl87-art/btuwdb2/main/index.html"
BASIS_CACHE = "aktionspreise_produkte.json"   # Zwischenspeicher, falls GitHub bremst
SB_URL = "https://mejwpbahcmlkwajkymnj.supabase.co/rest/v1/app_config"
SB_KEY = ("eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Im1landwYmFoY21sa3dhamt5bW5qIi"
          "wicm9sZSI6ImFub24iLCJpYXQiOjE3Nzc4MzQ2OTAsImV4cCI6MjA5MzQxMDY5MH0."
          "rzt-EiWxy8poy0vs00eEVvs-GYab9VOoiTAsrEScCrE")

MONATE = ["Januar", "Februar", "M\u00e4rz", "April", "Mai", "Juni",
          "Juli", "August", "September", "Oktober", "November", "Dezember"]

# Shop-Titel, die von unserem Produktnamen abweichen: Shop-ID -> unsere Produkt-ID.
# Hier eintragen, wenn das Skript ein Aktionsprodukt als "offen" meldet.
EXTRA_MAP = {}


# ── Netz ─────────────────────────────────────────────────────────────────
def log(text):
    """Ausgabe sofort schreiben, damit man den Fortschritt auch im Log sieht."""
    print(text, flush=True)


def fetch(url, tries=3, warten=20):
    last = None
    kurz = url.replace(SHOP, "").split("?")[0][:60] or url[:60]
    for i in range(tries):
        try:
            start = time.time()
            req = urllib.request.Request(url, headers={"User-Agent": UA,
                                                      "Accept-Language": "de-DE,de;q=0.9"})
            daten = urllib.request.urlopen(req, timeout=45).read().decode("utf-8", "ignore")
            log("    geladen: %-42s %6.1f s, %d KB" % (kurz, time.time() - start, len(daten) // 1024))
            return daten
        except Exception as e:
            last = e
            log("    Versuch %d von %d fehlgeschlagen: %s (%s)" % (i + 1, tries, kurz, e))
            if i < tries - 1:
                log("    warte %d Sekunden ..." % warten)
                time.sleep(warten)
    raise last


def sb(method, query, body=None):
    req = urllib.request.Request(
        SB_URL + query, method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"apikey": SB_KEY, "Authorization": "Bearer " + SB_KEY,
                 "Content-Type": "application/json", "Prefer": "return=minimal"})
    r = urllib.request.urlopen(req, timeout=40)
    txt = r.read().decode()
    return json.loads(txt) if txt.strip() else []


def sb_config(key):
    rows = sb("GET", "?key=eq.%s&select=value" % key)
    if not rows:
        return None
    v = rows[0]["value"]
    return json.loads(v) if isinstance(v, str) else v


def sb_config_schreiben(key, wert):
    jetzt = datetime.datetime.now(datetime.timezone.utc).isoformat()
    if sb("GET", "?key=eq.%s&select=key" % key):
        sb("PATCH", "?key=eq.%s" % key, {"value": wert, "updated_at": jetzt})
    else:
        sb("POST", "", [{"key": key, "value": wert, "updated_at": jetzt}])


# ── 1. Aktionspreise von den Shop-Aktionsseiten ──────────────────────────
def shop_aktionen():
    """Gibt die Aktionsprodukte zurueck und die Zahl der Seiten, die nicht
    geladen werden konnten. Bei Fehlern darf nichts geschrieben werden, sonst
    wuerde eine Shop-Sperre die vorhandenen Aktionspreise loeschen."""
    out = {}
    fehler = 0
    for handle in COLLECTIONS:
        log("  Aktionsseite /%s laden ..." % handle)
        try:
            html = fetch(SHOP + "/collections/" + handle)
        except Exception as e:
            log("  Warnung: %s nicht erreichbar (%s)" % (handle, e))
            fehler += 1
            continue
        for blk in re.split(r'<div data-id="', html)[1:]:
            sid = blk[:blk.find('"')]
            if not sid.isdigit() or "product-on-sale" not in blk[:600]:
                continue
            pm = re.search(r'data-cnstrc-item-price="(\d+),(\d{2})', blk)
            if not pm:
                continue
            nm = re.search(r'data-cnstrc-item-name="([^"]*)"', blk)
            pct = re.search(r'class="on-sale">-(\d+)%', blk[:4000])
            out[int(sid)] = {"aktion": float(pm.group(1) + "." + pm.group(2)),
                             "name": nm.group(1) if nm else "",
                             "pct": int(pct.group(1)) if pct else None}
    return out, fehler


# ── 2. Normalpreise aus dem Produktfeed ──────────────────────────────────
def shop_feed():
    feed = {}
    for page in (1, 2, 3, 4):
        log("  Produktfeed Seite %d laden ..." % page)
        data = json.loads(fetch(SHOP + "/products.json?limit=250&page=%d" % page))["products"]
        if not data:
            break
        for pr in data:
            feed[pr["id"]] = {"titel": pr["title"],
                              "preis": min(float(v["price"]) for v in pr["variants"])}
    return feed


# ── 3. Unsere Produkte aus der index.html ────────────────────────────────
def wdb_produkte():
    """Produkte aus der index.html. Ergebnis wird lokal zwischengespeichert,
    damit ein 429 von GitHub den Lauf nicht abbricht (der Preis-Sync laedt
    dieselbe Datei kurz vorher, deshalb kommt die Sperre schnell)."""
    log("  index.html von GitHub laden ...")
    html = None
    try:
        html = fetch(INDEX_URL, tries=2, warten=15)
    except Exception as e:
        log("  index.html nicht ladbar (%s), versuche Zwischenspeicher." % e)
    if html:
        prods = _produkte_parsen(html)
        prods += _eigene_produkte()
        if prods:
            try:
                with open(BASIS_CACHE, "w", encoding="utf-8") as f:
                    json.dump(prods, f, ensure_ascii=False)
            except Exception:
                pass
            return prods
        log("  index.html gelesen, aber keine Produkte erkannt.")
    try:
        with open(BASIS_CACHE, encoding="utf-8") as f:
            prods = json.load(f)
        log("  Produkte aus dem Zwischenspeicher %s (%d Stueck)." % (BASIS_CACHE, len(prods)))
        return prods
    except Exception:
        raise RuntimeError("Produkte weder von GitHub noch aus %s ladbar" % BASIS_CACHE)


def _eigene_produkte():
    """Produkte aus app_config.custom_products. Sie haben Text-IDs
    (shop-<Shop-ID>) und stehen nicht in der index.html."""
    try:
        cp = sb_config("custom_products") or []
    except Exception as e:
        log("  Hinweis: eigene Produkte nicht lesbar (%s)." % e)
        return []
    out = []
    for c in cp:
        if not isinstance(c, dict) or not c.get("id"):
            continue
        try:
            preis = float(c.get("price")) if c.get("price") is not None else None
        except Exception:
            preis = None
        out.append({"id": str(c["id"]), "name": c.get("name") or "",
                    "size": c.get("packageSize") or "", "price": preis,
                    "refOnly": bool(c.get("refOnly"))})
    if out:
        log("  eigene Produkte aus Supabase: %d" % len(out))
    return out


def pid_out(v):
    """Fuer das Schreiben nach Supabase: Zahlen-IDs bleiben Zahlen, damit der
    Vergleich in der Seite (===) weiter passt. Text-IDs bleiben Text."""
    t = str(v)
    return int(t) if t.isdigit() else t


def pid_sort(v):
    """Sortierung fuer Produkt-IDs: Zahlen numerisch, Text-IDs dahinter."""
    t = str(v)
    return (0, int(t), "") if t.isdigit() else (1, 0, t)


def _produkte_parsen(html):
    start = html.find("var PRODUCTS = [")
    ende = html.find("\n];", start)
    if start < 0 or ende < 0:
        return []
    body = html[start:ende]
    prods = []
    for m in re.finditer(r'\n    id: (\d+),(.{0,600}?)\n    category:', body, re.S):
        pid = m.group(1)          # als Text, es gibt auch IDs wie "shop-14976809632070"
        chunk = m.group(2)
        nm = re.search(r'name: "((?:[^"\\]|\\.)*)"', chunk)
        sz = re.search(r'packageSize: "((?:[^"\\]|\\.)*)"', chunk)
        pr = re.search(r'price: ([\d.]+)', chunk)
        prods.append({"id": pid,
                      "name": nm.group(1) if nm else "",
                      "size": sz.group(1) if sz else "",
                      "price": float(pr.group(1)) if pr else None,
                      "refOnly": "refOnly: true" in chunk})
    return prods


# ── 4. Zuordnung Shop-Produkt -> unsere Produkte ─────────────────────────
FORM = ["getr\u00e4nkepulver", "proteinpulver", "pulver", "kapseln", "kapsel", "softgel",
        "tabletten", "tablette", "tbl", "ampulle", "ampullen", "shot", "shots",
        "aromatisiertes", "riegel", "drops", "kautabletten", "tabs", "tab", "caps", "db", "stk"]


def norm(s):
    s = s.lower()
    s = s.replace("\u00e4", "ae").replace("\u00f6", "oe").replace("\u00fc", "ue").replace("\u00df", "ss")
    s = re.sub(r"\(.*?\)", " ", s)
    s = re.sub(r"[^a-z0-9%+ ]", " ", s)
    for w in FORM:
        s = s.replace(w.replace("\u00e4", "ae"), " ")
    return " ".join(s.split())


def groesse(s):
    m = re.search(r"(\d+[\d.,]*)\s*(g|kg|ml|l|tbl|tabs|tab|kautabletten|kapseln|kaps|caps|tabletten|st\u00fcck|softgel)", s.lower())
    if not m:
        return None
    zahl = m.group(1).replace(".", "").replace(",", ".")
    einheit = {"tbl": "tbl", "tabs": "tbl", "tab": "tbl", "tabletten": "tbl",
               "kautabletten": "tbl", "kapseln": "kaps", "kaps": "kaps",
               "caps": "kaps", "softgel": "kaps"}.get(m.group(2), m.group(2))
    try:
        return (float(zahl), einheit)
    except ValueError:
        return None


def lade_mapping():
    """Verifizierte Zuordnung aus preis_sync.py: Shop-ID -> Liste unserer IDs.

    Die Tabelle wird aus dem Dateitext gelesen, nicht importiert: ein Import
    von preis_sync wuerde dessen Report-Datei ueberschreiben.
    """
    rev = {}
    pfad = os.path.join(os.path.dirname(os.path.abspath(__file__)), "preis_sync.py")
    try:
        baum = ast.parse(open(pfad, encoding="utf-8").read())
        mp = None
        for knoten in baum.body:
            if isinstance(knoten, ast.Assign) and any(
                    getattr(z, "id", None) == "MAPPING" for z in knoten.targets):
                mp = json.loads(ast.literal_eval(knoten.value.args[0]))
                break
        if mp is None:
            raise ValueError("MAPPING nicht gefunden")
        for unsere, eintrag in mp.items():
            sid = eintrag.get("shop_product_id") if isinstance(eintrag, dict) else eintrag
            if sid:
                rev.setdefault(int(sid), []).append(str(unsere))
    except Exception as e:
        log("  Hinweis: MAPPING aus preis_sync.py nicht lesbar (%s), Zuordnung nur \u00fcber Namen." % e)
    return rev


def zuordnen(shop_id, shop_titel, prods, rev):
    if shop_id in rev:
        return sorted(rev[shop_id], key=pid_sort), "MAPPING"
    if shop_id in EXTRA_MAP:
        return [EXTRA_MAP[shop_id]], "EXTRA_MAP"
    st = norm(shop_titel.split(" - ")[0])
    sg = groesse(shop_titel)
    treffer, ohne_groesse = [], []
    for p in prods:
        if norm(p["name"]) != st:
            continue
        pg = groesse(p["size"] or "")
        if sg and pg and sg != pg:
            continue
        if sg and not pg:
            ohne_groesse.append(p)
            continue
        treffer.append(p)
    if not treffer and len(ohne_groesse) == 1:
        return [ohne_groesse[0]["id"]], "Name (Gr\u00f6\u00dfe fehlt in der WDB)"
    if len(treffer) == 1:
        return [treffer[0]["id"]], "Name+Gr\u00f6\u00dfe"
    if len(treffer) > 1:
        echte = [t for t in treffer if not t["refOnly"]] or treffer
        return [min(t["id"] for t in echte)], "Name+Gr\u00f6\u00dfe (mehrfach)"
    return [], "keine Zuordnung"


def basis_und_variante(pid, prods):
    """Referenz-Groessen (refOnly) haengen in der Kategorie am Hauptprodukt."""
    treffer = [x for x in prods if x["id"] == pid]
    if not treffer:
        return None, None
    p = treffer[0]
    if not p["refOnly"]:
        return pid, None
    basis = [x["id"] for x in prods if x["name"] == p["name"] and not x["refOnly"]]
    if basis:
        return sorted(basis, key=pid_sort)[0], pid
    return None, None


# ── 4b. Kombi-Angebote (mehrere Artikel zusammen) ──────────────────
# Shop-IDs aus /collections/pakete, die zusaetzlich als Monats-Kombi gelten sollen.
# Normalerweise nicht noetig: Kombis der Monatsaktion stehen in den Aktionsseiten.
KOMBI_IDS = []


PCT_ENDE = r"\s*[-\u2013]?\s*\d+\s*%\s*[-\u2013]?\s*\w*\s*$"


MENGE_PLUS = re.compile(r"(?<![\d,.])(\d{1,2})\s*\+\s*(\d{1,2})(?![\d,.])")
MENGE_MAL = re.compile(r"(?<![\d,.])(\d{1,2})\s*[x*\u00d7]\s*(\d{1,4}\s*(?:g|ml))\b", re.I)


def ist_kombi(titel):
    """Kombi ist alles, was mehrere Artikel oder mehrere Packungen buendelt."""
    kern = re.sub(PCT_ENDE, "", titel.split(" - ")[0])
    if (" + " in kern) or (" & " in kern):
        return True
    return bool(MENGE_PLUS.search(titel) or MENGE_MAL.search(titel))


# Titelteile aus Kombi-Angeboten, die auf mehrere Produkte passen und deshalb
# von Hand zugeordnet werden. Links der Titelteil (klein, ohne Sonderzeichen),
# rechts unsere Produkt-ID. Neue Faelle einfach hier ergaenzen.
KOMBI_NAMEN = {
    "one a day":               "37",    # One A Day-Multivitamin, nicht Kids/Professional/50+
    "one a day multivitamin":  "37",
    "maenner vitamin allrounder bundle": None,   # kein einzelnes Produkt
    "frauen vitamin allrounder bundle":  None,
}


def teil_zuordnen(text, prods):
    """Einen Titelteil wie '1 db One-a-day 100 tabs' einem Produkt zuordnen."""
    text = re.sub(r"^\s*\d+\s*(db|x|stk|st\u00fcck)\s*", "", text, flags=re.I).strip()
    if not text:
        return None
    tn = norm(text)
    # feste Zuordnung geht vor der Namenssuche
    if tn in KOMBI_NAMEN:
        fest = KOMBI_NAMEN[tn]
        if fest is None:
            return None
        if any(str(x["id"]) == str(fest) for x in prods):
            return str(fest)
        log("  Hinweis: feste Kombi-Zuordnung \"%s\" zeigt auf #%s, das Produkt gibt es nicht."
            % (text, fest))
        return None
    tg = groesse(text)
    if not tn:
        return None
    # "one a day 100" -> zusaetzlich ohne die angehaengte Zahl vergleichen
    tn_kurz = re.sub(r"\s*\d+[\d.,]*\s*$", "", tn).strip()
    treffer = []
    for p in prods:
        pn = norm(p["name"])
        if not pn:
            continue
        passt = (pn == tn or tn.startswith(pn + " ") or pn.startswith(tn + " ")
                 or (tn_kurz and (pn == tn_kurz or pn.startswith(tn_kurz + " "))))
        if passt:
            pg = groesse(p["size"] or "")
            if tg and pg and tg != pg:
                continue
            exakt = 0 if p["name"].strip().lower() == text.strip().lower() else 1
            treffer.append((p, exakt, 0 if pn == tn else 1, 0 if not p["refOnly"] else 1))

    if not treffer:
        return None
    if tg:
        mit = [t for t in treffer if groesse(t[0]["size"] or "") == tg]
        if mit:
            treffer = mit
    treffer.sort(key=lambda t: (t[1], t[2], t[3], pid_sort(t[0]["id"])))
    beste = [t for t in treffer if (t[1], t[2], t[3]) == (treffer[0][1], treffer[0][2], treffer[0][3])]
    if len(beste) > 1:
        return None          # nicht eindeutig, lieber melden als raten
    return beste[0][0]["id"]


def mengen_bauen(sid, titel, aktion, normal, pct, prods):
    """Mehrfachpack eines Artikels, z. B. 'Protein Bar 3+1' oder
    'Iso Whey Zero Sample Bundle - 17*25 g'. Gibt (Eintrag, offene Teile) zurueck."""
    menge = gratis = None
    rest = titel
    m = MENGE_PLUS.search(titel)
    if m:
        zahle, gratis = int(m.group(1)), int(m.group(2))
        menge = zahle + gratis
        rest = titel[:m.start()] + " " + titel[m.end():]
    else:
        m = MENGE_MAL.search(titel)
        if m:
            menge = int(m.group(1))
            rest = titel[:m.start()] + " " + m.group(2) + " "
    if not menge or menge < 2:
        return None, []
    rest = re.sub(PCT_ENDE, "", rest.split(" - ")[0])
    rest = re.sub(r"\b(bundle|paket|set|pack)\b", " ", rest, flags=re.I)
    pid = teil_zuordnen(rest, prods)
    if pid is None:
        return None, [rest.strip()]
    if not pct and normal and aktion:
        pct = int(round((1 - aktion / normal) * 100))
    eintrag = {"id": "shop-%d" % sid, "produkte": [pid_out(pid)], "menge": menge,
               "gratis": gratis, "text": titel.strip(), "preis": aktion,
               "pct": pct or None, "quelle": "shop", "shop_id": sid}
    return eintrag, []


def kombi_bauen(sid, titel, aktion, normal, pct, prods):
    if MENGE_PLUS.search(titel) or MENGE_MAL.search(titel):
        eintrag, offen = mengen_bauen(sid, titel, aktion, normal, pct, prods)
        if eintrag:
            return eintrag, []
        if offen:
            return None, offen
    kern = re.sub(PCT_ENDE, "", titel.split(" - ")[0])
    # "A + B + C from organic sources" meint die organic-Variante aller Teile,
    # nicht nur des letzten. Sonst landet die Kombi beim falschen Produkt.
    organic = bool(re.search(r"from organic sources\s*$", kern, re.I))
    if organic:
        kern = re.sub(r"\s*from organic sources\s*$", "", kern, flags=re.I)
    teile = [t for t in re.split(r"\s*\+\s*|\s+&\s+", kern) if t.strip()]
    ids, offen = [], []
    for t in teile:
        pid = None
        if organic:
            pid = teil_zuordnen(t.strip() + " from organic sources", prods)
        if pid is None:
            pid = teil_zuordnen(t, prods)
        if pid is None:
            offen.append(t.strip())
        elif pid not in ids:
            ids.append(pid)
    if len(ids) < 2:
        return None, offen or teile
    if not pct and normal and aktion:
        pct = int(round((1 - aktion / normal) * 100))
    return {"id": "shop-%d" % sid, "produkte": [pid_out(i) for i in ids], "text": titel.strip(),
            "preis": aktion, "pct": pct or None, "quelle": "shop", "shop_id": sid}, offen


def shop_kombis(akt, feed, prods):
    """Aktionsprodukte, die aus mehreren Artikeln bestehen, als Kombis aufbereiten."""
    kombis, offen = [], []
    kandidaten = dict(akt)
    if KOMBI_IDS:
        for sid in KOMBI_IDS:
            if sid not in kandidaten and sid in feed:
                kandidaten[sid] = {"aktion": feed[sid]["preis"], "name": feed[sid]["titel"], "pct": None}
    for sid, a in sorted(kandidaten.items()):
        titel = feed.get(sid, {}).get("titel") or a["name"]
        if not ist_kombi(titel):
            continue
        b, fehlt = kombi_bauen(sid, titel, a["aktion"], feed.get(sid, {}).get("preis"), a["pct"], prods)
        if b:
            kombis.append(b)
            log("  Kombi: %-42s %6.2f  %sProdukte %s"
                % (titel[:42], a["aktion"],
                   ("%dx, davon %d gratis, " % (b["menge"], b["gratis"])) if b.get("gratis")
                   else (("%dx, " % b["menge"]) if b.get("menge") else ""),
                   ", ".join("#%s" % i for i in b["produkte"])))
        else:
            offen.append((sid, titel, fehlt))
            log("  Kombi offen: %-40s Shop-ID %s \u2013 nicht zuzuordnen: %s"
                % (titel[:40], sid, ", ".join(fehlt)))
    return kombis


# ── 5. Aktionspreise zusammenstellen ─────────────────────────────────────
def sale_prices_bauen(akt, feed, prods, rev):
    heute = datetime.date.today().isoformat()
    byid = {p["id"]: p for p in prods}
    neu, offen = {}, []
    for sid, a in sorted(akt.items()):
        titel = feed.get(sid, {}).get("titel") or a["name"]
        if ist_kombi(titel):
            continue          # Kombis laufen ueber shop_kombis()
        normal = feed.get(sid, {}).get("preis")
        ids, weg = zuordnen(sid, titel, prods, rev)
        if not ids:
            offen.append((sid, titel, a["aktion"], "keine Zuordnung"))
            continue
        for pid in ids:
            w = byid.get(pid)
            if not w:
                log("  Warnung: Zuordnung zeigt auf #%s, das Produkt fehlt in der index.html "
                    "(Zwischenspeicher veraltet?)." % pid)
                continue
            basis = normal if normal else w["price"]
            if basis and a["aktion"] >= basis:
                offen.append((sid, titel, a["aktion"],
                              "Aktionspreis nicht niedriger als %.2f" % basis))
                continue
            pct = a["pct"] or (int(round((1 - a["aktion"] / basis) * 100)) if basis else None)
            neu[str(pid)] = {"price": a["aktion"], "normal": basis, "pct": pct,
                             "shop_id": sid, "name": w["name"], "stand": heute}
            log("  #%-4s %-38s %6.2f statt %6.2f  (-%s%%)  [%s]"
                  % (pid, w["name"][:38], a["aktion"], basis or 0, pct, weg))
    for sid, titel, preis, grund in offen:
        log("  offen: %-50s Shop-ID %s, Aktion %.2f \u2013 %s"
              % (titel[:50], sid, preis, grund))
    return neu


# ── 6. Monatskategorie pflegen ───────────────────────────────────────────
def _produktmenge(kombi):
    return {str(x) for x in (kombi.get("produkte") or [])}


def _preis_gleich(a, b):
    try:
        pa = float(a.get("preis")) if a.get("preis") is not None else None
        pb = float(b.get("preis")) if b.get("preis") is not None else None
    except (TypeError, ValueError):
        return False
    return pa is not None and pb is not None and abs(pa - pb) < 0.01


def _passende_kombi(behalten, k):
    """Sucht zu einer Shop-Kombi das von Hand gepflegte Gegenstueck.
    Zuerst exakt ueber die Produkte, erst danach unscharf ueber Preis und
    Produktzahl, damit Maenner- und Frauen-Pakete nicht vertauscht werden."""
    pk = _produktmenge(k)
    if not pk:
        return None
    for b in behalten:
        if _produktmenge(b) == pk:
            return b
    for b in behalten:
        pb = _produktmenge(b)
        if not pb or len(pb) != len(pk) or not _preis_gleich(b, k):
            continue
        if len(pb & pk) >= len(pk) - 1:
            return b
    return None


def bundles_mischen(vorhandene, kombis):
    """Von Hand gepflegte Kombis bleiben, die aus dem Shop werden ersetzt.
    Shop-Kombis, die ein von Hand gepflegtes Angebot doppeln, fallen weg."""
    behalten = [b for b in (vorhandene or []) if b.get("quelle") != "shop"]
    neue = []
    for k in kombis:
        doppelt = _passende_kombi(behalten, k)
        if doppelt:
            log('    uebersprungen: "%s" ist schon von Hand angelegt als "%s"'
                % (str(k.get("text"))[:45], str(doppelt.get("text"))[:45]))
            continue
        neue.append(k)
    return behalten + neue


def monatsname(erzwingen=None):
    return erzwingen or MONATE[datetime.date.today().month - 1]


def kategorie_pflegen(sale, kombis, prods, monat, schreiben):
    name = CAT_PREFIX + monat
    log("  Kategorien aus Supabase lesen ...")
    cats = sb_config("custom_categories") or []
    if not isinstance(cats, list):
        log("  Warnung: custom_categories hat ein unerwartetes Format, nichts geaendert.")
        return
    treffer = [c for c in cats if str(c.get("name", "")).strip().lower() == name.lower()]

    if treffer:
        cat = treffer[0]
        vorhanden = set()
        for pid in cat.get("productIds") or []:
            v = (cat.get("productVariants") or {}).get(str(pid))
            vorhanden.add(str(v) if v is not None else str(pid))
        ohne_aktion = sorted((p for p in vorhanden if p not in sale), key=pid_sort)
        nicht_drin = sorted((p for p in sale if str(p) not in vorhanden), key=pid_sort)
        log('  Kategorie "%s" vorhanden (%d Produkte), Produktliste bleibt unver\u00e4ndert.'
              % (name, len(vorhanden)))
        if ohne_aktion:
            log("    ohne Aktionspreis diesen Monat: "
                  + ", ".join("#%s" % p for p in ohne_aktion))
        if nicht_drin:
            log("    im Shop rabattiert, aber nicht in der Kategorie: "
                  + ", ".join("#%s" % p for p in nicht_drin))
        neue_bundles = bundles_mischen(cat.get("bundles"), kombis)
        fehlende = []
        bereits = {str(x) for x in (cat.get("productIds") or [])}
        for b in kombis:
            for pid in b["produkte"]:
                if str(pid) not in bereits and pid_out(pid) not in fehlende:
                    fehlende.append(pid_out(pid))
        aenderung = (cat.get("saleCat") is not True
                     or neue_bundles != (cat.get("bundles") or [])
                     or bool(fehlende))
        if kombis:
            log("    Kombi-Angebote aus dem Shop: %d" % len(kombis))
        if fehlende:
            log("    f\u00fcr die Kombi erg\u00e4nzt: " + ", ".join("#%s" % p for p in fehlende))
        if not aenderung:
            return
        if not schreiben:
            log("    \u00c4nderungen offen, werden mit --write gespeichert.")
            return
        cats = sb_config("custom_categories") or []
        for c in cats:
            if c.get("id") == cat.get("id"):
                c["saleCat"] = True
                c["bundles"] = bundles_mischen(c.get("bundles"), kombis)
                c["productIds"] = (c.get("productIds") or []) + [p for p in fehlende if p not in (c.get("productIds") or [])]
                c["updated_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        sb_config_schreiben("custom_categories", cats)
        log("    Kategorie aktualisiert.")
        return

    # Kategorie fehlt: neu anlegen
    ids, variants = [], {}
    for pid in sorted((str(p) for p in sale), key=pid_sort):
        basis, var = basis_und_variante(pid, prods)
        if basis is None:
            log("    #%s hat kein Hauptprodukt, wird nicht aufgenommen." % pid)
            continue
        basis = pid_out(basis)
        if basis not in ids:
            ids.append(basis)
        if var is not None:
            variants[str(basis)] = pid_out(var)
    if not ids:
        log('  Kategorie "%s" nicht angelegt: keine zuordenbaren Aktionsprodukte.' % name)
        return
    for b in kombis:
        for pid in b["produkte"]:
            if pid_out(pid) not in ids:
                ids.append(pid_out(pid))
    gebiet = next((c.get("gebiet") for c in cats if c.get("gebiet")), CAT_GEBIET)
    eintrag = {"id": str(uuid.uuid4()), "name": name, "emoji": CAT_EMOJI,
               "gebiet": gebiet, "global": True, "productIds": ids, "productSizes": {},
               "productVariants": variants, "saleCat": True, "bundles": kombis,
               "createdBy": CAT_ERSTELLER,
               "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat()}
    log('  Kategorie "%s" wird angelegt mit %d Produkten: %s'
          % (name, len(ids), ", ".join("#%s" % i for i in ids)))
    if variants:
        log("    Gr\u00f6\u00dfen-Varianten: "
              + ", ".join("#%s \u2192 #%s" % (k, v) for k, v in variants.items()))
    if not schreiben:
        log("    Probelauf, nichts geschrieben.")
        return
    cats = sb_config("custom_categories") or []
    cats = [c for c in cats if str(c.get("name", "")).strip().lower() != name.lower()]
    cats.append(eintrag)
    sb_config_schreiben("custom_categories", cats)
    log("    Kategorie gespeichert.")


# ── Ablauf ───────────────────────────────────────────────────────────────
def main():
    schreiben = "--write" in sys.argv
    erzwungen = None
    if "--monat" in sys.argv:
        erzwungen = sys.argv[sys.argv.index("--monat") + 1]
    monat = monatsname(erzwungen)

    log("Aktionspreise vom Shop lesen ...")
    akt, fehler = shop_aktionen()
    log("  %d Produkte mit Aktionskennzeichen gefunden." % len(akt))
    if fehler:
        log("  ABBRUCH: %d Aktionsseite(n) nicht ladbar. Es wird nichts geschrieben, "
            "damit die vorhandenen Aktionspreise erhalten bleiben." % fehler)
        return 1
    prods = wdb_produkte()
    rev = lade_mapping()
    if not akt:
        log("  Keine Aktion aktiv.")
        if schreiben:
            vorher = sb_config("sale_prices") or {}
            if vorher:
                sb_config_schreiben("sale_prices", {})
                log("  Alte Aktionspreise (%d) entfernt." % len(vorher))
        return 0
    feed = shop_feed()
    log("  Feed: %d Shop-Produkte | WDB: %d Produkte | MAPPING: %d Shop-IDs"
          % (len(feed), len(prods), len(rev)))
    neu = sale_prices_bauen(akt, feed, prods, rev)
    kombis = shop_kombis(akt, feed, prods)

    if schreiben:
        vorher = sb_config("sale_prices") or {}
        if vorher == neu:
            log("  Aktionspreise unver\u00e4ndert.")
        else:
            sb_config_schreiben("sale_prices", neu)
            log("  Aktionspreise geschrieben: %d (vorher %d)." % (len(neu), len(vorher)))
    else:
        log("  Probelauf: %d Aktionspreise, nichts geschrieben." % len(neu))

    log('Monatskategorie "%s%s" pruefen ...' % (CAT_PREFIX, monat))
    kategorie_pflegen(neu, kombis, prods, monat, schreiben)
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
