"""
daten_laden.py — Holt historische Forex-Tagesdaten und speichert sie lokal.

Quelle: Yahoo Finance (yfinance), kostenlos, kein Konto noetig.
Zweck: Grundlage fuer den Backtest, solange der cTrader-Live-Zugang
(WebID-Pruefung) noch nicht freigeschaltet ist.

Aufruf:
    python daten_laden.py            # laedt EUR/USD, Standardzeitraum
    python daten_laden.py GBPUSD=X   # anderes Paar
"""
import sys
from pathlib import Path
import yfinance as yf

DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(exist_ok=True)


def lade_daten(symbol: str = "EURUSD=X",
               start: str = "2019-01-01",
               end: str = "2026-08-01",
               interval: str = "1d"):
    """Laedt OHLC-Daten und speichert sie als CSV. Gibt den DataFrame zurueck."""
    df = yf.download(symbol, start=start, end=end, interval=interval,
                     progress=False, auto_adjust=True)
    if df.empty:
        raise SystemExit(f"Keine Daten fuer {symbol} erhalten.")

    # yfinance liefert teils MultiIndex-Spalten -> flach machen
    if hasattr(df.columns, "nlevels") and df.columns.nlevels > 1:
        df.columns = df.columns.get_level_values(0)

    # Nur die Spalten, die der Backtest braucht, in der erwarteten Schreibweise
    df = df[["Open", "High", "Low", "Close"]].dropna()

    ziel = DATA_DIR / f"{symbol.replace('=X', '')}_{interval}.csv"
    df.to_csv(ziel)
    print(f"Gespeichert: {ziel}")
    print(f"Zeilen: {len(df)}  Zeitraum: {df.index.min().date()} bis {df.index.max().date()}")
    return df


if __name__ == "__main__":
    symbol = sys.argv[1] if len(sys.argv) > 1 else "EURUSD=X"
    lade_daten(symbol)
