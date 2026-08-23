"""
Signal-Logik des Bots — exakt dieselbe Berechnung wie in der validierten
Backtest-Pipeline (strategies/trend_pullback.py):

Long-Signal, wenn auf der ZULETZT GESCHLOSSENEN Kerze gilt:
  1. Schlusskurs über EMA(TREND_LEN)          -> Aufwärtstrend
  2. RSI(RSI_LEN) kreuzt über RSI_OVERSOLD    -> Pullback endet

Dieses Modul hat KEINE MT5-Abhängigkeit und ist dadurch separat testbar.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

import config


def ema(series: pd.Series, length: int) -> pd.Series:
    return series.ewm(span=length, adjust=False).mean()


def rsi(series: pd.Series, length: int) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1 / length, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / length, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    out = 100 - (100 / (1 + rs))
    return out.fillna(50.0)


def atr(df: pd.DataFrame, length: int) -> pd.Series:
    prev_close = df["close"].shift(1)
    tr = pd.concat(
        [
            df["high"] - df["low"],
            (df["high"] - prev_close).abs(),
            (df["low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1 / length, adjust=False).mean()


def market_status(df: pd.DataFrame) -> dict | None:
    """
    Gibt den aktuellen Zustand eines Marktes zurück (für die Statusanzeige,
    unabhängig davon, ob ein Signal vorliegt). None, wenn zu wenig Daten.

    Felder:
      up_trend:   bool  — Kurs über der Trend-EMA?
      rsi:        float — aktueller RSI
      to_signal:  float — wie viele RSI-Punkte fehlen noch bis zur Oversold-Schwelle
                          (negativ = RSI schon unter der Schwelle, "geladen")
      ready:      bool  — Trend passt UND RSI im/unter Oversold-Bereich (Signal steht bevor)
    """
    needed = max(config.TREND_LEN, config.RSI_LEN, config.ATR_LEN) + 5
    if len(df) < needed:
        return None

    close = df["close"]
    ema_trend = ema(close, config.TREND_LEN)
    rsi_val = rsi(close, config.RSI_LEN)

    up_trend = bool(close.iloc[-1] > ema_trend.iloc[-1])
    cur_rsi = float(rsi_val.iloc[-1])
    to_signal = cur_rsi - config.RSI_OVERSOLD  # >0: über Schwelle, <0: darunter
    ready = up_trend and cur_rsi <= config.RSI_OVERSOLD + 5

    return {"up_trend": up_trend, "rsi": cur_rsi,
            "to_signal": to_signal, "ready": ready}


def check_signal(df: pd.DataFrame) -> dict | None:
    """
    Erwartet einen DataFrame GESCHLOSSENER Kerzen (open, high, low, close),
    chronologisch sortiert, letzte Zeile = zuletzt geschlossene Kerze.

    Gibt None zurück (kein Signal) oder ein Dict mit:
      entry_ref:  Schlusskurs der Signalkerze (Referenz)
      stop_dist:  ATR-basierter Stop-Abstand in Preiseinheiten
      rsi:        RSI-Wert der Signalkerze (fürs Log)
    """
    needed = max(config.TREND_LEN, config.RSI_LEN, config.ATR_LEN) + 5
    if len(df) < needed:
        return None

    close = df["close"]
    ema_trend = ema(close, config.TREND_LEN)
    rsi_val = rsi(close, config.RSI_LEN)
    atr_val = atr(df, config.ATR_LEN)

    up_trend = close.iloc[-1] > ema_trend.iloc[-1]
    cross_up = (rsi_val.iloc[-1] > config.RSI_OVERSOLD
                and rsi_val.iloc[-2] <= config.RSI_OVERSOLD)

    if not (up_trend and cross_up):
        return None

    stop_dist = float(atr_val.iloc[-1]) * config.ATR_STOP_MULT
    if not np.isfinite(stop_dist) or stop_dist <= 0:
        return None

    return {
        "entry_ref": float(close.iloc[-1]),
        "stop_dist": stop_dist,
        "rsi": float(rsi_val.iloc[-1]),
    }
