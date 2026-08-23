"""Mail mit dem korrigierten MT5-Paket."""
import sys
from email.message import EmailMessage
from pathlib import Path

zip_pfad = Path("/opt/data/tradingbot/mt5-windows.zip")

msg = EmailMessage()
msg["From"] = "SG Harmonie Gottow <social@harmonie-gottow.de>"
msg["To"] = "dome.herrmann@icloud.com"
msg["Subject"] = "Tradingbot: korrigiertes MT5-Paket (bitte dieses nehmen)"

msg.set_content("""Hallo Dominique,

danke fuer die Rueckmeldung. Daraus sind zwei Fehler in meinen Skripten
aufgefallen und ein wichtiger Befund, den wir vorher nicht auf dem
Schirm hatten. Im Anhang das korrigierte Paket - bitte das alte
ersetzen.

Was war falsch:

1. "EURUSD H1: keine Daten" lag an mir, nicht am Broker. Ich hatte
   100.000 Kerzen auf einmal abgefragt. Ein frisches Terminal hat die
   Historie noch nicht geladen und liefert dann gar nichts statt
   weniger. Das Skript versucht jetzt kleinere Mengen und faellt auf
   eine Zeitraum-Abfrage zurueck.

2. Die Zeitrahmen waren willkuerlich zugeordnet (CHFJPY auf H4, Silber
   auf H1). Jetzt sauber: Metalle auf H4, Devisen auf H1.

Der wichtige Befund:

Dein Demokonto hat 50.000 EUR, das spaetere Echtgeldkonto soll 500 bis
1.000 EUR haben. Das kleinste handelbare Lot ist ueberall 0,01 und
laesst sich nicht unterschreiten. Bei 1.000 EUR und 0,5 % Risiko sind
das 5 EUR je Trade - und da riskiert 0,01 Lot schon:

    EURUSD   1,76 EUR  -> passt
    USDJPY   2,01 EUR  -> passt
    CHFJPY   4,38 EUR  -> passt knapp
    GBPUSD  15,75 EUR  -> 3x zu gross
    XAUUSD  35,22 EUR  -> 7x zu gross

Mit 1.000 EUR sind also nur drei Maerkte handelbar, und Metalle fallen
komplett weg - ausgerechnet die, auf denen die Beispiel-Bots ihre besten
Zahlen behaupten.

Das ist kein Fehler, sondern eine Grenze des Kontos. Unangenehm daran
ist: Ein Demokonto mit 50.000 EUR gaukelt eine Auswahl vor, die das
echte Konto spaeter nicht hat. Wer auf Demo Gold handelt und dann mit
1.000 EUR live geht, stellt fest, dass der Bot jeden Gold-Trade
ablehnt.

Deshalb beobachtet der Bot jetzt EURUSD, USDJPY und CHFJPY - also das,
was auch spaeter real geht. Gold laeuft nur zur Beobachtung mit.

Noch etwas aufgefallen: Dein Broker fuehrt Gold dreimal - XAUUSD,
XAUUSD-F und GOLD-PERP. Nur der erste ist der normale Kassamarkt, die
anderen sind Futures mit anderer Kontraktgroesse. Die werden jetzt
ausdruecklich aussortiert.

Naechste Schritte, wie gehabt:

    python pruefe_verbindung.py     (hat jetzt einen Schritt 5 dazu)
    python hole_historie.py --jahre 10
    python beobachter.py

Falls bei Schritt 4 wieder "keine Daten" steht: im MT5-Terminal einmal
den EURUSD-Chart oeffnen, auf H1 stellen und weit nach links scrollen
oder Pos1 druecken. Das Terminal laedt die Historie erst beim Ansehen
nach. Danach das Skript nochmal laufen lassen.

Alles auch im Repo:
https://github.com/harmoniegottow/TradingBot  im Ordner mt5-windows

Viele Gruesse
""")

msg.add_attachment(zip_pfad.read_bytes(), maintype="application",
                   subtype="zip", filename="mt5-windows.zip")

sys.stdout.write(msg.as_string())
