"""Tests fuer handel.py - Sendesperren und Orderbau, ohne Netzwerk.

Die reine Rechnung liegt in risiko.py und wird in test_risiko.py geprueft.
Hier bleibt, was Protobuf oder die Betriebsart betrifft.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import handel
from handel import (
    MODUS_SENDEN,
    MODUS_TROCKENLAUF,
    order_bauen,
    senden_erlaubt,
    vorschlag_bauen,
)
from risiko import (
    Bestand,
    Kapitalstand,
    Kursstand,
    Symbolgrenzen,
    Tagesergebnis,
)

EINS = Decimal(1)


KAPITAL = Decimal("1000")


def ergebnis(realisiert="0", unrealisiert="0") -> Tagesergebnis:
    return Tagesergebnis(Decimal(realisiert), Decimal(unrealisiert), 0, 0)


GOLD = Symbolgrenzen(symbol_id=41, name="XAUUSD", min_volumen=100,
                     max_volumen=500_000, schritt_volumen=100,
                     lot_groesse=10_000, stellen=2)


EURUSD = Symbolgrenzen(symbol_id=1, name="EURUSD", min_volumen=100_000,
                       max_volumen=1_000_000_000, schritt_volumen=100_000,
                       lot_groesse=10_000_000, stellen=5)


class FalscheDaten:
    """Minimale Attrappe fuer ProtoOAPosition.tradeData."""

    def __init__(self, label="", symbol_id=41, volumen=100):
        self.label = label
        self.symbolId = symbol_id
        self.volume = volumen


class FalschePosition:
    def __init__(self, label="", positions_id=1):
        self.tradeData = FalscheDaten(label)
        self.positionId = positions_id


def bestand_mit(anzahl: int, label: str = "") -> Bestand:
    return Bestand(positionen=tuple(FalschePosition(label, i)
                                    for i in range(anzahl)), orders=())


def test_trockenlauf_sendet_nicht():
    """Gegenprobe zuerst: Auf demselben Konto MUSS 'senden' erlaubt sein."""
    darf_mit_senden, _ = senden_erlaubt(MODUS_SENDEN, False, False)
    assert darf_mit_senden, (
        "Selbst mit Modus 'senden' auf einem Demokonto wird gesperrt - dann"
        " prueft der Test unten nicht den Modus, sondern eine andere Sperre."
    )

    darf, grund = senden_erlaubt(MODUS_TROCKENLAUF, False, False)
    assert not darf
    assert MODUS_SENDEN in grund
    print("OK  Trockenlauf sendet nicht, obwohl Senden hier moeglich waere")


def test_livekonto_bleibt_ohne_zweite_bestaetigung_gesperrt():
    """Gegenprobe: Dieselben Einstellungen auf dem Demokonto erlauben Senden."""
    auf_demo, _ = senden_erlaubt(MODUS_SENDEN, False, False)
    assert auf_demo, (
        "Auf dem Demokonto wird schon gesperrt - der Test unten koennte die"
        " Live-Sperre gar nicht nachweisen."
    )

    darf, grund = senden_erlaubt(MODUS_SENDEN, True, False)
    assert not darf
    assert "ECHTGELD_AUSDRUECKLICH_ERLAUBT" in grund
    print("OK  Livekonto bleibt trotz Modus 'senden' ohne zweite Bestaetigung gesperrt")


def test_livekonto_mit_zweiter_bestaetigung_waere_erlaubt():
    darf, grund = senden_erlaubt(MODUS_SENDEN, True, True)
    assert darf
    assert "ACHTUNG" in grund and "echtem Geld" in grund
    print("OK  Livekonto mit zweiter Bestaetigung erlaubt - und sagt es laut")


def test_modus_allein_genuegt_auf_live_nicht():
    """Der Schalter fuer Echtgeld allein darf ebenfalls nicht genuegen."""
    darf, _ = senden_erlaubt(MODUS_TROCKENLAUF, True, True)
    assert not darf, "Echtgeld-Schalter ohne Modus 'senden' darf nicht reichen"
    print("OK  Beide Schalter noetig - einer allein genuegt nicht")


def _grenze(kapital: Decimal) -> Decimal:
    return kapital * handel.TAGESVERLUST_GRENZE_PROZENT / Decimal(100)


def test_order_enthaelt_alle_werte():
    vorschlag = vorschlag_bauen(
        GOLD, "BUY", Decimal("4000"), Decimal("3960"), Decimal("4080"),
        "Testanlass", umrechnung=EINS, kapital=Decimal("50000"))
    assert vorschlag.entscheid.angenommen

    order = order_bauen(4711, vorschlag)
    assert order.ctidTraderAccountId == 4711
    assert order.symbolId == GOLD.symbol_id
    assert order.volume == vorschlag.volumen
    assert order.label == vorschlag.label
    assert abs(order.stopLoss - 3960.0) < 1e-9
    assert abs(order.takeProfit - 4080.0) < 1e-9
    assert len(order.SerializeToString()) > 0
    print("OK  Die fertige Order traegt alle Werte")


class FalschesSymbol:
    """Minimale Attrappe fuer ProtoOALightSymbol."""

    def __init__(self, symbol_id, name, basis, notierung):
        self.symbolId, self.symbolName = symbol_id, name
        self.baseAssetId, self.quoteAssetId = basis, notierung


EUR, USD, JPY = 1, 2, 3


SYMBOLE = (
    FalschesSymbol(1, "EURUSD", EUR, USD),
    FalschesSymbol(4, "USDJPY", USD, JPY),
    FalschesSymbol(41, "XAUUSD", 9, USD),
)


def kurs(alter: timedelta, symbol="EURUSD", wert="1.0842") -> Kursstand:
    jetzt = datetime(2026, 9, 12, 12, 0, tzinfo=timezone.utc)
    return Kursstand(symbol, Decimal(wert), jetzt - alter, alter)


def test_vorgabe_ist_trockenlauf():
    assert handel.MODUS == MODUS_TROCKENLAUF
    assert handel.ECHTGELD_AUSDRUECKLICH_ERLAUBT is False
    print("OK  Vorgabe ist Trockenlauf, Echtgeld ist nicht erlaubt")

if __name__ == "__main__":
    for _name, _funktion in sorted(list(globals().items())):
        if _name.startswith("test_") and callable(_funktion):
            _funktion()
    print("\nAlle Tests fuer handel.py bestanden.")
