"""Warum null Trades bei den Indizes? Harnisch-Artefakt oder echt?"""
import pandas as pd

from pruefe_divergenz import lade
from strategien.divergenz_gold_silber import divergenz_vorbereiten

for a, b in (("GER40", "EUSTX50"), ("US30", "US500"), ("AUDUSD", "NZDUSD")):
    x = lade(a, "D_1")
    y = lade(b, "D_1")
    k = divergenz_vorbereiten(x, y)
    sig = k[k["DivSignal"]]
    print(f"{a}~{b}: {len(k)} Kerzen, {len(sig)} Divergenz-Ereignisse, "
          f"Kurs {k['Close'].iloc[-1]:.1f}")
    # Positionsgroesse 0.1 = 10 % von 100.000 = 10.000 Geldeinheiten
    # Wie viele ganze Kontrakte sind das beim jeweiligen Kurs?
    stueck = 10000 / k["Close"]
    print(f"   Stueckzahl bei 10.000 Einsatz: min {stueck.min():.2f}, "
          f"max {stueck.max():.2f}, aktuell {stueck.iloc[-1]:.2f}")
    print(f"   -> unter 1 Stueck an {(stueck < 1).mean() * 100:.1f} % der Tage")
