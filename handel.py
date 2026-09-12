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

import argparse
import sys
from datetime import datetime, timedelta, timezone
from dataclasses import replace
from decimal import Decimal
from functools import partial

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
from ctrader_open_api.messages.OpenApiMessages_pb2 import ProtoOAExecutionEvent
from ctrader_open_api.messages.OpenApiModelMessages_pb2 import (
    ProtoOAExecutionType,
    ProtoOAOrderType,
    ProtoOATradeSide,
    ProtoOATrendbarPeriod,
)
from ctrader_open_api import Protobuf
from google.protobuf.json_format import MessageToDict
from twisted.internet import defer, reactor

from lade_ctrader import kerze_umrechnen, millisekunden, symbol_zuordnen
from ausfuehrung import (
    AUSFUEHRUNG_TIMEOUT,
    Ausfuehrungsbefund,
    Ausfuehrungsmeldung,
    LAGE_OHNE_ANTWORT,
    auftragskennung_bauen,
    bestand_befund,
    meldung_einordnen,
    nach_zeitablauf_entscheiden,
    preisabweichung,
    protokoll_eintrag,
    protokoll_schreiben,
)
from risiko import (
    Bestand,
    Handelsfehler,
    KURS_RUECKBLICK,
    Kapitalstand,
    Kursstand,
    LABEL_PRAEFIX,
    MODUS_SENDEN,
    MODUS_TROCKENLAUF,
    NOT_AUS_DATEI,
    Ordervorschlag,
    RISIKO_PROZENT,
    SIMULATIONSKAPITAL,
    STANDARD_GELD_STELLEN,
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


class Nachrichtenzaehler:
    """Zaehlt Nachrichten an EINER Stelle der Empfaengerkette.

    Zwei Zaehler an verschiedenen Stellen machen sichtbar, ob die Wache die
    Kette wirklich weiterreicht: Verschluckte sie Nachrichten, stiege nur
    der aeussere Zaehler.
    """

    def __init__(self, weiter=None):
        self.anzahl = 0
        self._weiter = weiter

    def __call__(self, client, nachricht) -> None:
        self.anzahl += 1
        if self._weiter is not None:
            self._weiter(client, nachricht)


def generalprobe_einhaengen(client, dauer: int = 3600):
    """Haengt die Wache im Trockenlauf von Anfang an ein - ohne Order.

    Alle Antworten des normalen Ablaufs laufen durch denselben
    Nachrichtenempfaenger. Kommt der Trockenlauf mit eingehaengter Wache
    genauso durch wie ohne, ist die Verkettung gegen den echten Server
    bewiesen - ohne dass eine einzige Order entsteht.
    """
    innen = Nachrichtenzaehler(empfaenger_holen(client))
    client.setMessageReceivedCallback(innen)
    wache = Ausfuehrungswache(client, "generalprobe-ohne-order", timeout=dauer)
    return wache, innen


def generalprobe_auswerten(wache, innen) -> bool:
    """Beide Zaehler muessen gleich sein."""
    print(f"   Wache gesehen:            {wache.gesehen}")
    print(f"   Urspruenglicher Empfaenger: {innen.anzahl}")
    if wache.gesehen == 0:
        print("   ERGEBNIS: Die Wache hat keine einzige Nachricht gesehen -"
              " die Probe sagt nichts aus.")
        return False
    if wache.gesehen != innen.anzahl:
        print(f"   ERGEBNIS: FEHLER - {wache.gesehen - innen.anzahl}"
              " Nachrichten kamen nicht beim urspruenglichen Empfaenger an."
              " Die Verkettung ist kaputt.")
        return False
    print("   ERGEBNIS: Beide Zahlen gleich - die Verkettung haelt gegen den"
          " echten Server.")
    return True


@defer.inlineCallbacks
def versand_durchfuehren(client, konto_id: int, vorschlag: Ordervorschlag,
                         darf_senden: bool, sperrgrund, sende_hinweis: str):
    """Sendet, wenn alle Schalter passen - sonst wird nur protokolliert."""
    if not vorschlag.entscheid.angenommen:
        print("   Kein Versand: die Groessenrechnung hat abgelehnt.")
        return None
    if sperrgrund:
        print(f"   Kein Versand: {sperrgrund}")
        return None
    if not darf_senden:
        print(f"   Kein Versand: {sende_hinweis}")
        return None

    print()
    print("   " + "=" * 60)
    print("   ES WIRD JETZT EINE ECHTE ORDER GESENDET.")
    print("   " + "=" * 60)
    befund, verlauf = yield order_senden(client, konto_id, vorschlag)
    if befund.erfolgreich:
        yield gegenpruefung(client, konto_id, vorschlag, verlauf)
    return befund


@defer.inlineCallbacks
def ablauf(client, client_id, client_secret, token, args=None):
    probe = None
    if MODUS != MODUS_SENDEN:
        # Generalprobe: Die Wache horcht ab der ersten Nachricht mit. Es wird
        # keine Order gesendet - geprueft wird allein die Verkettung.
        probe = generalprobe_einhaengen(client)
        print("Generalprobe: Ausfuehrungswache eingehaengt (keine Order).")

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
    # Das Label ist zugleich die eindeutige Auftragskennung - siehe
    # auftragskennung_bauen(). Positionen tragen nur das Label, deshalb muss
    # die Kennung dort stehen.
    vorschlag = replace(vorschlag, label=auftragskennung_bauen(grenzen.name))

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
    einzelschuss = bool(args and args.eine_order)
    if darf and not einzelschuss:
        print("   Hinweis: Alle Schalter stehen auf Senden, aber --eine-order"
              " fehlt. Der erste echte Versand muss ein bewusster"
              " Einzelschuss sein.")
    yield versand_durchfuehren(
        client, konto_id, vorschlag, darf and einzelschuss, sperrgrund,
        sende_hinweis)

    if probe is not None:
        wache, innen = probe
        schritt(7, "Generalprobe: Verkettung des Nachrichtenempfaengers")
        generalprobe_auswerten(wache, innen)
        wache.beenden()


def meldung_aus_ereignis(ereignis) -> Ausfuehrungsmeldung:
    """Uebersetzt ein ProtoOAExecutionEvent in unseren einfachen Datensatz.

    Hier und nur hier wird Protobuf angefasst; die Auswertung selbst liegt
    netzwerkfrei in risiko.py.
    """
    order = ereignis.order
    daten = order.tradeData
    preis = (Decimal(str(order.executionPrice))
             if order.HasField("executionPrice") else None)
    return Ausfuehrungsmeldung(
        typ=ProtoOAExecutionType.Name(ereignis.executionType),
        kennung=order.clientOrderId or "",
        label=daten.label or "",
        fehlercode=ereignis.errorCode or "",
        volumen_angefordert=daten.volume,
        volumen_ausgefuehrt=order.executedVolume,
        ausfuehrungspreis=preis,
        positions_id=order.positionId,
    )


# Name des privaten Attributs, unter dem der Client seinen
# Nachrichtenempfaenger fuehrt. Siehe ctrader_open_api/client.py:
# setMessageReceivedCallback speichert dorthin.
EMPFAENGER_ATTRIBUT = "_messageReceivedCallback"


def empfaenger_holen(client):
    """Liefert den aktuellen Nachrichtenempfaenger des Clients.

    Bricht ab, wenn es ihn nicht gibt. Frueher stand hier ein
    getattr(..., None): Waere das Attribut umbenannt worden, haette sich die
    Wache lautlos NICHT eingehaengt - der Token-Waechter aus verbindung.py
    haette nicht mehr mitgehoert, und eine Order waere ohne Bestaetigung
    abgesetzt worden. Ein stilles None ist hier der teuerste Fehler.

    Fuer das Fehlen gibt es ZWEI Ursachen, und die Meldung nennt beide:
    entweder hat die Bibliothek das Attribut umbenannt, oder die Wache wurde
    zu frueh eingehaengt. Der echte Client legt das Attribut naemlich erst
    im ersten setMessageReceivedCallback-Aufruf an - vorher gibt es es gar
    nicht. Ohne den zweiten Hinweis sucht man in der Bibliothek, obwohl der
    Fehler im eigenen Ablauf liegt.
    """
    if not hasattr(client, EMPFAENGER_ATTRIBUT):
        raise Handelsfehler(
            f"Nachrichtenempfaenger des Clients nicht gefunden"
            f" (Attribut '{EMPFAENGER_ATTRIBUT}'). Zwei moegliche Ursachen:"
            "\n  1. Die Bibliothek ctrader-open-api hat das Attribut"
            " umbenannt - Fassung in requirements.txt gegen die installierte"
            " pruefen."
            "\n  2. Die Ausfuehrungswache wurde eingehaengt, BEVOR ein"
            " Empfaenger gesetzt war. Der Client legt das Attribut erst im"
            " ersten setMessageReceivedCallback-Aufruf an - pruefe die"
            " Reihenfolge in mit_verbindung_ausfuehren (verbindung.py)."
            "\nDie Wache kann sich nicht einhaengen, es wird nichts gesendet."
        )
    return getattr(client, EMPFAENGER_ATTRIBUT)


class Ausfuehrungswache:
    """Wartet auf die endgueltige Ausfuehrungsmeldung einer Order.

    Ausbleibender Fehler ist KEINE Bestaetigung: Laeuft die Zeit ab, ohne
    dass eine endgueltige Meldung kam, endet das Warten mit
    LAGE_OHNE_ANTWORT - und der Aufrufer sieht nach, statt zu wiederholen.
    """

    def __init__(self, client, kennung: str, uhr=reactor,
                 timeout: int = AUSFUEHRUNG_TIMEOUT):
        self._client = client
        self._kennung = kennung
        self._uhr = uhr
        self._fertig = defer.Deferred()
        self._verlauf = []
        # Zaehlt JEDE Nachricht, die die Wache sieht - nicht nur
        # Ausfuehrungsereignisse. Grundlage der Generalprobe.
        self.gesehen = 0
        # Vorherigen Empfaenger nicht verdraengen - verbindung.py horcht dort
        # auf zurueckgezogene Token.
        self._vorher = empfaenger_holen(client)
        client.setMessageReceivedCallback(self._empfangen)
        self._wecker = uhr.callLater(timeout, self._zeit_abgelaufen)

    @property
    def verlauf(self) -> tuple:
        return tuple(self._verlauf)

    def warten(self):
        return self._fertig

    def _empfangen(self, client, nachricht) -> None:
        self.gesehen += 1
        if self._vorher is not None:
            self._vorher(client, nachricht)
        if nachricht.payloadType != ProtoOAExecutionEvent().payloadType:
            return
        ereignis = Protobuf.extract(nachricht)
        meldung = meldung_aus_ereignis(ereignis)
        befund = meldung_einordnen(meldung, self._kennung)
        self._verlauf.append((meldung, befund))
        protokoll_schreiben(protokoll_eintrag(
            "ausfuehrung", {"meldung": MessageToDict(ereignis),
                            "befund": befund.text, "lage": befund.lage}))
        print(f"   [{befund.lage}] {befund.text}")
        if befund.endgueltig:
            self._abschliessen(befund)

    def beenden(self) -> None:
        """Haengt die Wache aus, ohne ein Ergebnis zu erzwingen.

        Fuer die Generalprobe: Dort horcht die Wache nur mit und soll am
        Ende sauber verschwinden, statt einen Zeitablauf zu melden.
        """
        if self._wecker.active():
            self._wecker.cancel()
        self._client.setMessageReceivedCallback(self._vorher or (lambda *_: None))

    def _zeit_abgelaufen(self) -> None:
        self._abschliessen(Ausfuehrungsbefund(
            LAGE_OHNE_ANTWORT, True, False,
            f"Innerhalb von {AUSFUEHRUNG_TIMEOUT} Sekunden kam keine"
            " endgueltige Meldung."))

    def _abschliessen(self, befund: Ausfuehrungsbefund) -> None:
        if self._fertig.called:
            return
        if self._wecker.active():
            self._wecker.cancel()
        self._client.setMessageReceivedCallback(self._vorher or (lambda *_: None))
        self._fertig.callback(befund)


@defer.inlineCallbacks
def order_senden(client, konto_id: int, vorschlag: Ordervorschlag,
                 uhr=reactor):
    """Sendet GENAU EINE Order und wertet die Bestaetigung aus.

    In dieser Funktion gibt es keinen Pfad, der ein zweites Mal sendet. Bei
    Unklarheit wird nachgesehen (ProtoOAReconcileReq), nicht nachgesendet -
    blindes Wiederholen ist der Weg, auf dem aus einer Order zwei
    Positionen werden.
    """
    order = order_bauen(konto_id, vorschlag)
    protokoll_schreiben(protokoll_eintrag("anfrage", MessageToDict(order)))
    print(f"   Sende Order mit Kennung {vorschlag.label} ...")

    wache = Ausfuehrungswache(client, vorschlag.label, uhr)
    # Der einzige Versand. Fehler der Anfrage selbst beenden das Warten.
    client.send(order, responseTimeoutInSeconds=AUSFUEHRUNG_TIMEOUT
                ).addErrback(lambda fehler: None)
    befund = yield wache.warten()

    if befund.lage == LAGE_OHNE_ANTWORT:
        print("   Keine Bestaetigung - Bestandsaufnahme statt Wiederholung.")
        antwort = yield anfrage_senden(
            client, ProtoOAReconcileReq(ctidTraderAccountId=konto_id))
        befund = nach_zeitablauf_entscheiden(
            bestand_befund(bestand_einlesen(antwort), vorschlag.label))
        protokoll_schreiben(protokoll_eintrag(
            "nachschau", {"lage": befund.lage, "text": befund.text}))
        print(f"   [{befund.lage}] {befund.text}")

    return befund, wache.verlauf


@defer.inlineCallbacks
def gegenpruefung(client, konto_id: int, vorschlag: Ordervorschlag,
                  verlauf: tuple):
    """Nach erfolgreicher Ausfuehrung sofort nachsehen.

    Genau eine Position mit dieser Kennung - und der Ausfuehrungspreis
    gegen den erwarteten.
    """
    antwort = yield anfrage_senden(
        client, ProtoOAReconcileReq(ctidTraderAccountId=konto_id))
    befund = bestand_befund(bestand_einlesen(antwort), vorschlag.label)

    if befund.genau_eine:
        print(f"   Gegenpruefung: genau eine Position mit {vorschlag.label}.")
    else:
        print(f"   ACHTUNG Gegenpruefung: {befund.anzahl} Positionen mit"
              f" {vorschlag.label} - erwartet war genau eine.")

    preise = [m.ausfuehrungspreis for m, _ in verlauf if m.ausfuehrungspreis]
    if preise:
        _, _, text = preisabweichung(vorschlag.einstieg, preise[-1])
        print(f"   {text}")
        protokoll_schreiben(protokoll_eintrag(
            "gegenpruefung", {"positionen": befund.anzahl, "preis": text}))
    else:
        protokoll_schreiben(protokoll_eintrag(
            "gegenpruefung", {"positionen": befund.anzahl,
                              "preis": "kein Ausfuehrungspreis gemeldet"}))
    return befund


def argumente_lesen(argv=None):
    parser = argparse.ArgumentParser(
        description="cTrader-Order-Schicht. Sendet ohne --eine-order nichts.")
    parser.add_argument(
        "--eine-order", action="store_true",
        help="genau EINE Order senden und beenden. Wirkt nur zusammen mit"
             " MODUS='senden' und den uebrigen Schaltern.")
    return parser.parse_args(argv)


def main() -> int:
    args = argumente_lesen()
    print(f"Modus: {MODUS} | Echtgeld erlaubt: {ECHTGELD_AUSDRUECKLICH_ERLAUBT}"
          f" | Einzelschuss: {args.eine_order}")
    kappe = ("keine" if SIMULATIONSKAPITAL is None
             else f"{SIMULATIONSKAPITAL} (nur auf Demokonten)")
    print(f"Risiko je Trade: {RISIKO_PROZENT} % | Simulationskappe: {kappe}")
    print("Risikobasis kommt vom Broker (Eigenkapital), nicht aus der"
          " Einstellung.")
    print(f"Not-Aus-Datei: {NOT_AUS_DATEI}"
          f" ({'VORHANDEN' if NOT_AUS_DATEI.exists() else 'nicht vorhanden'})")
    return mit_verbindung_ausfuehren(
        partial(ablauf, args=args), abschluss_text="Fertig.")


if __name__ == "__main__":
    sys.exit(main())
