"""
strategien/__init__.py — Sammelstelle aller Strategie-Bausteine.

Jede Strategie liegt in einer eigenen Datei und stellt EINE Klasse bereit,
die von backtesting.Strategy erbt. So sind alle austauschbar und werden vom
Vergleichsskript (vergleich.py) nach demselben Massstab getestet.

Die REGISTRY unten ist die zentrale Liste: Wer eine neue Strategie baut,
traegt sie hier ein - dann taucht sie automatisch im Vergleich auf.
"""
from strategien.trend_pullback import TrendPullback
from strategien.ma_kreuzung import MaKreuzung
from strategien.bullish_engulfing import BullishEngulfing
from strategien.orb import OpeningRangeBreakout
from strategien.impuls_fifty import ImpulsFifty

# Name (fuer die Tabelle) -> Strategie-Klasse
REGISTRY = {
    "Trend-Pullback": TrendPullback,
    "MA-Kreuzung": MaKreuzung,
    "Bullish-Engulfing": BullishEngulfing,
    "ORB": OpeningRangeBreakout,
    "Impuls-Fifty": ImpulsFifty,
}
