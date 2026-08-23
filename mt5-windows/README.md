# MT5 auf dem Windows-Rechner — Schritt fuer Schritt

Alles hier laeuft **nur unter Windows**, weil es das Python-Paket
`MetaTrader5` ausschliesslich fuer Windows gibt (geprueft 23.08.2026:
alle je erschienenen Versionen tragen nur `win32` und `win_amd64`).
Auf dem Linux-Server sind diese Skripte nicht ausfuehrbar.

Broker: **Pepperstone**, Demokonto.

---

## Einmalige Vorbereitung

1. **Python installieren** (Version 3.10 oder neuer) von python.org.
   Beim Installieren unbedingt den Haken bei
   **"Add python.exe to PATH"** setzen — sonst findet Windows Python
   spaeter nicht.
2. **MetaTrader 5 starten** und im **Demokonto** einloggen. Das Terminal
   muss die ganze Zeit laufen, solange eines dieser Skripte arbeitet.
3. **Diesen Ordner** (`mt5-windows`) auf den Windows-Rechner kopieren,
   zum Beispiel auf den Desktop.
4. **Eingabeaufforderung in diesem Ordner oeffnen:** Ordner im Explorer
   oeffnen, oben in die Adresszeile klicken, `cmd` eintippen, Enter.
   Es oeffnet sich ein schwarzes Fenster im richtigen Ordner.
5. **Pakete installieren** — im schwarzen Fenster eingeben:

       pip install MetaTrader5 pandas

---

## Schritt 1: Verbindung pruefen

    python pruefe_verbindung.py

Das Skript handelt nicht und aendert nichts. Es zeigt:

- ob die Verbindung steht und ob es wirklich ein Demokonto ist
- **wie Pepperstone die Maerkte tatsaechlich nennt.** Das ist der
  wichtigste Punkt: Pepperstone haengt je nach Kontotyp ein Kuerzel an
  (etwa `EURUSD.a` statt `EURUSD`). Welches, haengt vom Konto ab —
  deshalb wird es gesucht statt geraten.
- Spread, Mindest-Lot und Schrittweite je Markt
- wie viel Historie das Terminal bereithaelt

Am Ende steht eine fertige `MARKETS`-Zeile zum Kopieren.

**Bitte die Ausgabe dieses Schritts einmal zuruecksenden** — daran sehe
ich, ob wir die Konfiguration anpassen muessen.

---

## Schritt 2: Historie abholen (der sofortige Gewinn)

    python hole_historie.py --jahre 10

Holt Kurse als CSV im Format unseres Pruefstands. **Handelt nicht.**

Warum das zuerst kommt: Uns fehlt lange Historie. Bei der Divergenz-Idee
hatten wir zwei Jahre H4 gegen die behaupteten zehn — mit zehn Jahren
wird die Pruefung erst aussagekraeftig. Das bringt sofort Nutzen, ganz
ohne einen einzigen Trade.

Die Dateien landen im Unterordner `data`. Danach auf den Server nach
`tradingbot/data/` kopieren.

Falls ein Symbol nicht gefunden wird, den Namen aus Schritt 1 mitgeben:

    python hole_historie.py XAUUSD.a EURUSD.a --jahre 10

---

## Schritt 3: Beobachtungsmodus starten

    python beobachter.py

Der Bot erkennt Signale, rechnet aus, **was** er handeln wuerde, und
schreibt alles ins Journal — **sendet aber niemals einen Auftrag.**

Beenden mit `Strg + C`. Laeuft der Rechner durch, laeuft der Beobachter
durch. Wird er neu gestartet, macht er dort weiter, wo er aufgehoert hat.

### Warum beobachten statt auf Demo zu handeln?

Die Strategien der Beispiel-Bots haben unseren Pruefstand nicht
bestanden: zehn von zwoelf Laeufen verlieren Geld, die uebrigen zwei
sind von Zufall nicht zu unterscheiden. Demo-Handel wuerde Wochen kosten
und uns nichts sagen, was wir nicht schon wissen.

Der Beobachtungsmodus prueft dagegen genau das, was ein Backtest
**nicht** pruefen kann:

- Stimmen die Symbolnamen beim Broker?
- Kommen die Signale zur erwarteten Zeit?
- Liefert die broker-eigene Lot-Berechnung plausible Groessen?
  (Beim Vorgaenger-Bot hatte eine selbstgebaute Formel das Risiko bei
  Metallen um Faktor neun unterschaetzt.)
- Wie hoch sind Spread und Kosten in echt, nicht im Modell?

Das sind reale Erkenntnisse ohne jedes Risiko.

### Was dabei entsteht

| Datei | Inhalt |
|---|---|
| `beobachtung.csv` | jedes Signal mit Kurs, SL, TP, berechneter Lot-Groesse, echtem Risiko und Spread |
| `beobachter.log` | vollstaendiges Protokoll, auch die Begruendung, wenn NICHT gehandelt wuerde |
| `beobachter_state.json` | Merkzettel, damit ein Neustart keine Signale doppelt zaehlt |

Die CSV laesst sich direkt in Excel oeffnen (Semikolon-getrennt).
**Nach ein bis zwei Wochen bitte `beobachtung.csv` zurueckschicken** —
daraus sehen wir, ob Live-Verhalten und Backtest zusammenpassen.

### Eingestellte Strategien

Der Beobachter ueberwacht **zwei** Strategien gleichzeitig. Im Journal
steht in der Spalte `strategie`, welche das Signal ausgeloest hat.

**1. Trend + Pullback, nur Long.**
Short ist bewusst abgeschaltet: auf unseren Daten war "nur Long" auf
allen drei getesteten Maerkten besser (Gold Profitfaktor 1,59 gegen
1,48 mit Short). Maerkte: EURUSD und USDJPY auf H1, CHFJPY auf H4.

Ehrlicher Hinweis: Diese Strategie hat unseren Pruefstand **nicht**
bestanden. Sie laeuft mit, um zu sehen, ob sich das Live-Verhalten mit
dem Backtest deckt — nicht weil wir an sie glauben.

**2. Divergenz Gold gegen Silber** — der einzige gepruefte Fund.
Gold wird gehandelt, Silber dient nur als Referenz. Zeitrahmen H4.

Idee: Gold und Silber laufen normalerweise zusammen. Faellt Gold
gegenueber Silber deutlich zurueck und holt dann wieder auf, gilt das
als Kaufsignal fuer Gold.

Auf zehn Jahren echter Broker-Daten geprueft (15.447 Kerzen):

| Fenster | Trades | Profitfaktor | Zufall besser |
|---|---|---|---|
| Gesamt 10 Jahre | 136 | 1,95 | 0,5 % |
| Testfenster (unberuehrt) | 52 | 2,84 | 2,0 % |

Dazu: 11 von 15 Parametereinstellungen bestehen, bei fuenffachen Kosten
bleibt Profitfaktor 1,58, und gegen Zufallseinstiege mit demselben
Trendfilter gewinnt sie in 30 von 30 Laeufen.

**Aber:** Mit 1.000 EUR Echtgeld waere Gold gar nicht handelbar — das
kleinste Lot riskiert dort rund 35 EUR, siebenfach ueber Budget. Der
Beobachter schreibt das bei jedem Gold-Signal ausdruecklich ins
Protokoll.

### Warum die Maerkte so gewaehlt sind

Das Demokonto hat 50.000 EUR, ein spaeteres Echtgeldkonto soll 500 bis
1.000 EUR haben. Das kleinste handelbare Lot ist ueberall 0,01 und
laesst sich nicht unterschreiten. Bei 1.000 EUR und 0,5 % Risiko (also
5 EUR je Trade) riskiert dieses kleinste Lot:

| Markt | Risiko bei 0,01 Lot | mit 1.000 EUR |
|---|---|---|
| EURUSD | 1,76 EUR | passt |
| USDJPY | 2,01 EUR | passt |
| CHFJPY | 4,38 EUR | passt knapp |
| GBPUSD | 15,75 EUR | 3x zu gross |
| XAGUSD | 27,41 EUR | 5x zu gross |
| XAUUSD | 35,22 EUR | 7x zu gross |

Sonst gaukelt das grosse Demokonto eine Marktauswahl vor, die das echte
Konto spaeter gar nicht hat.

Aenderungen stehen oben in `beobachter.py` im Abschnitt "Einstellungen".

---

## Wenn etwas nicht klappt

**"Python nicht gefunden"** — Python ohne den PATH-Haken installiert.
Neu installieren, Haken setzen.

**"Das Paket MetaTrader5 fehlt"** — `pip install MetaTrader5 pandas`
im richtigen Ordner ausfuehren.

**"MT5-Initialisierung fehlgeschlagen"** — Terminal nicht gestartet oder
nicht eingeloggt.

**"Symbol nicht gefunden"** — `pruefe_verbindung.py` laufen lassen, dort
steht der echte Name.

**Der Beobachter meldet stundenlang nichts** — normal. Auf H1 kommt im
Schnitt alle paar Tage ein Signal, auf H4 seltener. In `beobachter.log`
steht bei jeder neuen Kerze, warum gerade kein Einstieg vorliegt.

---

## Was hier bewusst NICHT liegt

Ein Skript, das echte Auftraege sendet. Es gibt in `beobachter.py`
keinen einzigen Aufruf von `order_send()` — das wird auf dem Server
sogar automatisch geprueft (`test_beobachter.py`).

Echte Auftraege erst, wenn eine Strategie unseren Pruefstand besteht.
Vorher wuerden wir nur testen, ob eine verlierende Regel auch live
verliert. Die Antwort kennen wir.
