"""Tests fuer die reinen Funktionen aus auth/oauth_token.py (kein Netzwerk)."""
import stat
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from auth.oauth_token import (
    OAuthFehler,
    ablaufzeitpunkt_berechnen,
    antwort_auswerten,
    code_aus_eingabe_extrahieren,
    env_datei_aktualisieren,
    env_zeilen_ersetzen,
)

ERFOLGSANTWORT = {
    "errorCode": None,
    "accessToken": "zugang-123",
    "refreshToken": "erneuern-456",
    "tokenType": "bearer",
    "expiresIn": 2628000,
}


def test_code_aus_vollstaendiger_callback_url():
    url = "https://bienemorl.de/ctrader-callback?code=abc123&scope=trading"
    assert code_aus_eingabe_extrahieren(url) == "abc123"
    print("OK  Code aus vollstaendiger Callback-URL extrahiert")


def test_code_aus_url_mit_weiteren_parametern_davor():
    url = "https://bienemorl.de/ctrader-callback?state=xyz&code=abc123"
    assert code_aus_eingabe_extrahieren(url) == "abc123"
    print("OK  Code auch bei anderer Parameterreihenfolge gefunden")


def test_code_aus_url_mit_weiterleitung_im_pfad():
    url = (
        "https://bienemorl.de/de/weiter/ctrader-callback"
        "?code=abc123&scope=trading&state=xyz"
    )
    assert code_aus_eingabe_extrahieren(url) == "abc123"
    print("OK  Code auch bei zusaetzlicher Weiterleitung im Pfad gefunden")


def test_url_ohne_parameter_wird_nicht_als_code_durchgereicht():
    url = "https://bienemorl.de/ctrader-callback"
    try:
        ergebnis = code_aus_eingabe_extrahieren(url)
        assert False, f"haette OAuthFehler werfen muessen, gab aber {ergebnis!r} zurueck"
    except OAuthFehler as fehler:
        assert "code" in str(fehler)
    print("OK  URL ohne Parameter wird abgelehnt statt als Code verschickt")


def test_code_direkt_eingefuegt_ohne_url():
    assert code_aus_eingabe_extrahieren("  abc123XYZ  ") == "abc123XYZ"
    print("OK  Bloss eingefuegter Code wird akzeptiert")


def test_code_fehlt_in_url_wirft_fehler():
    url = "https://bienemorl.de/ctrader-callback?scope=trading"
    try:
        code_aus_eingabe_extrahieren(url)
        assert False, "haette OAuthFehler werfen muessen"
    except OAuthFehler:
        pass
    print("OK  Fehlender code-Parameter wird erkannt")


def test_leere_eingabe_wirft_fehler():
    try:
        code_aus_eingabe_extrahieren("   ")
        assert False, "haette OAuthFehler werfen muessen"
    except OAuthFehler:
        pass
    print("OK  Leere Eingabe wird abgelehnt")


def test_env_zeile_wird_ersetzt_nicht_verdoppelt():
    inhalt = "CTRADER_CLIENT_ID=abc\nCTRADER_ACCESS_TOKEN=alt\nCTRADER_ACCOUNT_ID=123\n"
    neu = env_zeilen_ersetzen(inhalt, {"CTRADER_ACCESS_TOKEN": "neu"})
    zeilen = neu.splitlines()
    assert zeilen.count("CTRADER_ACCESS_TOKEN=neu") == 1
    assert "CTRADER_CLIENT_ID=abc" in zeilen
    assert "CTRADER_ACCOUNT_ID=123" in zeilen
    assert not any(z.startswith("CTRADER_ACCESS_TOKEN=alt") for z in zeilen)
    print("OK  Bestehende .env-Zeile wird ersetzt statt verdoppelt")


def test_env_schluessel_wird_angehaengt_wenn_neu():
    inhalt = "CTRADER_CLIENT_ID=abc\n"
    neu = env_zeilen_ersetzen(inhalt, {"CTRADER_REFRESH_TOKEN": "rrr"})
    zeilen = neu.splitlines()
    assert "CTRADER_CLIENT_ID=abc" in zeilen
    assert "CTRADER_REFRESH_TOKEN=rrr" in zeilen
    print("OK  Neuer Schluessel wird angehaengt")


def test_mehrere_updates_gleichzeitig():
    inhalt = "A=1\nB=2\n"
    neu = env_zeilen_ersetzen(inhalt, {"A": "neu1", "C": "neu3"})
    zeilen = neu.splitlines()
    assert "A=neu1" in zeilen
    assert "B=2" in zeilen
    assert "C=neu3" in zeilen
    print("OK  Mehrere Updates in einem Durchlauf korrekt angewendet")


def test_errorcode_null_mit_token_ist_erfolg():
    ergebnis = antwort_auswerten(dict(ERFOLGSANTWORT), 200)
    assert ergebnis["accessToken"] == "zugang-123"
    assert ergebnis["refreshToken"] == "erneuern-456"
    assert ergebnis["expiresIn"] == 2628000
    print("OK  errorCode=null mit gueltigem Token gilt als Erfolg")


def test_echter_errorcode_ist_fehler():
    antwort = {"errorCode": "INVALID_REQUEST", "description": "code abgelaufen"}
    try:
        antwort_auswerten(antwort, 400)
        assert False, "haette OAuthFehler werfen muessen"
    except OAuthFehler as fehler:
        text = str(fehler)
        assert "INVALID_REQUEST" in text
        assert "code abgelaufen" in text
        assert "HTTP 400" in text
    print("OK  Echter errorCode wird als Fehler erkannt")


def test_antwort_ohne_accesstoken_ist_fehler():
    antwort = {"errorCode": None, "refreshToken": "erneuern-456", "expiresIn": 2628000}
    try:
        antwort_auswerten(antwort, 200)
        assert False, "haette OAuthFehler werfen muessen"
    except OAuthFehler as fehler:
        text = str(fehler)
        assert "accessToken" in text
        # Feldnamen ja, Werte nein - sonst stuende der Refresh-Token im Log.
        assert "erneuern-456" not in text
    print("OK  Fehlendes accessToken gilt als Fehler, ohne Werte im Text")


def test_verschachtelte_antwort_unter_payload():
    antwort = {"errorCode": None, "payload": dict(ERFOLGSANTWORT)}
    ergebnis = antwort_auswerten(antwort, 200)
    assert ergebnis["accessToken"] == "zugang-123"
    assert ergebnis["refreshToken"] == "erneuern-456"
    assert ergebnis["tokenType"] == "bearer"
    print("OK  Verschachtelte Antwort unter 'payload' wird gelesen")


def test_fehlertext_nutzt_alternative_beschreibungsfelder():
    antwort = {"errorCode": "ACCESS_DENIED", "error_description": "Zugriff verweigert"}
    try:
        antwort_auswerten(antwort, 403)
        assert False, "haette OAuthFehler werfen muessen"
    except OAuthFehler as fehler:
        assert "Zugriff verweigert" in str(fehler)
    print("OK  Beschreibung wird auch aus error_description gelesen")


def test_fehlertext_nennt_feldnamen_ohne_werte():
    antwort = {"errorCode": "BOOM", "payload": {"accessToken": "geheim-zugang"}}
    try:
        antwort_auswerten(antwort, 500)
        assert False, "haette OAuthFehler werfen muessen"
    except OAuthFehler as fehler:
        text = str(fehler)
        assert "payload.accessToken" in text
        assert "geheim-zugang" not in text
    print("OK  Fehlertext nennt Feldnamen, aber keine Werte")


def test_ablaufzeitpunkt_ist_iso_utc():
    jetzt = datetime(2026, 9, 12, 10, 0, 0, tzinfo=timezone.utc)
    assert ablaufzeitpunkt_berechnen(2628000, jetzt) == "2026-10-12T20:00:00+00:00"
    print("OK  Ablaufzeitpunkt wird als ISO-8601 in UTC berechnet")


def test_env_datei_bekommt_rechte_600():
    with tempfile.TemporaryDirectory() as ordner:
        pfad = Path(ordner) / ".env"
        pfad.write_text("CTRADER_CLIENT_ID=abc\n", encoding="utf-8")
        pfad.chmod(0o644)

        env_datei_aktualisieren(pfad, {"CTRADER_ACCESS_TOKEN": "geheim"})

        assert stat.S_IMODE(pfad.stat().st_mode) == 0o600
        assert "CTRADER_ACCESS_TOKEN=geheim" in pfad.read_text(encoding="utf-8")
    print("OK  .env wird nach dem Schreiben auf 600 gesetzt und geprueft")


def test_env_datei_wird_neu_mit_600_angelegt():
    with tempfile.TemporaryDirectory() as ordner:
        pfad = Path(ordner) / ".env"

        env_datei_aktualisieren(pfad, {"CTRADER_REFRESH_TOKEN": "geheim"})

        assert stat.S_IMODE(pfad.stat().st_mode) == 0o600
    print("OK  Neu angelegte .env hat von Anfang an die Rechte 600")


if __name__ == "__main__":
    test_code_aus_vollstaendiger_callback_url()
    test_code_aus_url_mit_weiteren_parametern_davor()
    test_code_aus_url_mit_weiterleitung_im_pfad()
    test_url_ohne_parameter_wird_nicht_als_code_durchgereicht()
    test_code_direkt_eingefuegt_ohne_url()
    test_code_fehlt_in_url_wirft_fehler()
    test_leere_eingabe_wirft_fehler()
    test_env_zeile_wird_ersetzt_nicht_verdoppelt()
    test_env_schluessel_wird_angehaengt_wenn_neu()
    test_mehrere_updates_gleichzeitig()
    test_errorcode_null_mit_token_ist_erfolg()
    test_echter_errorcode_ist_fehler()
    test_antwort_ohne_accesstoken_ist_fehler()
    test_verschachtelte_antwort_unter_payload()
    test_fehlertext_nutzt_alternative_beschreibungsfelder()
    test_fehlertext_nennt_feldnamen_ohne_werte()
    test_ablaufzeitpunkt_ist_iso_utc()
    test_env_datei_bekommt_rechte_600()
    test_env_datei_wird_neu_mit_600_angelegt()
    print("Alle Tests fuer oauth_token.py bestanden.")
