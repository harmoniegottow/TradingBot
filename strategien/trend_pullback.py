"""
strategien/trend_pullback.py — Baustein 1: Trend-Pullback (EMA + RSI + ATR).

Signal-Logik (aus beispiel-mt5-bot/strategy.py, broker-neutral):
  Long, wenn Schlusskurs ueber EMA(TREND_LEN) UND RSI(RSI_LEN) von unten ueber
  RSI_OVERSOLD kreuzt. Stop = ATR(ATR_LEN) * ATR_STOP_MULT, Ziel = Stop * RR.
"""
from __future__ import annotations

from backtesting import Strategy

from strategien.indikatoren import ema, rsi, atr


class TrendPullback(Strategy):
    trend_len = 150
    rsi_len = 14
    rsi_oversold = 35
    atr_len = 14
    atr_stop_mult = 2.0
    rr_ratio = 2.0

    def init(self):
        preis = self.data.Close
        self.ema_trend = self.I(ema, preis, self.trend_len)
        self.rsi_wert = self.I(rsi, preis, self.rsi_len)
        self.atr_wert = self.I(
            atr, self.data.High, self.data.Low, self.data.Close, self.atr_len
        )

    def next(self):
        if self.position:
            return
        kurs = self.data.Close[-1]
        up_trend = kurs > self.ema_trend[-1]
        cross_up = (
            self.rsi_wert[-1] > self.rsi_oversold
            and self.rsi_wert[-2] <= self.rsi_oversold
        )
        if not (up_trend and cross_up):
            return
        stop_dist = float(self.atr_wert[-1]) * self.atr_stop_mult
        if not (stop_dist > 0):
            return
        self.buy(size=0.1, sl=kurs - stop_dist, tp=kurs + stop_dist * self.rr_ratio)
