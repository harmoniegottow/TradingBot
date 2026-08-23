"""
pruefe_v2.py — Bringen die Neuerungen von David-V2 tatsaechlich etwas?

Vergleicht auf denselben Daten:
  - TrendPullback     (V1, nur Long, EMA150, ATR x2, keine Neutralzone)
  - TrendPullbackV2   (Long+Short, EMA200, ATR x1.5, Neutralzone 0.25 ATR)
  - TrendPullbackV2 nur Long   (isoliert die Wirkung der Short-Seite)
  - TrendPullbackV2 ohne Puffer (isoliert die Wirkung der Neutralzone)

Getestet auf den Maerkten, fuer die der Bot konfiguriert ist.
"""
from __future__ import annotations

import pandas as pd

from pruefstand import bewerte
from strategien.trend_pullback import TrendPullback
from strategien.trend_pullback_v2 import TrendPullbackV2
from pruefe_divergenz import lade

SPALTEN = ["Trades", "PF", "je Einsatz %", "Kaufen+Halten %", "vs K+H fair",
           "Zufall besser %", "Urteil"]


class V2NurLong(TrendPullbackV2):
    trade_short = False


class V2OhnePuffer(TrendPullbackV2):
    trend_buffer_atr = 0.0


VARIANTEN = {
    "V1 (nur Long)": TrendPullback,
    "V2 (Long+Short)": TrendPullbackV2,
    "V2 nur Long": V2NurLong,
    "V2 ohne Puffer": V2OhnePuffer,
}

MAERKTE = [("EURUSD", "H_1"), ("USDJPY", "H_1"), ("XAUUSD", "H_4")]


def main():
    for symbol, tf in MAERKTE:
        try:
            df = lade(symbol, tf)
        except SystemExit:
            print(f"{symbol} {tf}: keine Daten, uebersprungen")
            continue

        print("=" * 112)
        print(f"{symbol} {tf}   {df.index.min().date()} bis "
              f"{df.index.max().date()}   ({len(df)} Kerzen)")
        print("=" * 112)

        erg = {}
        for name, klasse in VARIANTEN.items():
            print(f"  ... {name}", flush=True)
            erg[name] = bewerte(df, klasse, runden=150)

        tabelle = pd.DataFrame(erg).T
        tabelle = tabelle[[s for s in SPALTEN if s in tabelle.columns]]
        print()
        with pd.option_context("display.width", 220, "display.max_columns", None):
            print(tabelle.to_string())
        print()


if __name__ == "__main__":
    main()
