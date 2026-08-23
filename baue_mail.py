"""Baut eine Roh-Mail mit dem ZIP als Anhang (fuer himalaya message send)."""
import sys
from email.message import EmailMessage
from pathlib import Path

zip_pfad = Path("/opt/data/tradingbot/mt5-windows.zip")

msg = EmailMessage()
msg["From"] = "SG Harmonie Gottow <social@harmonie-gottow.de>"
msg["To"] = "dome.herrmann@icloud.com"
msg["Subject"] = "Tradingbot: MT5-Paket fuer den Windows-Rechner"

msg.set_content("""Hallo Dominique,

im Anhang das MT5-Paket fuer Deinen Windows-Rechner.

ZIP entpacken, Ordner "mt5-windows" zum Beispiel auf den Desktop legen.
Die README darin erklaert alles Schritt fuer Schritt.

Kurzfassung:

1. Python ab 3.10 installieren, dabei den Haken bei
   "Add python.exe to PATH" setzen.
2. MT5 starten und im Demokonto einloggen.
3. Eingabeaufforderung im Ordner oeffnen (im Explorer oben in die
   Adresszeile klicken, cmd eintippen, Enter) und eingeben:
       pip install MetaTrader5 pandas
4. Dann der Reihe nach:
       python pruefe_verbindung.py
       python hole_historie.py --jahre 10
       python beobachter.py

Schritt 1 handelt nicht und aendert nichts. Er zeigt vor allem, wie
Pepperstone die Maerkte bei Deinem Konto wirklich nennt - da haengt je
nach Kontotyp ein Kuerzel dran, etwa EURUSD.a statt EURUSD. Bitte die
Ausgabe davon einmal zurueckschicken.

Schritt 2 holt zehn Jahre Kursdaten als CSV. Die Dateien landen im
Unterordner data und kommen zurueck auf den Server - damit koennen wir
alle bisherigen Auswertungen mit zehn statt zwei Jahren nachrechnen.

Schritt 3 ist der Beobachtungsmodus. Er erkennt Signale und
protokolliert, was er handeln wuerde, sendet aber keine Auftraege.

Alternativ liegt alles auch im Repo:
https://github.com/harmoniegottow/TradingBot  im Ordner mt5-windows

Viele Gruesse
""")

daten = zip_pfad.read_bytes()
msg.add_attachment(daten, maintype="application", subtype="zip",
                   filename="mt5-windows.zip")

sys.stdout.write(msg.as_string())
