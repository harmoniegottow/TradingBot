"""Tests fuer ausfuehrung.py - ohne Netzwerk, mit nachgebildeten Meldungen.

ABSICHERUNG (aus dem Blindtest-Audit): Jeder Test, der belegt, dass etwas
NICHT passiert, zeigt vorher, dass es an derselben Stelle passieren KOENNTE.

Dass dieses Modul ohne Netzwerk auskommt, prueft test_risiko_grenze.py.
"""
import json
import tempfile
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import risiko
from ausfuehrung import (
    LAGE_ABGELEHNT,
    LAGE_AUSGEFUEHRT,
    LAGE_OHNE_ANTWORT,
    LAGE_TEILWEISE,
    Ausfuehrungsmeldung,
    Bestandsbefund,
    auftragskennung_bauen,
    bestand_befund,
    meldung_einordnen,
    nach_zeitablauf_entscheiden,
    preisabweichung,
    protokoll_eintrag,
    protokoll_schreiben,
)
from risiko import Bestand, Handelsfehler, label_bauen

KENNUNG = "hermes-XAUUSD-20260912203302-a1b2c3d4"


def meldung(typ, kennung=KENNUNG, angefordert=700, ausgefuehrt=700,
            preis="4000.12", fehler="") -> Ausfuehrungsmeldung:
    return Ausfuehrungsmeldung(
        typ=typ, kennung=kennung, label=kennung, fehlercode=fehler,
        volumen_angefordert=angefordert, volumen_ausgefuehrt=ausgefuehrt,
        ausfuehrungspreis=Decimal(preis) if preis else None)


def test_abgelehnte_order_gilt_nicht_als_ausgefuehrt():
    """Gegenprobe: Dieselbe Meldung als FILLED MUSS als Erfolg gelten."""
    erfolg = meldung_einordnen(meldung("ORDER_FILLED"), KENNUNG)
    assert erfolg.erfolgreich and erfolg.lage == LAGE_AUSGEFUEHRT, (
        "Nicht einmal eine gefuellte Order gilt als Erfolg - der Test unten"
        " koennte eine falsche Einordnung gar nicht bemerken."
    )

    befund = meldung_einordnen(
        meldung("ORDER_REJECTED", ausgefuehrt=0, preis="",
                fehler="NOT_ENOUGH_MONEY"), KENNUNG)
    assert befund.lage == LAGE_ABGELEHNT
    assert befund.endgueltig and not befund.erfolgreich
    assert "NOT_ENOUGH_MONEY" in befund.text
    print("OK  Abgelehnte Order gilt nicht als ausgefuehrte Position")


def test_teilausfuehrung_gilt_nicht_als_volle():
    """Gegenprobe: Volles Volumen MUSS als voll erkannt werden."""
    voll = meldung_einordnen(meldung("ORDER_FILLED", ausgefuehrt=700), KENNUNG)
    assert voll.lage == LAGE_AUSGEFUEHRT, (
        "Volles Volumen wird nicht als voll erkannt - dann sagt der Test"
        " unten nichts ueber die Unterscheidung."
    )

    teil = meldung_einordnen(
        meldung("ORDER_FILLED", angefordert=700, ausgefuehrt=300), KENNUNG)
    assert teil.lage == LAGE_TEILWEISE, teil
    assert not teil.erfolgreich, "Teilausfuehrung darf nicht als Erfolg gelten"
    assert "300" in teil.text and "700" in teil.text

    zwischendrin = meldung_einordnen(
        meldung("ORDER_PARTIAL_FILL", ausgefuehrt=300), KENNUNG)
    assert zwischendrin.lage == LAGE_TEILWEISE
    assert not zwischendrin.endgueltig, (
        "Eine Teilfuellung mitten im Vorgang darf das Warten nicht beenden"
    )
    print("OK  Teilausfuehrung wird als solche erkannt, nicht als volle")


def test_unbekannte_meldung_gilt_nicht_als_bestaetigung():
    """Ausbleibender Fehler ist keine Zusage."""
    befund = meldung_einordnen(meldung("SWAP"), KENNUNG)
    assert not befund.erfolgreich and not befund.endgueltig
    assert "NICHT als Bestaetigung" in befund.text
    print("OK  Unbekannte Meldung gilt nicht als Bestaetigung")


def test_fremde_meldung_wird_uebergangen():
    """Gegenprobe: Die eigene Kennung MUSS beachtet werden."""
    eigen = meldung_einordnen(meldung("ORDER_FILLED"), KENNUNG)
    assert eigen.endgueltig, (
        "Die eigene Meldung wird uebergangen - dann prueft der Test unten"
        " nicht die Unterscheidung."
    )

    fremd = meldung_einordnen(meldung("ORDER_FILLED", kennung="anderer-bot"),
                              KENNUNG)
    assert not fremd.endgueltig and not fremd.erfolgreich
    print("OK  Meldung einer fremden Order wird uebergangen")


def test_auftragskennung_wird_nie_zweimal_vergeben():
    """Gegenprobe: Ohne Zufallsteil kollidieren Kennungen in derselben Sekunde.

    Ohne diesen Nachweis belegte der Test nur, dass 5000 Aufrufe
    verschieden sind - er wuesste nicht, ob das am Zufallsteil liegt.
    """
    jetzt = datetime(2026, 9, 12, 20, 33, 2, tzinfo=timezone.utc)
    ohne_zufall = {label_bauen("XAUUSD", jetzt) for _ in range(50)}
    assert len(ohne_zufall) == 1, (
        "Schon ohne Zufallsteil sind die Kennungen verschieden - der Test"
        " unten belegte dann nicht dessen Wirkung."
    )

    mit_zufall = {auftragskennung_bauen("XAUUSD", jetzt) for _ in range(5000)}
    assert len(mit_zufall) == 5000, (
        f"Nur {len(mit_zufall)} von 5000 Kennungen sind verschieden"
    )
    assert all(k.startswith(risiko.LABEL_PRAEFIX) for k in mit_zufall)
    print("OK  5000 Kennungen in derselben Sekunde, alle verschieden")


def test_nach_zeitablauf_wird_nie_nachgesendet():
    """Keine Entscheidung darf zu einem zweiten Versand fuehren.

    Gegenprobe: Die Funktion MUSS die Faelle ueberhaupt unterscheiden.
    """
    class FalschePos:
        def __init__(self, label):
            self.tradeData = type("D", (), {"label": label})()

    leer = nach_zeitablauf_entscheiden(Bestandsbefund(KENNUNG, (), ()))
    eine = nach_zeitablauf_entscheiden(
        Bestandsbefund(KENNUNG, (FalschePos(KENNUNG),), ()))
    assert leer.lage != eine.lage, (
        "Die Funktion unterscheidet die Faelle nicht - dann sagt der Test"
        " unten nichts."
    )

    zwei = nach_zeitablauf_entscheiden(
        Bestandsbefund(KENNUNG, (FalschePos(KENNUNG), FalschePos(KENNUNG)), ()))
    for befund in (leer, eine, zwei):
        assert befund.endgueltig, "Jede Lage muss zu einer Entscheidung fuehren"
        assert "wiederhol" not in befund.text.lower() or "NICHT" in befund.text
    assert leer.lage == LAGE_OHNE_ANTWORT
    assert eine.erfolgreich, "Genau eine Position heisst: Order kam an"
    assert not zwei.erfolgreich and "ACHTUNG" in zwei.text
    print("OK  Nach Zeitablauf wird entschieden, nie nachgesendet")


def test_bestand_befund_findet_nur_die_eigene_kennung():
    class FalschePos:
        def __init__(self, label):
            self.tradeData = type("D", (), {"label": label})()

    bestand = Bestand(
        positionen=(FalschePos(KENNUNG), FalschePos("anderer-bot-1")),
        orders=())
    befund = bestand_befund(bestand, KENNUNG)
    assert befund.genau_eine, befund.anzahl
    assert bestand_befund(bestand, "gibt-es-nicht").anzahl == 0
    print("OK  Bestandsaufnahme findet genau die eigene Kennung")


def test_preisabweichung_wird_beziffert():
    abstand, anteil, text = preisabweichung(Decimal("4000"), Decimal("4000.50"))
    assert abstand == Decimal("0.50")
    assert Decimal("0.012") < anteil < Decimal("0.013"), anteil
    assert "schlechter" in text
    _, _, besser = preisabweichung(Decimal("4000"), Decimal("3999.50"))
    assert "besser" in besser
    print(f"OK  {text}")


def test_protokoll_schreibt_utc_und_liest_sich_zurueck():
    import json
    import tempfile
    with tempfile.TemporaryDirectory() as ordner:
        ziel = Path(ordner) / "orders.jsonl"
        zeit = datetime(2026, 9, 12, 20, 33, 2, tzinfo=timezone.utc)
        protokoll_schreiben(protokoll_eintrag("anfrage", {"a": 1}, zeit), ziel)
        protokoll_schreiben(protokoll_eintrag("antwort", {"b": 2}, zeit), ziel)

        zeilen = [json.loads(z) for z in ziel.read_text().splitlines()]
        assert len(zeilen) == 2, "Der zweite Eintrag hat den ersten ersetzt"
        assert zeilen[0]["zeit"].endswith("+00:00"), zeilen[0]["zeit"]
        assert zeilen[0]["art"] == "anfrage"
        assert zeilen[1]["inhalt"] == {"b": 2}
    print("OK  Protokoll haengt an, mit Zeitstempel in UTC")


def test_protokollzeit_ohne_zeitzone_wird_abgelehnt():
    try:
        protokoll_eintrag("anfrage", {}, datetime(2026, 9, 12, 20, 33))
        assert False, "haette Handelsfehler werfen muessen"
    except Handelsfehler:
        pass
    print("OK  Protokollzeit ohne Zeitzone wird abgelehnt")

if __name__ == "__main__":
    for _name, _funktion in sorted(list(globals().items())):
        if _name.startswith("test_") and callable(_funktion):
            _funktion()
    print("\nAlle Tests fuer ausfuehrung.py bestanden.")
