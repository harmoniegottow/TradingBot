"""
backtest.py — Einzeltest EINER Strategie (Standard: Trend-Pullback).

Nutzt denselben Strategie-Baustein wie der Vergleich (strategien/), damit die
Logik nur an EINER Stelle liegt. Fuer den Vergleich mehrerer Strategien:
    python vergleich.py

Aufruf:
    python backtest.py                    # Trend-Pullback auf EURUSD-Tagesdaten
    python backtest.py MA-Kreuzung        # andere Strategie aus der REGISTRY
    python backtest.py Trend-Pullback XAUUSD 1h
"""
from pathlib import Path
import sys
import pandas as pd
from backtesting import Backtest

from strategien import REGISTRY

DATA_DIR = Path(__file__).parent / "data"


def lade_csv(symbol: str, intervall: str) -> pd.DataFrame:
    pfad = DATA_DIR / f"{symbol}_{intervall}.csv"
    if not pfad.exists():
        raise SystemExit(
            f"Datei fehlt: {pfad}. Erst 'python daten_laden.py' ausfuehren."
        )
    df = pd.read_csv(pfad, index_col=0, parse_dates=True)
    return df[["Open", "High", "Low", "Close"]].dropna()


def main():
    name = sys.argv[1] if len(sys.argv) > 1 else "Trend-Pullback"
    symbol = sys.argv[2] if len(sys.argv) > 2 else "EURUSD"
    intervall = sys.argv[3] if len(sys.argv) > 3 else "1d"

    if name not in REGISTRY:
        raise SystemExit(
            f"Unbekannte Strategie '{name}'. Verfuegbar: {', '.join(REGISTRY)}"
        )

    df = lade_csv(symbol, intervall)
    bt = Backtest(
        df,
        REGISTRY[name],
        cash=100000,
        commission=0.0002,   # ~2 Pips pro Trade (grosszuegige Kostenannahme)
        finalize_trades=True,
    )
    stats = bt.run()

    print("=" * 60)
    print(f"BACKTEST-ERGEBNIS  Strategie: {name}")
    print(f"Symbol: {symbol}  Intervall: {intervall}")
    print("=" * 60)
    for kennzahl in [
        "Start", "End", "Duration",
        "Return [%]", "Buy & Hold Return [%]",
        "Return (Ann.) [%]", "Volatility (Ann.) [%]",
        "Sharpe Ratio", "Max. Drawdown [%]",
        "# Trades", "Win Rate [%]", "Profit Factor",
    ]:
        if kennzahl in stats.index:
            print(f"  {kennzahl:26s}: {stats[kennzahl]}")
    print("=" * 60)
    if intervall == "1d":
        print("WARNUNG: TAGESdaten sind NUR ein Funktionsnachweis, NICHT der")
        print("validierte Zeitrahmen. Die Zahlen sagen nichts ueber die echte")
        print("Guete aus. Erst echte H1/H4-Historie macht den Test aussagekraeftig.")
    return stats


if __name__ == "__main__":
    main()
