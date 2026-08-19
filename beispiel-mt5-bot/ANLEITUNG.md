# 🤖 MT5 Trend+Pullback Bot — Anleitung für absolute Anfänger

> ## ⚠️ NUR FÜR DEMO-KONTEN
> Das hier ist ein **öffentliches Experiment**, kein fertiges Finanzprodukt
> und **keine Anlageberatung**. Der Bot verweigert von sich aus den Start
> auf einem Echtgeldkonto (das steht weiter unten genauer erklärt). Backtest-
> und Demo-Ergebnisse sagen NICHTS Sicheres über die Zukunft aus. Handle
> niemals mit echtem Geld, dessen Verlust du nicht verkraften könntest —
> und schon gar nicht, ohne diesen Bot vorher wochenlang auf einem
> Demo-Konto beobachtet zu haben.

Dieser Text erklärt dir alles Schritt für Schritt, so wie ein Freund es dir
erklären würde — auch wenn du noch nie programmiert oder gehandelt hast.
Jeder Fachbegriff wird beim ersten Auftauchen kurz erklärt.

---

## 1. Was macht dieser Bot überhaupt?

Der Bot beobachtet automatisch ein paar Finanzmärkte (Gold, Silber, Platin,
und zwei Währungspaare) und sucht nach einem ganz bestimmten, immer
gleichen Muster: **ein Aufwärtstrend, der kurz Luft geholt hat und
wahrscheinlich weitergeht.** Findet er dieses Muster, eröffnet er
automatisch eine kleine, streng risikobegrenzte Position — **immer nur in
Kaufrichtung ("Long")**, nie auf fallende Kurse spekulierend ("Short").

Diese Strategie wurde vorher an zehn Jahren echter Kursdaten getestet
(das nennt man **Backtest** — man lässt die Regeln rückwirkend auf alte
Kurse laufen und schaut, was dabei herausgekommen wäre). Das bedeutet
NICHT, dass sie in Zukunft genauso gut funktioniert — nur, dass sie
zumindest in der Vergangenheit einen nachvollziehbaren, nicht rein
zufälligen Vorteil hatte.

---

## 2. Was brauchst du dafür? (einmalig einrichten)

| Was | Warum | Kostet |
|---|---|---|
| **MetaTrader 5 (MT5)** | Das Handelsprogramm, mit dem der Bot verbunden wird. Es zeigt Kurse an und schickt Kauf-/Verkaufsaufträge an den Broker. | kostenlos |
| **Ein Demo-Konto** | Ein "Spielgeld-Konto" bei einem Broker (z. B. 50.000 € virtuell). Sieht in MT5 genau aus wie ein echtes Konto, aber es geht kein echtes Geld verloren. | kostenlos |
| **Python** | Die Programmiersprache, in der der Bot geschrieben ist. Ohne Python kann dein Computer die `bot.py`-Datei nicht ausführen. | kostenlos |
| **Windows** | Das Python-Paket, das mit MT5 spricht, funktioniert nur unter Windows. | — |

### Schritt für Schritt

1. **MetaTrader 5 herunterladen und installieren**, falls noch nicht
   geschehen (von deinem Broker oder direkt von metatrader5.com).
2. **Demo-Konto anlegen**: In MT5 oben auf "Datei" → "Konto eröffnen" →
   "Demo-Konto". Trag ein Startkapital ein (z. B. 50.000), fertig.
3. **Python installieren**: Auf python.org den Windows-Installer laden.
   **Wichtig beim Installieren:** unten den Haken bei "Add Python to PATH"
   setzen — sonst findet dein Computer Python später nicht.
4. **Algo-Handel erlauben**: Oben in der MT5-Werkzeugleiste gibt es einen
   Knopf **"Algo-Handel"** (bzw. "AutoTrading"). Er muss **grün** sein.
   Ist er rot/grau, einmal draufklicken. Ohne das darf KEIN Programm —
   auch dieser Bot nicht — automatisch Orders senden.
5. **Bot-Ordner entpacken**: Diese ZIP an einen Ort deiner Wahl entpacken,
   z. B. auf den Desktop.
6. **Python-Pakete installieren**: Im entpackten Ordner mit gedrückter
   Umschalt-Taste rechtsklicken → "PowerShell-Fenster hier öffnen" (oder
   "Eingabeaufforderung hier öffnen"), dann eingeben:

   ```
   pip install MetaTrader5 pandas
   ```

   Das lädt die zwei Software-Bausteine, die der Bot braucht: die
   Verbindung zu MT5 und ein Werkzeug für Tabellen-/Zahlenrechnungen.

Das war's — diese 6 Schritte machst du nur EIN einziges Mal.

---

## 3. Bot starten

MT5 muss laufen und in deinem Demo-Konto eingeloggt sein. Dann einfach
**doppelklick auf `start_bot.bat`** (im Bot-Ordner) — das öffnet ein
schwarzes Fenster und startet den Bot automatisch.

*(Alternative für Fortgeschrittene: im Bot-Ordner ein Terminal öffnen und
`python bot.py` eintippen — macht dasselbe.)*

### Was die ersten Zeilen bedeuten

Direkt nach dem Start siehst du ungefähr das hier:

```
Verbunden: Konto 12345678 (MetaQuotes-Demo), DEMO, Balance 50000.00 EUR
XAUUSD: aktiv (H1)
XAGUSD: aktiv (H1)
XPTUSD: aktiv (H1)
CHFJPY: aktiv (H4)
USDJPY: aktiv (H4)
Marktzustand beim Start:
   XAUUSD  (H1): Aufwärts ↑ | RSI 52 | RSI muss noch 17 Punkte fallen
Warte auf neue Kerzen...
```

- **"Verbunden: Konto ... DEMO ..."** — der Bot hat sich erfolgreich mit
  deinem MT5 verbunden und **bestätigt selbst, dass es ein Demo-Konto
  ist**. Stünde da "ECHTGELD" statt "DEMO", würde der Bot im nächsten
  Moment von selbst abbrechen (siehe Sicherheits-Kapitel unten).
- **"XAUUSD: aktiv (H1)"** — für jeden Markt eine Zeile: XAUUSD ist der
  Börsenname für Gold, "H1" heißt, der Bot schaut sich Stundenkerzen an
  (eine "Kerze" ist einfach der Kursverlauf innerhalb eines Zeitfensters:
  Eröffnung, Höchst-, Tiefst- und Schlusskurs dieser Stunde).
- **"Marktzustand beim Start"** — eine Momentaufnahme: wie weit ist jeder
  Markt gerade von einem Signal entfernt? **RSI** ist ein Indikator
  zwischen 0 und 100, der misst, wie "überkauft" oder "überverkauft" ein
  Markt gerade ist — eine Art Stimmungs-Thermometer für den Kurs.
- **"Warte auf neue Kerzen..."** — der Bot läuft jetzt dauerhaft im
  Hintergrund und prüft alle 30 Sekunden, ob eine neue Stunden-/4-Stunden-
  Kerze fertig ist und ob sie ein Signal auslöst.

**Es ist völlig normal, dass stunden- oder sogar tagelang gar nichts
passiert.** Die Strategie handelt im Schnitt nur etwa 2x pro Woche über
ALLE 5 Märkte zusammen. Kein Signal bedeutet kein Trade bedeutet: alles
läuft wie geplant.

---

## 4. Bot stoppen

Klick ins schwarze Fenster und drück **Strg + C**.

**Wichtig:** Falls der Bot gerade eine offene Position hat, bleibt die
**trotzdem sicher**, weil der **Stop-Loss** (die automatische
Verlust-Bremse, ein vorher festgelegter Kurs, bei dem die Position
automatisch geschlossen wird, um größere Verluste zu verhindern) und der
**Take-Profit** (das Gewinnziel, bei dem automatisch verkauft wird) **beim
Broker gespeichert sind, nicht in deinem Bot-Fenster**. Selbst wenn dein
PC komplett ausgeht, greifen diese Schutzmarken weiter.

---

## 5. Was der Bot tut — und was er bewusst NICHT tut

- Maximal **1 Position pro Markt** und maximal **3 Positionen insgesamt**
  gleichzeitig (Gold/Silber/Platin bewegen sich sehr ähnlich — 3 offene
  Metall-Positionen wären in Wahrheit 3x dasselbe Risiko).
- Jeder Trade riskiert **1 % des aktuellen Kontostands** (bei 50.000 €
  Demo-Kapital also ungefähr 500 €) — nie mehr.
- **Jede** Order geht IMMER mit Stop-Loss UND Take-Profit gleichzeitig
  raus. Eine Order ganz ohne Schutz gibt es in diesem Bot nicht.
- Der Bot fasst **ausschließlich seine eigenen Trades** an (erkennbar an
  einer internen Kennnummer, der "Magic Number") — du kannst daneben
  jederzeit von Hand traden, ohne dass sich der Bot einmischt.
- Er handelt **niemals alte, verpasste Signale nach**, wenn du ihn neu
  startest — nur brandneue Signale ab dem Moment des Starts zählen.
- Er handelt **ausschließlich Long** (auf steigende Kurse) — er wettet
  nie auf fallende Kurse.

---

## 6. Sicherheits-Bausteine (damit du weißt, worauf du dich verlässt)

- **Demo-Sperre:** In `config.py` steht `ALLOW_REAL_ACCOUNT = False`. Ist
  dein eingeloggtes Konto kein Demo-Konto, bricht der Bot beim Start
  sofort ab, bevor er auch nur einen einzigen Klick macht.
- **Realistische Positionsgrößen:** Der Bot fragt für jede geplante
  Position direkt den Broker, wie viel Geld sie beim Erreichen des
  Stop-Loss tatsächlich kosten würde (`order_calc_profit` — eine
  Broker-eigene Berechnungsfunktion), statt das selbst grob zu schätzen.
  Das verhindert genau den Fehler, der in einer älteren Community-Version
  aufgetreten ist (siehe `CHANGELOG.md`).
- **Immer abrunden, nie aufrunden:** Bei der Positionsgröße wird
  konsequent nach unten gerundet — im Zweifel wird lieber etwas WENIGER
  riskiert als geplant, nie mehr.
- **Doppelter Sicherheitscheck vor jeder Order:** Bevor eine Order
  abgeschickt wird, rechnet der Bot ein zweites Mal nach, ob das
  tatsächliche Risiko nicht mehr als das 1,5-fache des Ziels beträgt.
  Ist das der Fall, wird der Trade lieber ganz abgesagt.
- **Schutz-Wächter nach jeder Order:** Nach jeder eröffneten Position
  prüft der Bot aktiv nach, ob Stop-Loss und Take-Profit auch wirklich
  beim Broker angekommen sind. Falls nicht, versucht er es erneut — und
  schließt die Position notfalls sofort wieder, statt sie ungeschützt
  offen zu lassen.
- **Echtes Risiko im Protokoll:** Im Trade-Journal (`trades.csv`) landet
  das tatsächlich berechnete Risiko jedes Trades, nicht nur der geplante
  1 %-Zielwert.

---

## 7. Das Protokoll (Log)

Alles, was der Bot tut oder prüft, landet zweifach: im schwarzen Fenster
UND in der Datei `bot.log` im selben Ordner. Jedes Signal, jede Order,
jeder Grund für einen übersprungenen Trade steht dort — falls mal etwas
unklar ist, lohnt sich immer zuerst ein Blick in diese Datei.

Trades selbst (eröffnet UND geschlossen) landen zusätzlich in `trades.csv`
— das lässt sich direkt in Excel öffnen (Semikolon-getrennt).

---

## 8. Die Demo-Phase richtig nutzen (4–8 Wochen)

Einmal pro Woche kurz reinschauen und dir Folgendes notieren:

1. Wie viele Signale gab es? (Erwartung: ungefähr 2 pro Woche über alle
   5 Märkte zusammen — bei wenigen Märkten schwankt das stark.)
2. Wurden sie ausgeführt? Falls ein Signal übersprungen wurde — stand ein
   nachvollziehbarer Grund im Log?
3. Stimmen die Positionsgrößen ungefähr mit 1 % Risiko überein?
4. Lief dein PC/MT5 durchgehend? (Der Bot handelt nur, während er aktiv
   läuft — für echten Dauerbetrieb später eignet sich ein günstiger
   Windows-VPS, ein gemieteter Mini-Server, der rund um die Uhr läuft,
   für ca. 5–10 €/Monat.)

Nach 4–8 Wochen: Ähneln Trefferquote und Gewinn/Verlust-Verhältnis grob
dem, was im Backtest zu erwarten wäre (ungefähr 45–55 % Trefferquote,
Gewinner im Schnitt etwa doppelt so groß wie Verlierer)? Wenn ja, kannst
DU (niemand sonst) irgendwann in Ruhe über einen sehr kleinen
Echtgeld-Test nachdenken. Wenn nein, hat dir das Demo-Konto gerade bares
Geld gespart.

---

## 9. Einstellungen ändern

Alles Wichtige (Märkte, Risiko-Prozentsatz, Strategie-Parameter) steht in
`config.py`, mit deutschen Kommentaren direkt daneben. Nach jeder Änderung
den Bot einmal neu starten (Strg+C, dann wieder `start_bot.bat`).

---

## 10. FAQ — die 5 häufigsten Anfängerfragen

**1. "Der Bot läuft schon seit Stunden und hat noch keinen einzigen Trade
gemacht — ist er kaputt?"**
Nein, das ist normal. Die Strategie ist bewusst wählerisch: im Schnitt nur
etwa 2 Signale pro Woche über alle 5 Märkte. Kein Trade heißt: der Bot
wartet korrekt auf sein Muster, statt wild drauflos zu handeln.

**2. "Kann ich meinen PC ausschalten, während eine Position offen ist?"**
Der Bot selbst braucht einen laufenden PC, um NEUE Signale zu erkennen.
Aber eine BEREITS eröffnete Position ist trotzdem sicher, weil Stop-Loss
und Take-Profit beim Broker liegen — die greifen auch, wenn dein PC aus
ist. Für dauerhaften Betrieb (auch nachts, auch im Urlaub) brauchst du
später einen durchgehend laufenden Computer, z. B. einen kleinen
Windows-VPS.

**3. "Ich sehe 'ECHTGELD' statt 'DEMO' beim Verbinden — was mache ich
jetzt?"**
Nichts musst du tun — der Bot bricht in diesem Fall selbst sofort ab und
öffnet keine einzige Position. Prüf in MT5, ob wirklich dein Demo-Konto
eingeloggt ist (oben im Programm sichtbar), logg dich notfalls neu ein
und starte den Bot erneut.

**4. "Was ist eigentlich ein 'Pip' / ein 'Lot' / ein 'Spread'?"**
- **Lot** = die Größeneinheit einer Position (vergleichbar mit "wie viele
  Stück du kaufst") — der Bot berechnet diese Größe für dich automatisch
  aus deinem Risiko-Budget.
- **Spread** = der kleine Unterschied zwischen Kauf- und Verkaufspreis,
  den jeder Broker als eine Art eingebaute Gebühr verlangt.
- **Pip** = die kleinste übliche Kursbewegungs-Einheit bei den meisten
  Währungspaaren (z. B. von 1,1050 auf 1,1051).
  Du musst mit diesen Begriffen nichts selbst berechnen — der Bot
  übernimmt das —, aber sie tauchen im MT5-Terminal überall auf.

**5. "Ich habe eine Fehlermeldung bekommen / der Bot startet gar nicht —
was jetzt?"**
Fast immer einer von drei Gründen:
- MT5 läuft nicht oder ist nicht eingeloggt → MT5 öffnen und einloggen.
- "Algo-Handel" ist nicht grün → in MT5 draufklicken, bis er grün ist.
- Python-Pakete fehlen → im Bot-Ordner nochmal
  `pip install MetaTrader5 pandas` ausführen.
Steht eine konkrete Fehlermeldung im schwarzen Fenster, hilft meistens
schon ein Blick in `bot.log` — dort steht i.d.R. genauer, woran es lag.

---

## 11. Nochmal ganz deutlich

Dieser Bot ist ein öffentlich geteiltes Experiment aus einem
Trading-Bot-Recherche-Projekt — **keine Anlageberatung, keine
Gewinngarantie, keine Finanzdienstleistung**. Alles, was hier gezeigt oder
versprochen wird, bezieht sich ausschließlich auf ein Demo-("Spielgeld"-)
Konto. Handle nur mit echtem Geld, wenn du die vollen Risiken verstehst,
den Bot selbst über Wochen beobachtet hast und dir des Verlustrisikos
bewusst bist.
