#!/usr/bin/env python3
"""ausfuehrung.py - Auswertung von Orderausfuehrungen. Ohne Netzwerk.

Hier steht, was nach dem Absenden einer Order passiert: Auftragskennungen,
Einordnung der Ausfuehrungsmeldungen, die Entscheidung nach einem
Zeitablauf, Preisabweichung und das Orderprotokoll.

Wie risiko.py netzwerkfrei - kein Protobuf, kein Twisted. Das Uebersetzen
aus dem Protobuf und das Warten auf Meldungen liegen in handel.py.
test_risiko_grenze.py sichert die Grenze fuer beide Module ab.
"""
from __future__ import annotations

import json
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from risiko import LABEL_PRAEFIX, WURZEL, Bestand, Handelsfehler, label_bauen

LAGE_ANGENOMMEN = "angenommen"


LAGE_AUSGEFUEHRT = "ausgefuehrt"


LAGE_TEILWEISE = "teilweise ausgefuehrt"


LAGE_ABGELEHNT = "abgelehnt"


LAGE_STORNIERT = "storniert"


LAGE_ABGELAUFEN = "abgelaufen"


LAGE_FREMD = "fremde Order"


LAGE_UNBEKANNT = "unbekannte Meldung"


LAGE_OHNE_ANTWORT = "keine Antwort"


PROTOKOLL_DATEI = WURZEL / "orders-protokoll.jsonl"


AUSFUEHRUNG_TIMEOUT = 20


KENNUNG_ZUFALL_BYTES = 4


@dataclass(frozen=True)
class Ausfuehrungsmeldung:
    """Das, was aus einem ProtoOAExecutionEvent fuer uns zaehlt.

    Bewusst ein eigener, einfacher Datensatz: So bleibt die Auswertung hier
    netzwerkfrei und laesst sich mit nachgebildeten Meldungen pruefen. Das
    Uebersetzen aus dem Protobuf passiert in handel.py.
    """

    typ: str
    kennung: str = ""
    label: str = ""
    fehlercode: str = ""
    volumen_angefordert: int = 0
    volumen_ausgefuehrt: int = 0
    ausfuehrungspreis: Decimal | None = None
    positions_id: int = 0


@dataclass(frozen=True)
class Ausfuehrungsbefund:
    """Wie die Order steht - und ob weiter gewartet werden muss."""

    lage: str
    endgueltig: bool
    erfolgreich: bool
    text: str


@dataclass(frozen=True)
class Bestandsbefund:
    """Was die Bestandsaufnahme zu einer Auftragskennung findet."""

    kennung: str
    positionen: tuple
    orders: tuple

    @property
    def anzahl(self) -> int:
        return len(self.positionen)

    @property
    def genau_eine(self) -> bool:
        return self.anzahl == 1


def auftragskennung_bauen(symbol: str, jetzt: datetime = None,
                          zufall: str = None) -> str:
    """Eindeutige Kennung je Order - dieselbe fuer label und clientOrderId.

    Warum beides dieselbe Zeichenkette: Nach einem Zeitablauf muss sich zu
    einer Kennung eine POSITION finden lassen. Positionen tragen aber nur
    tradeData.label, Orders nur clientOrderId. Waeren es zwei verschiedene
    Werte, liesse sich genau die Pruefung nicht durchfuehren, auf die es
    beim Zeitablauf ankommt.

    Der Zufallsteil ist noetig, weil der Zeitstempel nur sekundengenau ist -
    zwei Orders in derselben Sekunde bekaemen sonst dieselbe Kennung.
    """
    grundlage = label_bauen(symbol, jetzt)
    return f"{grundlage}-{zufall or secrets.token_hex(KENNUNG_ZUFALL_BYTES)}"


def gehoert_uns(kennung: str) -> bool:
    return kennung.startswith(LABEL_PRAEFIX)


def meldung_einordnen(meldung: Ausfuehrungsmeldung,
                      erwartete_kennung: str) -> Ausfuehrungsbefund:
    """Ausfuehrungsmeldung einordnen. Ausbleibender Fehler ist KEINE Zusage.

    Jeder Ausfuehrungstyp wird ausdruecklich behandelt. Eine unbekannte
    Meldung gilt nicht als Erfolg, sondern als unbekannt - und beendet das
    Warten nicht.
    """
    if meldung.kennung and meldung.kennung != erwartete_kennung:
        return Ausfuehrungsbefund(
            LAGE_FREMD, False, False,
            f"Meldung betrifft {meldung.kennung}, erwartet wird"
            f" {erwartete_kennung} - wird uebergangen.")

    fehlend = (meldung.volumen_angefordert - meldung.volumen_ausgefuehrt)
    if meldung.typ == "ORDER_ACCEPTED":
        return Ausfuehrungsbefund(
            LAGE_ANGENOMMEN, False, False,
            "Order angenommen. Das ist noch keine Ausfuehrung - es wird"
            " weiter auf die Fuellung gewartet.")
    if meldung.typ == "ORDER_FILLED":
        if meldung.volumen_angefordert and fehlend > 0:
            return Ausfuehrungsbefund(
                LAGE_TEILWEISE, True, False,
                f"Order abgeschlossen, aber nur {meldung.volumen_ausgefuehrt}"
                f" von {meldung.volumen_angefordert} ausgefuehrt"
                f" ({fehlend} offen geblieben).")
        return Ausfuehrungsbefund(
            LAGE_AUSGEFUEHRT, True, True,
            f"Order vollstaendig ausgefuehrt: {meldung.volumen_ausgefuehrt}"
            f" zu {meldung.ausfuehrungspreis}.")
    if meldung.typ == "ORDER_PARTIAL_FILL":
        return Ausfuehrungsbefund(
            LAGE_TEILWEISE, False, False,
            f"Teilausfuehrung: {meldung.volumen_ausgefuehrt} von"
            f" {meldung.volumen_angefordert}. Der Rest steht noch aus.")
    if meldung.typ == "ORDER_REJECTED":
        return Ausfuehrungsbefund(
            LAGE_ABGELEHNT, True, False,
            f"Order abgelehnt: {meldung.fehlercode or 'ohne Fehlercode'}.")
    if meldung.typ == "ORDER_CANCELLED":
        return Ausfuehrungsbefund(
            LAGE_STORNIERT, True, False, "Order storniert.")
    if meldung.typ == "ORDER_EXPIRED":
        return Ausfuehrungsbefund(
            LAGE_ABGELAUFEN, True, False, "Order abgelaufen.")
    return Ausfuehrungsbefund(
        LAGE_UNBEKANNT, False, False,
        f"Unbekannter Ausfuehrungstyp '{meldung.typ}' - gilt NICHT als"
        " Bestaetigung.")


def bestand_befund(bestand: Bestand, kennung: str) -> Bestandsbefund:
    """Sucht Positionen und Orders zu einer Auftragskennung."""
    positionen = tuple(p for p in bestand.positionen
                       if p.tradeData.label == kennung)
    orders = tuple(o for o in bestand.orders
                   if getattr(o, "clientOrderId", "") == kennung)
    return Bestandsbefund(kennung, positionen, orders)


def nach_zeitablauf_entscheiden(befund: Bestandsbefund) -> Ausfuehrungsbefund:
    """Was nach ausbleibender Bestaetigung gilt - NIEMALS nachsenden.

    Aus einer Order werden zwei Positionen, wenn man bei Unklarheit
    wiederholt. Deshalb wird hier nachgesehen und entschieden, nie erneut
    gesendet. Diese Funktion kennt kein Ergebnis, das zu einem zweiten
    Versand fuehrt.
    """
    if befund.anzahl > 1:
        return Ausfuehrungsbefund(
            LAGE_UNBEKANNT, True, False,
            f"ACHTUNG: {befund.anzahl} Positionen tragen die Kennung"
            f" {befund.kennung}. Von Hand nachsehen, nichts senden.")
    if befund.genau_eine:
        return Ausfuehrungsbefund(
            LAGE_AUSGEFUEHRT, True, True,
            f"Keine Bestaetigung erhalten, aber die Bestandsaufnahme zeigt"
            f" genau eine Position mit der Kennung {befund.kennung}. Die"
            " Order ist angekommen. NICHT wiederholen.")
    if befund.orders:
        return Ausfuehrungsbefund(
            LAGE_ANGENOMMEN, True, False,
            f"Keine Bestaetigung erhalten. Die Order {befund.kennung} liegt"
            " noch als offene Order beim Broker. Abwarten, nicht wiederholen.")
    return Ausfuehrungsbefund(
        LAGE_OHNE_ANTWORT, True, False,
        f"Keine Bestaetigung und keine Spur von {befund.kennung} im Bestand."
        " Die Order ist vermutlich nicht angekommen. Sie wird trotzdem NICHT"
        " wiederholt - erst von Hand nachsehen.")


def preisabweichung(erwartet: Decimal, tatsaechlich: Decimal) -> tuple:
    """Abweichung des Ausfuehrungspreises, absolut und in Prozent."""
    abstand = tatsaechlich - erwartet
    anteil = (abstand / erwartet * Decimal(100)) if erwartet else Decimal(0)
    richtung = "schlechter" if abstand > 0 else "besser"
    return abstand, anteil, (
        f"Ausfuehrung zu {tatsaechlich} statt erwarteter {erwartet}:"
        f" {abstand:+.5f} ({anteil:+.4f} %, {richtung} beim Kauf)")


def protokoll_eintrag(art: str, inhalt, zeit: datetime = None) -> dict:
    """Ein Protokolleintrag mit Zeitstempel in UTC."""
    zeit = zeit or datetime.now(timezone.utc)
    if zeit.tzinfo is None:
        raise Handelsfehler("Protokollzeit ohne Zeitzone - UTC ist verlangt.")
    return {"zeit": zeit.astimezone(timezone.utc).isoformat(),
            "art": art, "inhalt": inhalt}


def protokoll_schreiben(eintrag: dict, pfad: Path = None) -> None:
    """Haengt einen Eintrag an. Eine Zeile JSON je Vorgang.

    Grundlage fuer Fehlersuche und Steuer - deshalb vollstaendig und
    unveraenderlich fortgeschrieben, nie ueberschrieben.

    Der Pfad wird erst beim Aufruf aufgeloest, nicht beim Laden des Moduls -
    sonst liesse er sich in Tests nicht umlenken und jeder Testlauf schriebe
    in das echte Protokoll.
    """
    pfad = pfad or PROTOKOLL_DATEI
    pfad.parent.mkdir(parents=True, exist_ok=True)
    with pfad.open("a", encoding="utf-8") as datei:
        datei.write(json.dumps(eintrag, ensure_ascii=False, default=str) + "\n")