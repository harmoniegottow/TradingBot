#!/usr/bin/env python3
"""hole_swapsaetze.py - aktuelle Swapsaetze vom Broker (cTrader Open API).

Gibt fuer jedes Symbol swapLong, swapShort, Berechnungsart und pipPosition
aus. Damit wird kosten.SWAP_SAETZE erweitert. Es wird NICHTS gehandelt.

    .venv/bin/python hole_swapsaetze.py EURUSD USDJPY CHFJPY XAUUSD
"""
from __future__ import annotations

import sys
from functools import partial

from ctrader_open_api.messages.OpenApiMessages_pb2 import (
    ProtoOAAccountAuthReq, ProtoOAApplicationAuthReq,
    ProtoOAGetAccountListByAccessTokenReq, ProtoOASymbolByIdReq,
    ProtoOASymbolsListReq)
from twisted.internet import defer

from lade_ctrader import symbol_zuordnen
from verbindung import anfrage_senden, konto_waehlen, mit_verbindung_ausfuehren


@defer.inlineCallbacks
def ablauf(client, client_id, client_secret, token, namen):
    yield anfrage_senden(client, ProtoOAApplicationAuthReq(
        clientId=client_id, clientSecret=client_secret))
    konten = yield anfrage_senden(
        client, ProtoOAGetAccountListByAccessTokenReq(accessToken=token))
    konto_id = konto_waehlen(list(konten.ctidTraderAccount))
    yield anfrage_senden(client, ProtoOAAccountAuthReq(
        ctidTraderAccountId=konto_id, accessToken=token))
    symbole = list((yield anfrage_senden(
        client, ProtoOASymbolsListReq(ctidTraderAccountId=konto_id))).symbol)
    for name in namen:
        sid, broker = symbol_zuordnen(symbole, name)
        d = (yield anfrage_senden(client, ProtoOASymbolByIdReq(
            ctidTraderAccountId=konto_id, symbolId=[sid]))).symbol[0]
        print(f"SWAP|{name}|long={d.swapLong}|short={d.swapShort}"
              f"|art={d.swapCalculationType}|pipPos={d.pipPosition}"
              f"|dreifach={d.swapRollover3Days}|zeit={d.swapTime}")


if __name__ == "__main__":
    sys.exit(mit_verbindung_ausfuehren(
        partial(ablauf, namen=sys.argv[1:] or ["EURUSD"])))
