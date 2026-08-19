"""
vergleich.py — Testet ALLE Strategien aus strategien/REGISTRY nach demselben
Massstab (gleiche Daten, gleiche Kosten) und stellt die Kennzahlen in einer
Tabelle nebeneinander.

Aufruf:
    python vergleich.py                 # Standard: EURUSD, Tagesdaten
    python vergleich.py XAUUSD 1h       # anderes Symbol / Intervall (falls CSV da)

WICHTIG zum Zeitrahmen: Laeuft dies auf EUR/USD-TAGESdaten, ist das nur ein
Funktionsnachweis der METHODE, KEINE Aussage ueber die Guete der Strategien.
Die Trend-Strategien sind fuer H1/H4 gebaut. Das Skript warnt am Ende.
"""
from pathlib import Path
import sys
import pandas as pd
from backtesting import Backtest

from strategien import REGISTRY

DATA_DIR = Path(__file__).parent / "data"

# Kennzahlen, die wir vergleichen (Name in stats -> Kurzname in der Tabelle)
KENNZAHLEN = {
    "Return [%]": "Ergebnis %",
    "Profit Factor": "Profitfaktor",
    "Max. Drawdown [%]": "Max.Ruecklauf %",
    "# Trades": "Trades",
    "Win Rate [%]": "Treffer %",
    "Sharpe Ratio": "Sharpe",
}


def lade_csv(symbol: str, intervall: str) -> pd.DataFrame:
    pfad = DATA_DIR / f"{symbol}_{intervall}.csv"
    if not pfad.exists():
        raise SystemExit(
            f"Datei fehlt: {pfad}. Erst 'python daten_laden.py' ausfuehren."
        )
    df = pd.read_csv(pfad, index_col=0, parse_dates=True)
    return df[["Open", "High", "Low", "Close"]].dropna()


def teste_eine(df: pd.DataFrame, strategie_klasse) -> dict:
    bt = Backtest(
        df,
        strategie_klasse,
        cash=100000,
        commission=0.0002,   # ~2 Pips pro Trade (grosszuegige Kostenannahme)
        finalize_trades=True,
    )
    stats = bt.run()
    zeile = {}
    for lang, kurz in KENNZAHLEN.items():
        wert = stats.get(lang, float("nan"))
        try:
            zeile[kurz] = round(float(wert), 2)
        except (TypeError, ValueError):
            zeile[kurz] = wert
    return zeile


def main():
    symbol = sys.argv[1] if len(sys.argv) > 1 else "EURUSD"
    intervall = sys.argv[2] if len(sys.argv) > 2 else "1d"
    df = lade_csv(symbol, intervall)

    zeitraum = f"{df.index.min().date()} bis {df.index.max().date()}"
    print("=" * 78)
    print("STRATEGIE-VERGLEICH  (gleiche Daten, gleiche Kosten fuer alle)")
    print(f"Symbol: {symbol}   Intervall: {intervall}   Zeitraum: {zeitraum}")
    print(f"Kerzen: {len(df)}   Kosten: 0.0002 (~2 Pips/Trade)")
    print("=" * 78)

    ergebnisse = {}
    for name, klasse in REGISTRY.items():
        ergebnisse[name] = teste_eine(df, klasse)

    tabelle = pd.DataFrame(ergebnisse).T   # Strategien als Zeilen
    with pd.option_context("display.width", 120,
                           "display.max_columns", None):
        print(tabelle.to_string())

    print("=" * 78)
    if intervall == "1d":
        print("WARNUNG: TAGESdaten sind NUR ein Funktionsnachweis der Methode.")
        print("Die Trend-Strategien sind fuer H1/H4 gebaut. Diese Zahlen sagen")
        print("NICHTS ueber die echte Guete aus. Erst mit echter H1/H4-Historie")
        print("aus dem cTrader-Zugang wird der Vergleich aussagekraeftig.")
    print("Lesehilfe: Profitfaktor > 1 = Gewinn je Risiko. Max.Ruecklauf =")
    print("groesster zwischenzeitlicher Verlust vom Hoch (je kleiner, desto")
    print("ruhiger). Wenige Trades = wenig statistische Aussagekraft.")
    return tabelle


if __name__ == "__main__":
    main()
