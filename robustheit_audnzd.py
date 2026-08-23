"""
robustheit_audnzd.py — Belastungsprobe fuer den zweiten Fund
(AUDUSD gehandelt, NZDUSD als Referenz, D1).

Gleiche drei Pruefungen wie bei Gold/Silber, damit die Ergebnisse
direkt vergleichbar sind: Zeitfenster, Parameter-Nachbarschaft, Kosten.
"""
from __future__ import annotations

import pandas as pd

from pruefstand import bewerte, KOSTEN_STANDARD
from strategien.divergenz_gold_silber import (
    DivergenzGoldSilber,
    divergenz_vorbereiten,
)
from pruefe_divergenz import lade

GEHANDELT, REFERENZ = "AUDUSD", "NZDUSD"


def kombi(ret_len=20, band_lookback=100, band_mult=1.5):
    return divergenz_vorbereiten(
        lade(GEHANDELT, "D_1"), lade(REFERENZ, "D_1"),
        ret_len=ret_len, band_lookback=band_lookback, band_mult=band_mult,
    )


def main():
    df = kombi()
    print("=" * 100)
    print(f"{GEHANDELT} ~ {REFERENZ}  D_1  {df.index.min().date()} bis "
          f"{df.index.max().date()}  ({len(df)} Kerzen)")
    print("=" * 100)

    print("\n-- Zeitfenster --")
    mitte = len(df) // 2
    drittel = len(df) // 3
    teile = {
        "Gesamt": df,
        "1. Haelfte": df.iloc[:mitte],
        "2. Haelfte": df.iloc[mitte:],
        "1. Drittel": df.iloc[:drittel],
        "2. Drittel": df.iloc[drittel:2 * drittel],
        "3. Drittel": df.iloc[2 * drittel:],
    }
    erg = {n: bewerte(t, DivergenzGoldSilber, runden=100)
           for n, t in teile.items()}
    print(pd.DataFrame(erg).T[
        ["Trades", "PF", "je Einsatz %", "Kaufen+Halten %",
         "Zufall besser %", "Urteil"]].to_string())

    print("\n-- Parameter-Nachbarschaft --")
    erg = {}
    for rl in (10, 20, 30):
        for bm in (1.0, 1.5, 2.0):
            erg[f"ret{rl}/band{bm}"] = bewerte(
                kombi(ret_len=rl, band_mult=bm), DivergenzGoldSilber, runden=60)
    print(pd.DataFrame(erg).T[
        ["Trades", "PF", "je Einsatz %", "Zufall besser %", "Urteil"]].to_string())

    print("\n-- Kosten --")
    erg = {}
    for f in (1, 2, 3):
        erg[f"{f}x Kosten"] = bewerte(
            df, DivergenzGoldSilber, kosten=KOSTEN_STANDARD * f, runden=100)
    print(pd.DataFrame(erg).T[
        ["Trades", "PF", "je Einsatz %", "Zufall besser %", "Urteil"]].to_string())


if __name__ == "__main__":
    main()
