#!/usr/bin/env python3
"""OAuth-Token-Verwaltung fuer die cTrader Open API.

Ohne Argument: Erstautorisierung (Autorisierungs-URL ausgeben, Code
entgegennehmen, sofort gegen ein Token tauschen).

Mit --refresh: bestehenden Refresh-Token gegen ein neues Access-/Refresh-Token
einloesen.

In beiden Faellen werden Access-Token, Refresh-Token und Ablaufzeitpunkt in
die .env geschrieben. Token und Secrets werden nie auf der Konsole oder im
Log ausgegeben.
"""

import argparse
import re
import stat
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qs, urlencode, urlparse

import requests
from dotenv import dotenv_values

AUTH_URL = "https://id.ctrader.com/my/settings/openapi/grantingaccess/"
TOKEN_URL = "https://openapi.ctrader.com/apps/token"
SCOPE = "trading"
PRODUCT = "web"
TIMEOUT_SEKUNDEN = 15
# Reihenfolge, in der nach einem Beschreibungstext im Fehlerfall gesucht wird.
BESCHREIBUNGS_FELDER = ("description", "errorDescription", "error_description", "error")
ENV_PFAD = Path(__file__).resolve().parent.parent / ".env"


class OAuthFehler(Exception):
    """Fehler bei Autorisierung, Token-Tausch oder .env-Verarbeitung."""


def env_werte_laden(pfad: Path = ENV_PFAD) -> dict:
    werte = dotenv_values(pfad)
    return {schluessel: (wert or "").strip() for schluessel, wert in werte.items()}


def pflichtfeld(werte: dict, schluessel: str) -> str:
    wert = werte.get(schluessel, "")
    if not wert:
        raise OAuthFehler(f"{schluessel} fehlt in {ENV_PFAD}. Bitte eintragen.")
    return wert


def autorisierungs_url_bauen(client_id: str, redirect_uri: str) -> str:
    parameter = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": SCOPE,
        "product": PRODUCT,
    }
    return f"{AUTH_URL}?{urlencode(parameter)}"


def _sieht_nach_url_aus(eingabe: str) -> bool:
    return eingabe.lower().startswith(("http://", "https://")) or "://" in eingabe


def _code_aus_url(url: str) -> str:
    """Zieht den code-Parameter aus der Callback-URL."""
    code = parse_qs(urlparse(url).query).get("code", [None])[0]
    if not code:
        raise OAuthFehler(
            "Die eingefuegte Adresse enthaelt keinen 'code'-Parameter. "
            "Wahrscheinlich hat eine Weiterleitung der Callback-Domain die "
            "Parameter verworfen (z. B. von https auf www oder auf eine "
            "Startseite). Bitte die Adresszeile unmittelbar nach der "
            "Zustimmung kopieren, ohne die Seite neu zu laden, und "
            "gegebenenfalls die Weiterleitung der Domain pruefen."
        )
    return code


def _blossen_code_pruefen(eingabe: str) -> str:
    """Plausibilitaet eines direkt eingefuegten Codes (keine URL-Reste)."""
    if any(zeichen.isspace() for zeichen in eingabe):
        raise OAuthFehler(
            "Die Eingabe enthaelt Leerzeichen und ist damit kein gueltiger Code. "
            "Bitte den Code allein oder die komplette Callback-URL einfuegen."
        )
    if "/" in eingabe or "?" in eingabe:
        raise OAuthFehler(
            "Die Eingabe sieht nach einem URL-Bruchstueck aus, nicht nach einem "
            "Code. Bitte die komplette Callback-URL (mit https://) oder nur den "
            "Code einfuegen."
        )
    return eingabe


def code_aus_eingabe_extrahieren(eingabe: str) -> str:
    """Akzeptiert entweder die komplette Callback-URL oder nur den Code.

    Eine erkennbare URL wird immer als URL behandelt - sonst wuerde eine
    URL ohne code-Parameter versehentlich als Code an cTrader gehen.
    """
    eingabe = eingabe.strip()
    if not eingabe:
        raise OAuthFehler("Keine Eingabe erhalten - Code oder Callback-URL noetig.")
    if _sieht_nach_url_aus(eingabe):
        return _code_aus_url(eingabe)
    return _blossen_code_pruefen(eingabe)


def token_gegen_code_tauschen(
    client_id: str, client_secret: str, redirect_uri: str, code: str
) -> dict:
    parameter = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "client_id": client_id,
        "client_secret": client_secret,
    }
    return _token_anfrage(parameter)


def token_erneuern(client_id: str, client_secret: str, refresh_token: str) -> dict:
    parameter = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": client_id,
        "client_secret": client_secret,
    }
    return _token_anfrage(parameter)


def _token_anfrage(parameter: dict) -> dict:
    try:
        antwort = requests.get(TOKEN_URL, params=parameter, timeout=TIMEOUT_SEKUNDEN)
    except requests.exceptions.Timeout as exc:
        raise OAuthFehler("Zeitueberschreitung bei der Verbindung zu cTrader.") from exc
    except requests.exceptions.RequestException as exc:
        raise OAuthFehler(f"Netzwerkfehler bei der Verbindung zu cTrader: {exc}") from exc

    try:
        daten = antwort.json()
    except ValueError as exc:
        raise OAuthFehler(
            f"Unerwartete Antwort von cTrader (Status {antwort.status_code})."
        ) from exc

    return antwort_auswerten(daten, antwort.status_code)


def _ebenen(daten: dict) -> tuple:
    """Antwortebenen: cTrader liefert die Felder mal direkt, mal unter 'payload'."""
    payload = daten.get("payload")
    if isinstance(payload, dict):
        return (daten, payload)
    return (daten,)


def _wert_aus_antwort(ebenen: tuple, name: str):
    """Erster echte Wert des Feldes ueber alle Ebenen (None und "" zaehlen nicht)."""
    for ebene in ebenen:
        wert = ebene.get(name)
        if wert is not None and wert != "":
            return wert
    return None


def _schluesselnamen(daten: dict) -> str:
    """Nur die Feldnamen der Antwort - ausdruecklich ohne Werte."""
    namen = []
    for name, wert in daten.items():
        if name == "payload" and isinstance(wert, dict):
            namen.extend(f"payload.{unterfeld}" for unterfeld in wert)
        else:
            namen.append(name)
    return ", ".join(sorted(namen)) if namen else "keine"


def _fehlertext(daten: dict, ebenen: tuple, status_code: int, error_code) -> str:
    beschreibung = None
    for feld in BESCHREIBUNGS_FELDER:
        beschreibung = _wert_aus_antwort(ebenen, feld)
        if beschreibung:
            break

    grund = error_code if error_code else "kein accessToken in der Antwort"
    erlaeuterung = str(beschreibung) if beschreibung else "keine weitere Beschreibung"
    return (
        f"cTrader lehnt ab: {grund} - {erlaeuterung} "
        f"(HTTP {status_code}; Felder in der Antwort: {_schluesselnamen(daten)})"
    )


def antwort_auswerten(daten: dict, status_code: int) -> dict:
    """Wertet die Token-Antwort aus und liefert die Felder vereinheitlicht.

    Ein Fehler liegt nur vor, wenn errorCode einen echten Wert traegt oder
    das accessToken fehlt. cTrader sendet errorCode auch im Erfolgsfall mit,
    dann aber als null - blosses Vorhandensein ist also kein Fehlersignal.
    """
    ebenen = _ebenen(daten)
    error_code = _wert_aus_antwort(ebenen, "errorCode")
    access_token = _wert_aus_antwort(ebenen, "accessToken")

    if error_code or not access_token:
        raise OAuthFehler(_fehlertext(daten, ebenen, status_code, error_code))

    ergebnis = {
        feld: _wert_aus_antwort(ebenen, feld)
        for feld in ("accessToken", "refreshToken", "tokenType", "expiresIn")
    }

    # Ohne diese beiden liesse sich kein vollstaendiger Satz speichern.
    for feld in ("refreshToken", "expiresIn"):
        if ergebnis[feld] is None:
            raise OAuthFehler(
                f"Antwort von cTrader enthaelt kein Feld '{feld}' "
                f"(HTTP {status_code}; Felder in der Antwort: "
                f"{_schluesselnamen(daten)})."
            )

    return ergebnis


def ablaufzeitpunkt_berechnen(
    expires_in_sekunden, jetzt: Optional[datetime] = None
) -> str:
    jetzt = jetzt or datetime.now(timezone.utc)
    ablauf = jetzt + timedelta(seconds=int(expires_in_sekunden))
    return ablauf.replace(microsecond=0).isoformat()


def env_zeilen_ersetzen(inhalt: str, updates: dict) -> str:
    """Ersetzt vorhandene KEY=... Zeilen, haengt fehlende Schluessel an."""
    zeilen = inhalt.splitlines()
    gesehen = set()
    ergebnis = []
    for zeile in zeilen:
        treffer = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)=", zeile)
        if treffer and treffer.group(1) in updates:
            schluessel = treffer.group(1)
            ergebnis.append(f"{schluessel}={updates[schluessel]}")
            gesehen.add(schluessel)
        else:
            ergebnis.append(zeile)
    for schluessel, wert in updates.items():
        if schluessel not in gesehen:
            ergebnis.append(f"{schluessel}={wert}")
    text = "\n".join(ergebnis)
    if not text.endswith("\n"):
        text += "\n"
    return text


def rechte_pruefen(pfad: Path) -> None:
    """Stellt sicher, dass die Datei nur fuer den Eigentuemer lesbar ist."""
    rechte = stat.S_IMODE(pfad.stat().st_mode)
    if rechte != 0o600:
        raise OAuthFehler(
            f"{pfad} hat die Rechte {oct(rechte)} statt 0o600. "
            "Die Token sind gespeichert, aber die Datei ist zu offen. "
            f"Bitte von Hand korrigieren: chmod 600 {pfad}"
        )


def env_datei_aktualisieren(pfad: Path, updates: dict) -> None:
    inhalt = pfad.read_text(encoding="utf-8") if pfad.exists() else ""
    neuer_inhalt = env_zeilen_ersetzen(inhalt, updates)
    # Erst anlegen und einschraenken, dann schreiben - sonst stuende der
    # Token kurz in einer Datei mit den Standardrechten der umask.
    if not pfad.exists():
        pfad.touch(mode=0o600)
    pfad.chmod(0o600)
    pfad.write_text(neuer_inhalt, encoding="utf-8")
    rechte_pruefen(pfad)


def _tokens_speichern(daten: dict) -> str:
    gueltig_bis = ablaufzeitpunkt_berechnen(daten["expiresIn"])
    env_datei_aktualisieren(
        ENV_PFAD,
        {
            "CTRADER_ACCESS_TOKEN": daten["accessToken"],
            "CTRADER_REFRESH_TOKEN": daten["refreshToken"],
            "CTRADER_TOKEN_EXPIRES_AT": gueltig_bis,
        },
    )
    return gueltig_bis


def erstautorisierung_ausfuehren() -> None:
    werte = env_werte_laden()
    client_id = pflichtfeld(werte, "CTRADER_CLIENT_ID")
    client_secret = pflichtfeld(werte, "CTRADER_CLIENT_SECRET")
    redirect_uri = pflichtfeld(werte, "CTRADER_REDIRECT_URI")

    url = autorisierungs_url_bauen(client_id, redirect_uri)
    print("Autorisierungs-URL im Browser oeffnen und Zugriff erlauben:")
    print(url)
    print()

    eingabe = input(
        "Danach die komplette Ziel-URL (oder nur den Code) einfuegen: "
    )
    code = code_aus_eingabe_extrahieren(eingabe)

    daten = token_gegen_code_tauschen(client_id, client_secret, redirect_uri, code)
    gueltig_bis = _tokens_speichern(daten)
    print(f"Access-Token gespeichert, gueltig bis {gueltig_bis}.")


def refresh_ausfuehren() -> None:
    werte = env_werte_laden()
    client_id = pflichtfeld(werte, "CTRADER_CLIENT_ID")
    client_secret = pflichtfeld(werte, "CTRADER_CLIENT_SECRET")
    refresh_token = werte.get("CTRADER_REFRESH_TOKEN", "")
    if not refresh_token:
        raise OAuthFehler(
            "Kein gespeicherter Refresh-Token gefunden. "
            "Zuerst einmalig ohne Argument ausfuehren."
        )

    daten = token_erneuern(client_id, client_secret, refresh_token)
    gueltig_bis = _tokens_speichern(daten)
    print(f"Access-Token gespeichert, gueltig bis {gueltig_bis}.")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="cTrader-OAuth-Token holen oder erneuern"
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Bestehenden Refresh-Token gegen ein neues Token einloesen",
    )
    args = parser.parse_args()

    try:
        if args.refresh:
            refresh_ausfuehren()
        else:
            erstautorisierung_ausfuehren()
        return 0
    except OAuthFehler as exc:
        print(f"Fehler: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nAbgebrochen.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
