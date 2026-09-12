#!/usr/bin/env python3
"""verbindung.py - Erster Verbindungstest zur cTrader Open API.

Meldet die Anwendung an, sucht das Demokonto zum gespeicherten Access-Token,
meldet das Konto an und zeigt Kontostand, Waehrung und Hebel. HANDELT NICHT
und aendert nichts.

Aufruf:

    .venv/bin/python verbindung.py

Voraussetzung: CTRADER_CLIENT_ID, CTRADER_CLIENT_SECRET und
CTRADER_ACCESS_TOKEN stehen in der .env. Fehlt oder faellt das Token aus,
hilft:

    .venv/bin/python auth/oauth_token.py --refresh

Das Access-Token wird nie ausgegeben - auch nicht gekuerzt.
"""
from __future__ import annotations

import sys
from decimal import Decimal

from ctrader_open_api import Client, EndPoints, Protobuf, TcpProtocol
from ctrader_open_api.messages.OpenApiMessages_pb2 import (
    ProtoOAAccountAuthReq,
    ProtoOAAccountsTokenInvalidatedEvent,
    ProtoOAApplicationAuthReq,
    ProtoOAAssetListReq,
    ProtoOAErrorRes,
    ProtoOAGetAccountListByAccessTokenReq,
    ProtoOATraderReq,
)
from twisted.internet import defer, reactor

from auth.oauth_token import OAuthFehler, env_werte_laden, pflichtfeld
# betrag_umrechnen liegt in risiko.py, damit dieses reine Rechenstueck ohne
# Netzwerkmodul auskommt. Hier weiterhin verfuegbar, damit bestehende
# Importe aus verbindung nicht brechen.
from risiko import betrag_umrechnen  # noqa: F401

HOST = EndPoints.PROTOBUF_DEMO_HOST
PORT = EndPoints.PROTOBUF_PORT
ERWARTETES_KONTO = 4266384
ANTWORT_TIMEOUT = 15
VERBINDUNGS_TIMEOUT = 20
# Geldbetraege kommen als Ganzzahl; moneyDigits sagt, wie viele Nachkomma-
# stellen darin stecken. Fehlt das Feld, sind es Hundertstel.
STANDARD_GELD_STELLEN = 2
HEBEL_TEILER = 100
# Fehlercodes, die auf ein abgelaufenes oder zurueckgezogenes Token deuten.
TOKEN_FEHLERCODES = frozenset({"OA_AUTH_TOKEN_EXPIRED", "CH_ACCESS_TOKEN_INVALID"})
LIVE_SPERRE_TEXT = (
    "Abbruch: Konto {kennung} ist ein LIVE-Konto (isLive=true).\n"
    "Ein Live-Konto wird niemals automatisch ausgewaehlt. Nur ein"
    " ausdruecklich per\nKonto-ID angefordertes Konto darf live sein.\n"
    f"Erwartet war das Demokonto {ERWARTETES_KONTO}, das in der Kontoliste"
    " nicht vorkommt.\nIst dieses Live-Konto wirklich gemeint, muss"
    " ERWARTETES_KONTO in verbindung.py\nausdruecklich darauf gesetzt werden."
)
REFRESH_HINWEIS = (
    "Das Access-Token ist abgelaufen oder ungueltig. Neues Token holen mit:\n"
    "    .venv/bin/python auth/oauth_token.py --refresh"
)


class Verbindungsfehler(Exception):
    """Fachlicher Fehler im Ablauf - wird verstaendlich gemeldet.

    `code` traegt den Fehlercode von cTrader, falls die Ausnahme aus einer
    ProtoOAErrorRes stammt. Aufrufer koennen damit gezielt reagieren, ohne
    im Meldungstext suchen zu muessen.
    """

    def __init__(self, text: str, code: str | None = None):
        super().__init__(text)
        self.code = code


def schritt(nummer: int, text: str) -> None:
    print(f"\nSchritt {nummer} - {text}")
    print("-" * 70)


def fehler_aus_antwort(antwort: ProtoOAErrorRes) -> Verbindungsfehler:
    code = antwort.errorCode or "unbekannt"
    if code in TOKEN_FEHLERCODES:
        return Verbindungsfehler(f"{code}: {REFRESH_HINWEIS}", code=code)
    beschreibung = antwort.description or "keine weitere Beschreibung"
    return Verbindungsfehler(
        f"cTrader meldet einen Fehler: {code} - {beschreibung}", code=code
    )


def antwort_pruefen(nachricht):
    """Packt die Antwort aus und macht eine Fehlerantwort zur Ausnahme."""
    antwort = Protobuf.extract(nachricht)
    if isinstance(antwort, ProtoOAErrorRes):
        raise fehler_aus_antwort(antwort)
    return antwort


def anfrage_senden(client: Client, anfrage):
    deferred = client.send(anfrage, responseTimeoutInSeconds=ANTWORT_TIMEOUT)
    deferred.addCallback(antwort_pruefen)
    return deferred


def _treffer_suchen(konten):
    """Sucht das vorgegebene Konto - ueber ctidTraderAccountId ODER traderLogin.

    Beide Nummern kommen im Alltag vor: cTrader zeigt den traderLogin, die API
    verlangt die ctidTraderAccountId. Die Vorgabe darf daher beides sein.
    """
    for konto in konten:
        if ERWARTETES_KONTO in (konto.ctidTraderAccountId, konto.traderLogin):
            return konto
    return None


def konto_waehlen(konten) -> int:
    """Sucht das erwartete Demokonto in der Kontoliste."""
    if not konten:
        raise Verbindungsfehler(
            "Die Kontoliste ist leer. Das Token ist gueltig, aber es haengt kein\n"
            "Handelskonto daran. Das Demokonto ist dann noch nicht mit der cTID\n"
            "verknuepft - ein bekannter Stolperstein, kein Programmfehler.\n"
            "Abhilfe: im cTrader-Web unter der cTID das Demokonto hinzufuegen\n"
            "(Konto verknuepfen), danach dieses Skript erneut ausfuehren."
        )

    for konto in konten:
        print(
            f"   Konto {konto.ctidTraderAccountId}"
            f" | {'Live' if konto.isLive else 'Demo'}"
            f" | Login {konto.traderLogin}"
        )
    # Die Kontoliste kennt die Waehrung nicht - die steht erst in Schritt 4.
    print("   (Die Kontowaehrung liefert erst ProtoOATraderReq in Schritt 4.)")

    treffer = _treffer_suchen(konten)
    if treffer is not None:
        ueber = ("ctidTraderAccountId"
                 if treffer.ctidTraderAccountId == ERWARTETES_KONTO
                 else "traderLogin")
        print(f"\n   Treffer auf {ERWARTETES_KONTO} ueber {ueber}:"
              f" ctidTraderAccountId {treffer.ctidTraderAccountId},"
              f" traderLogin {treffer.traderLogin}.")
        # Ausdruecklich per Vorgabe angefordert - hier waere auch live
        # zulaessig, es muss dann aber unuebersehbar dastehen.
        if treffer.isLive:
            print("   ACHTUNG: Dieses Konto ist ein LIVE-Konto (isLive=true),"
                  " kein Demokonto.")
        else:
            print("   isLive=false - bestaetigt als Demokonto.")
        return treffer.ctidTraderAccountId

    if len(konten) == 1:
        einziges = konten[0]
        if einziges.isLive:
            raise Verbindungsfehler(
                LIVE_SPERRE_TEXT.format(kennung=einziges.ctidTraderAccountId)
            )
        # Notbehelf, kein normaler Weg: die Vorgabe passt auf nichts.
        print(f"\n   WARNUNG: Kein Konto passt auf {ERWARTETES_KONTO} - weder"
              " als ctidTraderAccountId noch als traderLogin."
              "\n   Ersatzweise wird das einzige vorhandene Konto benutzt:"
              f" ctidTraderAccountId {einziges.ctidTraderAccountId},"
              f" traderLogin {einziges.traderLogin}, isLive=false."
              "\n   Das ist ein Notbehelf. Bitte ERWARTETES_KONTO in"
              " verbindung.py richtigstellen.")
        return einziges.ctidTraderAccountId

    raise Verbindungsfehler(
        f"Kein Konto passt auf {ERWARTETES_KONTO} - weder als"
        " ctidTraderAccountId noch als traderLogin. Gefunden"
        " (ctidTraderAccountId/traderLogin): "
        + ", ".join(f"{k.ctidTraderAccountId}/{k.traderLogin}" for k in konten)
        + ". Bitte ERWARTETES_KONTO in diesem Skript anpassen."
    )


def geld_stellen(trader) -> int:
    if trader.HasField("moneyDigits"):
        return trader.moneyDigits
    return STANDARD_GELD_STELLEN


def waehrung_suchen(assets, deposit_asset_id: int) -> str:
    for asset in assets:
        if asset.assetId == deposit_asset_id:
            return asset.name or asset.displayName
    return f"Asset-Kennung {deposit_asset_id}"


def kontostand_ausgeben(trader, assets) -> None:
    stellen = geld_stellen(trader)
    kontostand = betrag_umrechnen(trader.balance, stellen)
    waehrung = waehrung_suchen(assets, trader.depositAssetId)

    print(f"   Konto:      {trader.ctidTraderAccountId} (Login {trader.traderLogin})")
    print(f"   Kontostand: {kontostand:.{stellen}f} {waehrung}")
    print(f"   Waehrung:   {waehrung}")
    if trader.HasField("leverageInCents"):
        print(f"   Hebel:      1:{trader.leverageInCents // HEBEL_TEILER}")
    else:
        print("   Hebel:      nicht angegeben")
    if trader.brokerName:
        print(f"   Broker:     {trader.brokerName}")


@defer.inlineCallbacks
def ablauf_ausfuehren(client: Client, client_id: str, client_secret: str, token: str):
    schritt(1, "Anwendung anmelden (ProtoOAApplicationAuthReq)")
    yield anfrage_senden(
        client, ProtoOAApplicationAuthReq(clientId=client_id, clientSecret=client_secret)
    )
    print("   Anwendung angemeldet.")

    schritt(2, "Konten zum Access-Token abfragen")
    konten_antwort = yield anfrage_senden(
        client, ProtoOAGetAccountListByAccessTokenReq(accessToken=token)
    )
    konto_id = konto_waehlen(list(konten_antwort.ctidTraderAccount))

    schritt(3, f"Konto {konto_id} anmelden (ProtoOAAccountAuthReq)")
    yield anfrage_senden(
        client, ProtoOAAccountAuthReq(ctidTraderAccountId=konto_id, accessToken=token)
    )
    print("   Konto angemeldet.")

    schritt(4, "Kontostand abfragen (ProtoOATraderReq)")
    trader_antwort = yield anfrage_senden(
        client, ProtoOATraderReq(ctidTraderAccountId=konto_id)
    )
    # Die Waehrung steckt als Asset-Kennung im Trader - erst die Asset-Liste
    # macht daraus einen lesbaren Namen wie "EUR".
    asset_antwort = yield anfrage_senden(
        client, ProtoOAAssetListReq(ctidTraderAccountId=konto_id)
    )
    kontostand_ausgeben(trader_antwort.trader, list(asset_antwort.asset))


def mit_verbindung_ausfuehren(ablauf, abschluss_text: str = "Fertig.") -> int:
    """Baut die Verbindung auf, fuehrt `ablauf` aus und liefert den Exit-Code.

    `ablauf` wird als ablauf(client, client_id, client_secret, token) gerufen
    und muss ein Deferred liefern. Verbindungsaufbau, Zeitueberschreitung,
    Fehlerausgabe und das saubere Anhalten des Reactors passieren hier - so
    steht diese Mechanik nur an einer Stelle.
    """
    try:
        werte = env_werte_laden()
        client_id = pflichtfeld(werte, "CTRADER_CLIENT_ID")
        client_secret = pflichtfeld(werte, "CTRADER_CLIENT_SECRET")
        token = pflichtfeld(werte, "CTRADER_ACCESS_TOKEN")
    except OAuthFehler as exc:
        print(f"Fehler: {exc}", file=sys.stderr)
        return 1

    # Fehlschlag ist die Vorgabe - nur ein vollstaendiger Lauf setzt auf 0.
    zustand = {"code": 1, "beendet": False}
    client = Client(HOST, PORT, TcpProtocol)

    def beenden(code: int) -> None:
        if zustand["beendet"]:
            return
        zustand["code"] = code
        zustand["beendet"] = True
        if wachhund.active():
            wachhund.cancel()
        client.stopService()
        if reactor.running:
            reactor.callLater(0, reactor.stop)

    def bei_zeitueberschreitung() -> None:
        print(
            f"Fehler: Keine Verbindung zu {HOST}:{PORT} innerhalb von"
            f" {VERBINDUNGS_TIMEOUT} Sekunden.",
            file=sys.stderr,
        )
        beenden(1)

    def bei_fehler(failure) -> None:
        if failure.check(Verbindungsfehler):
            print(f"\nFehler: {failure.value}", file=sys.stderr)
        else:
            print(f"\nUnerwarteter Fehler: {failure.getErrorMessage()}", file=sys.stderr)
        beenden(1)

    def bei_verbindung(_client) -> None:
        if wachhund.active():
            wachhund.cancel()
        print(f"Verbunden mit {HOST}:{PORT}.")
        deferred = ablauf(client, client_id, client_secret, token)
        deferred.addCallbacks(lambda _: erfolgreich_beenden(), bei_fehler)

    def erfolgreich_beenden() -> None:
        print(f"\n{abschluss_text}")
        beenden(0)

    def bei_trennung(_client, grund) -> None:
        if not zustand["beendet"]:
            print(f"\nFehler: Verbindung abgebrochen: {grund}", file=sys.stderr)
            beenden(1)

    def bei_nachricht(_client, nachricht) -> None:
        # Unaufgeforderte Meldung des Servers, wenn das Token zurueckgezogen wird.
        if nachricht.payloadType == ProtoOAAccountsTokenInvalidatedEvent().payloadType:
            print(f"\nFehler: {REFRESH_HINWEIS}", file=sys.stderr)
            beenden(1)

    print(f"Verbindungsaufbau zu {HOST}:{PORT} (Demo) ...")
    wachhund = reactor.callLater(VERBINDUNGS_TIMEOUT, bei_zeitueberschreitung)
    client.setConnectedCallback(bei_verbindung)
    client.setDisconnectedCallback(bei_trennung)
    client.setMessageReceivedCallback(bei_nachricht)
    client.startService()
    reactor.run()
    return zustand["code"]


def main() -> int:
    return mit_verbindung_ausfuehren(
        ablauf_ausfuehren, abschluss_text="Verbindung erfolgreich geprueft."
    )


if __name__ == "__main__":
    sys.exit(main())
