"""
pruefung_quelle.py — Prueft die Behauptung des geliehenen MT5-Bots auf GENAU
den Instrumenten und Zeitrahmen, fuer die sie aufgestellt wurde.

Die Quelle (beispiel-mt5-bot/config.py) behauptet:
    XAUUSD  H1  Profitfaktor 1.92
    XAGUSD  H1  Profitfaktor 1.30
    XPTUSD  H1  Profitfaktor 1.52   (Platin: beim Broker nicht geladen)
    CHFJPY  H4  "mehrfach validiert"
    USDJPY  H4  "4h-Kern"

Parameter exakt wie in der Quelle: EMA 150, RSI 14, RSI-Schwelle 35,
ATR 14, Stop 2x ATR, Verhaeltnis 2:1, nur Long.

EURUSD laeuft als Kontrollgruppe mit: dafuer wurde NIE etwas behauptet.

Zu den Kosten: backtesting.py rechnet 'commission' anteilig. 0.0002 sind also
2 Basispunkte, bei EURUSD etwa 2 Pips. Bei Gold entspricht das rund 0,92 USD
Spanne je Seite, was fuer XAUUSD realistisch bis leicht grosszuegig ist.
Zusaetzlich wird eine kostenfreie Variante gerechnet, um zu trennen, ob eine
Strategie an der Logik oder an den Kosten scheitert.
"""
from pathlib import Path

import pandas as pd
from backtesting import Backtest

from strategien.trend_pullback import TrendPullback

DATA_DIR = Path(__file__).parent / "data"

# Symbol -> (Zeitrahmen laut Quelle, behaupteter Profitfaktor)
BEHAUPTUNG = {
    "XAUUSD": ("H_1", "1.92"),
    "XAGUSD": ("H_1", "1.30"),
    "CHFJPY": ("H_4", "validiert"),
    "USDJPY": ("H_4", "validiert"),
    "EURUSD": ("H_1", "-"),   # Kontrollgruppe, keine Behauptung
}


def lade(symbol: str, tf: str) -> pd.DataFrame:
    pfad = DATA_DIR / f"{symbol}_{tf}.csv"
    df = pd.read_csv(pfad, index_col=0, parse_dates=True)
    return df[["Open", "High", "Low", "Close"]].dropna()


def teste(df: pd.DataFrame, kosten: float) -> dict:
    stats = Backtest(
        df, TrendPullback, cash=100_000, commission=kosten, finalize_trades=True
    ).run()
    return {
        "Trades": int(stats["# Trades"]),
        "PF": stats.get("Profit Factor", float("nan")),
        "Ergebnis %": stats["Return [%]"],
        "Treffer %": stats.get("Win Rate [%]", float("nan")),
        "Ruecklauf %": stats["Max. Drawdown [%]"],
    }


def main():
    print("=" * 92)
    print("PRUEFUNG DER QUELLBEHAUPTUNG — Trend-Pullback auf den Original-Instrumenten")
    print("Parameter der Quelle: EMA150 / RSI14 Schwelle 35 / ATR14 Stop 2x / RR 2:1 / nur Long")
    print("=" * 92)

    zeilen = {}
    for symbol, (tf, behauptet) in BEHAUPTUNG.items():
        df = lade(symbol, tf)
        mit = teste(df, 0.0002)
        ohne = teste(df, 0.0)
        label = f"{symbol} {tf.replace('_', '')}"
        zeilen[label] = {
            "behauptet PF": behauptet,
            "Bars": len(df),
            **{k: (round(v, 2) if isinstance(v, float) else v) for k, v in mit.items()},
            "PF ohne Kosten": round(ohne["PF"], 2) if ohne["PF"] == ohne["PF"] else ohne["PF"],
        }

    tab = pd.DataFrame(zeilen).T
    with pd.option_context("display.width", 200, "display.max_columns", None):
        print(tab.to_string())

    print("=" * 92)
    print("Lesehilfe: PF = Profitfaktor. Ueber 1,0 verdient Geld, darunter verliert.")
    print("'PF ohne Kosten' trennt Logikproblem von Kostenproblem: liegt der Wert")
    print("ohne Kosten ueber 1,0 und mit Kosten darunter, frisst die Spanne den Rand.")
    print("Wenige Trades (unter etwa 30) haben kaum statistische Aussagekraft.")
    print()
    print("WICHTIG: Zeitraum ist 2 Jahre (Broker-Historie ab 2024-08). Die Quelle")
    print("nennt ihren Testzeitraum nicht, kann also einen anderen gemessen haben.")
    return tab


if __name__ == "__main__":
    main()
