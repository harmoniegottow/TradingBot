"""
strategien/ma_kreuzung.py — Baustein 2: Kreuzung zweier gleitender Durchschnitte.

Dient als EINFACHER VERGLEICHSMASSSTAB. Wenn eine komplexere Strategie diese
simple Regel nicht schlaegt, lohnt der Mehraufwand nicht.

Signal-Logik:
  Kurzer gleitender Durchschnitt kreuzt langen von unten nach oben -> Long.
  Position wird geschlossen, wenn er von oben nach unten zurueckkreuzt.
"""
from __future__ import annotations

from backtesting import Strategy
from backtesting.lib import crossover

from strategien.indikatoren import sma


class MaKreuzung(Strategy):
    kurz = 20
    lang = 50

    def init(self):
        preis = self.data.Close
        self.ma_kurz = self.I(sma, preis, self.kurz)
        self.ma_lang = self.I(sma, preis, self.lang)

    def next(self):
        if crossover(self.ma_kurz, self.ma_lang):
            self.position.close()
            self.buy(size=0.1)
        elif crossover(self.ma_lang, self.ma_kurz):
            self.position.close()
