# -*- coding: utf-8 -*-
"""
BTUWDB2 - Nachlauf Uebersetzungen
=================================
Sucht neue oder geaenderte deutsche Texte in Supabase (eigene Produkte und
Admin-Aenderungen), uebersetzt nur diese und ergaenzt die Sprachdateien.

Aufruf:
    python uebersetzung_nachlauf.py            Testlauf, schreibt nichts
    python uebersetzung_nachlauf.py --write    schreibt nach Supabase

Was der Nachlauf NICHT sieht: Produkttexte, die fest in der index.html stehen.
Werden die geaendert, muss die Textliste i18n_source neu gebaut werden.
Das passiert beim naechsten Push der index.html.
"""

import json, re, sys, time, threading, queue, urllib.request, urllib.error, urllib.parse, datetime

BASE = "https://mejwpbahcmlkwajkymnj.supabase.co/rest/v1"
ANON = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Im1landwYmFoY21sa3dhamt5bW5qIiwicm9sZSI6ImFub24iLCJpYXQiOjE3Nzc4MzQ2OTAsImV4cCI6MjA5MzQxMDY5MH0.rzt-EiWxy8poy0vs00eEVvs-GYab9VOoiTAsrEScCrE"
KOPF = {"apikey": ANON, "Authorization": "Bearer " + ANON, "Content-Type": "application/json"}
SPRACHEN = ["en", "hu", "ru", "tr", "ar"]
SCHREIBEN = "--write" in sys.argv

TEXTFELDER = ["notes", "dosage", "flavors", "bcaa", "warning", "subcategory"]
LISTENFELDER = ["keyIngredients", "freeFrom"]
SKIP_KATEGORIEN = ["Bekleidung", "Shaker & Zubehoer", "Shaker & Zubeh\u00f6r", "Zubeh\u00f6r"]

# ---------------------------------------------------------------- Supabase
def hole(schluessel):
    r = urllib.request.Request(
        BASE + "/app_config?key=eq." + urllib.parse.quote(schluessel) + "&select=value",
        headers={"apikey": ANON, "Authorization": "Bearer " + ANON})
    zeilen = json.load(urllib.request.urlopen(r, timeout=120))
    if not zeilen:
        return None
    wert = zeilen[0]["value"]
    if isinstance(wert, str):
        try: wert = json.loads(wert)
        except Exception: return None
    return wert

def schreibe(schluessel, wert):
    kopf = dict(KOPF)
    kopf["Prefer"] = "resolution=merge-duplicates,return=minimal"
    koerper = json.dumps({"key": schluessel, "value": wert,
                          "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat()}).encode()
    r = urllib.request.Request(BASE + "/app_config", data=koerper, headers=kopf, method="POST")
    urllib.request.urlopen(r, timeout=300)

# ---------------------------------------------------------------- Schluessel
def schluessel_fuer(text):
    """Muss Zeichen fuer Zeichen der Funktion i18nHash in der index.html entsprechen."""
    h1, h2 = 2166136261, 305419896
    # JavaScript zaehlt in UTF-16-Einheiten, Emojis sind dort zwei Zeichen
    roh = text.encode("utf-16-le")
    for i in range(0, len(roh), 2):
        c = roh[i] | (roh[i + 1] << 8)
        h1 = ((h1 ^ c) * 16777619) & 0xFFFFFFFF
        h2 = ((h2 ^ c) * 16777619) & 0xFFFFFFFF
    def b36(n):
        if n == 0: return "0"
        zeichen = "0123456789abcdefghijklmnopqrstuvwxyz"
        out = ""
        while n:
            out = zeichen[n % 36] + out
            n //= 36
        return out
    return b36(h1) + "-" + b36(h2)

# ---------------------------------------------------------------- Quizlogik
ABK = re.compile(r"(?:\b(?:z|B|ca|bzw|ggf|inkl|evtl|u|d|h|Nr|Abb|max|min|vgl|ml|mg|g|Vit|Kps|Tbl|St|ca)\.)$", re.I)
SATZ = re.compile(r"[.!?](?=\s|$)")
FORMSATZ = re.compile(r"^(?:Trinkfertige[sr]?\b|Kapsel-Alternative|Tablettenform|Pulverform|Fl\u00fcssige[sr]? (?:Form|Version)|Gleiche[sr]? (?:Wirkformel|thermogene|Formel)|Basisversion|PRO-Version|Zuckerfreie Version|Praktisch f\u00fcr|F\u00fcr Personen, die|F\u00fcr Nutzer, die|F\u00fcr unterwegs|Ideal f\u00fcr unterwegs|Alternative zu|Kein Abmessen|Identische)", re.I)
SUBSTANZ = re.compile(r"\d|mg|\u00b5g|%|Vitamin|Protein|Amino|Kreatin|Creatin|Carnitin|Arginin|Koffein|Extrakt|Kollagen|Magnesium|Zink|Calcium|Eisen|Omega|Glutamin|Leucin|Ballaststoff|Kohlenhydrat|unterst\u00fctzt|tr\u00e4gt bei|f\u00f6rdert|hilft|reduziert|erh\u00f6ht|liefert|enth\u00e4lt|besteht aus", re.I)
BAD_NOTES = re.compile(r"automatisch vom shop \u00fcbernommen|bitte im admin erg\u00e4nzen|bitte angabe|laut produktetikett", re.I)
EINSTIEG = re.compile(r"^\s*(?:Warum|Wie|Was|Wozu|Wieso|Wann|Wer)\b[^?]{0,120}\?\s*", re.I)

def erster_satz(text):
    if not text: return ""
    s = str(text).strip()
    for m in SATZ.finditer(s):
        kandidat = s[:m.start() + 1].strip()
        if len(kandidat) < 20: continue
        if ABK.search(kandidat): continue
        return kandidat
    w = s.split(" ")
    return " ".join(w[:12]) + ("\u2026" if len(w) > 12 else "")

def quiz_beschreibung(notes):
    if not notes: return ""
    rest = EINSTIEG.sub("", str(notes).strip()).strip()
    for _ in range(3):
        if not FORMSATZ.search(rest): break
        satz = erster_satz(rest)
        if not satz or SUBSTANZ.search(satz): break
        kuerzer = rest[rest.find(satz) + len(satz):].strip()
        if len(kuerzer) < 45: break
        rest = kuerzer
    out = ""
    for _ in range(3):
        if not rest or len(out) >= 45: break
        satz = erster_satz(rest)
        if not satz: break
        out = (out + " " if out else "") + satz
        rest = rest[rest.find(satz) + len(satz):].strip()
        if len(out) > 200: break
    for _ in range(2):
        if not rest or SUBSTANZ.search(out) or len(out) >= 200: break
        satz = erster_satz(rest)
        if not satz: break
        out += " " + satz
        rest = rest[rest.find(satz) + len(satz):].strip()
    return out.strip()

# ---------------------------------------------------------------- Uebersetzen
def schutzmuster(begriffe):
    begriffe = sorted({b for b in begriffe if b and len(b) >= 7}, key=len, reverse=True)
    if not begriffe:
        return None
    return re.compile("|".join(re.escape(b) for b in begriffe))

PLATZ = re.compile(r"\{[^}]{1,20}\}")

def schuetzen(text, muster):
    marken = []
    def ersetze(m):
        marken.append(m.group(0))
        return "\u27e6%d\u27e7" % (len(marken) - 1)
    t = PLATZ.sub(ersetze, text)
    if muster:
        t = muster.sub(ersetze, t)
    return t, marken

def zurueck(text, marken):
    for i, m in enumerate(marken):
        marke = "\u27e6%d\u27e7" % i
        if marke not in text:
            return None
        text = text.replace(marke, m)
    return text

def rufe_dienst(text, ziel, versuch=1):
    """Ruft den offenen Uebersetzungsdienst. Bei Drosselung (429) lange warten."""
    q = urllib.parse.urlencode({"client": "gtx", "sl": "de", "tl": ziel, "dt": "t", "q": text})
    r = urllib.request.Request("https://translate.googleapis.com/translate_a/single?" + q,
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126"})
    try:
        d = json.load(urllib.request.urlopen(r, timeout=30))
        return "".join(x[0] for x in d[0] if x[0])
    except urllib.error.HTTPError as e:
        if e.code in (429, 503) and versuch <= 5:
            warte = 30 * versuch
            print("  Dienst gedrosselt, warte %d Sekunden" % warte)
            time.sleep(warte)
            return rufe_dienst(text, ziel, versuch + 1)
        raise
    except Exception:
        if versuch < 4:
            time.sleep(3 * versuch)
            return rufe_dienst(text, ziel, versuch + 1)
        raise

def bloecke(eintraege, max_zeichen=1200, max_zeilen=10):
    raus, akt, z = [], [], 0
    for e in eintraege:
        if akt and (z + len(e[1]) > max_zeichen or len(akt) >= max_zeilen):
            raus.append(akt); akt = []; z = 0
        akt.append(e); z += len(e[1])
    if akt: raus.append(akt)
    return raus

def uebersetze(offen, ziel, muster):
    """offen: Liste aus (schluessel, deutscher Text). Gibt {schluessel: Uebersetzung} zurueck."""
    ergebnis, fehler = {}, []
    q = queue.Queue()
    for b in bloecke(offen): q.put(b)
    sperre = threading.Lock()

    def arbeiter():
        while True:
            try: block = q.get_nowait()
            except queue.Empty: return
            try:
                zeilen, alle_marken = [], []
                for _, text in block:
                    t, m = schuetzen(text.replace("\n", " "), muster)
                    zeilen.append(t); alle_marken.append(m)
                antwort = rufe_dienst("\n".join(zeilen), ziel).split("\n")
                if len(antwort) != len(block):
                    if len(block) > 1:
                        for e in block: q.put([e])
                    else:
                        with sperre: fehler.append(block[0][0])
                    q.task_done(); continue
                for (sch, text), teil, marken in zip(block, antwort, alle_marken):
                    fertig = zurueck(teil.strip(), marken)
                    if fertig is None:
                        fertig = rufe_dienst(text.replace("\n", " "), ziel).strip()
                    with sperre: ergebnis[sch] = fertig
            except Exception as ex:
                with sperre: fehler.append(block[0][0])
            q.task_done()

    faeden = [threading.Thread(target=arbeiter) for _ in range(2)]
    for f in faeden: f.start()
    for f in faeden: f.join()
    return ergebnis, fehler

# ---------------------------------------------------------------- Texte sammeln
def sammle_texte():
    """Alle deutschen Texte aus den Supabase-Daten, als {schluessel: text}."""
    gefunden = {}
    def merke(text):
        if not isinstance(text, str): return
        t = text.strip()
        if len(t) < 2: return
        gefunden[schluessel_fuer(t)] = t

    eigene = hole("custom_products") or []
    aenderungen = hole("product_overrides") or {}

    for p in eigene:
        for f in TEXTFELDER: merke(p.get(f))
        for f in LISTENFELDER:
            for v in (p.get(f) or []): merke(v)
        if p.get("subcategory"): merke(str(p["subcategory"]).split("(")[0].strip())
        if p.get("category") not in SKIP_KATEGORIEN:
            notes = p.get("notes") or ""
            if len(notes.strip()) >= 30 and not BAD_NOTES.search(notes):
                b = quiz_beschreibung(notes)
                if b and len(b) >= 10: merke(b)

    for o in aenderungen.values():
        if not isinstance(o, dict): continue
        for f in TEXTFELDER: merke(o.get(f))
        for f in LISTENFELDER:
            for v in (o.get(f) or []): merke(v)
        if o.get("subcategory"): merke(str(o["subcategory"]).split("(")[0].strip())
        notes = o.get("notes") or ""
        if len(notes.strip()) >= 30 and not BAD_NOTES.search(notes):
            b = quiz_beschreibung(notes)
            if b and len(b) >= 10: merke(b)

    for p in eigene:
        merke(p.get("packageSize"))
        merke(p.get("legalStatus"))

    kategorien = hole("custom_categories") or []
    for c in kategorien:
        if not isinstance(c, dict): continue
        merke(c.get("name"))
        for b in (c.get("bundles") or []):
            if isinstance(b, dict):
                merke(b.get("text")); merke(b.get("name"))

    print("  eigene Produkte: %d, Admin-Aenderungen: %d, eigene Kategorien: %d, Texte daraus: %d"
          % (len(eigene), len(aenderungen), len(kategorien), len(gefunden)))
    return gefunden

# ---------------------------------------------------------------- Hauptlauf
def main():
    print("Nachlauf Uebersetzungen %s" % datetime.datetime.now().strftime("%d.%m.%Y %H:%M"))
    if not SCHREIBEN:
        print("TESTLAUF, es wird nichts geschrieben. Mit --write starten zum Schreiben.")

    quelle = hole("i18n_source")
    if not quelle:
        print("FEHLER: Textliste i18n_source nicht gefunden.")
        return 1
    bekannt = {e["k"]: e["t"] for e in quelle}
    print("  Textliste: %d Eintraege" % len(bekannt))

    aktuell = sammle_texte()
    neu = {k: t for k, t in aktuell.items() if k not in bekannt}
    print("  neue Texte: %d" % len(neu))

    if neu:
        quelle = quelle + [{"k": k, "t": t, "c": "nachlauf"} for k, t in neu.items()]
        bekannt.update(neu)
        if SCHREIBEN:
            schreibe("i18n_source", quelle)
            print("  Textliste ergaenzt und gespeichert.")

    schutz = hole("i18n_schutz") or []
    eigene = hole("custom_products") or []
    schutz = list(schutz) + [p.get("name") for p in eigene if p.get("name")]
    schutz += ["from organic sources", "Organic", "organic", "One-A-Day", "One-a-Day"]
    muster = schutzmuster(schutz)

    gesamt_fehler = 0
    for ziel in SPRACHEN:
        karte = hole("i18n_" + ziel) or {}
        offen = [(k, bekannt[k]) for k in bekannt if k not in karte]
        if not offen:
            print("  %s: nichts zu tun (%d Texte vorhanden)" % (ziel, len(karte)))
            continue
        print("  %s: %d Texte offen" % (ziel, len(offen)))
        if not SCHREIBEN:
            continue
        ergebnis, fehler = uebersetze(offen, ziel, muster)
        karte.update(ergebnis)
        schreibe("i18n_" + ziel, karte)
        gesamt_fehler += len(fehler)
        print("  %s: %d uebersetzt, %d Fehler, jetzt %d Texte"
              % (ziel, len(ergebnis), len(fehler), len(karte)))

    print("fertig%s" % (", %d Fehler" % gesamt_fehler if gesamt_fehler else ""))
    return 2 if gesamt_fehler else 0

if __name__ == "__main__":
    sys.exit(main())
