#!/usr/bin/env python3
"""lade_ctrader_voll.py - Vollhistorie aller Korb-Symbole nach data-ctrader/.

Symbole aus korb.json, Zeitrahmen H1 und H4, so weit zurueck wie cTrader
liefert. Der Lauf dauert lange und ist deshalb wiederaufnehmbar: jeder
geladene Abschnitt liegt als Teildatei unter data-ctrader/.teile/. Ein
Neustart ueberspringt, was schon da ist.

Aufruf:

    .venv/bin/python lade_ctrader_voll.py                 # alles
    .venv/bin/python lade_ctrader_voll.py --symbole XAUUSD XAGUSD
    .venv/bin/python lade_ctrader_voll.py --zeitrahmen H4
    .venv/bin/python lade_ctrader_voll.py --neu           # Teildateien verwerfen

Das Access-Token wird nie ausgegeben.
"""
from __future__ import annotations

import argparse
import csv
import json
import shutil
import sys
from datetime import datetime, timezone
from decimal import Decimal
from functools import partial
from pathlib import Path

from ctrader_open_api.messages.OpenApiMessages_pb2 import (
    ProtoOAAccountAuthReq,
    ProtoOAApplicationAuthReq,
    ProtoOAGetAccountListByAccessTokenReq,
    ProtoOASymbolsListReq,
)
from ctrader_open_api.messages.OpenApiModelMessages_pb2 import ProtoOATrendbarPeriod
from twisted.internet import defer

from lade_ctrader import (
    ZEITRAHMEN,
    ZIEL_ORDNER,
    GRUND_NULLVOLUMEN,
    Drosselung,
    abschnitt_laden,
    abschnitte_bilden,
    entfernte_schreiben,
    kerze_umrechnen,
    nullvolumen_trennen,
    symbol_zuordnen,
    zeilen_aufbereiten,
    zeilen_schreiben,
)
from verbindung import (
    Verbindungsfehler,
    anfrage_senden,
    konto_waehlen,
    mit_verbindung_ausfuehren,
)

WURZEL = Path(__file__).resolve().parent
KORB_DATEI = WURZEL / "korb.json"
TEILE_ORDNER = ZIEL_ORDNER / ".teile"

# Startpunkte mit Sicherheitsabstand. Gemessen beginnt XAUUSD H1 im Oktober
# 2010 und H4 im Januar 2007; leere Abschnitte davor kosten nur eine Anfrage.
STARTPUNKT = {
    "H1": datetime(2006, 1, 1, tzinfo=timezone.utc),
    "H4": datetime(2004, 1, 1, tzinfo=timezone.utc),
}
STANDARD_ZEITRAHMEN = ("H1", "H4")


def korb_lesen() -> dict:
    if not KORB_DATEI.exists():
        raise SystemExit(f"{KORB_DATEI} fehlt.")
    return json.loads(KORB_DATEI.read_text(encoding="utf-8"))


def teil_pfad(symbol: str, zeitrahmen: str, von: datetime) -> Path:
    return TEILE_ORDNER / f"{symbol}_{zeitrahmen}" / f"{von:%Y%m%d}.csv"


def teil_lesen(pfad: Path) -> list:
    """Teildatei zurueck in Zeilen wandeln - Preise bleiben exakt (Decimal)."""
    zeilen = []
    with pfad.open(newline="", encoding="utf-8") as datei:
        for satz in csv.DictReader(datei):
            zeit = datetime.strptime(satz["Zeit"], "%Y-%m-%d %H:%M:%S")
            zeilen.append((
                zeit.replace(tzinfo=timezone.utc),
                Decimal(satz["Open"]), Decimal(satz["High"]),
                Decimal(satz["Low"]), Decimal(satz["Close"]),
                int(satz["Volume"]),
            ))
    return zeilen


@defer.inlineCallbacks
def zeitrahmen_laden(client, drossel, konto_id, symbol, symbol_id, zeitrahmen):
    """Laedt einen Zeitrahmen eines Symbols und schreibt die fertige Datei."""
    periode_name, suffix, minuten, laenge = ZEITRAHMEN[zeitrahmen]
    periode = ProtoOATrendbarPeriod.Value(periode_name)
    bis = datetime.now(timezone.utc)
    abschnitte = abschnitte_bilden(STARTPUNKT[zeitrahmen], bis, laenge)

    geladen = uebersprungen = 0
    alle_zeilen = []
    for von, abschnitt_bis in abschnitte:
        pfad = teil_pfad(symbol, zeitrahmen, von)
        # Der letzte Abschnitt waechst noch - der wird nie zwischengespeichert,
        # sonst fehlten beim Wiederaufnehmen die neuesten Kerzen.
        laeuft_noch = abschnitt_bis >= bis
        if pfad.exists() and not laeuft_noch:
            alle_zeilen.extend(teil_lesen(pfad))
            uebersprungen += 1
            continue

        balken = yield abschnitt_laden(
            client, drossel, konto_id, symbol_id, periode, von, abschnitt_bis,
            leise=True, minuten=minuten,
        )
        zeilen = sorted({kerze_umrechnen(b)[0]: kerze_umrechnen(b)
                         for b in balken}.values())
        if not laeuft_noch:
            zeilen_schreiben(pfad, zeilen)
        alle_zeilen.extend(zeilen)
        geladen += 1

    fertig = zeilen_aufbereiten(
        alle_zeilen, STARTPUNKT[zeitrahmen], bis, minuten
    )
    if not fertig:
        print(f"   {symbol} {zeitrahmen}: keine Kerzen erhalten.")
        return

    fertig, ohne_volumen = nullvolumen_trennen(fertig)
    entfernte_schreiben(symbol, suffix, ohne_volumen, GRUND_NULLVOLUMEN)

    ziel = zeilen_schreiben(ZIEL_ORDNER / f"{symbol}_{suffix}.csv", fertig)
    print(f"   {symbol:<8} {zeitrahmen:<3} {len(fertig):>7} Kerzen  "
          f"{fertig[0][0]:%Y-%m-%d} bis {fertig[-1][0]:%Y-%m-%d}  "
          f"(neu {geladen}, uebersprungen {uebersprungen},"
          f" ohne Volumen {len(ohne_volumen)})  -> {ziel.name}")


@defer.inlineCallbacks
def ablauf(client, client_id, client_secret, token, args):
    yield anfrage_senden(client, ProtoOAApplicationAuthReq(
        clientId=client_id, clientSecret=client_secret))
    konten = yield anfrage_senden(
        client, ProtoOAGetAccountListByAccessTokenReq(accessToken=token))
    konto_id = konto_waehlen(list(konten.ctidTraderAccount))
    yield anfrage_senden(client, ProtoOAAccountAuthReq(
        ctidTraderAccountId=konto_id, accessToken=token))

    symbol_antwort = yield anfrage_senden(
        client, ProtoOASymbolsListReq(ctidTraderAccountId=konto_id))
    verfuegbar = list(symbol_antwort.symbol)

    korb = korb_lesen()
    namen = args.symbole or sorted(korb)
    print(f"\n{len(namen)} Symbole, Zeitrahmen {', '.join(args.zeitrahmen)}")
    print("-" * 78)

    symbol_ids = {}
    for name in namen:
        try:
            symbol_id, _ = symbol_zuordnen(verfuegbar, name)
        except Verbindungsfehler as fehler:
            print(f"   {name}: uebersprungen - {str(fehler).splitlines()[0]}")
            continue
        if name in korb and korb[name] != symbol_id:
            print(f"   {name}: korb.json nennt {korb[name]}, der Broker"
                  f" {symbol_id} - es gilt der Broker.")
        symbol_ids[name] = symbol_id

    print("-" * 78)
    drossel = Drosselung()
    for nummer, name in enumerate(sorted(symbol_ids), 1):
        print(f"[{nummer}/{len(symbol_ids)}] {name}")
        for zeitrahmen in args.zeitrahmen:
            yield zeitrahmen_laden(client, drossel, konto_id, name,
                                   symbol_ids[name], zeitrahmen)


def argumente_lesen(argv=None):
    parser = argparse.ArgumentParser(description="Vollhistorie aus cTrader laden")
    parser.add_argument("--symbole", nargs="+", help="statt aller Korb-Symbole")
    parser.add_argument("--zeitrahmen", nargs="+", default=list(STANDARD_ZEITRAHMEN),
                        choices=sorted(ZEITRAHMEN))
    parser.add_argument("--neu", action="store_true",
                        help="Teildateien verwerfen und alles neu laden")
    return parser.parse_args(argv)


def main() -> int:
    args = argumente_lesen()
    if args.neu and TEILE_ORDNER.exists():
        shutil.rmtree(TEILE_ORDNER)
        print(f"Teildateien unter {TEILE_ORDNER} verworfen.")
    return mit_verbindung_ausfuehren(
        partial(ablauf, args=args), abschluss_text="Vollhistorie fertig."
    )


if __name__ == "__main__":
    sys.exit(main())
