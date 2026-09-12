"""kosten.py - Handelskosten getrennt nach Art: Spread und Swap.

Bis hierher kannte der Pruefstand nur EINE Zahl: KOSTEN_STANDARD = 2
Basispunkte je Seite. Darin steckte der Spread, und zwar pro Trade. Der
Swap kam gar nicht vor - backtesting.py kennt den Begriff nicht.

Fuer eine Strategie, die Positionen ueber Tage haelt, ist das der groessere
Posten. Gemessen am 12.09.2026: Gold kostet rund 1,87 Basispunkte PRO NACHT.
Beim Median-Trade der Divergenz (vier gewichtete Rollover) sind das gut
7 Basispunkte gegen 4 Basispunkte Pauschale fuer die ganze Runde.

Deshalb hier zwei getrennte Kostenarten. Getrennt, weil es zwei
verschiedene Fragen sind: Ein weiterer Spread trifft haeufige Trades,
ein hoeherer Swap trifft lange Haltedauern.
"""
from __future__ import annotations

from dataclasses import dataclass, replace

import pandas as pd

# Mittwoch. Der Broker meldet swapRollover3Days = 3 = WEDNESDAY; an diesem
# Rollover wird dreifach berechnet, weil das Wochenende mitlaeuft.
# pandas zaehlt Montag als 0, Mittwoch also als 2.
MITTWOCH = 2
# Der Broker meldet swapTime = 1260 Minuten, also 21:00 UTC. Genau dann
# wird umgebucht - nicht um Mitternacht. Bei einem Median von vier
# Rollovern verschiebt eine Naeherung auf Mitternacht das Ergebnis um bis
# zu einem Viertel, deshalb wird hier die echte Stunde gerechnet.
ROLLOVER_STUNDE = 21


@dataclass(frozen=True)
class Swapsatz:
    """Uebernachtkosten eines Symbols, wie der Broker sie meldet.

    Die Saetze stehen in PIPS je Einheit und Nacht (ProtoOASymbol,
    swapCalculationType = PIPS). Negativ heisst Kosten, positiv heisst
    Gutschrift - Shorts auf Metalle bringen derzeit etwas ein.

    Gerechnet wird in float, nicht in Decimal: backtesting.py fuehrt alle
    Betraege als float, und eine Decimal-Fassade davor waere Schein-
    genauigkeit. In der Order-Schicht (risiko.py) gilt weiterhin Decimal.
    """

    symbol: str
    long_pips: float
    short_pips: float
    pip: float
    gemessen: str
    dreifach_am: int = MITTWOCH

    def mal(self, faktor: float) -> "Swapsatz":
        """Skalierte Kopie fuer die Belastungsprobe."""
        return replace(self, long_pips=self.long_pips * faktor,
                       short_pips=self.short_pips * faktor,
                       gemessen=f"{self.gemessen}, x{faktor:g}")

    def je_einheit_und_nacht(self, ist_long: bool) -> float:
        """Betrag je Einheit und Nacht. Negativ = Kosten."""
        pips = self.long_pips if ist_long else self.short_pips
        return pips * self.pip

    def basispunkte(self, kurs: float, ist_long: bool = True) -> float:
        """Kosten je Nacht in Basispunkten des Kurswerts - zum Vergleichen."""
        return abs(self.je_einheit_und_nacht(ist_long)) / kurs * 10_000


# Gemessen am 12.09.2026 ueber ProtoOASymbol am Pepperstone-Demokonto
# (swapCalculationType = PIPS, swapRollover3Days = WEDNESDAY, swapTime
# 21:00 UTC). Kommission ist bei beiden Symbolen null - der Broker rechnet
# ueber den Spread ab.
#
# ACHTUNG: Diese Saetze haengen am Zinsniveau und gelten NICHT rueckwirkend
# fuer zehn Jahre. In der Nullzinsphase waren sie deutlich kleiner. Wer die
# Vergangenheit genau nachrechnen will, braucht historische Saetze - die
# liefert die API nicht.
SWAP_SAETZE = {
    "XAUUSD": Swapsatz("XAUUSD", long_pips=-8.15, short_pips=2.91, pip=0.1,
                       gemessen="ProtoOASymbol am 12.09.2026"),
    "XAGUSD": Swapsatz("XAGUSD", long_pips=-1.66, short_pips=0.49, pip=0.01,
                       gemessen="ProtoOASymbol am 12.09.2026"),
}


def rollover_zeitpunkte(eintritt, austritt,
                        stunde: int = ROLLOVER_STUNDE) -> list:
    """Alle Umbuchungszeitpunkte, die ein Trade tatsaechlich erlebt.

    Der Rollover liegt um 21:00 UTC. Ein Trade, der um 22:00 eingeht und am
    naechsten Tag um 18:00 schliesst, erlebt KEINEN - obwohl er ueber
    Mitternacht lief. Umgekehrt erlebt einer von 20:00 bis 22:00 einen,
    obwohl er nur zwei Stunden dauert.
    """
    erster = eintritt.normalize() + pd.Timedelta(hours=stunde)
    if erster <= eintritt:
        erster += pd.Timedelta(days=1)
    if erster > austritt:
        return []
    return list(pd.date_range(erster, austritt, freq="D"))


def naechte(eintritt, austritt, dreifach_am: int = MITTWOCH,
            stunde: int = ROLLOVER_STUNDE) -> int:
    """Gewichtete Rollover zwischen Ein- und Ausstieg.

    Der Mittwoch-Rollover zaehlt dreifach, weil das Wochenende mitlaeuft.
    """
    return sum(3 if zeitpunkt.weekday() == dreifach_am else 1
               for zeitpunkt in rollover_zeitpunkte(eintritt, austritt, stunde))


def swap_je_trade(trades: pd.DataFrame, satz: Swapsatz) -> pd.Series:
    """Swapbetrag je Trade in Kontowaehrung. Negativ = Kosten.

    Richtungsabhaengig: Longs zahlen swapLong, Shorts swapShort.
    """
    if trades.empty:
        return pd.Series(dtype=float)

    def betrag(zeile) -> float:
        ist_long = zeile["Size"] > 0
        anzahl = naechte(zeile["EntryTime"], zeile["ExitTime"],
                         satz.dreifach_am)
        return (abs(zeile["Size"]) * satz.je_einheit_und_nacht(ist_long)
                * anzahl)

    return trades.apply(betrag, axis=1)


def profitfaktor(gewinne: pd.Series) -> float:
    """Profitfaktor aus einer Reihe von Trade-Ergebnissen."""
    plus = gewinne[gewinne > 0].sum()
    minus = -gewinne[gewinne < 0].sum()
    if minus <= 0:
        return float("inf") if plus > 0 else float("nan")
    return float(plus / minus)
