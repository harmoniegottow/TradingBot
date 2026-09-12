#!/usr/bin/env python3
"""risiko.py - Risikorechnung fuer den Handel. Ohne Netzwerk.

Hier steht ausschliesslich reine Rechnung: Positionsgroessen, Risikobasis,
Sperren, Kursalter, Waehrungsumrechnung. Kein Protobuf, keine Verbindung,
kein Twisted - deshalb laesst sich alles ohne Broker pruefen.

Diese Grenze ist keine Stilfrage, sondern der Grund, warum die Tests ohne
Konto laufen. test_risiko.py sichert sie ab: Ein Import von
ctrader_open_api oder twisted - auch ueber Umwege - laesst den Test
fehlschlagen.

Die Verbindung und alles Protobuf liegen in handel.py.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from decimal import ROUND_DOWN, ROUND_UP, Decimal
from pathlib import Path

WURZEL = Path(__file__).resolve().parent


MODUS_TROCKENLAUF = "trockenlauf"


MODUS_SENDEN = "senden"


SIMULATIONSKAPITAL = Decimal("1000")


RISIKO_PROZENT = Decimal("0.5")


MAX_OFFENE_POSITIONEN = 3


TAGESVERLUST_GRENZE_PROZENT = Decimal("3")


NOT_AUS_DATEI = WURZEL / "NOT-AUS"


VOLUMEN_JE_EINHEIT = Decimal(100)


LABEL_PRAEFIX = "hermes"


STANDARD_GELD_STELLEN = 2


KURS_RUECKBLICK = {
    MODUS_TROCKENLAUF: timedelta(days=4),
    MODUS_SENDEN: timedelta(hours=2),
}


MAX_KURSALTER_SENDEN = timedelta(minutes=15)


MARKT_GESCHLOSSEN_AB = timedelta(hours=1)


WOCHENTAGE = ("Mo", "Di", "Mi", "Do", "Fr", "Sa", "So")


class Handelsfehler(Exception):
    """Fachlicher Fehler in der Order-Schicht."""


@dataclass(frozen=True)
class Symbolgrenzen:
    """Volumengrenzen eines Symbols, wie der Broker sie meldet."""

    symbol_id: int
    name: str
    min_volumen: int
    max_volumen: int
    schritt_volumen: int
    lot_groesse: int
    stellen: int

    @classmethod
    def aus_protobuf(cls, symbol, name: str) -> "Symbolgrenzen":
        return cls(
            symbol_id=symbol.symbolId, name=name,
            min_volumen=symbol.minVolume, max_volumen=symbol.maxVolume,
            schritt_volumen=symbol.stepVolume, lot_groesse=symbol.lotSize,
            stellen=symbol.digits,
        )


@dataclass(frozen=True)
class Volumenentscheid:
    """Ergebnis der Groessenrechnung - angenommen oder mit Begruendung nicht."""

    angenommen: bool
    volumen: int
    berechnetes_volumen: int
    einheiten: Decimal
    risiko_betrag: Decimal
    tatsaechliches_risiko: Decimal
    begruendung: str

    @property
    def risikofaktor(self) -> Decimal:
        """Um welchen Faktor das kleinste Volumen ueber der Vorgabe liegt."""
        if self.risiko_betrag <= 0:
            return Decimal(0)
        return self.tatsaechliches_risiko / self.risiko_betrag


@dataclass(frozen=True)
class Bestand:
    """Was beim Start schon offen ist. Ohne das oeffnet ein Neustart doppelt."""

    positionen: tuple
    orders: tuple

    @property
    def anzahl_positionen(self) -> int:
        return len(self.positionen)

    def labels(self) -> set:
        return {p.tradeData.label for p in self.positionen
                if p.tradeData.label}

    def eigene(self) -> tuple:
        return tuple(p for p in self.positionen
                     if p.tradeData.label.startswith(LABEL_PRAEFIX))


@dataclass(frozen=True)
class Tagesergebnis:
    """Ergebnis des laufenden Tages - geschlossen UND offen.

    Beides zusammen, mit Absicht: Eine Grenze, die nur geschlossene Trades
    zaehlt, laesst einen laufenden Verlust beliebig gross werden. Man muesste
    die Position nur offen lassen, und die Sperre bliebe stumm.
    """

    realisiert: Decimal
    unrealisiert: Decimal
    anzahl_deals: int
    anzahl_positionen: int

    @property
    def gesamt(self) -> Decimal:
        return self.realisiert + self.unrealisiert

    def __str__(self) -> str:
        return (f"realisiert {self.realisiert:.2f} ({self.anzahl_deals} Deals)"
                f" + unrealisiert {self.unrealisiert:.2f}"
                f" ({self.anzahl_positionen} offene) = {self.gesamt:.2f}")


@dataclass(frozen=True)
class Kursstand:
    """Ein Kurs mit seinem Alter - das Alter gehoert immer dazu.

    Ein Kurs ohne Zeitstempel ist im Handel wertlos: Am Montagmorgen sieht
    ein Freitagskurs genauso aus wie ein aktueller.
    """

    symbol: str
    wert: Decimal
    zeit: datetime
    alter: timedelta

    def alter_text(self) -> str:
        stunden = self.alter.total_seconds() / 3600
        if stunden < 1.5:
            return f"{int(self.alter.total_seconds() // 60)} Minuten alt"
        if stunden < 48:
            return f"{int(stunden)} Stunden alt"
        return f"{int(stunden // 24)} Tage alt"

    def __str__(self) -> str:
        tag = WOCHENTAGE[self.zeit.weekday()]
        zusatz = (" - Markt geschlossen"
                  if self.alter > MARKT_GESCHLOSSEN_AB else "")
        return (f"Kurs {self.symbol} {self.wert} (Stand {tag}"
                f" {self.zeit:%H:%M} UTC, {self.alter_text()}{zusatz})")


@dataclass(frozen=True)
class Umrechnung:
    """Faktor von der Notierungswaehrung des Symbols in die Kontowaehrung."""

    faktor: Decimal
    beschreibung: str


@dataclass(frozen=True)
class Kapitalbasis:
    """Eigenkapital beim Broker und die daraus abgeleitete Risikobasis."""

    eigenkapital: Decimal
    risikobasis: Decimal
    waehrung: str
    konto_ist_live: bool
    kappe: Decimal | None

    @property
    def gekappt(self) -> bool:
        return self.risikobasis < self.eigenkapital

    def zeilen(self) -> str:
        konto = "Live" if self.konto_ist_live else "Demo"
        if self.konto_ist_live:
            hinweis = f"[{konto}, Simulationskappe wirkungslos]"
        elif self.gekappt:
            hinweis = f"[{konto}, Simulationskappe aktiv]"
        elif self.kappe is not None:
            hinweis = (f"[{konto}, Kappe {self.kappe:.2f} {self.waehrung}"
                       " nicht wirksam]")
        else:
            hinweis = f"[{konto}, keine Kappe gesetzt]"
        beschriftung = "Risikobasis (gekappt):" if self.gekappt else "Risikobasis:"
        return (f"Eigenkapital (Broker): {self.eigenkapital:.2f}"
                f" {self.waehrung}\n"
                f"{beschriftung:<23}{self.risikobasis:.2f}"
                f" {self.waehrung}  {hinweis}")


@dataclass(frozen=True)
class Kapitalstand:
    """Ein Kapitalbetrag, mit dem gerechnet wird - und ob er massgeblich ist.

    ACHTUNG, nicht verdrehen: Massgeblich ist die RISIKOBASIS, nicht das
    volle Eigenkapital. Das Eigenkapital steht nur zur Anzeige daneben, damit
    der Unterschied sichtbar bleibt - auf dem Demokonto mit 50.000 kaeme eine
    Position zustande, mit der gekappten Basis von 1.000 nicht.
    """

    name: str
    betrag: Decimal
    waehrung: str
    massgeblich: bool


@dataclass(frozen=True)
class Ordervorschlag:
    """Eine fertige, noch nicht gesendete Order."""

    symbol: str
    symbol_id: int
    seite: str
    volumen: int
    einstieg: Decimal
    stop: Decimal
    ziel: Decimal
    label: str
    begruendung: str
    entscheid: Volumenentscheid


def auf_schritt_abrunden(volumen: Decimal, schritt: int) -> int:
    """Immer ABrunden - aufrunden wuerde das Risiko ueberschreiten."""
    if schritt <= 0:
        raise Handelsfehler(f"Ungueltiger stepVolume: {schritt}")
    schritte = (volumen / Decimal(schritt)).to_integral_value(rounding=ROUND_DOWN)
    return int(schritte * Decimal(schritt))


def volumen_berechnen(
    kapital: Decimal,
    risiko_prozent: Decimal,
    stop_abstand: Decimal,
    grenzen: Symbolgrenzen,
    umrechnung: Decimal,
) -> Volumenentscheid:
    """Positionsgroesse aus Kapital, Risiko und Stop-Abstand.

    `umrechnung` rechnet den Kursabstand von der Notierungswaehrung des
    Symbols in die Kontowaehrung um. Der Wert ist PFLICHT und hat bewusst
    keine Vorgabe: Ein stillschweigendes "mal eins" waere bei einem
    EUR-Konto und einem in USD notierten Symbol um rund ein Zehntel daneben,
    ohne dass es jemand bemerkt.

    Alles in Decimal. Mit Fliesskomma entstehen bei Volumenschritten
    Rundungsreste, die genau an der Mindestgrenze zum Ausschlag fuehren.
    """
    if umrechnung <= 0:
        return Volumenentscheid(
            False, 0, 0, Decimal(0), Decimal(0), Decimal(0),
            f"Abgelehnt: Umrechnungsfaktor {umrechnung} ist unbrauchbar."
            " Ohne gesicherten Kurs wird keine Groesse berechnet.",
        )
    if stop_abstand <= 0:
        return Volumenentscheid(
            False, 0, 0, Decimal(0), Decimal(0), Decimal(0),
            f"Stop-Abstand {stop_abstand} ist nicht positiv - keine Groesse"
            " berechenbar.",
        )

    risiko_betrag = kapital * risiko_prozent / Decimal(100)
    verlust_je_einheit = stop_abstand * umrechnung
    einheiten = risiko_betrag / verlust_je_einheit
    roh = einheiten * VOLUMEN_JE_EINHEIT
    volumen = auf_schritt_abrunden(roh, grenzen.schritt_volumen)

    if volumen < grenzen.min_volumen:
        kleinstes_risiko = (Decimal(grenzen.min_volumen) / VOLUMEN_JE_EINHEIT
                            * verlust_je_einheit)
        # Zur Anzeige der UNGERUNDETE Wert: Auf den Schritt abgerundet waere
        # er hier null, und "Volumen 0" sagt nichts darueber, wie weit es
        # danebenlag. "Volumen 12 gegen Mindestvolumen 100" sagt es.
        return Volumenentscheid(
            False, 0, int(roh), einheiten, risiko_betrag, kleinstes_risiko,
            f"Abgelehnt: Errechnetes Volumen {volumen} liegt unter dem"
            f" Mindestvolumen {grenzen.min_volumen}. Schon die kleinste"
            f" Position riskiert {kleinstes_risiko:.2f} statt der erlaubten"
            f" {risiko_betrag:.2f}. Mit diesem Kapital ist {grenzen.name}"
            " bei diesem Stop nicht handelbar.",
        )

    gedeckelt = ""
    if volumen > grenzen.max_volumen:
        volumen = auf_schritt_abrunden(
            Decimal(grenzen.max_volumen), grenzen.schritt_volumen)
        gedeckelt = (f" Auf das Hoechstvolumen {grenzen.max_volumen} gedeckelt"
                     " - das Risiko liegt dadurch UNTER der Vorgabe.")

    tatsaechlich = Decimal(volumen) / VOLUMEN_JE_EINHEIT * verlust_je_einheit
    return Volumenentscheid(
        True, volumen, volumen, einheiten, risiko_betrag, tatsaechlich,
        f"Angenommen: {volumen} ({Decimal(volumen) / Decimal(grenzen.lot_groesse)}"
        f" Lot), Risiko {tatsaechlich:.2f} von erlaubten"
        f" {risiko_betrag:.2f}.{gedeckelt}",
    )


def tagesbeginn_utc(jetzt: datetime = None) -> datetime:
    """Beginn des Handelstages: 00:00 UTC. Ausdruecklich NICHT Serverzeit.

    Der Broker-Server laeuft auf UTC+2 bzw. UTC+3 (siehe
    data-mt5/ACHTUNG-Zeitstempel.md), die Ortszeit auf wieder etwas anderem.
    Wer die Grenze an eine dieser Zeiten haengt, verschiebt sie zweimal im
    Jahr - und im Winter 2017/18 hat der Broker eine Umstellung schlicht
    ausgelassen. Deshalb hier eine feste, nachpruefbare Grenze: 00:00 UTC.
    """
    jetzt = jetzt or datetime.now(timezone.utc)
    if jetzt.tzinfo is None:
        raise Handelsfehler("Zeitpunkt ohne Zeitzone - UTC ist verlangt.")
    return datetime.combine(jetzt.astimezone(timezone.utc).date(),
                            time(0, 0), tzinfo=timezone.utc)


def _geld(rohwert: int, traeger, standard: int = STANDARD_GELD_STELLEN) -> Decimal:
    """Ganzzahlbetrag in einen echten Betrag wandeln, moneyDigits beachtend."""
    stellen = (traeger.moneyDigits if traeger.HasField("moneyDigits")
               else standard)
    return betrag_umrechnen(rohwert, stellen)


def realisiertes_ergebnis(deals) -> tuple[Decimal, int]:
    """Summe der heute geschlossenen Trades, netto.

    Netto heisst: Rohgewinn plus Swap plus Kommission. Die Kommission ist
    negativ - wer sie weglaesst, meldet einen zu kleinen Verlust.
    """
    summe = Decimal(0)
    gezaehlt = 0
    for deal in deals:
        if not deal.HasField("closePositionDetail"):
            continue
        detail = deal.closePositionDetail
        summe += (_geld(detail.grossProfit, detail)
                  + _geld(detail.swap, detail)
                  + _geld(detail.commission, detail))
        gezaehlt += 1
    return summe, gezaehlt


def unrealisiertes_ergebnis(antwort) -> tuple[Decimal, int]:
    """Summe der offenen Positionen, netto.

    netUnrealizedPnL statt grossUnrealizedPnL: Swap und Kommission gehoeren
    zum laufenden Verlust dazu.
    """
    stellen = (antwort.moneyDigits if antwort.HasField("moneyDigits")
               else STANDARD_GELD_STELLEN)
    eintraege = list(antwort.positionUnrealizedPnL)
    summe = sum((betrag_umrechnen(e.netUnrealizedPnL, stellen)
                 for e in eintraege), Decimal(0))
    return summe, len(eintraege)


def eigenkapital_bestimmen(kontostand: Decimal,
                           unrealisiert: Decimal) -> Decimal:
    """Eigenkapital = Kontostand plus unrealisiertes Ergebnis.

    Nicht der Kontostand allein: Der zeigt bei drei tief im Minus stehenden
    Positionen noch den alten Stand. Gerechnet wird mit dem, was das Konto
    heute wert ist.
    """
    return kontostand + unrealisiert


def risikobasis_bestimmen(eigenkapital: Decimal, konto_ist_live: bool,
                          waehrung: str = "",
                          kappe: Decimal | None = SIMULATIONSKAPITAL
                          ) -> Kapitalbasis:
    """Risikobasis aus dem Eigenkapital, auf dem Demokonto gekappt.

    Die Basis kommt IMMER vom Broker. Faellt das Konto, muessen die
    Positionen mitschrumpfen - eine feste Zahl wuerde das Risiko genau dann
    erhoehen, wenn es schlecht laeuft: Nach einem Verlust von der Haelfte
    waere jeder Trade auf einmal doppelt so gross gemessen am verbliebenen
    Kapital.

    Die Kappe greift ausschliesslich, wenn isLive false ist. Auf einem
    Livekonto bleibt sie wirkungslos, auch wenn sie gesetzt ist - so kann
    eine vergessene Testeinstellung im Echtbetrieb keinen Schaden anrichten.
    """
    basis = eigenkapital
    if not konto_ist_live and kappe is not None:
        basis = min(eigenkapital, kappe)
    return Kapitalbasis(eigenkapital, basis, waehrung, konto_ist_live, kappe)


def konversionssymbol_finden(symbole, notierung_id: int, konto_id: int):
    """Sucht ein Symbol, das Notierungs- und Kontowaehrung verbindet.

    Liefert (symbolId, invertieren) oder None. `invertieren` ist wahr, wenn
    das gefundene Symbol die Kontowaehrung als Basis fuehrt (EURUSD fuer
    USD nach EUR) - dann ist der Kehrwert des Kurses gefragt.
    """
    for symbol in symbole:
        if (symbol.baseAssetId == notierung_id
                and symbol.quoteAssetId == konto_id):
            return symbol.symbolId, False
    for symbol in symbole:
        if (symbol.baseAssetId == konto_id
                and symbol.quoteAssetId == notierung_id):
            return symbol.symbolId, True
    return None


def kursalter_pruefen(kurs: Kursstand, modus: str) -> str | None:
    """Ist der Kurs fuer diesen Modus frisch genug? Grund oder None.

    Im Trockenlauf ist jedes Alter zulaessig - es wird nur ausgegeben. Im
    Modus SENDEN ist ein alter Kurs ein Abbruchgrund: Eine Order gegen einen
    Freitagskurs am Montagmorgen geht zum falschen Preis ins Risiko.
    """
    if modus != MODUS_SENDEN:
        return None
    if kurs.alter > MAX_KURSALTER_SENDEN:
        return (f"Kurs fuer {kurs.symbol} ist {kurs.alter_text()}"
                f" (Stand {kurs.zeit:%Y-%m-%d %H:%M} UTC), erlaubt sind im"
                f" Modus '{MODUS_SENDEN}' hoechstens"
                f" {int(MAX_KURSALTER_SENDEN.total_seconds() // 60)} Minuten."
                " Es wird keine Order gebaut.")
    return None


def umrechnungsfaktor(kurs: Decimal, invertieren: bool) -> Decimal:
    if kurs <= 0:
        raise Handelsfehler(f"Unbrauchbarer Kurs fuer die Umrechnung: {kurs}")
    return (Decimal(1) / kurs) if invertieren else kurs


def label_bauen(symbol: str, jetzt: datetime = None) -> str:
    """Eigenes Kennzeichen je Order, damit der Bot nur seine Trades anfasst."""
    jetzt = jetzt or datetime.now(timezone.utc)
    return f"{LABEL_PRAEFIX}-{symbol}-{jetzt:%Y%m%d%H%M%S}"


def sperren_pruefen(bestand: Bestand, tagesergebnis: Tagesergebnis,
                    kapital: Decimal) -> str | None:
    """Gruende, nichts zu eroeffnen. Liefert None, wenn nichts entgegensteht.

    Reihenfolge mit Absicht: Der Not-Aus kommt zuerst, damit er auch dann
    greift, wenn eine andere Pruefung fehlerhaft waere.

    Der Tag beginnt um 00:00 UTC (siehe tagesbeginn_utc), und gezaehlt wird
    das Ergebnis aus geschlossenen UND offenen Positionen.
    """
    if NOT_AUS_DATEI.exists():
        return (f"NOT-AUS: Die Datei {NOT_AUS_DATEI.name} existiert."
                " Es wird nichts eroeffnet. Zum Aufheben die Datei loeschen.")

    offen = bestand.anzahl_positionen
    if offen >= MAX_OFFENE_POSITIONEN:
        return (f"Hoechstzahl erreicht: {offen} offene Positionen,"
                f" erlaubt sind {MAX_OFFENE_POSITIONEN}.")

    grenze = -(kapital * TAGESVERLUST_GRENZE_PROZENT / Decimal(100))
    if tagesergebnis.gesamt <= grenze:
        return (f"Tagesverlustgrenze erreicht: {tagesergebnis} bei"
                f" {kapital:.2f} Kapital (Grenze {grenze:.2f}). Heute wird"
                " nichts mehr eroeffnet. Tagesbeginn ist 00:00 UTC.")
    return None


# Zweiter Risikosatz, der bei einer Ablehnung zum Vergleich genannt wird.
VERGLEICHS_RISIKO = Decimal("1")


def noetiges_kapital(kleinstes_risiko: Decimal,
                     risiko_prozent: Decimal) -> Decimal:
    """Wie viel Kapital die kleinste Position bei diesem Risikosatz braucht.

    Umkehrung der Groessenrechnung: Wenn schon das Mindestvolumen mehr
    riskiert als erlaubt, ist die Frage nicht "wie klein kann die Position
    werden" - sie kann nicht kleiner werden -, sondern "wie viel Kapital
    macht dieses Risiko vertretbar".
    """
    if risiko_prozent <= 0:
        raise Handelsfehler(f"Risikosatz {risiko_prozent} ist nicht positiv.")
    return kleinstes_risiko * Decimal(100) / risiko_prozent


def _aufgerundet(betrag: Decimal) -> Decimal:
    """Auf zwei geltende Ziffern AUFrunden.

    Aufgerundet, nicht gerundet: Die Zahl ist eine Untergrenze, und eine zu
    niedrig genannte Untergrenze fuehrt zur naechsten Ablehnung.
    """
    if betrag <= 0:
        return Decimal(0)
    schritt = Decimal(10) ** (betrag.adjusted() - 1)
    return (betrag / schritt).to_integral_value(rounding=ROUND_UP) * schritt


def _prozent(wert: Decimal) -> str:
    return f"{wert}".replace(".", ",")


def kapitalhinweis(kleinstes_risiko: Decimal, waehrung: str,
                   risiko_prozent: Decimal = RISIKO_PROZENT) -> str:
    """Was eine Ablehnung wegen Mindestvolumen praktisch bedeutet."""
    saetze = [risiko_prozent]
    if VERGLEICHS_RISIKO != risiko_prozent:
        saetze.append(VERGLEICHS_RISIKO)
    teile = [
        f"fuer {_prozent(satz)} % rund"
        f" {_aufgerundet(noetiges_kapital(kleinstes_risiko, satz)):.0f}"
        f" {waehrung}".rstrip()
        for satz in saetze
    ]
    return "Noetig waeren " + ", ".join(teile) + "."


def ablehnungstext(entscheid: Volumenentscheid, grenzen: Symbolgrenzen,
                   waehrung: str = "",
                   risiko_prozent: Decimal = RISIKO_PROZENT) -> str:
    """Einheitlicher Ablehnungstext - im Vergleich wie im Protokoll gleich."""
    if entscheid.berechnetes_volumen >= grenzen.min_volumen:
        return entscheid.begruendung
    return (f"ABGELEHNT, unter Mindestvolumen {grenzen.min_volumen}"
            f" ({entscheid.risikofaktor:.0f}-faches Risiko)."
            f" {kapitalhinweis(entscheid.tatsaechliches_risiko, waehrung, risiko_prozent)}")


def groessen_vergleich(grenzen: Symbolgrenzen, stop_abstand: Decimal,
                       umrechnung: Decimal, staende: tuple,
                       risiko_prozent: Decimal = RISIKO_PROZENT) -> tuple:
    """Rechnet dieselbe Position fuer mehrere Kapitalstaende durch."""
    return tuple(
        (stand, volumen_berechnen(stand.betrag, risiko_prozent, stop_abstand,
                                  grenzen, umrechnung))
        for stand in staende
    )


def vergleich_text(grenzen: Symbolgrenzen, seite: str, stop_abstand: Decimal,
                   notierung: str, vergleich: tuple,
                   risiko_prozent: Decimal = RISIKO_PROZENT) -> str:
    """Beide Kapitalstaende nebeneinander, mit Ergebnis je Stand."""
    richtung = "Long" if seite == "BUY" else "Short"
    prozent = f"{risiko_prozent}".replace(".", ",")
    zeilen = [f"{grenzen.name} {richtung}, Stop {stop_abstand:.2f} {notierung}"]
    breite = max(len(f"{s.betrag:.0f} {s.waehrung}") for s, _ in vergleich)
    for stand, entscheid in vergleich:
        kopf = f"mit {f'{stand.betrag:.0f} {stand.waehrung}':<{breite}} ({prozent} %):"
        if entscheid.angenommen:
            ergebnis = (f"Volumen {entscheid.volumen}  ->  Order wird gebaut"
                        f" (Risiko {entscheid.tatsaechliches_risiko:.2f}"
                        f" {stand.waehrung})")
        elif entscheid.berechnetes_volumen < grenzen.min_volumen:
            ergebnis = (f"Volumen {entscheid.berechnetes_volumen}  ->  "
                        + ablehnungstext(entscheid, grenzen, stand.waehrung,
                                         risiko_prozent))
        else:
            ergebnis = f"ABGELEHNT: {entscheid.begruendung}"
        marke = "  [massgeblich]" if stand.massgeblich else ""
        zeilen.append(f"  {kopf}  {ergebnis}{marke}")
    return "\n".join(zeilen)


def protokollzeile(vorschlag: Ordervorschlag, sperrgrund: str | None,
                   sende_hinweis: str, grenzen: Symbolgrenzen = None,
                   waehrung: str = "",
                   risiko_prozent: Decimal = RISIKO_PROZENT) -> str:
    """Die vollstaendige Order als lesbare Zeile - statt sie zu senden.

    Im Ablehnungsfall dieselbe Darstellung wie im Vergleichsblock: das
    BERECHNETE Volumen mit dem Grund dahinter. Frueher stand hier "Volumen 0"
    und daneben ein Risiko - das las sich, als truege eine Position der
    Groesse null ein Risiko von 34,49.
    """
    entscheid = vorschlag.entscheid
    abgelehnt = not entscheid.angenommen
    zustand = ("NICHT GESENDET" if (abgelehnt or sperrgrund)
               else "WUERDE GESENDET")

    if abgelehnt:
        grund = (ablehnungstext(entscheid, grenzen, waehrung, risiko_prozent)
                 if grenzen is not None else entscheid.begruendung)
        volumen_zeile = f"    Volumen       {entscheid.berechnetes_volumen}  ->  {grund}"
        risiko_zeile = (f"    Risiko        kleinste Position"
                        f" {entscheid.tatsaechliches_risiko:.2f},"
                        f" erlaubt {entscheid.risiko_betrag:.2f}")
    else:
        volumen_zeile = (f"    Volumen       {vorschlag.volumen}"
                         f"  (Einheiten {entscheid.einheiten:.4f})")
        risiko_zeile = (f"    Risiko        {entscheid.tatsaechliches_risiko:.2f}"
                        f" von erlaubten {entscheid.risiko_betrag:.2f}")

    zeilen = [
        f"[TROCKENLAUF] {zustand}  {vorschlag.symbol} {vorschlag.seite}",
        f"    symbolId      {vorschlag.symbol_id}",
        volumen_zeile,
        f"    Einstieg      {vorschlag.einstieg}",
        f"    Stop          {vorschlag.stop}",
        f"    Ziel          {vorschlag.ziel}",
        f"    Label         {vorschlag.label}",
        risiko_zeile,
        f"    Anlass        {vorschlag.begruendung}",
        f"    Senden        {sende_hinweis}",
    ]
    # Nur echte Sperren werden hier genannt. Der Ablehnungsgrund steht schon
    # in der Volumenzeile - zweimal derselbe Satz hilft niemandem.
    if sperrgrund:
        zeilen.append(f"    GESPERRT      {sperrgrund}")
    return "\n".join(zeilen)


def vorschlag_bauen(grenzen: Symbolgrenzen, seite: str, einstieg: Decimal,
                    stop: Decimal, ziel: Decimal, begruendung: str,
                    umrechnung: Decimal, kapital: Decimal,
                    risiko_prozent: Decimal = RISIKO_PROZENT) -> Ordervorschlag:
    entscheid = volumen_berechnen(
        kapital, risiko_prozent, abs(einstieg - stop), grenzen, umrechnung)
    return Ordervorschlag(
        symbol=grenzen.name, symbol_id=grenzen.symbol_id, seite=seite,
        volumen=entscheid.volumen, einstieg=einstieg, stop=stop, ziel=ziel,
        label=label_bauen(grenzen.name), begruendung=begruendung,
        entscheid=entscheid,
    )

def betrag_umrechnen(rohwert: int, stellen: int) -> Decimal:
    """Ganzzahlbetrag in einen echten Betrag wandeln.

    cTrader liefert Geldbetraege als Ganzzahl; moneyDigits sagt, wie viele
    Nachkommastellen darin stecken. Lag frueher in verbindung.py und ist
    hierher gezogen, damit risiko.py ohne Netzwerkmodul auskommt.
    """
    return Decimal(rohwert) / (Decimal(10) ** stellen)
