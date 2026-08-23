"""
pruefe_divergenz.py — Prueft die Behauptung des Beispiel-Bots 3
(Intermarket-Divergenz Gold gegen Silber) auf UNSEREN eigenen Daten.

Behauptung aus dessen config.py:
  "Out-of-Sample-Verhaeltnis 2,43-2,65 (3 Split-Methoden), 142 Trades auf
   H4 ueber 10 Jahre, Gewinn-Konzentration sehr niedrig, gewinnt klar in
   3 von 5 Testfenstern. Auf Tagesbasis (D1) bestaetigt sich dieselbe
   Richtung."

Geprueft wird mit dem bestehenden Pruefstand (Permutationstest +
Kaufen-und-Halten + Einsatz-Normierung), auf H4 UND D1, und immer im
Vergleich zur Baseline Trend-Pullback auf demselben Datensatz.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

from pruefstand import bewerte, lesehilfe, KOSTEN_STANDARD
from strategien.trend_pullback import TrendPullback
from strategien.divergenz_gold_silber import (
    DivergenzGoldSilber,
    divergenz_vorbereiten,
)

DATA_DIR = Path(__file__).parent / "data"


def lade(symbol: str, intervall: str) -> pd.DataFrame:
    pfad = DATA_DIR / f"{symbol}_{intervall}.csv"
    if not pfad.exists():
        raise SystemExit(f"Datei fehlt: {pfad}")
    df = pd.read_csv(pfad, index_col=0, parse_dates=True)
    return df[["Open", "High", "Low", "Close"]].dropna()


def lauf(intervall: str, runden: int) -> pd.DataFrame:
    gold = lade("XAUUSD", intervall)
    silber = lade("XAGUSD", intervall)
    kombi = divergenz_vorbereiten(gold, silber).dropna(subset=["Close"])

    treffer = int(kombi["DivSignal"].sum())
    zeitraum = f"{kombi.index.min().date()} bis {kombi.index.max().date()}"
    print("=" * 104)
    print(f"XAUUSD {intervall}   {zeitraum}   Kerzen: {len(kombi)}")
    print(f"Divergenz-Ereignisse im Zeitraum (vor Trendfilter): {treffer}")
    print(f"Kosten: {KOSTEN_STANDARD}")
    print("=" * 104)

    ergebnisse = {}
    print("  ... teste Divergenz Gold/Silber", flush=True)
    ergebnisse["Divergenz G/S"] = bewerte(
        kombi, DivergenzGoldSilber, runden=runden
    )
    print("  ... teste Trend-Pullback (Baseline, gleiche Daten)", flush=True)
    ergebnisse["Trend-Pullback"] = bewerte(gold, TrendPullback, runden=runden)

    tabelle = pd.DataFrame(ergebnisse).T
    print()
    with pd.option_context("display.width", 220, "display.max_columns", None):
        print(tabelle.to_string())
    print()
    return tabelle


def main():
    runden = 200
    if "--schnell" in sys.argv:
        runden = 50
    for intervall in ("H_4", "D_1"):
        lauf(intervall, runden)
    print("=" * 104)
    print(lesehilfe())


if __name__ == "__main__":
    main()
