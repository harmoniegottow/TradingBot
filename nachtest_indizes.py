"""
nachtest_indizes.py — Korrektur eines Fehlers im eigenen Pruefaufbau.

Im ersten Lauf von divergenz_paare.py meldeten GER40~EUSTX50 und
US30~US500 null Trades. Das war KEIN Strategieergebnis, sondern ein
Fehler meines Aufbaus: bei 100.000 Kapital und Positionsgroesse 0,1
stehen 10.000 je Trade bereit. Bei Indexstaenden von 26.000 bzw. 53.000
reicht das nicht fuer ein ganzes Stueck, und backtesting.py verwirft die
Order ("insufficient margin"). An 91 % bzw. 100 % der Tage war der
Einsatz zu klein.

Hier derselbe Test mit 10 Mio. Kapital, damit die Stueckelung nie bindet.
Alles andere unveraendert.
"""
from __future__ import annotations

import pandas as pd
from backtesting import Backtest

import pruefstand
from pruefstand import bewerte
from strategien.divergenz_gold_silber import (
    DivergenzGoldSilber,
    divergenz_vorbereiten,
)
from pruefe_divergenz import lade

# Kapital hochsetzen, damit auch ein Indexstand von 53.000 handelbar ist.
pruefstand.KAPITAL = 10_000_000

PAARE = [
    ("EUSTX50", "GER40"),
    ("GER40", "EUSTX50"),
    ("US30", "US500"),
    ("US500", "US30"),
]

SPALTEN = ["Trades", "PF", "je Einsatz %", "Kaufen+Halten %", "vs K+H fair",
           "Zufall besser %", "Urteil"]


def main():
    print("=" * 116)
    print("NACHTEST INDIZES — mit 10 Mio. Kapital (Stueckelung bindet nicht mehr)")
    print("=" * 116)
    ergebnisse = {}
    for a, b in PAARE:
        print(f"  ... {a}~{b}", flush=True)
        k = divergenz_vorbereiten(lade(a, "D_1"), lade(b, "D_1"))
        z = bewerte(k, DivergenzGoldSilber, runden=150)
        z["Ereignisse"] = int(k["DivSignal"].sum())
        ergebnisse[f"{a}~{b}"] = z

    tabelle = pd.DataFrame(ergebnisse).T
    tabelle = tabelle[["Ereignisse"] + [s for s in SPALTEN if s in tabelle.columns]]
    print()
    with pd.option_context("display.width", 240, "display.max_columns", None):
        print(tabelle.to_string())


if __name__ == "__main__":
    main()
