"""
divergenz_paare_h4.py — Uebertragungstest auf ZEHN Jahren H4.

Frueher (zwei Jahre, D1) ergab der Uebertragungstest 1 Treffer von 12 —
also genau die Zufallsrate. Jetzt mit zehn Jahren echten H4-Daten neu.

Auswahl VOR dem Test festgelegt: alle Paare aus den gelieferten neun
Maerkten, deren Tagesrenditen mindestens so eng korrelieren wie
Gold/Silber. Beide Richtungen. Parameter unveraendert.
"""
from __future__ import annotations

import itertools

import pandas as pd

from pruefstand import bewerte
from strategien.divergenz_gold_silber import (
    DivergenzGoldSilber,
    divergenz_vorbereiten,
)
from divergenz_zehnjahre import lade

SYMBOLE = ["XAUUSD", "XAGUSD", "XPTUSD", "EURUSD", "GBPUSD",
           "USDJPY", "CHFJPY", "AUDUSD", "NZDUSD"]

MIN_KORR = 0.70   # vorab gesetzt, knapp unter Gold/Silber

SPALTEN = ["Trades", "PF", "je Einsatz %", "Kaufen+Halten %",
           "vs K+H fair", "Zufall besser %", "Urteil"]


def main():
    daten = {s: lade(s, "H_4") for s in SYMBOLE}

    # Korrelationen auf H4-Renditen
    schluss = pd.DataFrame({s: d["Close"] for s, d in daten.items()})
    ret = schluss.pct_change(fill_method=None)

    paare = []
    for a, b in itertools.combinations(SYMBOLE, 2):
        j = ret[[a, b]].dropna()
        if len(j) < 5000:
            continue
        k = j[a].corr(j[b])
        if k >= MIN_KORR:
            paare.append((a, b, k))
    paare.sort(key=lambda x: -x[2])

    anzahl = len(paare) * 2
    print("=" * 116)
    print("UEBERTRAGUNGSTEST AUF ZEHN JAHREN H4")
    print(f"Korrelationsschwelle {MIN_KORR} -> {len(paare)} Paare "
          f"x 2 Richtungen = {anzahl} Tests")
    print(f"Rein zufaellig erwartete Treffer: {anzahl * 0.05:.1f}")
    print("=" * 116)
    for a, b, k in paare:
        print(f"  {a} / {b}: Korrelation {k:.3f}")
    print()

    erg = {}
    for a, b, k in paare:
        for gehandelt, referenz in ((a, b), (b, a)):
            name = f"{gehandelt}~{referenz}"
            print(f"  ... {name}", flush=True)
            kombi = divergenz_vorbereiten(daten[gehandelt], daten[referenz])
            z = bewerte(kombi, DivergenzGoldSilber, runden=120)
            z["Ereignisse"] = int(kombi["DivSignal"].sum())
            erg[name] = z

    if not erg:
        print("Keine Paare ueber der Korrelationsschwelle.")
        return

    tab = pd.DataFrame(erg).T
    tab = tab[["Ereignisse"] + [s for s in SPALTEN if s in tab.columns]]
    print()
    with pd.option_context("display.width", 240, "display.max_columns", None):
        print(tab.to_string())
    print("=" * 116)
    print("Urteile:", ", ".join(f"{k}: {v}"
                                for k, v in tab["Urteil"].value_counts().items()))
    treffer = list(tab.index[tab["Urteil"] == "PRUEFEN"])
    print(f"PRUEFEN: {treffer if treffer else 'keines'}")
    print(f"Zufaellig erwartet: {anzahl * 0.05:.1f}")


if __name__ == "__main__":
    main()
