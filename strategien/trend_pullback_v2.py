"""
strategien/trend_pullback_v2.py — David-V2-Variante des Trend-Pullback.

Unterschiede zur bestehenden TrendPullback-Klasse (bewusst als EIGENER
Baustein, damit das Original vergleichbar bleibt):
  1. Long UND Short (Short gespiegelt ueber 100 - rsi_oversold)
  2. Neutralzone um die Trend-EMA (trend_buffer_atr * ATR) — dicht an der
     EMA entscheidet Rauschen ueber die Richtung, dort wird nicht gehandelt
  3. EMA200 statt EMA150, ATR-Stop 1.5 statt 2.0

Damit laesst sich messen, ob die drei Neuerungen des fremden Bots
tatsaechlich etwas bringen — statt es zu glauben.
"""
from __future__ import annotations

from backtesting import Strategy

from strategien.indikatoren import ema, rsi, atr
from strategien.zeitrahmen import (
    ungeprueft,
    zeitrahmen_pruefen,
)

# Fuer welchen Zeitrahmen die Parameter gemeint sind.
ZEITRAHMEN = ungeprueft(
    "ungeprueft: laeuft im Beobachter auf H1 (EURUSD, USDJPY) und H4 (CHFJPY, XAUUSD) und wurde in pruefe_v2.py auf beiden gelaufen. Laut beobachter.py hat nur die Divergenz den Pruefstand bestanden, also gibt es keinen Beleg fuer einen Zeitrahmen")


class TrendPullbackV2(Strategy):
    trend_len = 200
    rsi_len = 14
    rsi_oversold = 35
    atr_len = 14
    atr_stop_mult = 1.5
    rr_ratio = 2.0
    trend_buffer_atr = 0.25
    trade_long = True
    trade_short = True

    def init(self):
        # Bricht ab, wenn die Daten nicht zu ZEITRAHMEN passen.
        zeitrahmen_pruefen(self.data.index, ZEITRAHMEN,
                           type(self).__name__)
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
        ema_jetzt = self.ema_trend[-1]
        atr_jetzt = float(self.atr_wert[-1])
        if not (atr_jetzt > 0):
            return

        puffer = atr_jetzt * self.trend_buffer_atr
        stop_dist = atr_jetzt * self.atr_stop_mult
        if not (stop_dist > 0):
            return

        rsi_jetzt = self.rsi_wert[-1]
        rsi_vor = self.rsi_wert[-2]
        ueberkauft = 100.0 - self.rsi_oversold

        if kurs > ema_jetzt + puffer:
            if not self.trade_long:
                return
            if rsi_vor <= self.rsi_oversold < rsi_jetzt:
                self.buy(size=0.1, sl=kurs - stop_dist,
                         tp=kurs + stop_dist * self.rr_ratio)
        elif kurs < ema_jetzt - puffer:
            if not self.trade_short:
                return
            if rsi_vor >= ueberkauft > rsi_jetzt:
                self.sell(size=0.1, sl=kurs + stop_dist,
                          tp=kurs - stop_dist * self.rr_ratio)
