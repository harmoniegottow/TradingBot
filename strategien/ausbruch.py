"""
strategien/ausbruch.py - Ausbruch in Trendrichtung, eigene Regel fuer Short.

Warum ein eigener Baustein statt der gespiegelten V2-Regel:
Maerkte fallen anders, als sie steigen. Abwaertsbewegungen sind kuerzer,
schneller und schwankungsreicher; Ruecksetzer im Abwaertstrend fallen oft
flach aus, deshalb erreicht der RSI die gespiegelte Zone (65) selten sauber.
Ein Profi handelt im Abwaertstrend eher den Bruch nach unten als den
Ruecksetzer nach oben.

Regel (beide Richtungen gleich gebaut, damit der Vergleich fair ist):
  Trend    Kurs unter EMA200 UND EMA50 unter EMA200  (Long: beides darueber)
  Signal   Schlusskurs bricht das Tief der letzten `kanal_len` Kerzen
           (Long: das Hoch) - Donchian-Kanal, Wert der VORkerze, kein Blick
           in die Zukunft
  Stop     `atr_stop_mult` mal ATR14, Ziel `rr_ratio` mal Stopdistanz

Erstellt am 05.10.2026 fuer die Short-Pruefung (short_pruefung.py).
"""
from __future__ import annotations

import pandas as pd
from backtesting import Strategy

from strategien.indikatoren import atr, ema
from strategien.zeitrahmen import ungeprueft, zeitrahmen_pruefen

ZEITRAHMEN = ungeprueft(
    "ungeprueft: neu am 05.10.2026, auf H1 und H4 gerechnet, noch kein Beleg")


def _tiefst(low, n):
    return pd.Series(low).rolling(n).min().shift(1).to_numpy()


def _hoechst(high, n):
    return pd.Series(high).rolling(n).max().shift(1).to_numpy()


class Ausbruch(Strategy):
    trend_len = 200
    schnell_len = 50
    kanal_len = 20
    atr_len = 14
    atr_stop_mult = 2.0
    rr_ratio = 2.0
    trade_long = False
    trade_short = True

    def init(self):
        zeitrahmen_pruefen(self.data.index, ZEITRAHMEN, type(self).__name__)
        c = self.data.Close
        self.ema_lang = self.I(ema, c, self.trend_len)
        self.ema_kurz = self.I(ema, c, self.schnell_len)
        self.atr_wert = self.I(atr, self.data.High, self.data.Low, c,
                               self.atr_len)
        self.kanal_tief = self.I(_tiefst, self.data.Low, self.kanal_len)
        self.kanal_hoch = self.I(_hoechst, self.data.High, self.kanal_len)

    def next(self):
        if self.position:
            return
        kurs = self.data.Close[-1]
        a = float(self.atr_wert[-1])
        if not (a > 0):
            return
        stop = a * self.atr_stop_mult
        lang, kurz = self.ema_lang[-1], self.ema_kurz[-1]

        if self.trade_short and kurs < lang and kurz < lang \
                and kurs < self.kanal_tief[-1]:
            self.sell(size=0.1, sl=kurs + stop, tp=kurs - stop * self.rr_ratio)
        elif self.trade_long and kurs > lang and kurz > lang \
                and kurs > self.kanal_hoch[-1]:
            self.buy(size=0.1, sl=kurs - stop, tp=kurs + stop * self.rr_ratio)
