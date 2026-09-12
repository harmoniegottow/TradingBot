"""strategien/zeitrahmen.py - Zu welchem Zeitrahmen gehoeren die Parameter?

Alle Bausteine in strategien/ rechnen in KERZEN, nicht in Zeit: RET_LEN=20,
BAND_LOOKBACK=100, trend_len=150. Was diese Zahlen bedeuten, haengt
vollstaendig am Zeitrahmen der uebergebenen Daten - 100 Kerzen sind auf H4
gut sechzehn Handelstage, auf H1 gut vier, auf M15 einer.

Bis hierher stand der Zeitrahmen nirgends im Baustein. Gab man versehentlich
H1-Daten hinein, lief alles durch, lieferte Zahlen und mass etwas voellig
anderes. Nichts bemerkte es.

Deshalb: Jeder Baustein sagt, wofuer seine Parameter gemeint sind, und beim
Aufruf wird der tatsaechliche Kerzenabstand AUS DEN DATEN gemessen und
dagegen gehalten. Gemessen, nicht aus dem Dateinamen gelesen - ein falsch
benanntes XAUUSD_H_4.csv mit H1-Inhalt muss auffliegen.
"""
from __future__ import annotations

import sys
from collections import Counter
from dataclasses import dataclass
from datetime import timedelta

# Kuerzel wie im Dateinamen -> Kerzenlaenge in Minuten.
MINUTEN = {"M_1": 1, "M_5": 5, "M_15": 15, "M_30": 30,
           "H_1": 60, "H_4": 240, "D_1": 1440, "W_1": 10080}
# So viele Kerzen braucht es mindestens, um den Abstand verlaesslich zu messen.
MIN_KERZEN = 10


class ZeitrahmenFehler(Exception):
    """Die Daten passen nicht zum Zeitrahmen, fuer den der Baustein gilt."""


@dataclass(frozen=True)
class Zeitrahmenangabe:
    """Fuer welchen Zeitrahmen die Parameter eines Bausteins gemeint sind.

    `kuerzel` ist None, solange es keinen Beleg gibt. Dann wird nichts
    geprueft - eine geratene Angabe waere schlimmer als keine, weil sie
    Sicherheit vortaeuscht.
    """

    kuerzel: str | None
    beleg: str

    @property
    def minuten(self) -> int | None:
        return MINUTEN[self.kuerzel] if self.kuerzel else None

    @property
    def belegt(self) -> bool:
        return self.kuerzel is not None

    def __str__(self) -> str:
        return f"{self.kuerzel or 'ungeprueft'} ({self.beleg})"


def ungeprueft(beleg: str) -> Zeitrahmenangabe:
    return Zeitrahmenangabe(None, beleg)


def kuerzel_zu(abstand: timedelta) -> str:
    """Kerzenabstand in ein lesbares Kuerzel wandeln."""
    minuten = int(abstand.total_seconds() // 60)
    for kuerzel, dauer in MINUTEN.items():
        if dauer == minuten:
            return kuerzel
    return f"{minuten} Minuten"


def abstand_messen(index) -> timedelta:
    """Haeufigster Abstand zwischen zwei Kerzen - AUS DEN DATEN.

    Der haeufigste Abstand, nicht der mittlere: Wochenenden und Feiertage
    reissen Luecken, die einen Mittelwert verziehen wuerden. Der Normalfall
    ist dagegen mit Abstand am haeufigsten.
    """
    if len(index) < MIN_KERZEN:
        raise ZeitrahmenFehler(
            f"Nur {len(index)} Kerzen - das reicht nicht, um den Abstand zu"
            f" messen (mindestens {MIN_KERZEN} noetig).")
    abstaende = Counter(b - a for a, b in zip(index, index[1:]))
    return abstaende.most_common(1)[0][0]


def referenz_pruefen(index, angabe: Zeitrahmenangabe,
                     quelle: str = "") -> timedelta | None:
    """Wie zeitrahmen_pruefen, aber fuer eine REFERENZreihe.

    Hier gilt eine andere Regel, und das hat einen Grund: Die Referenz wird
    auf den Index der gehandelten Reihe gelegt (reindex mit ffill). Deren
    Takt bestimmt also die Parameter, nicht der eigene. Eine FEINERE
    Referenz ist damit unschaedlich - es wird ohnehin nur der jeweils letzte
    Kurs auf oder vor dem Zeitpunkt benutzt.

    Eine GROEBERE Referenz ist dagegen ein Fehler: Ein Tageskurs wuerde
    ueber sechs H4-Kerzen hinweg fortgeschrieben, und die Divergenz maesse
    gegen einen tagealten Stand.
    """
    if not angabe.belegt:
        return None

    gemessen = abstand_messen(index)
    erlaubt = timedelta(minutes=angabe.minuten)
    if gemessen <= erlaubt:
        return gemessen

    woher = f"{quelle}: " if quelle else ""
    raise ZeitrahmenFehler(
        f"{woher}Die Referenzreihe hat einen Kerzenabstand von"
        f" {kuerzel_zu(gemessen)} und ist damit GROEBER als die verlangten"
        f" {angabe.kuerzel} ({angabe.beleg}).\n"
        "Ein groeberer Kurs wuerde ueber mehrere Kerzen fortgeschrieben, die"
        " Divergenz maesse dann gegen einen veralteten Stand. Feiner waere"
        " zulaessig, groeber nicht. Abbruch."
    )


def zeitrahmen_pruefen(index, angabe: Zeitrahmenangabe,
                       quelle: str = "") -> timedelta | None:
    """Passen die Daten zum Zeitrahmen des Bausteins? Sonst ABBRUCH.

    Liefert den gemessenen Abstand zurueck. Ist der Baustein ungeprueft,
    wird nichts geprueft und None zurueckgegeben.
    """
    if not angabe.belegt:
        return None

    gemessen = abstand_messen(index)
    erwartet = timedelta(minutes=angabe.minuten)
    if gemessen == erwartet:
        return gemessen

    woher = f"{quelle}: " if quelle else ""
    raise ZeitrahmenFehler(
        f"{woher}Die Daten haben einen Kerzenabstand von"
        f" {kuerzel_zu(gemessen)}, der Baustein ist aber fuer"
        f" {angabe.kuerzel} gemacht ({angabe.beleg}).\n"
        "Der Abstand wurde AUS DEN DATEN gemessen, nicht aus dem Dateinamen -"
        " eine falsch benannte Datei faellt hier auf.\n"
        "Die Parameter zaehlen Kerzen, nicht Zeit: Mit diesen Daten misst der"
        " Baustein etwas anderes als das, was geprueft wurde. Abbruch."
    )


# Vermerk fuer Ausgaben. Steht dort, wo die Zahl auftaucht - nicht nur im
# Quelltext. Eine Kennzahl aus einem ungeprueften Baustein sieht sonst
# genauso belastbar aus wie eine aus dem geprueften.
VERMERK_UNGEPRUEFT = "[Zeitrahmen ungeprueft]"
VERMERK_FEHLT = "[Zeitrahmenangabe fehlt]"


def angabe_von(klasse) -> Zeitrahmenangabe | None:
    """Liest die ZEITRAHMEN-Angabe aus dem Modul einer Strategieklasse."""
    modul = sys.modules.get(getattr(klasse, "__module__", ""))
    return getattr(modul, "ZEITRAHMEN", None) if modul else None


def spaltenwert(angabe: Zeitrahmenangabe | None) -> str:
    """Kurzform fuer eine Tabellenspalte."""
    if angabe is None:
        return "fehlt"
    return angabe.kuerzel if angabe.belegt else "ungeprueft"


def vermerk(angabe: Zeitrahmenangabe | None) -> str:
    """Vermerk fuer eine Ausgabezeile. Leer, wenn der Zeitrahmen belegt ist."""
    if angabe is None:
        return VERMERK_FEHLT
    return "" if angabe.belegt else VERMERK_UNGEPRUEFT
