"""Tests fuer die reinen Funktionen aus lade_ctrader.py (kein Netzwerk).

Schwerpunkt ist die Preis-Dekodierung: low ist absolut, die drei Deltas
werden darauf addiert, alles in 1/100000. Genau hier faellt ein Vorzeichen-
oder Faktorfehler sonst erst im Backtest auf.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from ctrader_open_api.messages.OpenApiModelMessages_pb2 import (
    ProtoOALightSymbol,
    ProtoOATrendbar,
)

from lade_ctrader import (
    abschnitte_bilden,
    kerze_umrechnen,
    kerzen_aufbereiten,
    rest_anfang,
    symbol_zuordnen,
)
from verbindung import Verbindungsfehler


def balken(low: int, d_open: int, d_high: int, d_close: int,
           minuten: int, volumen: int = 100) -> ProtoOATrendbar:
    return ProtoOATrendbar(
        low=low, deltaOpen=d_open, deltaHigh=d_high, deltaClose=d_close,
        utcTimestampInMinutes=minuten, volume=volumen,
    )


def minuten_seit_epoche(text: str) -> int:
    zeit = datetime.strptime(text, "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
    return int(zeit.timestamp() // 60)


def test_preise_werden_aus_low_und_deltas_gebaut():
    # low 2500,00000 | open +3,00000 | high +8,00000 | close +5,50000
    zeile = kerze_umrechnen(
        balken(250_000_000, 300_000, 800_000, 550_000,
               minuten_seit_epoche("2026-07-01 10:00"))
    )
    zeit, offen, hoch, tief, schluss, volumen = zeile
    assert tief == Decimal("2500")
    assert offen == Decimal("2503")
    assert hoch == Decimal("2508")
    assert schluss == Decimal("2505.5")
    assert volumen == 100
    assert zeit == datetime(2026, 7, 1, 10, 0, tzinfo=timezone.utc)
    print("OK  Preise werden aus low plus Deltas gebaut, geteilt durch 100000")


def test_dekodierung_ist_exakt_nicht_gerundet():
    # 1/100000 genau - mit float entstuende hier ein Rundungsrest.
    zeile = kerze_umrechnen(balken(123_456_789, 1, 2, 3, minuten_seit_epoche(
        "2026-07-01 10:00")))
    assert zeile[3] == Decimal("1234.56789")
    assert zeile[1] == Decimal("1234.5679")
    assert all(isinstance(wert, Decimal) for wert in zeile[1:5])
    print("OK  Dekodierung rechnet exakt mit Decimal")


def test_low_ist_nie_groesser_als_die_anderen_preise():
    zeile = kerze_umrechnen(balken(250_000_000, 300_000, 800_000, 550_000,
                                   minuten_seit_epoche("2026-07-01 10:00")))
    _, offen, hoch, tief, schluss, _ = zeile
    assert tief <= min(offen, hoch, schluss)
    assert hoch >= max(offen, tief, schluss)
    print("OK  Low bleibt der kleinste, High der groesste Wert")


def test_abschnitte_sind_lueckenlos_und_ohne_ueberschneidung():
    von = datetime(2026, 1, 1, tzinfo=timezone.utc)
    bis = datetime(2026, 4, 1, tzinfo=timezone.utc)
    abschnitte = abschnitte_bilden(von, bis, timedelta(days=30))

    assert abschnitte[0][0] == von
    assert abschnitte[-1][1] == bis
    for (_, ende), (start, _) in zip(abschnitte, abschnitte[1:]):
        assert ende == start, "Abschnitte muessen nahtlos aneinander stossen"
    print("OK  Abschnitte sind lueckenlos und ueberschneidungsfrei")


def test_laufende_kerze_wird_verworfen():
    jetzt = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    laufend = int(jetzt.timestamp() // 60)              # beginnt jetzt
    fertig = laufend - 120                              # zwei Stunden alt
    von = jetzt - timedelta(days=1)
    bis = jetzt + timedelta(hours=2)

    zeilen = kerzen_aufbereiten(
        [balken(100, 1, 2, 3, fertig), balken(100, 1, 2, 3, laufend)],
        von, bis, minuten=60,
    )
    assert len(zeilen) == 1
    assert zeilen[0][0] < jetzt
    print("OK  Noch laufende Kerze wird verworfen")


def test_doppelte_kerzen_werden_entdoppelt_und_sortiert():
    von = datetime(2026, 7, 1, tzinfo=timezone.utc)
    bis = datetime(2026, 7, 2, tzinfo=timezone.utc)
    spaet = minuten_seit_epoche("2026-07-01 12:00")
    frueh = minuten_seit_epoche("2026-07-01 08:00")

    zeilen = kerzen_aufbereiten(
        [balken(100, 1, 2, 3, spaet), balken(100, 1, 2, 3, frueh),
         balken(100, 1, 2, 3, spaet)],
        von, bis, minuten=60,
    )
    assert len(zeilen) == 2, "Ueberschneidung der Abschnitte muss entdoppelt werden"
    assert zeilen[0][0] < zeilen[1][0], "Kerzen muessen aufsteigend sortiert sein"
    print("OK  Doppelte Kerzen werden entdoppelt, Reihenfolge stimmt")


def test_kerzen_ausserhalb_des_zeitraums_fallen_weg():
    von = datetime(2026, 7, 1, tzinfo=timezone.utc)
    bis = datetime(2026, 7, 2, tzinfo=timezone.utc)
    zeilen = kerzen_aufbereiten(
        [balken(100, 1, 2, 3, minuten_seit_epoche("2026-06-30 23:00")),
         balken(100, 1, 2, 3, minuten_seit_epoche("2026-07-01 12:00")),
         balken(100, 1, 2, 3, minuten_seit_epoche("2026-07-02 00:00"))],
        von, bis, minuten=60,
    )
    assert len(zeilen) == 1, "Bis-Datum ist ausschliesslich, Von-Datum einschliesslich"
    print("OK  Kerzen ausserhalb des Zeitraums fallen weg")


def test_vollstaendige_antwort_braucht_keine_nachforderung():
    bis = datetime(2026, 7, 2, tzinfo=timezone.utc)
    letzte = datetime(2026, 7, 1, 23, 0, tzinfo=timezone.utc)
    assert rest_anfang(letzte, bis, minuten=60) is None
    print("OK  Vollstaendige Antwort loest keine Nachforderung aus")


def test_frueh_endende_antwort_wird_nachgefordert():
    """Endet eine Antwort weit vor dem angefragten Ende, wird nachgeholt.

    Vorsichtsmassnahme, kein belegter Serverfehler: Anfragen bis 600 Tage
    kamen in der Messung vollstaendig zurueck.
    """
    bis = datetime(2020, 8, 23, tzinfo=timezone.utc)
    letzte = datetime(2020, 6, 30, 21, 0, tzinfo=timezone.utc)
    weiter = rest_anfang(letzte, bis, minuten=240)

    assert weiter is not None, "frueh endende Antwort muss auffallen"
    assert weiter == datetime(2020, 7, 1, 1, 0, tzinfo=timezone.utc)
    print("OK  Frueh endende Antwort wird erkannt")


def test_letzte_laufende_kerze_gilt_nicht_als_kuerzung():
    """Bis-Datum in der Zukunft: die fehlende letzte Kerze ist normal."""
    bis = datetime(2026, 9, 12, 14, 30, tzinfo=timezone.utc)
    letzte = datetime(2026, 9, 12, 13, 0, tzinfo=timezone.utc)
    assert rest_anfang(letzte, bis, minuten=60) is None
    print("OK  Laufende Kerze am Rand loest keine Nachforderung aus")


def test_symbol_wird_ueber_alternativnamen_gefunden():
    symbole = [
        ProtoOALightSymbol(symbolId=41, symbolName="GOLD"),
        ProtoOALightSymbol(symbolId=1, symbolName="EURUSD"),
    ]
    symbol_id, name = symbol_zuordnen(symbole, "XAUUSD")
    assert symbol_id == 41
    assert name == "GOLD"
    print("OK  XAUUSD wird ueber den Alternativnamen GOLD gefunden")


def test_unbekanntes_symbol_wirft_fehler_mit_vorschlaegen():
    symbole = [ProtoOALightSymbol(symbolId=1, symbolName="EURUSD")]
    try:
        symbol_zuordnen(symbole, "XAUUSD")
        assert False, "haette Verbindungsfehler werfen muessen"
    except Verbindungsfehler as fehler:
        assert "XAUUSD" in str(fehler)
    print("OK  Unbekanntes Symbol wirft Fehler mit Hinweisen")


if __name__ == "__main__":
    test_preise_werden_aus_low_und_deltas_gebaut()
    test_dekodierung_ist_exakt_nicht_gerundet()
    test_low_ist_nie_groesser_als_die_anderen_preise()
    test_abschnitte_sind_lueckenlos_und_ohne_ueberschneidung()
    test_laufende_kerze_wird_verworfen()
    test_doppelte_kerzen_werden_entdoppelt_und_sortiert()
    test_kerzen_ausserhalb_des_zeitraums_fallen_weg()
    test_vollstaendige_antwort_braucht_keine_nachforderung()
    test_frueh_endende_antwort_wird_nachgefordert()
    test_letzte_laufende_kerze_gilt_nicht_als_kuerzung()
    test_symbol_wird_ueber_alternativnamen_gefunden()
    test_unbekanntes_symbol_wirft_fehler_mit_vorschlaegen()
    print("Alle Tests fuer lade_ctrader.py bestanden.")
