"""
divergenz_paare.py — Uebertraegt die Gold/Silber-Divergenz auf andere
korrelierte Paare. Zweck: War der Fund ein echter Mechanismus oder
Gold-spezifisches Rauschen?

WICHTIG — Auswahl VOR dem Test festgelegt (keine Rosinenpickerei):
Kriterium war Korrelation der Tagesrenditen >= 0,75, also mindestens so
eng wie Gold/Silber selbst (0,786), plus mindestens 1500 gemeinsame Tage.
Aus jeder Instrumenten-Familie wurde das am staerksten korrelierte Paar
genommen, damit nicht dreimal derselbe Index-Cluster gezaehlt wird.
Beide Handelsrichtungen je Paar (A mit Referenz B, und B mit Referenz A),
weil bei Gold/Silber die Wahl "Gold wird gehandelt" ebenfalls gesetzt war.

Parameter bleiben EXAKT die des Fundes (ret_len 20, band 100, mult 1.5,
EMA150, ATR14 x2, RR 2). Es wird nichts nachjustiert — sonst waere das
Ergebnis wieder nur Anpassung an die neuen Daten.
"""
from __future__ import annotations

import sys

import pandas as pd

from pruefstand import bewerte
from strategien.divergenz_gold_silber import (
    DivergenzGoldSilber,
    divergenz_vorbereiten,
)
from pruefe_divergenz import lade

# Vorab festgelegt, siehe korrelationen.py
PAARE = [
    ("XAUUSD", "XAGUSD", 0.786, "Metalle (der Fund selbst)"),
    ("AUDUSD", "NZDUSD", 0.840, "Rohstoffwaehrungen"),
    ("AUDJPY", "CADJPY", 0.806, "Yen-Crosses Rohstoff"),
    ("EURJPY", "GBPJPY", 0.783, "Yen-Crosses Europa"),
    ("EUSTX50", "GER40", 0.960, "Indizes Europa"),
    ("US30", "US500", 0.943, "Indizes USA"),
]

SPALTEN = ["Trades", "PF", "je Einsatz %", "Kaufen+Halten %", "vs K+H fair",
           "Zufall besser %", "Urteil"]


def teste(gehandelt: str, referenz: str, intervall: str, runden: int) -> dict | None:
    try:
        x = lade(gehandelt, intervall)
        y = lade(referenz, intervall)
    except SystemExit:
        return None
    kombi = divergenz_vorbereiten(x, y)
    if len(kombi) < 400:
        return None
    zeile = bewerte(kombi, DivergenzGoldSilber, runden=runden)
    zeile["Ereignisse"] = int(kombi["DivSignal"].sum())
    return zeile


def main():
    intervall = "D_1"
    runden = 50 if "--schnell" in sys.argv else 150

    anzahl_tests = len(PAARE) * 2
    print("=" * 116)
    print("DIVERGENZ AUF ANDEREN PAAREN — haelt der Mechanismus ausserhalb von Gold?")
    print(f"Zeitrahmen: {intervall}   Parameter unveraendert vom Fund")
    print(f"Vorab festgelegt: {len(PAARE)} Paare x 2 Richtungen = {anzahl_tests} Tests")
    print(f"Erwartete Zufallstreffer bei 5-%-Schwelle: "
          f"{anzahl_tests * 0.05:.1f}")
    print("=" * 116)

    ergebnisse = {}
    for a, b, korr, familie in PAARE:
        for gehandelt, referenz in ((a, b), (b, a)):
            name = f"{gehandelt}~{referenz}"
            print(f"  ... {name:<18} ({familie}, r={korr})", flush=True)
            z = teste(gehandelt, referenz, intervall, runden)
            if z is None:
                print(f"      uebersprungen (Daten fehlen)")
                continue
            ergebnisse[name] = z

    tabelle = pd.DataFrame(ergebnisse).T
    spalten = ["Ereignisse"] + [s for s in SPALTEN if s in tabelle.columns]
    tabelle = tabelle[spalten]

    print()
    with pd.option_context("display.width", 240, "display.max_columns", None):
        print(tabelle.to_string())
    print("=" * 116)

    urteile = tabelle["Urteil"].value_counts()
    print("Urteile:", ", ".join(f"{k}: {v}" for k, v in urteile.items()))
    bestanden = list(tabelle.index[tabelle["Urteil"] == "PRUEFEN"])
    print(f"PRUEFEN: {bestanden if bestanden else 'keines'}")
    print(f"Zum Vergleich — rein zufaellig erwartet: {anzahl_tests * 0.05:.1f} Treffer")


if __name__ == "__main__":
    main()
