"""
pruefe_impuls_usdjpy.py — Ist der eine Treffer echt oder Zufall?

Impuls-Fifty auf USDJPY H1 kam als einziges von 24 Tests auf PRUEFEN
(PF 1.16, 119 Trades). Bei 24 Tests sind rein zufaellig 1,2 Treffer zu
erwarten — dieser eine ist also genau das, was Zufall produziert.

Bevor irgendjemand darauf setzt, dieselbe Belastungsprobe wie bei der
Divergenz: Zeitfenster, Parameter-Nachbarschaft, Kosten. Zusaetzlich
der Uebertragungstest auf die anderen Maerkte.
"""
from __future__ import annotations

import pandas as pd

from pruefstand import bewerte, KOSTEN_STANDARD
from strategien.impuls_fifty import ImpulsFifty
from alle_strategien_zehnjahre import lade


def main():
    df = lade("USDJPY", "H_1")
    print("=" * 100)
    print(f"IMPULS-FIFTY auf USDJPY H1 — der einzige Treffer von 24 Tests")
    print(f"{df.index.min().date()} bis {df.index.max().date()}, "
          f"{len(df)} Kerzen")
    print("=" * 100)

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
    erg = {k: bewerte(v, ImpulsFifty, runden=100) for k, v in teile.items()}
    print(pd.DataFrame(erg).T[["Trades", "PF", "je Einsatz %",
                               "Kaufen+Halten %", "Zufall besser %",
                               "Urteil"]].to_string())

    print("\n-- 2. Uebertragung auf andere Maerkte --")
    erg = {}
    for sym, tf in (("EURUSD", "H_1"), ("GBPUSD", "H_1"), ("AUDUSD", "H_1"),
                    ("NZDUSD", "H_1"), ("CHFJPY", "H_1"), ("XAUUSD", "H_1")):
        d = lade(sym, tf)
        if d is None:
            continue
        erg[f"{sym} {tf}"] = bewerte(d, ImpulsFifty, runden=100)
    print(pd.DataFrame(erg).T[["Trades", "PF", "je Einsatz %",
                               "Zufall besser %", "Urteil"]].to_string())

    print("\n-- 3. Kosten --")
    erg = {}
    for f in (1, 2, 3):
        erg[f"{f}x Kosten"] = bewerte(df, ImpulsFifty,
                                      kosten=KOSTEN_STANDARD * f, runden=100)
    print(pd.DataFrame(erg).T[["Trades", "PF", "je Einsatz %",
                               "Zufall besser %", "Urteil"]].to_string())


if __name__ == "__main__":
    main()
