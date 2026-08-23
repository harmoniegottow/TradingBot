"""
divergenz_zehnjahre.py — Die Divergenz-Idee auf ZEHN Jahren H4.

Endlich der Test, den die Quelle behauptet hat: "142 Trades auf H4 ueber
10 Jahre". Bisher hatten wir nur zwei Jahre H4 (3090 Kerzen) und mussten
das Urteil offen lassen. Jetzt: 15447 Kerzen.

WICHTIG — Aufteilung VOR dem Rechnen festgelegt:
  Training  = erste 7 Jahre (2016-08 bis ca. 2023-08)
  Test      = letzte 3 Jahre (ca. 2023-08 bis 2026-08)
Die Testdaten werden GENAU EINMAL gerechnet, ohne davor irgendetwas
anzupassen. Parameter bleiben exakt die der Quelle (ret 20, band 100,
mult 1.5, EMA150, ATR14 x2, RR 2). Es wird nichts nachjustiert.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from pruefstand import bewerte, lesehilfe
from strategien.divergenz_gold_silber import (
    DivergenzGoldSilber,
    divergenz_vorbereiten,
)

DATA = Path(__file__).parent / "data-mt5"

SPALTEN = ["Trades", "PF", "je Einsatz %", "Kaufen+Halten %", "vs K+H fair",
           "Ruecklauf %", "Zufall besser %", "Urteil"]


def lade(symbol: str, tf: str) -> pd.DataFrame:
    df = pd.read_csv(DATA / f"{symbol}_{tf}.csv", index_col=0, parse_dates=True)
    if df.index.tz is not None:
        df.index = df.index.tz_localize(None)
    return df[["Open", "High", "Low", "Close"]].dropna()


def main():
    gold = lade("XAUUSD", "H_4")
    silber = lade("XAGUSD", "H_4")
    kombi = divergenz_vorbereiten(gold, silber)

    # Feste Aufteilung nach Datum, VOR jedem Rechnen bestimmt.
    grenze = kombi.index.min() + pd.Timedelta(days=365 * 7)
    training = kombi[kombi.index < grenze]
    test = kombi[kombi.index >= grenze]

    print("=" * 112)
    print("DIVERGENZ GOLD/SILBER — ZEHN JAHRE H4 (echte Broker-Daten)")
    print(f"Gesamt:   {len(kombi)} Kerzen, {kombi.index.min().date()} "
          f"bis {kombi.index.max().date()}")
    print(f"Training: {len(training)} Kerzen bis {grenze.date()} "
          f"({int(kombi['DivSignal'][kombi.index < grenze].sum())} Ereignisse)")
    print(f"Test:     {len(test)} Kerzen ab {grenze.date()} "
          f"({int(kombi['DivSignal'][kombi.index >= grenze].sum())} Ereignisse)")
    print("Parameter unveraendert von der Quelle. Test wird EINMAL gerechnet.")
    print("=" * 112)

    erg = {}
    for name, df in (("Gesamt 10 Jahre", kombi),
                     ("Training 7 J.", training),
                     ("TEST 3 J.", test)):
        print(f"  ... {name}", flush=True)
        erg[name] = bewerte(df, DivergenzGoldSilber, runden=200)

    tabelle = pd.DataFrame(erg).T[SPALTEN]
    print()
    with pd.option_context("display.width", 240, "display.max_columns", None):
        print(tabelle.to_string())
    print("=" * 112)
    print(lesehilfe())


if __name__ == "__main__":
    main()
