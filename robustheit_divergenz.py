"""
robustheit_divergenz.py — Haelt der Divergenz-Fund einer Belastungsprobe stand?

Ein einzelnes gruenes Urteil ist kein Beleg. Drei Pruefungen:
  1. Zeitfenster: gewinnt die Strategie in BEIDEN Haelften, oder haengt
     alles an einer guten Phase?
  2. Parameter-Nachbarschaft: bleiben benachbarte Werte aehnlich gut?
     Ein Fund, der nur bei exakt einer Einstellung funktioniert, ist
     an die Daten angepasst und nicht echt.
  3. Kosten: haelt der Fund auch bei doppelten Handelskosten?
"""
from __future__ import annotations

import pandas as pd

from pruefstand import bewerte, KOSTEN_STANDARD
from strategien.divergenz_gold_silber import (
    DivergenzGoldSilber,
    divergenz_vorbereiten,
)
from pruefe_divergenz import lade


def kombi(intervall: str, ret_len=20, band_lookback=100, band_mult=1.5):
    gold = lade("XAUUSD", intervall)
    silber = lade("XAGUSD", intervall)
    return divergenz_vorbereiten(
        gold, silber, ret_len=ret_len,
        band_lookback=band_lookback, band_mult=band_mult,
    )


def zeile(df, runden=100, **kw):
    return bewerte(df, DivergenzGoldSilber, runden=runden, **kw)


def main():
    for intervall in ("H_4", "D_1"):
        df = kombi(intervall)
        print("=" * 100)
        print(f"XAUUSD {intervall}  {df.index.min().date()} bis "
              f"{df.index.max().date()}  ({len(df)} Kerzen)")
        print("=" * 100)

        # --- 1. Zeitfenster-Split -------------------------------------
        mitte = len(df) // 2
        teile = {
            "Gesamt": df,
            "1. Haelfte": df.iloc[:mitte],
            "2. Haelfte": df.iloc[mitte:],
        }
        erg = {}
        for name, teil in teile.items():
            erg[name] = zeile(teil)
        print("\n-- Zeitfenster --")
        print(pd.DataFrame(erg).T[
            ["Trades", "PF", "je Einsatz %", "Kaufen+Halten %",
             "Zufall besser %", "Urteil"]].to_string())

        # --- 2. Parameter-Nachbarschaft -------------------------------
        print("\n-- Parameter-Nachbarschaft (Gesamtzeitraum) --")
        erg = {}
        for rl in (10, 20, 30):
            for bm in (1.0, 1.5, 2.0):
                d = kombi(intervall, ret_len=rl, band_mult=bm)
                erg[f"ret{rl}/band{bm}"] = zeile(d, runden=60)
        print(pd.DataFrame(erg).T[
            ["Trades", "PF", "je Einsatz %", "Zufall besser %",
             "Urteil"]].to_string())

        # --- 3. Kostenempfindlichkeit ---------------------------------
        print("\n-- Kosten --")
        erg = {}
        for faktor in (1, 2, 3):
            erg[f"{faktor}x Kosten"] = zeile(
                df, kosten=KOSTEN_STANDARD * faktor
            )
        print(pd.DataFrame(erg).T[
            ["Trades", "PF", "je Einsatz %", "Zufall besser %",
             "Urteil"]].to_string())
        print()


if __name__ == "__main__":
    main()
