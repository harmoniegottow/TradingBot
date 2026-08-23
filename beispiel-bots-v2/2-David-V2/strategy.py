"""
Handelslogik: Trend + Pullback (Long UND Short).

Regeln — ausschließlich auf GESCHLOSSENEN Kerzen (bot.py entfernt die
laufende Kerze bereits, bevor der DataFrame hier ankommt):

  LONG:
    Trend:    Schlusskurs über der EMA(config.TREND_LEN)
    Pullback: RSI ist unter config.RSI_OVERSOLD gefallen
    Signal:   RSI kreuzt von unten wieder über config.RSI_OVERSOLD
    Stop:     unter dem Einstieg

  SHORT (gespiegelt):
    Trend:    Schlusskurs unter der EMA(config.TREND_LEN)
    Pullback: RSI ist über RSI_OVERBOUGHT (= 100 - RSI_OVERSOLD) gestiegen
    Signal:   RSI kreuzt von oben wieder unter RSI_OVERBOUGHT
    Stop:     über dem Einstieg

  Stop-Abstand in beiden Fällen: ATR(config.ATR_LEN) * config.ATR_STOP_MULT
  (den Take-Profit setzt bot.py daraus über config.RR_RATIO)

  Neutralzone: Liegt der Kurs sehr nah an der EMA, wird NICHT gehandelt.
  Ein Kurs 0,1 Pips über der EMA ist praktisch dasselbe wie 0,1 Pips
  darunter — ohne Puffer entscheidet reines Rauschen über die Richtung.
  Breite: config.TREND_BUFFER_ATR * ATR.

Von bot.py genutzte Schnittstelle:
  check_signal(df)  -> None | {"dir": "long"|"short", "rsi": float,
                               "stop_dist": float}
  market_status(df) -> None | {"trend": "up"|"down"|"neutral",
                               "ready": bool, "rsi": float,
                               "to_signal": float, "richtung": str}

df: DataFrame mit den Spalten open/high/low/close, Zeitindex aufsteigend.
Benötigt nur pandas — keine zusätzlichen TA-Bibliotheken.
"""

from __future__ import annotations

import pandas as pd

import config

# So viele geschlossene Kerzen sind mindestens nötig, damit alle
# Indikatoren stabil berechenbar sind (+2, weil das RSI-Kreuz zwei
# aufeinanderfolgende Kerzen vergleicht).
#
# Achtung EMA: ewm(min_periods=length) liefert zwar ab genau `length`
# Kerzen einen Wert, dieser ist aber noch stark vom allerersten Kurs
# geprägt. Eine EMA braucht praktisch das Zwei- bis Dreifache ihrer
# Spanne, um eingeschwungen zu sein. Mit dem Faktor 2 wird der
# Trendfilter erst benutzt, wenn er wirklich aussagekräftig ist.
EMA_WARMUP_FACTOR = 2

MIN_BARS = max(
    config.TREND_LEN * EMA_WARMUP_FACTOR,
    config.RSI_LEN + 1,
    config.ATR_LEN + 1,
) + 2


# ----------------------------------------------------------------------
# Indikatoren
# ----------------------------------------------------------------------
def ema(series: pd.Series, length: int) -> pd.Series:
    """Exponentiell gewichteter gleitender Durchschnitt."""
    return series.ewm(span=length, adjust=False, min_periods=length).mean()


def rsi(close: pd.Series, length: int) -> pd.Series:
    """Relative Strength Index mit Wilder-Glättung (alpha = 1/length)."""
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)
    avg_gain = gain.ewm(alpha=1.0 / length, adjust=False, min_periods=length).mean()
    avg_loss = loss.ewm(alpha=1.0 / length, adjust=False, min_periods=length).mean()

    # Division nur dort ausführen, wo avg_loss > 0 ist. Sonst entsteht
    # inf/NaN samt Laufzeitwarnung, bevor die Sonderfälle unten greifen.
    rs = avg_gain.divide(avg_loss.where(avg_loss > 0))
    out = 100.0 - 100.0 / (1.0 + rs)

    flat = avg_loss.eq(0)
    out = out.mask(flat & avg_gain.gt(0), 100.0)   # nur Gewinne
    out = out.mask(flat & avg_gain.eq(0), 50.0)    # völlig flacher Markt
    return out


def atr(df: pd.DataFrame, length: int) -> pd.Series:
    """Average True Range (Wilder-Glättung) — Maß für die Schwankungsbreite."""
    prev_close = df["close"].shift(1)
    true_range = pd.concat(
        [
            df["high"] - df["low"],
            (df["high"] - prev_close).abs(),
            (df["low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return true_range.ewm(alpha=1.0 / length, adjust=False, min_periods=length).mean()


# ----------------------------------------------------------------------
# interner Blick auf die letzte(n) Kerze(n)
# ----------------------------------------------------------------------
def _snapshot(df: pd.DataFrame) -> dict | None:
    """Indikatorwerte der letzten geschlossenen Kerze; None bei zu wenig Daten."""
    if df is None or len(df) < MIN_BARS:
        return None

    close = df["close"]
    ema_series = ema(close, config.TREND_LEN)
    rsi_series = rsi(close, config.RSI_LEN)
    atr_series = atr(df, config.ATR_LEN)

    values = (
        close.iloc[-1],
        ema_series.iloc[-1],
        rsi_series.iloc[-1],
        rsi_series.iloc[-2],
        atr_series.iloc[-1],
    )
    if any(pd.isna(v) for v in values):
        return None

    c, e, rsi_now, rsi_prev, atr_now = (float(v) for v in values)

    # Neutralzone um die EMA: innerhalb dieses Bands ist die Trendrichtung
    # reines Rauschen, deshalb wird dort gar nicht gehandelt.
    puffer = atr_now * config.TREND_BUFFER_ATR
    if c > e + puffer:
        trend = "up"
    elif c < e - puffer:
        trend = "down"
    else:
        trend = "neutral"

    return {
        "close": c,
        "ema": e,
        "rsi": rsi_now,
        "rsi_prev": rsi_prev,
        "atr": atr_now,
        "trend": trend,
        "puffer": puffer,
    }


def rsi_overbought() -> float:
    """
    Spiegelbild von RSI_OVERSOLD für die Short-Seite.

    Bei RSI_OVERSOLD = 35 ergibt das 65 — der Pullback nach oben im
    Abwärtstrend ist damit genauso streng definiert wie der Pullback
    nach unten im Aufwärtstrend.
    """
    return 100.0 - config.RSI_OVERSOLD


# ----------------------------------------------------------------------
# öffentliche Schnittstelle (von bot.py aufgerufen)
# ----------------------------------------------------------------------
def check_signal(df: pd.DataFrame) -> dict | None:
    """
    Prüft die letzte geschlossene Kerze auf ein Long- ODER Short-Signal.

    Rückgabe bei Signal: {"dir": "long"|"short", "rsi": aktueller RSI,
    "stop_dist": Stop-Abstand in Preiseinheiten}; sonst None.
    """
    s = _snapshot(df)
    if s is None or s["trend"] == "neutral":
        return None

    stop_dist = s["atr"] * config.ATR_STOP_MULT
    if stop_dist <= 0:
        return None

    if s["trend"] == "up":
        if not config.TRADE_LONG:
            return None
        # RSI kreuzt von unten über die Pullback-Schwelle
        if not (s["rsi_prev"] <= config.RSI_OVERSOLD < s["rsi"]):
            return None
        return {"dir": "long", "rsi": s["rsi"], "stop_dist": stop_dist}

    if not config.TRADE_SHORT:
        return None
    # Gespiegelt: RSI kreuzt von oben unter die Überkauft-Schwelle
    ob = rsi_overbought()
    if not (s["rsi_prev"] >= ob > s["rsi"]):
        return None
    return {"dir": "short", "rsi": s["rsi"], "stop_dist": stop_dist}


def signals_vectorized(df: pd.DataFrame) -> pd.DataFrame:
    """
    Berechnet die Signale für ALLE Kerzen auf einmal — nur für Backtests.

    check_signal() rechnet je Aufruf alle Indikatoren neu durch. Im
    Live-Betrieb ist das egal (ein Aufruf pro Kerze), im Backtest bedeutet
    es tausende Wiederholungen derselben Rechnung.

    Diese Funktion liefert exakt dieselben Signale, nur in einem Durchgang.
    Die Gleichheit wird in test_strategy.py gegen check_signal() geprüft —
    falls du die Regeln oben änderst, MUSS diese Funktion mitgezogen werden.

    Rückgabe: DataFrame mit den Spalten
      long      (bool)  — Long-Einstieg auf dieser Kerze
      short     (bool)  — Short-Einstieg auf dieser Kerze
      signal    (bool)  — long ODER short (Bequemlichkeit)
      rsi       (float) — RSI dieser Kerze
      stop_dist (float) — Stop-Abstand in Preiseinheiten
      trend     (str)   — "up" | "down" | "neutral"
    """
    close = df["close"]
    ema_s = ema(close, config.TREND_LEN)
    rsi_s = rsi(close, config.RSI_LEN)
    atr_s = atr(df, config.ATR_LEN)

    puffer = atr_s * config.TREND_BUFFER_ATR
    up_trend = close > ema_s + puffer
    down_trend = close < ema_s - puffer

    ob = rsi_overbought()
    rsi_prev = rsi_s.shift(1)
    crossed_up = (rsi_prev <= config.RSI_OVERSOLD) & (rsi_s > config.RSI_OVERSOLD)
    crossed_down = (rsi_prev >= ob) & (rsi_s < ob)
    stop_dist = atr_s * config.ATR_STOP_MULT

    gueltig = (
        ema_s.notna() & rsi_s.notna() & rsi_prev.notna()
        & atr_s.notna() & (stop_dist > 0)
    )
    # Vor MIN_BARS gibt check_signal() immer None zurück — hier genauso,
    # sonst weichen die Ergebnisse an den ersten Kerzen voneinander ab.
    zu_frueh = pd.Series(range(len(df)), index=df.index) < MIN_BARS - 1

    long_sig = up_trend & crossed_up & gueltig & ~zu_frueh
    short_sig = down_trend & crossed_down & gueltig & ~zu_frueh
    if not config.TRADE_LONG:
        long_sig = long_sig & False
    if not config.TRADE_SHORT:
        short_sig = short_sig & False

    trend = pd.Series("neutral", index=df.index, dtype=object)
    trend[up_trend] = "up"
    trend[down_trend] = "down"

    return pd.DataFrame({
        "long": long_sig,
        "short": short_sig,
        "signal": long_sig | short_sig,
        "rsi": rsi_s,
        "stop_dist": stop_dist,
        "trend": trend,
    }, index=df.index)


def market_status(df: pd.DataFrame) -> dict | None:
    """
    Aktueller Marktzustand für die Statusanzeige in bot.py.

    Rückgabe: {"trend": "up"|"down"|"neutral", "ready": Rücksetzer läuft
    (nächstes RSI-Kreuz würde auslösen), "rsi": aktueller RSI,
    "to_signal": fehlende RSI-Punkte bis zur Pullback-Zone,
    "richtung": welche Seite gehandelt würde};
    None bei zu wenigen Kerzen.
    """
    s = _snapshot(df)
    if s is None:
        return None

    trend = s["trend"]
    rsi_now = s["rsi"]
    ob = rsi_overbought()

    if trend == "up" and config.TRADE_LONG:
        richtung = "long"
        ready = rsi_now <= config.RSI_OVERSOLD
        to_signal = max(0.0, rsi_now - config.RSI_OVERSOLD)
    elif trend == "down" and config.TRADE_SHORT:
        richtung = "short"
        ready = rsi_now >= ob
        to_signal = max(0.0, ob - rsi_now)
    else:
        richtung = "keine"
        ready = False
        to_signal = 0.0

    return {
        "trend": trend,
        "rsi": rsi_now,
        "ready": ready,
        "to_signal": to_signal,
        "richtung": richtung,
    }
