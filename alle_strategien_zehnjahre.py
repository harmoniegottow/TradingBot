"""
alle_strategien_zehnjahre.py — Alle Bausteine der Registry auf zehn Jahren.

Die bisherigen Urteile beruhten auf ZWEI Jahren. Bei der Divergenz hat
sich gezeigt, dass ein "parameter-bruechig"-Urteil auf kurzer Strecke ein
Stichprobenproblem sein kann und kein Befund. Also werden jetzt alle
Strategien mit den zehn Jahren echter Broker-Daten neu geprueft.

Ausgabe: eine Tabelle je Markt, dazu am Ende eine Zusammenfassung,
was sich gegenueber den Zwei-Jahres-Urteilen geaendert hat.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

from pruefstand import bewerte, lesehilfe
from strategien import REGISTRY
from strategien.trend_pullback_v2 import TrendPullbackV2

DATA = Path(__file__).parent / "data-mt5"

SPALTEN = ["Trades", "PF", "je Einsatz %", "Kaufen+Halten %", "vs K+H fair",
           "Ruecklauf %", "Zufall besser %", "Urteil"]

# Was auf zwei Jahren EURUSD H1 herauskam (aus fruehereren Laeufen),
# damit die Veraenderung sichtbar wird.
FRUEHER_EURUSD_H1 = {
    "Trend-Pullback": "verliert (PF 0.63)",
    "MA-Kreuzung": "verliert (PF 0.84)",
    "ORB": "verliert (PF 0.68)",
    "Bullish-Engulfing": "verliert (PF 0.55)",
}


def lade(symbol: str, tf: str) -> pd.DataFrame:
    pfad = DATA / f"{symbol}_{tf}.csv"
    if not pfad.exists():
        return None
    df = pd.read_csv(pfad, index_col=0, parse_dates=True)
    if df.index.tz is not None:
        df.index = df.index.tz_localize(None)
    return df[["Open", "High", "Low", "Close"]].dropna()


def main():
    schnell = "--schnell" in sys.argv
    runden = 50 if schnell else 150

    maerkte = [("EURUSD", "H_1"), ("USDJPY", "H_1"),
               ("XAUUSD", "H_4"), ("CHFJPY", "H_4")]

    klassen = dict(REGISTRY)
    klassen["Trend-Pullback-V2"] = TrendPullbackV2

    alle = {}
    for symbol, tf in maerkte:
        df = lade(symbol, tf)
        if df is None:
            print(f"{symbol} {tf}: keine Daten, uebersprungen")
            continue

        print("=" * 112)
        print(f"{symbol} {tf}   {df.index.min().date()} bis "
              f"{df.index.max().date()}   ({len(df)} Kerzen)")
        print("=" * 112)

        erg = {}
        for name, klasse in klassen.items():
            print(f"  ... {name}", flush=True)
            erg[name] = bewerte(df, klasse, runden=runden)

        tab = pd.DataFrame(erg).T[SPALTEN]
        print()
        with pd.option_context("display.width", 240, "display.max_columns", None):
            print(tab.to_string())
        print()
        alle[f"{symbol} {tf}"] = tab

    print("=" * 112)
    print("ZUSAMMENFASSUNG — welche Strategie besteht wo?")
    print("=" * 112)
    for markt, tab in alle.items():
        gut = list(tab.index[tab["Urteil"] == "PRUEFEN"])
        print(f"  {markt:<14} PRUEFEN: {', '.join(gut) if gut else 'keine'}")

    print("\nVergleich zu den frueheren Zwei-Jahres-Urteilen (EURUSD H1):")
    eur = alle.get("EURUSD H_1")
    if eur is not None:
        for name, frueher in FRUEHER_EURUSD_H1.items():
            if name in eur.index:
                jetzt = f"{eur.loc[name, 'Urteil']} (PF {eur.loc[name, 'PF']})"
                pfeil = "->" if jetzt.split()[0] != frueher.split()[0] else "  "
                print(f"  {name:<20} frueher {frueher:<22} {pfeil} jetzt {jetzt}")

    print()
    print(lesehilfe())


if __name__ == "__main__":
    main()
