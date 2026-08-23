# MT5 unter Windows — was hier liegt

Dieser Ordner enthaelt Skripte, die **nur unter Windows** laufen, weil das
Python-Paket `MetaTrader5` ausschliesslich fuer Windows veroeffentlicht wird
(geprueft 23.08.2026: alle je erschienenen Versionen tragen nur die
Plattform-Kennungen `win32` und `win_amd64`).

Auf dem Linux-Server sind sie nicht ausfuehrbar. Sie gehoeren auf den
Rechner, auf dem das MT5-Terminal laeuft.

## Einmalige Vorbereitung auf dem Windows-Rechner

1. Python ab 3.10 installieren, beim Installieren den Haken bei
   **"Add python.exe to PATH"** setzen.
2. MT5 starten und im **Demokonto** einloggen.
3. Eingabeaufforderung in diesem Ordner oeffnen (Adresszeile im Explorer
   anklicken, `cmd` eintippen, Enter) und eingeben:

       pip install MetaTrader5 pandas

## hole_historie.py — Kursdaten abholen

Holt Kurse als CSV im selben Format wie unsere `data/`-Dateien. **Handelt
nicht**, liest nur.

    python hole_historie.py                  Standardliste, 10 Jahre, H1+H4+D1
    python hole_historie.py XAUUSD XAGUSD    nur diese Symbole
    python hole_historie.py --jahre 10       Zeitraum festlegen

Die Dateien landen im Unterordner `data` und werden danach auf den Server
nach `tradingbot/data/` kopiert.

**Warum das zuerst kommt:** Uns fehlt lange Historie. Fuer die
Divergenz-Idee hatten wir zwei Jahre H4 gegen die behaupteten zehn — mit
zehn Jahren wird die Pruefung erst aussagekraeftig. Das bringt sofort
Nutzen, ganz ohne einen einzigen Trade.

## Falls ein Symbol nicht gefunden wird

Broker benennen Maerkte unterschiedlich (`GOLD` statt `XAUUSD`,
`EURUSD.a`, `EURUSD.m`). Im MT5-Marktfenster nachsehen, wie der Markt
beim eigenen Broker heisst, und den Namen beim Aufruf mitgeben.

## Was hier bewusst NICHT liegt

Ein Skript, das echte Auftraege sendet. Begruendung steht in der
Vault-Notiz "MetaTrader 5 Demokonto": Die Strategien der Beispiel-Bots
haben unseren Pruefstand nicht bestanden — zehn von zwoelf Laeufen
verlieren Geld, die uebrigen zwei sind von Zufall nicht zu unterscheiden.
Ein Demokonto kostet zwar kein Geld, aber Wochen an Zeit und erzeugt
Vertrauen in Zahlen, die wir vorher schon als wertlos gemessen haben.

Naechster sinnvoller Schritt ist der Beobachtungsmodus: Bot erkennt
Signale und schreibt das Journal, sendet aber keine Auftraege.
