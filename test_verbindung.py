"""Tests fuer die Kontoauswahl aus verbindung.py (kein Netzwerk, kein Reactor).

Gearbeitet wird mit echten ProtoOACtidTraderAccount-Objekten, damit die
isLive-Auswertung genau so laeuft wie spaeter gegen den Server.
"""
import io
from contextlib import redirect_stdout

from ctrader_open_api.messages.OpenApiModelMessages_pb2 import ProtoOACtidTraderAccount

from verbindung import ERWARTETES_KONTO, Verbindungsfehler, konto_waehlen


def konto(kennung: int, *, live: bool, login: int = 111) -> ProtoOACtidTraderAccount:
    return ProtoOACtidTraderAccount(
        ctidTraderAccountId=kennung, isLive=live, traderLogin=login
    )


def waehlen_ohne_ausgabe(konten):
    """Ruft konto_waehlen auf und liefert (Ergebnis, Ausgabetext)."""
    puffer = io.StringIO()
    with redirect_stdout(puffer):
        ergebnis = konto_waehlen(konten)
    return ergebnis, puffer.getvalue()


def test_einzelnes_live_konto_wird_nicht_automatisch_gewaehlt():
    konten = [konto(9999999, live=True)]
    puffer = io.StringIO()
    try:
        with redirect_stdout(puffer):
            ergebnis = konto_waehlen(konten)
        assert False, f"haette abbrechen muessen, gab aber {ergebnis!r} zurueck"
    except Verbindungsfehler as fehler:
        text = str(fehler)
        assert "LIVE-Konto" in text
        assert "niemals automatisch" in text
        assert "9999999" in text
    print("OK  Einzelnes Live-Konto wird nicht automatisch gewaehlt")


def test_einzelnes_demokonto_wird_als_notbehelf_gewaehlt():
    ergebnis, ausgabe = waehlen_ohne_ausgabe([konto(5555555, live=False)])
    assert ergebnis == 5555555
    assert "WARNUNG" in ausgabe, "Fallback muss als Warnung erkennbar sein"
    assert "Notbehelf" in ausgabe
    assert "isLive=false" in ausgabe
    print("OK  Einzelnes Demokonto wird als Notbehelf mit Warnung gewaehlt")


def test_treffer_ueber_trader_login():
    """Der Alltagsfall: 4266384 ist der Login, die API-Kennung eine andere."""
    konten = [konto(48369355, live=False, login=ERWARTETES_KONTO)]
    ergebnis, ausgabe = waehlen_ohne_ausgabe(konten)

    assert ergebnis == 48369355, "zurueck muss die ctidTraderAccountId kommen"
    assert "traderLogin" in ausgabe
    assert "48369355" in ausgabe and str(ERWARTETES_KONTO) in ausgabe
    assert "WARNUNG" not in ausgabe
    print("OK  Treffer ueber traderLogin, beide Nummern ausgegeben")


def test_treffer_ueber_ctid_trader_account_id():
    konten = [konto(ERWARTETES_KONTO, live=False, login=999999)]
    ergebnis, ausgabe = waehlen_ohne_ausgabe(konten)

    assert ergebnis == ERWARTETES_KONTO
    assert "ctidTraderAccountId" in ausgabe
    assert "999999" in ausgabe, "auch der Login muss dastehen"
    assert "WARNUNG" not in ausgabe
    print("OK  Treffer ueber ctidTraderAccountId, beide Nummern ausgegeben")


def test_treffer_ueber_login_bei_live_konto_wird_gemeldet():
    """Live bleibt erlaubt, wenn das Konto ausdruecklich vorgegeben ist."""
    konten = [konto(48369355, live=True, login=ERWARTETES_KONTO)]
    ergebnis, ausgabe = waehlen_ohne_ausgabe(konten)

    assert ergebnis == 48369355
    assert "ACHTUNG" in ausgabe and "LIVE-Konto" in ausgabe
    print("OK  Live-Treffer ueber Login wird zugelassen und laut gemeldet")


def test_konfigurierte_id_wird_als_demo_bestaetigt():
    konten = [konto(ERWARTETES_KONTO, live=False), konto(7777777, live=False)]
    ergebnis, ausgabe = waehlen_ohne_ausgabe(konten)
    assert ergebnis == ERWARTETES_KONTO
    assert "isLive=false" in ausgabe
    assert "bestaetigt als Demokonto" in ausgabe
    assert "WARNUNG" not in ausgabe, "Ein Treffer ist kein Notbehelf"
    print("OK  Treffer auf konfigurierte ID wird mit isLive=false bestaetigt")


def test_konfigurierte_id_als_live_wird_deutlich_gemeldet():
    ergebnis, ausgabe = waehlen_ohne_ausgabe([konto(ERWARTETES_KONTO, live=True)])
    assert ergebnis == ERWARTETES_KONTO
    assert "ACHTUNG" in ausgabe
    assert "LIVE-Konto" in ausgabe
    print("OK  Konfigurierte ID als Live-Konto wird unuebersehbar gemeldet")


def test_live_konto_neben_demokonto_wird_uebergangen():
    konten = [konto(ERWARTETES_KONTO, live=False), konto(8888888, live=True)]
    ergebnis, _ = waehlen_ohne_ausgabe(konten)
    assert ergebnis == ERWARTETES_KONTO
    print("OK  Live-Konto neben der konfigurierten ID wird nicht gewaehlt")


def test_mehrere_konten_ohne_treffer_brechen_ab():
    konten = [konto(1111111, live=False), konto(2222222, live=True)]
    try:
        waehlen_ohne_ausgabe(konten)
        assert False, "haette Verbindungsfehler werfen muessen"
    except Verbindungsfehler as fehler:
        assert str(ERWARTETES_KONTO) in str(fehler)
    print("OK  Mehrere Konten ohne Treffer brechen ab")


def test_leere_kontoliste_nennt_ctid_verknuepfung():
    try:
        waehlen_ohne_ausgabe([])
        assert False, "haette Verbindungsfehler werfen muessen"
    except Verbindungsfehler as fehler:
        assert "cTID" in str(fehler)
    print("OK  Leere Kontoliste nennt die fehlende cTID-Verknuepfung")


if __name__ == "__main__":
    test_einzelnes_live_konto_wird_nicht_automatisch_gewaehlt()
    test_einzelnes_demokonto_wird_als_notbehelf_gewaehlt()
    test_treffer_ueber_trader_login()
    test_treffer_ueber_ctid_trader_account_id()
    test_treffer_ueber_login_bei_live_konto_wird_gemeldet()
    test_konfigurierte_id_wird_als_demo_bestaetigt()
    test_konfigurierte_id_als_live_wird_deutlich_gemeldet()
    test_live_konto_neben_demokonto_wird_uebergangen()
    test_mehrere_konten_ohne_treffer_brechen_ab()
    test_leere_kontoliste_nennt_ctid_verknuepfung()
    print("Alle Tests fuer verbindung.py bestanden.")
