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
from strategien.zeitrahmen import (
    Zeitrahmenangabe,
    referenz_pruefen,
    zeitrahmen_pruefen,
)

# Fuer welchen Zeitrahmen die Parameter unten gemeint sind.
ZEITRAHMEN = Zeitrahmenangabe("H_4", "belegt durch divergenz_zehnjahre.py: zehn Jahre, 15447 H4-Kerzen, PF 1,95, 136 Trades; bestaetigt durch robustheit_zehnjahre.py und richtungstest.py")

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
    """Haengt 'DivSignal' (Long) und 'DivSignalShort' an den Gold-DataFrame.

    Der Short-Zweig ist die exakte Spiegelung: Ist Gold gegenueber Silber zu
    TEUER geworden (Differenz ueber dem oberen Band) und kommt zurueck, gilt
    das als Verkaufssignal. Gleiche Schwellen, gleiche Bandbreite, keine
    eigenen Parameter - sonst waere es eine zweite Strategie und keine
    Spiegelung.

    Silber wird per ffill auf den Gold-Index gelegt: es wird immer der
    letzte bekannte Silberkurs AUF ODER VOR dem Gold-Zeitstempel benutzt,
    nie ein spaeterer. Sonst entsteht ein Blick in die Zukunft.
    """
    # Zuerst pruefen, wofuer die Parameter unten ueberhaupt gelten. Der
    # Abstand wird aus den Daten gemessen, nicht aus einem Dateinamen.
    zeitrahmen_pruefen(df_gold.index, ZEITRAHMEN, "Divergenz Gold")
    # Silber wird auf den Gold-Index gelegt - eine feinere Reihe ist
    # unschaedlich, eine groebere nicht. Deshalb hier die andere Pruefung.
    referenz_pruefen(df_silber.index, ZEITRAHMEN, "Divergenz Silber")

    out = df_gold.copy()
    y = df_silber["Close"].reindex(out.index, method="ffill")

    ret_x = out["Close"] / out["Close"].shift(ret_len) - 1.0
    ret_y = y / y.shift(ret_len) - 1.0
    d = ret_x - ret_y

    mean = d.rolling(band_lookback, min_periods=band_lookback).mean()
    std = d.rolling(band_lookback, min_periods=band_lookback).std()
    band_unten = mean - band_mult * std
    band_oben = mean + band_mult * std
    gueltig = d.notna() & mean.notna() & std.notna()

    # Long: Differenz war unter dem unteren Band und kommt zurueck darueber.
    unter = d <= band_unten
    out["DivSignal"] = (unter.shift(1).fillna(False) & ~unter.fillna(False)
                        & gueltig)

    # Short: gespiegelt. War ueber dem oberen Band und kommt zurueck darunter.
    ueber = d >= band_oben
    out["DivSignalShort"] = (ueber.shift(1).fillna(False)
                             & ~ueber.fillna(False) & gueltig)
    return out


class DivergenzGoldSilber(Strategy):
    trend_len = 150
    atr_len = 14
    atr_stop_mult = 2.0
    rr_ratio = 2.0

    # Schalter fuer die Richtungen. Short steht auf False, damit alle
    # bisherigen Skripte unveraendert dieselben Zahlen liefern wie vorher -
    # ein stiller Wechsel der Vorgabe waere schlimmer als ein Schalter.
    handle_long = True
    handle_short = False

    def init(self):
        # Bricht ab, wenn die Daten nicht zu ZEITRAHMEN passen.
        zeitrahmen_pruefen(self.data.index, ZEITRAHMEN,
                           type(self).__name__)
        preis = self.data.Close
        self.ema_trend = self.I(ema, preis, self.trend_len)
        self.atr_wert = self.I(
            atr, self.data.High, self.data.Low, self.data.Close, self.atr_len
        )

    def next(self):
        if self.position:
            return
        kurs = self.data.Close[-1]
        stop_dist = float(self.atr_wert[-1]) * self.atr_stop_mult
        if not (stop_dist > 0):
            return

        if (self.handle_long and bool(self.data.DivSignal[-1])
                and kurs > self.ema_trend[-1]):
            self.buy(size=0.1, sl=kurs - stop_dist,
                     tp=kurs + stop_dist * self.rr_ratio)
            return

        # Gespiegelt: Trendfilter ebenfalls umgedreht - nur unter der EMA.
        if (self.handle_short and bool(self.data.DivSignalShort[-1])
                and kurs < self.ema_trend[-1]):
            self.sell(size=0.1, sl=kurs + stop_dist,
                      tp=kurs - stop_dist * self.rr_ratio)


class DivergenzNurShort(DivergenzGoldSilber):
    """Nur die Short-Seite - fuer die Symmetriefrage."""

    handle_long = False
    handle_short = True


class DivergenzBeideRichtungen(DivergenzGoldSilber):
    """Beide Richtungen."""

    handle_long = True
    handle_short = True
