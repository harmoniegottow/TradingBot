"""
robustheit_zehnjahre.py — Belastungsprobe des Divergenz-Funds auf zehn Jahren.

Auf zwei Jahren war der Fund parameter-bruechig (nur 3 von 9 Einstellungen
hielten). Das war der Hauptgrund fuer das Urteil "kein Beleg". Mit zehn
Jahren wird die Frage neu gestellt — und diesmal auch auf den TESTDATEN,
die bei der Parametersuche nie benutzt wurden.

Drei Pruefungen, identisch zu frueher:
  1. Zeitfenster (Haelften, Drittel, einzelne Jahre)
  2. Parameter-Nachbarschaft
  3. Kosten
"""
from __future__ import annotations

import pandas as pd

from pruefstand import bewerte, KOSTEN_STANDARD
from strategien.divergenz_gold_silber import (
    DivergenzGoldSilber,
    divergenz_vorbereiten,
)
from divergenz_zehnjahre import lade


def kombi(ret_len=20, band_lookback=100, band_mult=1.5):
    return divergenz_vorbereiten(
        lade("XAUUSD", "H_4"), lade("XAGUSD", "H_4"),
        ret_len=ret_len, band_lookback=band_lookback, band_mult=band_mult)


def main():
    df = kombi()
    print("=" * 104)
    print(f"XAUUSD~XAGUSD H4  {df.index.min().date()} bis "
          f"{df.index.max().date()}  ({len(df)} Kerzen)")
    print("=" * 104)

    print("\n-- 1. Zeitfenster --")
    n = len(df)
    teile = {
        "Gesamt": df,
        "1. Haelfte": df.iloc[:n // 2],
        "2. Haelfte": df.iloc[n // 2:],
        "1. Drittel": df.iloc[:n // 3],
        "2. Drittel": df.iloc[n // 3:2 * n // 3],
        "3. Drittel": df.iloc[2 * n // 3:],
    }
    erg = {k: bewerte(v, DivergenzGoldSilber, runden=120)
           for k, v in teile.items()}
    print(pd.DataFrame(erg).T[["Trades", "PF", "je Einsatz %",
                               "Kaufen+Halten %", "Zufall besser %",
                               "Urteil"]].to_string())

    print("\n-- 2. Parameter-Nachbarschaft --")
    erg = {}
    for rl in (10, 15, 20, 25, 30):
        for bm in (1.0, 1.5, 2.0):
            erg[f"ret{rl}/band{bm}"] = bewerte(
                kombi(ret_len=rl, band_mult=bm), DivergenzGoldSilber, runden=80)
    tab = pd.DataFrame(erg).T[["Trades", "PF", "je Einsatz %",
                               "Zufall besser %", "Urteil"]]
    print(tab.to_string())
    bestanden = int((tab["Urteil"] == "PRUEFEN").sum())
    print(f"\n  Bestanden: {bestanden} von {len(tab)} Einstellungen")

    print("\n-- 2b. Band-Rueckblick variiert (band_lookback) --")
    erg = {}
    for bl in (50, 100, 150, 200):
        erg[f"lookback{bl}"] = bewerte(
            kombi(band_lookback=bl), DivergenzGoldSilber, runden=80)
    print(pd.DataFrame(erg).T[["Trades", "PF", "je Einsatz %",
                               "Zufall besser %", "Urteil"]].to_string())

    print("\n-- 3. Kosten --")
    erg = {}
    for f in (1, 2, 3, 5):
        erg[f"{f}x Kosten"] = bewerte(
            df, DivergenzGoldSilber, kosten=KOSTEN_STANDARD * f, runden=120)
    print(pd.DataFrame(erg).T[["Trades", "PF", "je Einsatz %",
                               "Zufall besser %", "Urteil"]].to_string())


if __name__ == "__main__":
    main()
