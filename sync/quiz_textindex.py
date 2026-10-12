# -*- coding: utf-8 -*-
"""
quiz_textindex.py  (Stand 07.09.2026)

Baut den Vergleichsindex fuer den Textabgleich im Quiz und legt ihn in Supabase
unter app_config.quiz_textindex ab. Die Auswertung in BTUWDB2 laedt ihn und
zeigt bei jeder Freitextantwort, wie viele Woerter woertlich uebernommen wurden.

Quellen: die Produktbeschreibungen aus shop.biotechusa.de und die eigene Kartei
(index.html + product_overrides + custom_products).

Aufruf:
    python quiz_textindex.py            Probelauf, schreibt nichts
    python quiz_textindex.py --write    baut den Index und schreibt ihn
    python quiz_textindex.py --write --immer   ignoriert das Hoechstalter

Standardmaessig wird nur neu gebaut, wenn der gespeicherte Index aelter als
MAX_ALTER Tage ist. Der Aufruf kostet dann nur einen kurzen Lesezugriff.

Rueckgabewert 1 heisst: Shop nicht erreichbar, der alte Index bleibt stehen.
Es wird in dem Fall nichts geschrieben.
"""

import sys
import re
import json
import base64
import struct
import zlib
import time
import html
import unicodedata
import datetime
import urllib.request
import urllib.error

SUPA = "https://mejwpbahcmlkwajkymnj.supabase.co/rest/v1"
KEY = ("eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Im1l"
       "andwYmFoY21sa3dhamt5bW5qIiwicm9sZSI6ImFub24iLCJpYXQiOjE3Nzc4MzQ2OTAsImV4cCI6"
       "MjA5MzQxMDY5MH0.rzt-EiWxy8poy0vs00eEVvs-GYab9VOoiTAsrEScCrE")
INDEX_URL = "https://raw.githubusercontent.com/herbertprantl87-art/btuwdb2/main/index.html"
SHOP = "https://shop.biotechusa.de/products.json?limit=250&page=%d"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

MAX_ALTER = 7          # Tage, ab denen neu gebaut wird
N = 5                  # Laenge der verglichenen Wortfolgen
OHNE_TYP = ("Bekleidung", "Zubeh\u00f6r", "Accessories", "Apparel")

TOK = re.compile(u"[0-9A-Za-z\u00C0-\u024F\u0370-\u03FF\u0400-\u04FF]+")


def log(*a):
    print(*a)
    sys.stdout.flush()


def hole(url, versuche=3, pause=20):
    for i in range(versuche):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=45) as r:
                return r.read()
        except Exception as e:
            log("   Versuch %d fehlgeschlagen: %s" % (i + 1, e))
            if i < versuche - 1:
                time.sleep(pause)
    return None


def supa(pfad, daten=None, upsert=False):
    kopf = {"apikey": KEY, "Authorization": "Bearer " + KEY,
            "Content-Type": "application/json"}
    if upsert:
        kopf["Prefer"] = "resolution=merge-duplicates,return=minimal"
    req = urllib.request.Request(SUPA + "/" + pfad,
                                 data=json.dumps(daten).encode() if daten is not None else None,
                                 method="POST" if daten is not None else "GET",
                                 headers=kopf)
    with urllib.request.urlopen(req, timeout=60) as r:
        roh = r.read()
        return json.loads(roh) if roh else None


# ─── Normalisierung, muss mit txTokens() in der index.html uebereinstimmen ────
def tokens(text):
    out = []
    for m in TOK.finditer(text or ""):
        w = m.group(0).lower().replace(u"\u00df", "ss")
        w = unicodedata.normalize("NFKD", w)
        w = re.sub("[^a-z0-9]", "", w)
        if w:
            out.append(w)
    return out


def shingles(text, ziel):
    t = tokens(text)
    for i in range(len(t) - N + 1):
        ziel.add(zlib.crc32((" ".join(t[i:i + N])).encode("ascii")) & 0xFFFFFFFF)


def text_von(d):
    teile = []
    for f in ("notes", "dosage", "subcategory", "bcaa"):
        if d.get(f):
            teile.append(str(d[f]))
    ki = d.get("keyIngredients")
    if isinstance(ki, list):
        teile += [str(x) for x in ki]
    elif ki:
        teile.append(str(ki))
    return " ".join(teile)


def kartei_aus_index(quelltext):
    """Zieht notes, dosage, subcategory und keyIngredients aus PRODUCTS."""
    prods = {}
    ab = quelltext.find("id: 1,")
    if ab < 0:
        return prods
    teile = re.split(r"\n\s*\{\s*\n\s*id:\s*(\d+),", quelltext[max(0, ab - 200):])
    for i in range(1, len(teile) - 1, 2):
        pid, body = teile[i], teile[i + 1][:6000]
        if "category:" not in body:
            continue
        txt = [m.group(2) for m in
               re.finditer(r'(notes|dosage|subcategory|bcaa):\s*"((?:[^"\\]|\\.)*)"', body)]
        ki = re.search(r'keyIngredients:\s*\[(.*?)\]', body, re.S)
        if ki:
            txt += re.findall(r'"((?:[^"\\]|\\.)*)"', ki.group(1))
        prods[pid] = " ".join(txt).replace("\\n", " ").replace('\\"', '"')
    return prods


def main():
    schreiben = "--write" in sys.argv
    immer = "--immer" in sys.argv

    log("=" * 60)
    log("Quiz-Textindex, Lauf vom %s" % datetime.datetime.now().strftime("%d.%m.%Y %H:%M"))

    # 1) Alter des vorhandenen Index pruefen
    try:
        vorhanden = supa("app_config?key=eq.quiz_textindex&select=value")
    except Exception as e:
        log("Supabase nicht erreichbar: %s" % e)
        return 1
    if vorhanden and not immer:
        wert = vorhanden[0].get("value") or {}
        if isinstance(wert, str):
            try:
                wert = json.loads(wert)
            except Exception:
                wert = {}
        stand = wert.get("stand")
        if stand:
            try:
                tage = (datetime.date.today() - datetime.date.fromisoformat(stand)).days
                log("Vorhandener Index: Stand %s (%d Tage alt), %s Wortfolgen"
                    % (stand, tage, wert.get("n", "?")))
                if tage < MAX_ALTER:
                    log("Juenger als %d Tage, nichts zu tun." % MAX_ALTER)
                    return 0
            except ValueError:
                pass

    menge = set()

    # 2) Shop-Beschreibungen
    shop_n = 0
    seite = 1
    while True:
        log("Shop-Seite %d laden..." % seite)
        roh = hole(SHOP % seite)
        if roh is None:
            log("FEHLER: Shop nicht erreichbar. Der alte Index bleibt stehen.")
            return 1
        try:
            produkte = json.loads(roh.decode("utf-8")).get("products", [])
        except Exception as e:
            log("FEHLER: Shop-Antwort unlesbar (%s). Der alte Index bleibt stehen." % e)
            return 1
        if not produkte:
            break
        for p in produkte:
            if (p.get("product_type") or "") in OHNE_TYP:
                continue
            txt = re.sub(r"<[^>]+>", " ", p.get("body_html") or "")
            shingles(html.unescape(txt), menge)
            shop_n += 1
        seite += 1
        if seite > 10:
            break
    log("   %d Shop-Produkte verarbeitet" % shop_n)

    if shop_n < 100:
        log("FEHLER: nur %d Shop-Produkte, das sieht nach einer Teilantwort aus. "
            "Der alte Index bleibt stehen." % shop_n)
        return 1

    # 3) Eigene Kartei
    log("Eigene Kartei laden...")
    roh = hole(INDEX_URL, versuche=2, pause=15)
    kartei = kartei_aus_index(roh.decode("utf-8", "replace")) if roh else {}
    log("   %d Produkte aus der index.html" % len(kartei))
    for t in kartei.values():
        shingles(t, menge)

    try:
        ov = supa("app_config?key=eq.product_overrides&select=value")
        cp = supa("app_config?key=eq.custom_products&select=value")
        ov = (ov[0]["value"] if ov else {}) or {}
        cp = (cp[0]["value"] if cp else []) or []
        if isinstance(ov, str):
            ov = json.loads(ov)
        if isinstance(cp, str):
            cp = json.loads(cp)
        for o in ov.values():
            shingles(text_von(o), menge)
        for c in cp:
            shingles(text_von(c), menge)
        log("   %d Overrides, %d eigene Produkte" % (len(ov), len(cp)))
    except Exception as e:
        log("   Hinweis: Overrides/eigene Produkte nicht geladen (%s)" % e)

    # 4) Packen
    arr = sorted(menge)
    b64 = base64.b64encode(b"".join(struct.pack("<I", x) for x in arr)).decode("ascii")
    wert = {"stand": datetime.date.today().isoformat(), "n": len(arr),
            "quellen": {"shop": shop_n, "kartei": len(kartei)}, "d": b64}
    log("Index fertig: %d Wortfolgen, %d KB" % (len(arr), len(b64) // 1024))

    if not schreiben:
        log("Probelauf, nichts geschrieben. Mit --write ausfuehren.")
        return 0

    supa("app_config", [{"key": "quiz_textindex", "value": wert}], upsert=True)
    log("In Supabase geschrieben.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        log("ABBRUCH: %s" % e)
        sys.exit(1)
