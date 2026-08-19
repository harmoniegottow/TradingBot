"""
strategien/bullish_engulfing.py — Baustein 3: Umschliessende Kerze im Aufwaertstrend.

Ein KERZENMUSTER (anderer Signaltyp als die beiden Indikator-Strategien).

Signal-Logik (Bullish Engulfing):
  Vorletzte Kerze faellt (rot: Schluss < Eroeffnung).
  Letzte Kerze steigt (gruen: Schluss > Eroeffnung) UND ihr Koerper
  "umschliesst" den der Vorkerze (Eroeffnung <= vorheriger Schluss,
  Schluss >= vorherige Eroeffnung).
  Zusatzfilter: nur handeln, wenn der Kurs ueber der Trend-EMA liegt
  (kein Gegentrend-Handel). Stop unter dem Tief der Signalkerze, Ziel 2:1.
"""
from __future__ import annotations

from backtesting import Strategy

from strategien.indikatoren import ema


class BullishEngulfing(Strategy):
    trend_len = 150
    rr_ratio = 2.0

    def init(self):
        self.ema_trend = self.I(ema, self.data.Close, self.trend_len)

    def next(self):
        if self.position:
            return
        # Zwei abgeschlossene Kerzen noetig
        o1, c1 = self.data.Open[-2], self.data.Close[-2]   # Vorkerze
        o0, c0 = self.data.Open[-1], self.data.Close[-1]   # Signalkerze
        tief0 = self.data.Low[-1]
        kurs = c0

        rot_davor = c1 < o1
        gruen_jetzt = c0 > o0
        umschliesst = (o0 <= c1) and (c0 >= o1)
        im_aufwaertstrend = kurs > self.ema_trend[-1]

        if not (rot_davor and gruen_jetzt and umschliesst and im_aufwaertstrend):
            return

        stop_dist = kurs - tief0
        if not (stop_dist > 0):
            return
        self.buy(size=0.1, sl=tief0, tp=kurs + stop_dist * self.rr_ratio)
