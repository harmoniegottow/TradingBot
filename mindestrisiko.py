"""
mindestrisiko.py — Welche Maerkte sind mit KLEINEM Kapital ueberhaupt handelbar?

Hintergrund: Das Demokonto hat 50.000 EUR, das spaetere Echtgeldkonto
soll 500 bis 1.000 EUR haben. Bei 0,5 % Risiko sind das 250 EUR gegen
2,50 bis 5 EUR pro Trade — Faktor 50 bis 100 Unterschied.

Das ist keine Kleinigkeit: Das Mindest-Lot betraegt ueberall 0,01. Wenn
schon 0,01 Lot mehr riskiert als das gesamte Zielrisiko, ist der Markt
mit kleinem Konto NICHT handelbar — der Bot muesste jeden Trade ablehnen.

Hier wird das vorab ausgerechnet, aus dem tatsaechlichen ATR unserer
Kursdaten. Kontraktgroessen nach Standard (1 Lot):
  FX-Paare  = 100.000 Einheiten der Basiswaehrung
  XAUUSD    = 100 Unzen
  XAGUSD    = 5.000 Unzen
  XPTUSD    = 100 Unzen
"""
from __future__ import annotations

import pandas as pd

from pruefe_divergenz import lade
from strategien.indikatoren import atr

# 1 Lot = wie viele Einheiten?
KONTRAKT = {
    "XAUUSD": 100, "XAGUSD": 5000, "XPTUSD": 100,
    "EURUSD": 100_000, "GBPUSD": 100_000, "USDJPY": 100_000,
    "CHFJPY": 100_000, "AUDUSD": 100_000, "NZDUSD": 100_000,
}

# Grobe Umrechnung in EUR (Kurse Stand der Daten, reicht fuer die
# Groessenordnung — es geht um Faktor 2 oder 50, nicht um Cent).
IN_EUR = {"USD": 0.92, "JPY": 0.0060, "EUR": 1.0}

WAEHRUNG = {
    "XAUUSD": "USD", "XAGUSD": "USD", "XPTUSD": "USD",
    "EURUSD": "USD", "GBPUSD": "USD", "AUDUSD": "USD", "NZDUSD": "USD",
    "USDJPY": "JPY", "CHFJPY": "JPY",
}

ATR_STOP_MULT = 1.5
MIN_LOT = 0.01

MAERKTE = [
    ("EURUSD", "H_1"), ("GBPUSD", "D_1"), ("USDJPY", "H_1"),
    ("AUDUSD", "D_1"), ("NZDUSD", "D_1"), ("CHFJPY", "H_4"),
    ("XAUUSD", "H_4"), ("XAGUSD", "H_4"), ("XPTUSD", "D_1"),
]

KAPITAL = [1000, 5000, 50_000]
RISIKO_PCT = 0.5


def main():
    print("=" * 100)
    print("MINDESTRISIKO JE MARKT — reicht das Kapital fuer das kleinste Lot?")
    print(f"Annahme: Stop = ATR x {ATR_STOP_MULT}, Mindest-Lot {MIN_LOT}, "
          f"Risiko {RISIKO_PCT} % vom Kapital")
    print("=" * 100)
    print(f"{'Markt':<9} {'TF':<5} {'ATR':>10} {'Stop':>10} "
          f"{'Risiko 0.01 Lot':>16}   {'1.000':>8} {'5.000':>8} {'50.000':>8}")
    print("-" * 100)

    zeilen = []
    for symbol, tf in MAERKTE:
        try:
            df = lade(symbol, tf)
        except SystemExit:
            continue
        a = pd.Series(atr(df["High"], df["Low"], df["Close"], 14)).dropna()
        if a.empty:
            continue
        atr_typisch = float(a.median())
        stop = atr_typisch * ATR_STOP_MULT

        einheiten = KONTRAKT[symbol] * MIN_LOT
        risiko_quote = stop * einheiten          # in Kurswaehrung
        risiko_eur = risiko_quote * IN_EUR[WAEHRUNG[symbol]]

        spalten = []
        for kap in KAPITAL:
            ziel = kap * RISIKO_PCT / 100
            spalten.append("ja" if risiko_eur <= ziel else
                           f"{risiko_eur / ziel:.0f}x zu gross")

        print(f"{symbol:<9} {tf:<5} {atr_typisch:>10.4f} {stop:>10.4f} "
              f"{risiko_eur:>13.2f} EUR   "
              f"{spalten[0]:>8} {spalten[1]:>8} {spalten[2]:>8}")
        zeilen.append((symbol, risiko_eur))

    print("-" * 100)
    print("\nLesart: 'ja' = mit dem kleinsten Lot bleibt das Risiko im Rahmen.")
    print("'Nx zu gross' = schon das kleinste Lot riskiert das N-fache des Ziels.")
    print("\nBei 1.000 EUR Kapital sind 0,5 % genau 5 EUR Risiko pro Trade.")
    handelbar = [s for s, r in zeilen if r <= 5]
    print(f"Handelbar bei 1.000 EUR: {', '.join(handelbar) if handelbar else 'KEINER'}")


if __name__ == "__main__":
    main()
