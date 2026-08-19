"""
strategien/indikatoren.py — Gemeinsame Indikator-Berechnungen.

ALLE Strategien nutzen genau diese Funktionen. So ist sichergestellt, dass
EMA, RSI und ATR ueberall identisch gerechnet werden - keine Differenzen im
Datenmodell zwischen Backtest und spaeterem Live-Bot.

Bewusst identisch zur Logik in beispiel-mt5-bot/strategy.py.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def ema(werte, laenge: int) -> pd.Series:
    """Exponentiell gewichteter gleitender Durchschnitt."""
    return pd.Series(werte).ewm(span=laenge, adjust=False).mean()


def sma(werte, laenge: int) -> pd.Series:
    """Einfacher gleitender Durchschnitt."""
    return pd.Series(werte).rolling(int(laenge)).mean()


def rsi(werte, laenge: int) -> pd.Series:
    """Relative-Staerke-Index (0 bis 100)."""
    serie = pd.Series(werte)
    delta = serie.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1 / laenge, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / laenge, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    out = 100 - (100 / (1 + rs))
    return out.fillna(50.0)


def atr(high, low, close, laenge: int) -> pd.Series:
    """Average True Range - mittlere Schwankungsbreite, fuer Stop-Abstaende."""
    high = pd.Series(high)
    low = pd.Series(low)
    close = pd.Series(close)
    prev_close = close.shift(1)
    tr = pd.concat(
        [
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1 / laenge, adjust=False).mean()
