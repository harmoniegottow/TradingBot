"""
vergleich.py — Testet ALLE Strategien aus strategien/REGISTRY nach demselben
Massstab und stellt die Kennzahlen nebeneinander.

Seit 22.08.2026 laeuft jede Strategie zwingend durch pruefstand.py, also gegen
Zufall UND gegen Kaufen-und-Halten. Grund: der Trend-Pullback sah auf Gold H1
mit Profitfaktor 1,42 gut aus, war aber nachweislich nur der Aufwaertstrend
(Gold selbst +83,7 %, Zufallseinstiege im Mittel PF 1,15). Ein Profitfaktor
allein ist wertlos.

Aufruf:
    python vergleich.py                      # EURUSD H_1
    python vergleich.py XAUUSD H_1           # anderes Symbol / Zeitrahmen
    python vergleich.py XAUUSD H_1 --schnell # ohne Permutationstest (schnell)
"""
from pathlib import Path
import sys

import pandas as pd

from pruefstand import KOSTEN_STANDARD, bewerte, lesehilfe
from strategien import REGISTRY

DATA_DIR = Path(__file__).parent / "data"

SPALTEN = [
    "Trades",
    "PF",
    "Ergebnis %",
    "Einsatz %",
    "je Einsatz %",
    "Kaufen+Halten %",
    "vs K+H fair",
    "Ruecklauf %",
    "Zufall PF",
    "Zufall besser %",
    "Urteil",
]


def lade_csv(symbol: str, intervall: str) -> pd.DataFrame:
    pfad = DATA_DIR / f"{symbol}_{intervall}.csv"
    if not pfad.exists():
        vorhanden = sorted(p.stem for p in DATA_DIR.glob("*.csv"))
        raise SystemExit(
            f"Datei fehlt: {pfad}\n"
            f"Vorhanden: {', '.join(vorhanden) or 'nichts'}\n"
            f"Laden mit: python3 daten_mcp.py {symbol} {intervall} 730"
        )
    df = pd.read_csv(pfad, index_col=0, parse_dates=True)
    return df[["Open", "High", "Low", "Close"]].dropna()


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    schnell = "--schnell" in sys.argv
    symbol = args[0] if args else "EURUSD"
    intervall = args[1] if len(args) > 1 else "H_1"

    df = lade_csv(symbol, intervall)
    zeitraum = f"{df.index.min().date()} bis {df.index.max().date()}"

    print("=" * 104)
    print("STRATEGIE-VERGLEICH  (gleiche Daten, gleiche Kosten, gleicher Massstab)")
    print(f"Symbol: {symbol}   Zeitrahmen: {intervall}   Zeitraum: {zeitraum}")
    print(f"Kerzen: {len(df)}   Kosten: {KOSTEN_STANDARD} (~2 Pips/Trade)")
    if schnell:
        print("SCHNELLMODUS: ohne Permutationstest, Spalten 'Zufall' fehlen.")
    print("=" * 104)

    ergebnisse = {}
    for name, klasse in REGISTRY.items():
        print(f"  ... teste {name}", flush=True)
        ergebnisse[name] = bewerte(df, klasse, mit_permutation=not schnell)

    tabelle = pd.DataFrame(ergebnisse).T
    spalten = [s for s in SPALTEN if s in tabelle.columns]
    tabelle = tabelle[spalten]

    print()
    with pd.option_context("display.width", 200, "display.max_columns", None):
        print(tabelle.to_string())
    print("=" * 104)
    print(lesehilfe())
    print("=" * 104)

    bestanden = [n for n, z in ergebnisse.items() if z["Urteil"] == "PRUEFEN"]
    if bestanden:
        print(f"Weiter ansehen: {', '.join(bestanden)}")
    else:
        print("Ergebnis: KEINE Strategie haelt allen drei Pruefungen stand.")
        print("Das ist der Normalfall. Jetzt NICHT die Parameter passend drehen,")
        print("bis eine Zahl gefaellt - das waere Kurvenanpassung und faellt live um.")
    return tabelle


if __name__ == "__main__":
    main()
