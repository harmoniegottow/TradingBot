"""Mail mit dem erweiterten Beobachter."""
import sys
from email.message import EmailMessage
from pathlib import Path

zip_pfad = Path("/opt/data/tradingbot/mt5-windows.zip")

msg = EmailMessage()
msg["From"] = "SG Harmonie Gottow <social@harmonie-gottow.de>"
msg["To"] = "dome.herrmann@icloud.com"
msg["Subject"] = "Tradingbot: Beobachter mit Divergenz — bitte dieses Paket nehmen"

msg.set_content("""Hallo Dominique,

danke fuer die zehn Jahre Daten. Damit sind zwei Sachen fertig
geworden - im Anhang das aktualisierte Paket, bitte das alte ersetzen.

1. DIVERGENZ IST JETZT IM BEOBACHTER

Der Beobachter ueberwacht ab sofort ZWEI Strategien gleichzeitig:
Trend+Pullback auf EURUSD, USDJPY und CHFJPY sowie die Divergenz
Gold/Silber auf H4. Im Journal steht in der neuen Spalte "strategie",
welche das Signal ausgeloest hat.

Abgesichert habe ich das mit vier Pruefungen hier auf dem Server:

  - Die Divergenz im Beobachter erkennt exakt dieselben 205 Signale
    wie der geprueft Backtest - keines zu viel, keines zu wenig.
  - Kein Zukunftsblick: Haenge ich dem Silber kuenstlich spaetere
    Kurse an, aendert sich am Signal nichts. Das war der
    gefaehrlichste denkbare Fehler.
  - Weiterhin kein einziger Auftrags-Aufruf im Code.
  - Bei jedem Gold-Signal wird protokolliert, dass der Trade mit
    1.000 EUR Kapital nicht moeglich waere.

2. ALLE ANDEREN STRATEGIEN NEU GEPRUEFT

Sechs Bausteine auf vier Maerkten, zehn Jahre - also 24 Tests. Ergebnis:
genau ein PRUEFEN. Rein zufaellig waeren 1,2 zu erwarten.

Der eine Treffer (Impuls-Fifty auf USDJPY) hat die Belastungsprobe dann
nicht bestanden: Schon bei doppelten Handelskosten kippt er ins Minus,
und das letzte Drittel des Zeitraums verliert. Zum Vergleich - die
Divergenz haelt bis zum Fuenffachen der Kosten.

Damit bleibt es dabei: Die Divergenz Gold/Silber ist der einzige
belastbare Fund. Sie sticht nicht knapp heraus, sondern deutlich.

Nebenbefund: Die frueheren Urteile auf zwei Jahren waren bei allen
anderen Strategien richtig. Die Divergenz war die Ausnahme, wo die
kurze Datenbasis in die Irre gefuehrt hat - nicht die Regel.

WAS DU TUN MUSST

    ZIP entpacken, alten Ordner ersetzen
    python beobachter.py

Laeuft dann durch, solange der Rechner an ist. Beenden mit Strg+C.

Nach ein bis zwei Wochen bitte die beobachtung.csv zurueckschicken.
Daraus sehen wir, ob Signalhaeufigkeit, Spread und Lot-Groessen zu dem
passen, was der Backtest unterstellt.

EINE OFFENE FRAGE

Unser einziger gepruefter Fund handelt Gold. Und Gold traegt ein Konto
mit 1.000 EUR nicht - das kleinste Lot riskiert dort rund 35 EUR, das
Siebenfache des Budgets. Wir sollten klaeren, wie viel Kapital das
Echtgeldkonto am Ende wirklich haben soll, bevor wir weiterbauen.

Alles auch im Repo:
https://github.com/harmoniegottow/TradingBot  im Ordner mt5-windows

Viele Gruesse
""")

msg.add_attachment(zip_pfad.read_bytes(), maintype="application",
                   subtype="zip", filename="mt5-windows.zip")

sys.stdout.write(msg.as_string())
