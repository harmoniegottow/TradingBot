"""
Signal-Logik des Gold/Silber-Divergenz-Bots — exakt dieselbe Berechnung
wie im Forschungs-Skript
backtest-pipeline/idea_r28_intermarket_divergenz.py
(Funktion build_divergenz_signals(), Paar XAUUSD/XAGUSD, H4).

Konzept: Gold und Silber bewegen sich normalerweise sehr aehnlich.
Die Differenz ihrer 20-Kerzen-Renditen (Momentum-Differenz, NICHT der
Kurs-Spread) wird auf ein eigenes -1,5-Standardabweichungs-Band
bezogen. Faellt Gold gegenueber Silber deutlich zurueck (Differenz
unter das Band) und holt dann wieder auf (Differenz kreuzt zurueck
darueber), gilt das als Long-Signal fuer Gold — kombiniert mit dem
ueblichen EMA150-Trendfilter.

BESONDERHEIT: dieses Signal braucht ZWEI Kurse (XAUUSD + XAGUSD), nicht
nur den gehandelten Markt selbst. `check_signal()` erwartet deshalb
BEIDE DataFrames (wie beim BTC-Season-Bot).

Long-Signal, wenn auf der ZULETZT GESCHLOSSENEN XAUUSD-Kerze gilt:
  1. d(t-1) <= band(t-1)   -> Gold war gegenueber Silber deutlich
                              abgehaengt (Vorkerze)
  2. d(t)   >  band(t)     -> und die Differenz kreuzt JETZT wieder
                              darueber (echtes Uebergangs-Ereignis,
                              kein Dauerzustand)
  3. Schlusskurs XAUUSD ueber EMA(TREND_LEN)  -> kein Kauf im
                              echten Abwaertstrend

Dieses Modul hat KEINE MT5-Abhaengigkeit und ist dadurch separat testbar.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

import config


def ema(series: pd.Series, length: int) -> pd.Series:
    return series.ewm(span=length, adjust=False).mean()


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


def _diff_und_band(df_x: pd.DataFrame, df_y: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """Momentum-Differenz d(t) und ihr -1,5-Sigma-Band, auf den
    XAUUSD-Kerzenindex gelegt (letzter bekannter XAGUSD-Kurs AUF ODER VOR
    jedem XAUUSD-Zeitstempel, nie spaeter -- wie beim BTC-Season-Bot)."""
    y_on_x = df_y["close"].reindex(df_x.index, method="ffill")
    if y_on_x.isna().all():
        return None, None

    ret_x = df_x["close"] / df_x["close"].shift(config.RET_LEN) - 1.0
    ret_y = y_on_x / y_on_x.shift(config.RET_LEN) - 1.0
    d = ret_x - ret_y

    mean = d.rolling(config.BAND_LOOKBACK, min_periods=config.BAND_LOOKBACK).mean()
    std = d.rolling(config.BAND_LOOKBACK, min_periods=config.BAND_LOOKBACK).std()
    band = mean - config.BAND_MULT * std
    return d, band


def market_status(df_xau: pd.DataFrame, df_xag: pd.DataFrame) -> dict | None:
    needed = max(config.TREND_LEN, config.RET_LEN + config.BAND_LOOKBACK) + 5
    if len(df_xau) < needed or len(df_xag) < needed:
        return None

    d, band = _diff_und_band(df_xau, df_xag)
    if d is None or pd.isna(d.iloc[-1]) or pd.isna(band.iloc[-1]):
        return None

    ema_trend = ema(df_xau["close"], config.TREND_LEN)
    up_trend = bool(df_xau["close"].iloc[-1] > ema_trend.iloc[-1])
    unter_band = bool(d.iloc[-1] <= band.iloc[-1])
    return {
        "up_trend": up_trend,
        "d": float(d.iloc[-1]),
        "band": float(band.iloc[-1]),
        "unter_band": unter_band,
        "ready": up_trend and unter_band,
    }


def check_signal(df_xau: pd.DataFrame, df_xag: pd.DataFrame) -> dict | None:
    """
    Erwartet zwei DataFrames GESCHLOSSENER Kerzen (open, high, low, close),
    chronologisch sortiert, letzte Zeile = zuletzt geschlossene Kerze.
    df_xau = der gehandelte Markt (Gold), df_xag = nur Referenz (Silber).
    """
    needed = max(config.TREND_LEN, config.RET_LEN + config.BAND_LOOKBACK,
                 config.ATR_LEN) + 5
    if len(df_xau) < needed or len(df_xag) < needed:
        return None

    d, band = _diff_und_band(df_xau, df_xag)
    if d is None:
        return None
    if pd.isna(d.iloc[-1]) or pd.isna(d.iloc[-2]) or pd.isna(band.iloc[-1]) or pd.isna(band.iloc[-2]):
        return None

    now_unter = d.iloc[-1] <= band.iloc[-1]
    prev_unter = d.iloc[-2] <= band.iloc[-2]
    kreuzung = (not now_unter) and prev_unter   # echtes Uebergangs-Ereignis

    ema_trend = ema(df_xau["close"], config.TREND_LEN)
    atr_val = atr(df_xau, config.ATR_LEN)
    up_trend = df_xau["close"].iloc[-1] > ema_trend.iloc[-1]

    if not (kreuzung and up_trend):
        return None

    stop_dist = float(atr_val.iloc[-1]) * config.ATR_STOP_MULT
    if not np.isfinite(stop_dist) or stop_dist <= 0:
        return None

    return {
        "entry_ref": float(df_xau["close"].iloc[-1]),
        "stop_dist": stop_dist,
        "rsi": float(d.iloc[-1]),  # Feld wiederverwendet: Momentum-Differenz statt RSI
    }
