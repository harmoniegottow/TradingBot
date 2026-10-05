#!/usr/bin/env python3
"""
Vergleich verschiedener Chance-Risiko-Verhaeltnisse (CRV).

FRAGE
-----
Alle Bausteine arbeiten bisher mit CRV 1:2 (Ziel = zweifache Stopdistanz).
Bringt ein weiteres Ziel mehr? Also 1:3 oder 1:5?

WAS DABEI PASSIERT
------------------
Ein groesseres Ziel wirkt in zwei Richtungen GEGENLAEUFIG:
  + Jeder Gewinner traegt mehr.
  - Weniger Trades erreichen das Ziel, die Trefferquote faellt.
  - Positionen laufen laenger, damit steigen Swapkosten und das Risiko,
    dass eine Gegenbewegung den Stop zuerst holt.

Welche Richtung ueberwiegt, ist eine EMPIRISCHE Frage, keine theoretische.
Die verbreitete Behauptung "hoeheres CRV ist immer besser" unterstellt eine
gleichbleibende Trefferquote. Genau die bleibt aber nicht gleich.

Rechnerisch gilt fuer den Gewinnschwellenwert der Trefferquote:
    CRV 1:2  ->  33,3 % noetig
    CRV 1:3  ->  25,0 % noetig
    CRV 1:5  ->  16,7 % noetig
Die Frage ist, ob die tatsaechliche Trefferquote schneller faellt als
dieser Schwellenwert.

Aufruf:
    ./.venv/bin/python crv_vergleich.py
    ./.venv/bin/python crv_vergleich.py --schnell
"""

from __future__ import annotations

import sys
import warnings
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))

from pruefstand import bewerte                           # noqa: E402
from strategien import REGISTRY                          # noqa: E402
from strategien.trend_pullback_v2 import TrendPullbackV2  # noqa: E402

warnings.filterwarnings("ignore")

DATA = Path(__file__).parent / "data-mt5"
CRV_WERTE = [2.0, 3.0, 5.0]

# ORB bleibt draussen: durch den Zeitstempelversatz in den MT5-Daten sind
# seine Ergebnisse hinfaellig (Befund 12.09.2026). Eine CRV-Variation
# darauf waere das Verfeinern einer falschen Messung.
AUSGESCHLOSSEN = {"ORB"}


def lade(symbol: str, tf: str) -> pd.DataFrame | None:
    pfad = DATA / f"{symbol}_{tf}.csv"
    if not pfad.exists():
        return None
    df = pd.read_csv(pfad, index_col=0, parse_dates=True)
    if df.index.tz is not None:
        df.index = df.index.tz_localize(None)
    return df[["Open", "High", "Low", "Close"]].dropna()


def mit_crv(klasse, crv: float):
    """Erzeugt eine Variante der Strategie mit anderem Ziel."""
    return type(f"{klasse.__name__}_CRV{crv:g}", (klasse,), {"rr_ratio": crv})


def main() -> None:
    schnell = "--schnell" in sys.argv
    runden = 40 if schnell else 150

    maerkte = [("EURUSD", "H_1"), ("USDJPY", "H_1"),
               ("XAUUSD", "H_4"), ("CHFJPY", "H_4")]

    klassen = {k: v for k, v in REGISTRY.items() if k not in AUSGESCHLOSSEN}
    klassen["Trend-Pullback-V2"] = TrendPullbackV2

    print("=" * 100)
    print("CRV-Vergleich: 1:2 gegen 1:3 gegen 1:5")
    print("Zehn Jahre, Spread beidseitig, Zufallsvergleich je Lauf")
    print("ORB ausgeschlossen (Zeitstempelbefund vom 12.09.2026)")
    print("=" * 100)

    zeilen = []
    for symbol, tf in maerkte:
        df = lade(symbol, tf)
        if df is None:
            continue
        print(f"\n--- {symbol} {tf} ---", flush=True)
        for name, basis in klassen.items():
            eintrag = {"Markt": f"{symbol} {tf}", "Strategie": name}
            for crv in CRV_WERTE:
                try:
                    erg = bewerte(df, mit_crv(basis, crv), runden=runden)
                    eintrag[f"PF {crv:g}"] = erg["PF"]
                    eintrag[f"N {crv:g}"] = erg["Trades"]
                except Exception as e:
                    eintrag[f"PF {crv:g}"] = float("nan")
                    eintrag[f"N {crv:g}"] = 0
                    print(f"    {name} CRV {crv:g}: {type(e).__name__}")
            zeilen.append(eintrag)
            pf = [eintrag.get(f"PF {c:g}") for c in CRV_WERTE]
            print(f"  {name:20} PF  "
                  + "  ".join(f"1:{c:g}={p:5.2f}" if p == p else f"1:{c:g}=  n/a"
                              for c, p in zip(CRV_WERTE, pf)), flush=True)

    tab = pd.DataFrame(zeilen)
    tab.to_csv("/tmp/crv_vergleich.csv", index=False)

    print("\n" + "=" * 100)
    print("GESAMT")
    print("=" * 100)
    spalten = ["Markt", "Strategie"] + [f"PF {c:g}" for c in CRV_WERTE] \
              + [f"N {c:g}" for c in CRV_WERTE]
    with pd.option_context("display.width", 220, "display.max_columns", None):
        print(tab[spalten].to_string(index=False,
                                     float_format=lambda x: f"{x:5.2f}"))

    # Auswertung: wie oft gewinnt welches CRV?
    print("\nWelches Ziel liefert je Kombination den hoechsten Profitfaktor?")
    sieger = {c: 0 for c in CRV_WERTE}
    for _, r in tab.iterrows():
        werte = {c: r.get(f"PF {c:g}") for c in CRV_WERTE}
        werte = {c: v for c, v in werte.items() if v == v}
        if werte:
            sieger[max(werte, key=werte.get)] += 1
    for c, n in sieger.items():
        print(f"  CRV 1:{c:g}  gewinnt {n:2} von {len(tab)} Kombinationen")

    print("\nMittlerer Profitfaktor je Ziel:")
    for c in CRV_WERTE:
        s = tab[f"PF {c:g}"].dropna()
        print(f"  CRV 1:{c:g}  Mittel {s.mean():.3f}   "
              f"ueber 1,0: {int((s > 1.0).sum())} von {len(s)}")

    print("\nTabelle gespeichert: /tmp/crv_vergleich.csv")


if __name__ == "__main__":
    main()
