"""
strategien/divergenz_gold_silber.py — Baustein: Intermarket-Divergenz Gold/Silber.

Signal-Logik uebernommen aus dem Beispiel-Bot 3 (beispiel-bots-v2/
3-Divergenz-Gold-Silber/strategy.py), broker-neutral:

  d(t)    = Rendite_Gold(RET_LEN) - Rendite_Silber(RET_LEN)
  band(t) = rollender Mittelwert(d, BAND_LOOKBACK) - BAND_MULT * Std(d, ...)
  Long, wenn d von unter dem Band zurueck darueber kreuzt
        UND Schlusskurs Gold ueber EMA(TREND_LEN).
  Stop = ATR(ATR_LEN) * ATR_STOP_MULT, Ziel = Stop * RR.

BESONDERHEIT: braucht ZWEI Kursreihen. Die Divergenz wird deshalb VORHER
berechnet und als Spalte "DivSignal" an den Gold-DataFrame gehaengt
(siehe divergenz_vorbereiten()). Der Strategie-Baustein liest nur noch
diese Spalte — dadurch bleibt er zur REGISTRY kompatibel.
"""
from __future__ import annotations

import pandas as pd
from backtesting import Strategy

from strategien.indikatoren import ema, atr

RET_LEN = 20
BAND_LOOKBACK = 100
BAND_MULT = 1.5


def divergenz_vorbereiten(
    df_gold: pd.DataFrame,
    df_silber: pd.DataFrame,
    ret_len: int = RET_LEN,
    band_lookback: int = BAND_LOOKBACK,
    band_mult: float = BAND_MULT,
) -> pd.DataFrame:
    """Haengt die Spalte 'DivSignal' (bool) an den Gold-DataFrame.

    Silber wird per ffill auf den Gold-Index gelegt: es wird immer der
    letzte bekannte Silberkurs AUF ODER VOR dem Gold-Zeitstempel benutzt,
    nie ein spaeterer. Sonst entsteht ein Blick in die Zukunft.
    """
    out = df_gold.copy()
    y = df_silber["Close"].reindex(out.index, method="ffill")

    ret_x = out["Close"] / out["Close"].shift(ret_len) - 1.0
    ret_y = y / y.shift(ret_len) - 1.0
    d = ret_x - ret_y

    mean = d.rolling(band_lookback, min_periods=band_lookback).mean()
    std = d.rolling(band_lookback, min_periods=band_lookback).std()
    band = mean - band_mult * std

    unter = d <= band
    # Echtes Uebergangs-Ereignis: Vorkerze unter dem Band, jetzt darueber.
    out["DivSignal"] = unter.shift(1).fillna(False) & ~unter.fillna(False)
    out["DivSignal"] = out["DivSignal"] & d.notna() & band.notna()
    return out


class DivergenzGoldSilber(Strategy):
    trend_len = 150
    atr_len = 14
    atr_stop_mult = 2.0
    rr_ratio = 2.0

    def init(self):
        preis = self.data.Close
        self.ema_trend = self.I(ema, preis, self.trend_len)
        self.atr_wert = self.I(
            atr, self.data.High, self.data.Low, self.data.Close, self.atr_len
        )

    def next(self):
        if self.position:
            return
        if not bool(self.data.DivSignal[-1]):
            return
        kurs = self.data.Close[-1]
        if not (kurs > self.ema_trend[-1]):
            return
        stop_dist = float(self.atr_wert[-1]) * self.atr_stop_mult
        if not (stop_dist > 0):
            return
        self.buy(size=0.1, sl=kurs - stop_dist, tp=kurs + stop_dist * self.rr_ratio)
