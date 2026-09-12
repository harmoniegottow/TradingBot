#!/usr/bin/env python3
"""lade_ctrader.py - Historische Kerzen aus der cTrader Open API holen.

Schreibt CSV-Dateien nach data-ctrader/ im selben Format wie data/ und
data-mt5/ (Spalten Zeit,Open,High,Low,Close,Volume), damit pruefstand.py
und vergleich.py sie ohne Anpassung lesen koennen.

Aufruf:

    .venv/bin/python lade_ctrader.py XAUUSD H1 2026-07-01 2026-08-01

Von-Datum einschliesslich, Bis-Datum ausschliesslich, beides UTC. Der
Dateiname folgt der Projektschreibweise: XAUUSD_H_1.csv.

Das Access-Token wird nie ausgegeben.
"""
from __future__ import annotations

import argparse
import csv
import sys
import time
from collections import deque
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from functools import partial
from pathlib import Path

from ctrader_open_api.messages.OpenApiMessages_pb2 import (
    ProtoOAAccountAuthReq,
    ProtoOAApplicationAuthReq,
    ProtoOAGetAccountListByAccessTokenReq,
    ProtoOAGetTrendbarsReq,
    ProtoOASymbolsListReq,
)
from ctrader_open_api.messages.OpenApiModelMessages_pb2 import ProtoOATrendbarPeriod
from twisted.internet import defer, reactor, task

from verbindung import (
    Verbindungsfehler,
    anfrage_senden,
    konto_waehlen,
    mit_verbindung_ausfuehren,
    schritt,
)

ZIEL_ORDNER = Path(__file__).resolve().parent / "data-ctrader"
SPALTEN = ("Zeit", "Open", "High", "Low", "Close", "Volume")
# Protokoll der zentral entfernten Kerzen - nichts verschwindet unbemerkt.
ENTFERNT_DATEI = ZIEL_ORDNER / "entfernte_kerzen.csv"
ENTFERNT_SPALTEN = ("Symbol", "Zeitrahmen", "Zeit", "Grund")
GRUND_NULLVOLUMEN = "Volumen null"

# Preise kommen als Ganzzahl in Einheiten von 1/100000.
PREIS_FAKTOR = Decimal(100_000)
PREIS_STELLEN = 5

# Zeitrahmen: Name -> (Protobuf-Konstante, Dateisuffix, Laenge in Minuten).
# Die Abschnittslaenge richtet sich danach, wie viele Kerzen der Server je
# Anfrage herausgibt - lieber knapp bemessen und dafuer verlaesslich.
ZEITRAHMEN = {
    "M1": ("M1", "M_1", 1, timedelta(days=3)),
    "M5": ("M5", "M_5", 5, timedelta(days=14)),
    "M15": ("M15", "M_15", 15, timedelta(days=40)),
    "M30": ("M30", "M_30", 30, timedelta(days=80)),
    "H1": ("H1", "H_1", 60, timedelta(days=150)),
    "H4": ("H4", "H_4", 240, timedelta(days=300)),
    "D1": ("D1", "D_1", 1440, timedelta(days=1200)),
    "W1": ("W1", "W_1", 10080, timedelta(days=2400)),
}

# Uebliche Bezeichnungen beim Broker, falls der Grundname nicht vorkommt.
NAMENS_ALTERNATIVEN = {
    "XAUUSD": ["GOLD", "GOLDUSD", "XAU/USD"],
    "XAGUSD": ["SILVER", "SILVERUSD", "XAG/USD"],
    "XPTUSD": ["PLATINUM"],
}

# Hoechstens so viele Anfragen fuer historische Daten je Sekunde.
ANFRAGEN_JE_SEKUNDE = 5
DROSSEL_FENSTER = 1.0
# Lehnt der Server den Zeitraum ab, wird der Abschnitt halbiert.
HALBIEREN_FEHLERCODES = frozenset({"INCORRECT_BOUNDARIES"})
# Bei zu vielen Anfragen kurz warten und denselben Abschnitt wiederholen.
BREMSE_FEHLERCODE = "REQUEST_FREQUENCY_EXCEEDED"
BREMSE_WARTEZEIT = 2.0
MAX_BREMS_VERSUCHE = 3
# Kleiner wird ein Abschnitt nicht - sonst dreht sich die Halbierung im Kreis.
MIN_ABSCHNITT = timedelta(hours=1)
# Vorsichtsmassnahme: Endet eine Antwort mehr als diese Zahl Kerzen vor dem
# angefragten Ende, wird der Rest nachgefordert. Gemessen wurde eine solche
# Kuerzung bisher NICHT - Anfragen bis 600 Tage kamen vollstaendig zurueck.
FEHLBETRAG_KERZEN = 2
# Notbremse gegen endloses Nachfordern.
MAX_NACHFORDERUNGEN = 60


class Drosselung:
    """Laesst hoechstens `hoechstzahl` Anfragen je Zeitfenster durch."""

    def __init__(self, hoechstzahl: int = ANFRAGEN_JE_SEKUNDE,
                 fenster: float = DROSSEL_FENSTER):
        self._hoechstzahl = hoechstzahl
        self._fenster = fenster
        self._zeiten: deque[float] = deque()

    @defer.inlineCallbacks
    def warten(self):
        while True:
            jetzt = time.monotonic()
            while self._zeiten and jetzt - self._zeiten[0] >= self._fenster:
                self._zeiten.popleft()
            if len(self._zeiten) < self._hoechstzahl:
                break
            yield task.deferLater(reactor, self._fenster - (jetzt - self._zeiten[0]))
        self._zeiten.append(time.monotonic())


def datum_lesen(text: str) -> datetime:
    try:
        return datetime.strptime(text, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise SystemExit(f"Datum '{text}' ist nicht im Format JJJJ-MM-TT.") from exc


def millisekunden(zeitpunkt: datetime) -> int:
    return int(zeitpunkt.timestamp() * 1000)


def symbol_zuordnen(symbole, gesucht: str) -> tuple[int, str]:
    """Sucht die symbolId zum Namen, auch unter den ueblichen Alternativen."""
    nach_name = {s.symbolName.upper(): s for s in symbole}
    kandidaten = [gesucht.upper()] + [
        name.upper() for name in NAMENS_ALTERNATIVEN.get(gesucht.upper(), [])
    ]
    for name in kandidaten:
        treffer = nach_name.get(name)
        if treffer is not None:
            print(f"   {gesucht} -> symbolId {treffer.symbolId} (Broker nennt es"
                  f" '{treffer.symbolName}')")
            return treffer.symbolId, treffer.symbolName

    # Nichts gefunden - beim Suchen helfen statt nur abzubrechen.
    teiltreffer = sorted(
        s.symbolName for s in symbole if gesucht.upper()[:3] in s.symbolName.upper()
    )
    raise Verbindungsfehler(
        f"Symbol '{gesucht}' nicht gefunden. Gesucht wurde auch nach:"
        f" {', '.join(kandidaten[1:]) or 'keine Alternativen hinterlegt'}.\n"
        f"Aehnliche Namen beim Broker: {', '.join(teiltreffer[:15]) or 'keine'}"
    )


def kerze_umrechnen(balken) -> tuple[datetime, Decimal, Decimal, Decimal, Decimal, int]:
    """Trendbar in Zeit und echte Preise wandeln.

    low ist absolut, deltaOpen/deltaHigh/deltaClose sind Abstaende, die auf
    low ADDIERT werden. Alles in Einheiten von 1/100000, daher Decimal.
    """
    tief = Decimal(balken.low)
    zeit = datetime.fromtimestamp(balken.utcTimestampInMinutes * 60, tz=timezone.utc)
    return (
        zeit,
        (tief + Decimal(balken.deltaOpen)) / PREIS_FAKTOR,
        (tief + Decimal(balken.deltaHigh)) / PREIS_FAKTOR,
        tief / PREIS_FAKTOR,
        (tief + Decimal(balken.deltaClose)) / PREIS_FAKTOR,
        balken.volume,
    )


def _darf_halbieren(fehler: Verbindungsfehler, von: datetime, bis: datetime) -> bool:
    return fehler.code in HALBIEREN_FEHLERCODES and (bis - von) > MIN_ABSCHNITT


def rest_anfang(letzte_kerze: datetime, bis: datetime, minuten: int):
    """Ab wann fehlt noch etwas? Liefert None, wenn der Abschnitt komplett ist.

    Netz, kein belegter Fehlerfall: Sollte eine Antwort frueher enden als
    angefragt, wird der Rest nachgeholt statt still verloren zu gehen.

    Wichtig fuer die Einordnung: Eine frueh endende Antwort bedeutet nicht
    zwingend einen Fehler. Fehlen beim Broker echte Daten - etwa XAUUSD H4
    von Juli bis September 2020 -, endet die Antwort ebenfalls frueher. Die
    Nachforderung holt dann schlicht nichts, und das ist richtig so.
    """
    dauer = timedelta(minutes=minuten)
    fehlbetrag = bis - (letzte_kerze + dauer)
    if fehlbetrag <= dauer * FEHLBETRAG_KERZEN:
        return None
    return letzte_kerze + dauer


@defer.inlineCallbacks
def abschnitt_laden(client, drossel, konto_id, symbol_id, periode, von, bis,
                    tiefe=0, leise=False, minuten=None, nachforderung=0):
    """Holt einen Zeitabschnitt; halbiert ihn, wenn der Server ihn ablehnt."""
    for versuch in range(MAX_BREMS_VERSUCHE + 1):
        yield drossel.warten()
        try:
            antwort = yield anfrage_senden(
                client,
                ProtoOAGetTrendbarsReq(
                    ctidTraderAccountId=konto_id,
                    symbolId=symbol_id,
                    period=periode,
                    fromTimestamp=millisekunden(von),
                    toTimestamp=millisekunden(bis),
                ),
            )
        except Verbindungsfehler as fehler:
            if fehler.code == BREMSE_FEHLERCODE and versuch < MAX_BREMS_VERSUCHE:
                print(f"      Server bremst, warte {BREMSE_WARTEZEIT:.0f}s ...")
                yield task.deferLater(reactor, BREMSE_WARTEZEIT)
                continue
            if _darf_halbieren(fehler, von, bis):
                mitte = von + (bis - von) / 2
                print(f"      Abschnitt zu gross ({fehler.code}), halbiere bei"
                      f" {mitte:%Y-%m-%d %H:%M}")
                links = yield abschnitt_laden(
                    client, drossel, konto_id, symbol_id, periode, von, mitte,
                    tiefe + 1, leise, minuten,
                )
                rechts = yield abschnitt_laden(
                    client, drossel, konto_id, symbol_id, periode, mitte, bis,
                    tiefe + 1, leise, minuten,
                )
                return links + rechts
            raise
        else:
            balken = list(antwort.trendbar)
            if not leise:
                print(f"      {von:%Y-%m-%d} bis {bis:%Y-%m-%d}:"
                      f" {len(balken)} Kerzen")
            if balken and minuten and nachforderung < MAX_NACHFORDERUNGEN:
                letzte = max(kerze_umrechnen(b)[0] for b in balken)
                weiter = rest_anfang(letzte, bis, minuten)
                if weiter is not None:
                    if not leise:
                        print(f"      Antwort endet bei {letzte:%Y-%m-%d},"
                              f" fordere Rest ab {weiter:%Y-%m-%d} nach")
                    rest = yield abschnitt_laden(
                        client, drossel, konto_id, symbol_id, periode, weiter,
                        bis, tiefe, leise, minuten, nachforderung + 1,
                    )
                    balken.extend(rest)
            return balken

    raise Verbindungsfehler(
        f"Abschnitt {von:%Y-%m-%d} bis {bis:%Y-%m-%d} auch nach"
        f" {MAX_BREMS_VERSUCHE} Wiederholungen abgelehnt."
    )


def abschnitte_bilden(von: datetime, bis: datetime, laenge: timedelta) -> list:
    """Halboffene Abschnitte [start, ende) - luecken- und ueberschneidungsfrei."""
    abschnitte = []
    start = von
    while start < bis:
        ende = min(start + laenge, bis)
        abschnitte.append((start, ende))
        start = ende
    return abschnitte


def kerzen_aufbereiten(balken_liste, von, bis, minuten: int) -> list:
    """Trendbars dekodieren und aufbereiten."""
    return zeilen_aufbereiten(
        (kerze_umrechnen(balken) for balken in balken_liste), von, bis, minuten
    )


def zeilen_aufbereiten(zeilen, von, bis, minuten: int) -> list:
    """Sortieren, entdoppeln, Zeitraum beschneiden, laufende Kerze verwerfen.

    Arbeitet auf fertigen Zeilen, damit auch zwischengespeicherte Teildateien
    durch dieselbe Pruefung laufen wie frisch geholte Kerzen.
    """
    jetzt = datetime.now(timezone.utc)
    dauer = timedelta(minutes=minuten)
    nach_zeit = {}
    verworfen_laufend = 0

    for zeile in zeilen:
        zeit = zeile[0]
        if zeit < von or zeit >= bis:
            continue
        # Nur abgeschlossene Kerzen: das Ende muss in der Vergangenheit liegen.
        if zeit + dauer > jetzt:
            verworfen_laufend += 1
            continue
        nach_zeit[zeit] = zeile

    if verworfen_laufend:
        print(f"   {verworfen_laufend} noch laufende Kerze(n) verworfen.")
    return [nach_zeit[zeit] for zeit in sorted(nach_zeit)]


def nullvolumen_trennen(zeilen) -> tuple[list, list]:
    """Trennt Kerzen ohne Volumen ab - zentral fuer alle Symbole.

    Der Broker legt vor der Wocheneroeffnung Fuellkerzen ohne Handel an. Die
    echten Sonntagskerzen ab etwa 20:00 UTC tragen Volumen und bleiben; nur
    das Volumen entscheidet, nicht der Wochentag. Entfernte Kerzen landen in
    entfernte_kerzen.csv, damit Haeufungen auffindbar bleiben.
    """
    behalten, entfernt = [], []
    for zeile in zeilen:
        (entfernt if zeile[5] == 0 else behalten).append(zeile)
    return behalten, entfernt


def entfernte_schreiben(symbol: str, zeitrahmen: str, entfernt, grund: str) -> None:
    """Schreibt das Protokoll fort: eigene Eintraege ersetzen, fremde behalten."""
    ZIEL_ORDNER.mkdir(exist_ok=True)
    vorhanden = []
    if ENTFERNT_DATEI.exists():
        with ENTFERNT_DATEI.open(newline="", encoding="utf-8") as datei:
            vorhanden = [satz for satz in csv.DictReader(datei)
                         if not (satz["Symbol"] == symbol
                                 and satz["Zeitrahmen"] == zeitrahmen)]
    neu = [{"Symbol": symbol, "Zeitrahmen": zeitrahmen,
            "Zeit": zeile[0].strftime("%Y-%m-%d %H:%M:%S"), "Grund": grund}
           for zeile in entfernt]
    alle = sorted(vorhanden + neu,
                  key=lambda s: (s["Symbol"], s["Zeitrahmen"], s["Zeit"]))
    with ENTFERNT_DATEI.open("w", newline="", encoding="utf-8") as datei:
        schreiber = csv.DictWriter(datei, fieldnames=ENTFERNT_SPALTEN)
        schreiber.writeheader()
        schreiber.writerows(alle)


def zeilen_schreiben(pfad: Path, zeilen) -> Path:
    """Schreibt Kerzen im Projektformat. Erst in .tmp, dann umbenennen -
    ein Abbruch mitten im Schreiben hinterlaesst so keine halbe Datei."""
    pfad.parent.mkdir(parents=True, exist_ok=True)
    vorlaeufig = pfad.with_suffix(pfad.suffix + ".tmp")
    with vorlaeufig.open("w", newline="", encoding="utf-8") as datei:
        schreiber = csv.writer(datei)
        schreiber.writerow(SPALTEN)
        for zeit, offen, hoch, tief, schluss, volumen in zeilen:
            schreiber.writerow([
                zeit.strftime("%Y-%m-%d %H:%M:%S"),
                f"{offen:.{PREIS_STELLEN}f}",
                f"{hoch:.{PREIS_STELLEN}f}",
                f"{tief:.{PREIS_STELLEN}f}",
                f"{schluss:.{PREIS_STELLEN}f}",
                volumen,
            ])
    vorlaeufig.replace(pfad)
    return pfad


def csv_schreiben(zeilen, symbol: str, suffix: str) -> Path:
    return zeilen_schreiben(ZIEL_ORDNER / f"{symbol}_{suffix}.csv", zeilen)


def luecken_melden(zeilen, minuten: int) -> None:
    """Groessere Spruenge benennen - Wochenenden sind normal, der Rest nicht."""
    dauer = timedelta(minutes=minuten)
    spruenge = [
        (vorher[0], nachher[0], nachher[0] - vorher[0])
        for vorher, nachher in zip(zeilen, zeilen[1:])
        if nachher[0] - vorher[0] > dauer
    ]
    if not spruenge:
        print("   Keine Spruenge - lueckenlose Reihe.")
        return
    print(f"   {len(spruenge)} Spruenge groesser als ein Zeitrahmen"
          " (Wochenenden und Feiertage sind normal):")
    for anfang, ende, abstand in spruenge[:5]:
        print(f"      {anfang:%Y-%m-%d %H:%M} -> {ende:%Y-%m-%d %H:%M}"
              f"  ({abstand})")
    if len(spruenge) > 5:
        print(f"      ... und {len(spruenge) - 5} weitere")


@defer.inlineCallbacks
def daten_ablauf(client, client_id, client_secret, token, args):
    periode_name, suffix, minuten, abschnitt_laenge = ZEITRAHMEN[args.zeitrahmen]
    periode = ProtoOATrendbarPeriod.Value(periode_name)

    schritt(1, "Anwendung und Konto anmelden")
    yield anfrage_senden(
        client,
        ProtoOAApplicationAuthReq(clientId=client_id, clientSecret=client_secret),
    )
    konten = yield anfrage_senden(
        client, ProtoOAGetAccountListByAccessTokenReq(accessToken=token)
    )
    konto_id = konto_waehlen(list(konten.ctidTraderAccount))
    yield anfrage_senden(
        client, ProtoOAAccountAuthReq(ctidTraderAccountId=konto_id, accessToken=token)
    )
    print("   Konto angemeldet.")

    schritt(2, "Symbolliste abrufen und Namen zuordnen")
    symbol_antwort = yield anfrage_senden(
        client, ProtoOASymbolsListReq(ctidTraderAccountId=konto_id)
    )
    symbole = list(symbol_antwort.symbol)
    print(f"   {len(symbole)} Symbole beim Broker.")
    symbol_id, broker_name = symbol_zuordnen(symbole, args.symbol)

    schritt(3, f"Kerzen holen: {args.symbol} {args.zeitrahmen}")
    abschnitte = abschnitte_bilden(args.von, args.bis, abschnitt_laenge)
    print(f"   {args.von:%Y-%m-%d} bis {args.bis:%Y-%m-%d} in"
          f" {len(abschnitte)} Abschnitt(en), hoechstens"
          f" {ANFRAGEN_JE_SEKUNDE} Anfragen je Sekunde.")

    drossel = Drosselung()
    alle_balken = []
    for von, bis in abschnitte:
        balken = yield abschnitt_laden(
            client, drossel, konto_id, symbol_id, periode, von, bis,
            minuten=minuten,
        )
        alle_balken.extend(balken)

    schritt(4, "Aufbereiten und speichern")
    zeilen = kerzen_aufbereiten(alle_balken, args.von, args.bis, minuten)
    if not zeilen:
        raise Verbindungsfehler(
            f"Keine abgeschlossenen Kerzen fuer {args.symbol} {args.zeitrahmen}"
            f" im Zeitraum {args.von:%Y-%m-%d} bis {args.bis:%Y-%m-%d} erhalten."
        )
    print(f"   {len(alle_balken)} Kerzen empfangen, {len(zeilen)} nach"
          " Entdoppeln und Zuschnitt.")
    zeilen, ohne_volumen = nullvolumen_trennen(zeilen)
    if ohne_volumen:
        entfernte_schreiben(args.symbol.upper(), suffix, ohne_volumen,
                            GRUND_NULLVOLUMEN)
        print(f"   {len(ohne_volumen)} Kerzen ohne Volumen entfernt"
              f" - protokolliert in {ENTFERNT_DATEI.name}")
    luecken_melden(zeilen, minuten)

    pfad = csv_schreiben(zeilen, args.symbol.upper(), suffix)
    print(f"\n   Gespeichert: {pfad}")
    print(f"   Broker-Symbol: {broker_name}")
    print(f"   Zeitraum: {zeilen[0][0]:%Y-%m-%d %H:%M} bis"
          f" {zeilen[-1][0]:%Y-%m-%d %H:%M} UTC")


def argumente_lesen(argv=None):
    parser = argparse.ArgumentParser(
        description="Historische Kerzen aus der cTrader Open API laden"
    )
    parser.add_argument("symbol", help="z. B. XAUUSD")
    parser.add_argument("zeitrahmen", choices=sorted(ZEITRAHMEN), help="z. B. H1")
    parser.add_argument("von", help="Startdatum JJJJ-MM-TT (UTC, einschliesslich)")
    parser.add_argument("bis", help="Enddatum JJJJ-MM-TT (UTC, ausschliesslich)")
    args = parser.parse_args(argv)
    args.von = datum_lesen(args.von)
    args.bis = datum_lesen(args.bis)
    if args.bis <= args.von:
        raise SystemExit("Das Bis-Datum muss nach dem Von-Datum liegen.")
    return args


def main() -> int:
    args = argumente_lesen()
    return mit_verbindung_ausfuehren(
        partial(daten_ablauf, args=args), abschluss_text="Fertig."
    )


if __name__ == "__main__":
    sys.exit(main())
