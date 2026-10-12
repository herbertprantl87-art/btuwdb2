"""Laedt die Sync-Skripte fuer die Tests, ohne dass sie etwas tun.

preis_sync.py darf nicht normal importiert werden: beim Import leitet es die
Ausgabe um und ueberschreibt preis_sync_report.txt. Deshalb wird der Quelltext
gelesen, die Umleitung und der Startblock (if __name__ == "__main__") entfernt
und der Rest in einem eigenen Namensraum ausgefuehrt. Netzzugriffe passieren
erst in den Funktionen, die Tests ersetzen sie durch Attrappen.
"""
import ast
import os
import re
import sys
import types

WURZEL = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SYNC = os.path.join(WURZEL, "sync")
INDEX = os.environ.get("BTU_INDEX") or os.path.join(WURZEL, "index.html")


def _ist_stdout_umleitung(knoten):
    if not isinstance(knoten, ast.Assign):
        return False
    return any(isinstance(z, ast.Attribute) and z.attr == "stdout"
               and getattr(z.value, "id", None) == "sys" for z in knoten.targets)


def _ist_startblock(knoten):
    return (isinstance(knoten, ast.If) and isinstance(knoten.test, ast.Compare)
            and getattr(knoten.test.left, "id", None) == "__name__")


def skript(name):
    pfad = os.environ.get("BTU_SYNC_" + name.upper()) or os.path.join(SYNC, name + ".py")
    with open(pfad, encoding="utf-8") as f:
        quelle = f.read()
    baum = ast.parse(quelle)
    baum.body = [k for k in baum.body if not _ist_stdout_umleitung(k) and not _ist_startblock(k)]
    modul = types.ModuleType("btu_" + name)
    modul.__file__ = pfad
    alt_argv = sys.argv
    sys.argv = [pfad]          # Skripte lesen sys.argv beim Laden (z. B. --write)
    try:
        exec(compile(baum, pfad, "exec"), modul.__dict__)
    finally:
        sys.argv = alt_argv
    return modul


def index_html():
    with open(INDEX, encoding="utf-8") as f:
        return f.read()


def index_produkt_ids():
    """Alle Produkt-IDs aus PRODUCTS in der index.html (auch refOnly)."""
    html = index_html()
    start = html.find("var PRODUCTS = [")
    ende = html.find("\n];", start)
    assert start >= 0 and ende > start, "PRODUCTS nicht in index.html gefunden"
    return re.findall(r"\n    id: (\d+),", html[start:ende])
