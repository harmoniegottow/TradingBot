#!/usr/bin/env python3
"""handel.py - Order-Schicht fuer cTrader. ERSTER SCHRITT: nur Trockenlauf.

Dieses Modul sendet NICHTS. Es liest Bestand, Tagesergebnis und Kurse beim
Broker, laesst risiko.py die Groesse rechnen, baut vollstaendige Orders und
schreibt sie als Protokollzeile.

Die Aufteilung: Hier liegen Verbindung, Protobuf und Ausgabe. Die reine
Rechnung - Positionsgroesse, Risikobasis, Sperren, Kursalter, Umrechnung -
liegt in risiko.py und kommt ohne Netzwerk aus.

Aufruf:

    .venv/bin/python handel.py                 # Bestand lesen, Order zeigen

Die Risikobasis ist das Eigenkapital beim Broker. Auf dem Demokonto wird sie
zusaetzlich auf SIMULATIONSKAPITAL gekappt, damit dort Positionen entstehen,
wie es sie spaeter mit kleinem Echtgeldkonto wirklich gaebe.

Das Access-Token wird nie ausgegeben.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from ctrader_open_api.messages.OpenApiMessages_pb2 import (
    ProtoOAAccountAuthReq,
    ProtoOAApplicationAuthReq,
    ProtoOAAssetListReq,
    ProtoOADealListReq,
    ProtoOAGetAccountListByAccessTokenReq,
    ProtoOAGetPositionUnrealizedPnLReq,
    ProtoOAGetTrendbarsReq,
    ProtoOANewOrderReq,
    ProtoOAReconcileReq,
    ProtoOASymbolByIdReq,
    ProtoOASymbolsListReq,
    ProtoOATraderReq,
)
from ctrader_open_api.messages.OpenApiModelMessages_pb2 import (
    ProtoOAOrderType,
    ProtoOATradeSide,
    ProtoOATrendbarPeriod,
)
from twisted.internet import defer

from lade_ctrader import kerze_umrechnen, millisekunden, symbol_zuordnen
from risiko import (
    KURS_RUECKBLICK,
    LABEL_PRAEFIX,
    MODUS_SENDEN,
    MODUS_TROCKENLAUF,
    NOT_AUS_DATEI,
    RISIKO_PROZENT,
    SIMULATIONSKAPITAL,
    STANDARD_GELD_STELLEN,
    Bestand,
    Handelsfehler,
    Kapitalstand,
    Kursstand,
    Ordervorschlag,
    Symbolgrenzen,
    Tagesergebnis,
    Umrechnung,
    _geld,
    eigenkapital_bestimmen,
    groessen_vergleich,
    konversionssymbol_finden,
    kursalter_pruefen,
    protokollzeile,
    realisiertes_ergebnis,
    risikobasis_bestimmen,
    sperren_pruefen,
    tagesbeginn_utc,
    umrechnungsfaktor,
    unrealisiertes_ergebnis,
    vergleich_text,
    vorschlag_bauen,
)
from verbindung import anfrage_senden, konto_waehlen, mit_verbindung_ausfuehren, schritt

MODUS = MODUS_TROCKENLAUF


ECHTGELD_AUSDRUECKLICH_ERLAUBT = False


MAX_DEALS = 1000


def bestand_einlesen(antwort) -> Bestand:
    """ProtoOAReconcileRes auswerten - was ist schon offen?"""
    return Bestand(positionen=tuple(antwort.position),
                   orders=tuple(antwort.order))


def senden_erlaubt(modus: str, konto_ist_live: bool,
                   echtgeld_erlaubt: bool) -> tuple[bool, str]:
    """Darf ueberhaupt gesendet werden? Drei Schalter, alle muessen passen."""
    if modus != MODUS_SENDEN:
        return False, (f"Modus ist '{modus}' - es wird nichts gesendet."
                       f" Senden verlangt MODUS = '{MODUS_SENDEN}'.")
    if konto_ist_live and not echtgeld_erlaubt:
        return False, ("Livekonto erkannt (isLive=true), aber"
                       " ECHTGELD_AUSDRUECKLICH_ERLAUBT steht auf False."
                       " Der Modus allein genuegt auf einem Livekonto nicht.")
    if konto_ist_live:
        return True, ("ACHTUNG: Livekonto, und Echtgeld ist ausdruecklich"
                      " erlaubt. Es wird mit echtem Geld gehandelt.")
    return True, "Demokonto und Modus 'senden' - Senden waere erlaubt."


def order_bauen(konto_id: int, vorschlag: Ordervorschlag) -> ProtoOANewOrderReq:
    """Baut die fertige Order. Sie wird hier NICHT gesendet.

    Am Protobuf-Rand werden Preise zu double - das verlangt das Format.
    Gerechnet wurde bis hierher ausschliesslich mit Decimal.
    """
    return ProtoOANewOrderReq(
        ctidTraderAccountId=konto_id,
        symbolId=vorschlag.symbol_id,
        orderType=ProtoOAOrderType.Value("MARKET"),
        tradeSide=ProtoOATradeSide.Value(vorschlag.seite),
        volume=vorschlag.volumen,
        stopLoss=float(vorschlag.stop),
        takeProfit=float(vorschlag.ziel),
        label=vorschlag.label,
        comment=vorschlag.begruendung[:100],
    )


@defer.inlineCallbacks
def letzter_kurs(client, konto_id: int, symbol_id: int, symbol_name: str,
                 modus: str = MODUS_TROCKENLAUF, jetzt: datetime = None
                 ) -> Kursstand:
    """Letzter abgeschlossener Minutenschluss, mit seinem Alter.

    Bewusst die letzte FERTIGE Kerze und kein laufender Tick: Sie ist
    nachpruefbar und aendert sich nicht zwischen zwei Aufrufen.

    Der Rueckblick haengt am Modus. Am Wochenende steht der Markt zwei Tage
    still - im Trockenlauf wird deshalb bis zu vier Tage zurueckgeschaut und
    das Alter ausgewiesen, statt mit leeren Haenden dazustehen.
    """
    jetzt = jetzt or datetime.now(timezone.utc)
    rueckblick = KURS_RUECKBLICK.get(modus, KURS_RUECKBLICK[MODUS_TROCKENLAUF])
    antwort = yield anfrage_senden(client, ProtoOAGetTrendbarsReq(
        ctidTraderAccountId=konto_id, symbolId=symbol_id,
        period=ProtoOATrendbarPeriod.Value("M1"),
        fromTimestamp=millisekunden(jetzt - rueckblick),
        toTimestamp=millisekunden(jetzt),
    ))
    balken = list(antwort.trendbar)
    if not balken:
        raise Handelsfehler(
            f"Kein Kurs fuer {symbol_name} (symbolId {symbol_id}) in den"
            f" letzten {rueckblick.days} Tagen"
            f" {int(rueckblick.seconds // 3600)} Stunden erhalten."
            " Symbol beim Broker nicht handelbar oder Markt lange geschlossen."
        )
    neueste = max(balken, key=lambda b: b.utcTimestampInMinutes)
    zeile = kerze_umrechnen(neueste)
    # Der Zeitstempel markiert den BEGINN der Kerze; ihr Schluss liegt eine
    # Minute spaeter. Das Alter wird ab dem Schluss gerechnet.
    schluss_zeit = zeile[0] + timedelta(minutes=1)
    return Kursstand(symbol_name, zeile[4], schluss_zeit,
                     max(jetzt - schluss_zeit, timedelta(0)))


@defer.inlineCallbacks
def umrechnung_beschaffen(client, konto_id: int, symbole, konto_asset_id: int,
                          notierung_id: int, namen: dict,
                          modus: str = MODUS_TROCKENLAUF) -> Umrechnung:
    """Faktor von der Notierungswaehrung in die Kontowaehrung.

    Bricht ab, wenn kein Kurs zu beschaffen ist. Mit Faktor eins
    weiterzurechnen waere der teurere Fehler: Die Position waere dann um den
    Wechselkurs zu gross, und zwar stillschweigend.
    """
    konto_name = namen.get(konto_asset_id, str(konto_asset_id))
    notierung_name = namen.get(notierung_id, str(notierung_id))
    if notierung_id == konto_asset_id:
        return Umrechnung(Decimal(1),
                          f"Notierung und Konto beide in {konto_name}"
                          " - Faktor eins.")

    treffer = konversionssymbol_finden(symbole, notierung_id, konto_asset_id)
    if treffer is None:
        raise Handelsfehler(
            f"Kein Symbol verbindet {notierung_name} mit {konto_name}."
            " Ohne Kurs wird nicht gerechnet - der Trade faellt aus."
        )
    symbol_id, invertieren = treffer
    name = next((s.symbolName for s in symbole if s.symbolId == symbol_id),
                str(symbol_id))
    kurs = yield letzter_kurs(client, konto_id, symbol_id, name, modus)

    zu_alt = kursalter_pruefen(kurs, modus)
    if zu_alt:
        raise Handelsfehler(zu_alt)

    faktor = umrechnungsfaktor(kurs.wert, invertieren)
    richtung = "Kehrwert" if invertieren else "direkt"
    return Umrechnung(
        faktor,
        f"{kurs}\n   {notierung_name} nach {konto_name} ueber {name}"
        f" ({richtung}), Faktor {faktor:.6f}",
    )


@defer.inlineCallbacks
def tagesergebnis_holen(client, konto_id: int, jetzt: datetime = None
                        ) -> Tagesergebnis:
    """Ergebnis seit 00:00 UTC: geschlossene Trades plus offene Positionen."""
    jetzt = jetzt or datetime.now(timezone.utc)
    beginn = tagesbeginn_utc(jetzt)

    deals = yield anfrage_senden(client, ProtoOADealListReq(
        ctidTraderAccountId=konto_id,
        fromTimestamp=millisekunden(beginn),
        toTimestamp=millisekunden(jetzt),
        maxRows=MAX_DEALS,
    ))
    realisiert, anzahl_deals = realisiertes_ergebnis(list(deals.deal))
    if deals.hasMore:
        print(f"   WARNUNG: Mehr als {MAX_DEALS} Deals heute - das"
              " realisierte Ergebnis ist unvollstaendig.")

    offen = yield anfrage_senden(client, ProtoOAGetPositionUnrealizedPnLReq(
        ctidTraderAccountId=konto_id))
    unrealisiert, anzahl_offen = unrealisiertes_ergebnis(offen)

    return Tagesergebnis(realisiert, unrealisiert, anzahl_deals, anzahl_offen)


@defer.inlineCallbacks
def ablauf(client, client_id, client_secret, token):
    schritt(1, "Anwendung und Konto anmelden")
    yield anfrage_senden(client, ProtoOAApplicationAuthReq(
        clientId=client_id, clientSecret=client_secret))
    konten = yield anfrage_senden(
        client, ProtoOAGetAccountListByAccessTokenReq(accessToken=token))
    konto_liste = list(konten.ctidTraderAccount)
    konto_id = konto_waehlen(konto_liste)
    ist_live = next(k.isLive for k in konto_liste
                    if k.ctidTraderAccountId == konto_id)
    yield anfrage_senden(client, ProtoOAAccountAuthReq(
        ctidTraderAccountId=konto_id, accessToken=token))

    schritt(2, "Bestandsaufnahme (ProtoOAReconcileReq)")
    antwort = yield anfrage_senden(
        client, ProtoOAReconcileReq(ctidTraderAccountId=konto_id))
    bestand = bestand_einlesen(antwort)
    print(f"   {bestand.anzahl_positionen} offene Positionen,"
          f" {len(bestand.orders)} offene Orders.")
    for position in bestand.positionen:
        daten = position.tradeData
        print(f"      Position {position.positionId}: symbolId"
              f" {daten.symbolId}, Volumen {daten.volume},"
              f" Label '{daten.label or '(ohne)'}'")
    print(f"   Davon mit eigenem Kennzeichen '{LABEL_PRAEFIX}':"
          f" {len(bestand.eigene())}")

    schritt(3, "Tagesergebnis seit 00:00 UTC")
    tagesergebnis = yield tagesergebnis_holen(client, konto_id)
    print(f"   Tagesbeginn: {tagesbeginn_utc():%Y-%m-%d %H:%M} UTC")
    print(f"   {tagesergebnis}")

    schritt(4, "Waehrung und Symbolgrenzen")
    trader = (yield anfrage_senden(
        client, ProtoOATraderReq(ctidTraderAccountId=konto_id))).trader
    anlagen = list((yield anfrage_senden(
        client, ProtoOAAssetListReq(ctidTraderAccountId=konto_id))).asset)
    namen = {a.assetId: (a.name or a.displayName) for a in anlagen}
    print(f"   Kontowaehrung: {namen.get(trader.depositAssetId)}")

    symbole = list((yield anfrage_senden(
        client, ProtoOASymbolsListReq(ctidTraderAccountId=konto_id))).symbol)
    symbol_id, broker_name = symbol_zuordnen(symbole, "XAUUSD")
    leicht = next(s for s in symbole if s.symbolId == symbol_id)
    print(f"   {broker_name} notiert in"
          f" {namen.get(leicht.quoteAssetId)}")

    umrechnung = yield umrechnung_beschaffen(
        client, konto_id, symbole, trader.depositAssetId,
        leicht.quoteAssetId, namen, MODUS)
    print(f"   {umrechnung.beschreibung}")

    detail = yield anfrage_senden(client, ProtoOASymbolByIdReq(
        ctidTraderAccountId=konto_id, symbolId=[symbol_id]))
    grenzen = Symbolgrenzen.aus_protobuf(detail.symbol[0], broker_name)
    print(f"   {grenzen.name}: min {grenzen.min_volumen}, max"
          f" {grenzen.max_volumen}, Schritt {grenzen.schritt_volumen},"
          f" lotSize {grenzen.lot_groesse}")

    schritt(5, "Risikobasis und Groesse")
    # Beispielwerte - die echten kommen spaeter aus der Strategie.
    einstieg, stop, ziel = (Decimal("4000.00"), Decimal("3960.00"),
                            Decimal("4080.00"))
    konto_waehrung = namen.get(trader.depositAssetId, "?")
    notierung = namen.get(leicht.quoteAssetId, "?")

    # Die Risikobasis kommt vom Broker: Kontostand plus unrealisiertes
    # Ergebnis der offenen Positionen - dieselbe Quelle wie fuer die
    # Tagesverlustgrenze. Auf dem Demokonto wird sie zusaetzlich gekappt.
    # Nicht durch eine feste Zahl ersetzen: Faellt das Konto, muessen die
    # Positionen mitschrumpfen.
    eigenkapital = eigenkapital_bestimmen(_geld(trader.balance, trader),
                                          tagesergebnis.unrealisiert)
    basis = risikobasis_bestimmen(eigenkapital, ist_live, konto_waehrung)
    print(basis.zeilen())
    print()

    # MASSGEBLICH ist die Risikobasis. Das volle Eigenkapital steht nur
    # daneben, damit der Unterschied sichtbar bleibt. Nicht umdrehen.
    staende = (
        Kapitalstand("Risikobasis", basis.risikobasis, konto_waehrung, True),
        Kapitalstand("Eigenkapital", basis.eigenkapital, konto_waehrung, False),
    )
    vergleich = groessen_vergleich(grenzen, abs(einstieg - stop),
                                   umrechnung.faktor, staende)
    print()
    print(vergleich_text(grenzen, "BUY", abs(einstieg - stop), notierung,
                         vergleich))

    schritt(6, "Order vorbereiten und protokollieren (nichts wird gesendet)")
    vorschlag = vorschlag_bauen(
        grenzen, "BUY", einstieg, stop, ziel,
        "Beispiel-Anlass (Trockenlauf, keine Strategie angeschlossen)",
        umrechnung=umrechnung.faktor, kapital=basis.risikobasis)

    darf, sende_hinweis = senden_erlaubt(
        MODUS, ist_live, ECHTGELD_AUSDRUECKLICH_ERLAUBT)
    # Der Ablehnungsgrund der Groessenrechnung wird NICHT zum Sperrgrund
    # gemacht - er steht bereits in der Volumenzeile des Protokolls.
    sperrgrund = sperren_pruefen(bestand, tagesergebnis, basis.risikobasis)

    print()
    print(protokollzeile(vorschlag, sperrgrund, sende_hinweis, grenzen,
                         konto_waehrung))
    print()
    if vorschlag.entscheid.angenommen:
        order = order_bauen(konto_id, vorschlag)
        print(f"   Fertige ProtoOANewOrderReq (NICHT gesendet):"
              f" {len(order.SerializeToString())} Bytes")
    if darf and sperrgrund is None and vorschlag.entscheid.angenommen:
        print("   Hinweis: Alle Schalter stuenden auf Senden - diese Fassung"
              " sendet trotzdem nichts.")


def main() -> int:
    print(f"Modus: {MODUS} | Echtgeld erlaubt: {ECHTGELD_AUSDRUECKLICH_ERLAUBT}")
    kappe = ("keine" if SIMULATIONSKAPITAL is None
             else f"{SIMULATIONSKAPITAL} (nur auf Demokonten)")
    print(f"Risiko je Trade: {RISIKO_PROZENT} % | Simulationskappe: {kappe}")
    print("Risikobasis kommt vom Broker (Eigenkapital), nicht aus der"
          " Einstellung.")
    print(f"Not-Aus-Datei: {NOT_AUS_DATEI}"
          f" ({'VORHANDEN' if NOT_AUS_DATEI.exists() else 'nicht vorhanden'})")
    return mit_verbindung_ausfuehren(ablauf, abschluss_text="Trockenlauf fertig.")


if __name__ == "__main__":
    sys.exit(main())