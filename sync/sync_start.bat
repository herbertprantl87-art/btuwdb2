@echo off
setlocal
rem -- BTUWDB2: Preis-Sync, Aktionspreise, Quiz-Textindex und Uebersetzungen hintereinander ausfuehren --
rem Doppelklick = Testlauf, Fenster bleibt am Ende offen.
rem Aufgabenplanung: als Argument  /auto  eintragen, dann kein Warten am Ende.

cd /d "%~dp0"

set PY=C:\Users\prantl.herbert\AppData\Local\Python\pythoncore-3.14-64\python.exe

if not exist "%PY%" (
  echo FEHLER: Python nicht gefunden unter:
  echo   %PY%
  echo Pfad in dieser Datei in der Zeile "set PY=" anpassen.
  if not "%~1"=="/auto" pause
  exit /b 1
)

echo ===== Lauf %DATE% %TIME% ===== >> sync_log.txt

echo.
echo [1 von 4] Preis-Sync laeuft. Das dauert ein bis drei Minuten.
"%PY%" -u preis_sync.py --write >> sync_log.txt 2>&1
set RC1=%ERRORLEVEL%
echo --- Preis-Sync beendet, Rueckgabewert %RC1% >> sync_log.txt
echo           fertig, Rueckgabewert %RC1%

echo.
echo [2 von 4] Aktionspreise und Monatskategorie:
"%PY%" -u aktionspreise.py --write 2>&1
set RC2=%ERRORLEVEL%
echo --- Aktionspreise beendet, Rueckgabewert %RC2% >> sync_log.txt
echo.
echo           fertig, Rueckgabewert %RC2%

echo.
echo [3 von 4] Quiz-Textindex (baut nur neu, wenn aelter als 7 Tage):
"%PY%" -u quiz_textindex.py --write 2>&1
set RC3=%ERRORLEVEL%
echo --- Quiz-Textindex beendet, Rueckgabewert %RC3% >> sync_log.txt
echo.
echo           fertig, Rueckgabewert %RC3%

echo.
echo [4 von 4] Uebersetzungen fuer neue und geaenderte Texte:
"%PY%" -u uebersetzung_nachlauf.py --write 2>&1
set RC4=%ERRORLEVEL%
echo --- Uebersetzungen beendet, Rueckgabewert %RC4% >> sync_log.txt
echo.
echo           fertig, Rueckgabewert %RC4%

echo.
echo Protokoll Preis-Sync: sync_log.txt und preis_sync_report.txt

if not "%~1"=="/auto" pause
exit /b 0
