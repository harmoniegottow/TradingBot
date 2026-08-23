"""
trockenlauf.py — Prueft die Signal-Logik eines Beispiel-Bots OHNE MT5.

Die Datei strategy.py der Bots braucht nur pandas und config, keine
Broker-Anbindung. Damit laesst sich hier auf dem Server pruefen, ob die
Logik laeuft und wie oft sie ueberhaupt anschlaegt — bevor irgendetwas
an ein echtes Terminal angeschlossen wird.

Aufruf aus dem jeweiligen Bot-Ordner:
    python3 trockenlauf.py <CSV-Pfad>
"""
from __future__ import annotations

import sys

import pandas as pd

import config
import strategy


def lade(pfad: str) -> pd.DataFrame:
    df = pd.read_csv(pfad, index_col=0, parse_dates=True)
    df = df.rename(columns=str.lower)
    return df[["open", "high", "low", "close"]].dropna()


def main():
    pfad = sys.argv[1]
    df = lade(pfad)
    print(f"Daten: {pfad}")
    print(f"  {len(df)} Kerzen, {df.index.min().date()} bis {df.index.max().date()}")

    mindest = getattr(strategy, "MIN_BARS", 400)
    print(f"  Mindestkerzen laut Strategie: {mindest}")
    print(f"  BARS_HISTORY laut config: {config.BARS_HISTORY}")

    # Fenster wie im Livebetrieb durchschieben: der Bot sieht immer nur
    # die letzten BARS_HISTORY Kerzen und prueft die zuletzt geschlossene.
    fenster = config.BARS_HISTORY
    signale = []
    richtungen = {}
    for i in range(fenster, len(df) + 1):
        teil = df.iloc[i - fenster:i]
        sig = strategy.check_signal(teil)
        if sig:
            r = sig.get("dir", "long")
            richtungen[r] = richtungen.get(r, 0) + 1
            signale.append((teil.index[-1], r, sig))

    print(f"\nSignale im gesamten Zeitraum: {len(signale)}")
    if richtungen:
        print("  nach Richtung:", ", ".join(f"{k}: {v}" for k, v in richtungen.items()))
    if signale:
        spanne_tage = (df.index[-1] - df.index[fenster]).days or 1
        print(f"  Haeufigkeit: rund alle {spanne_tage / len(signale):.0f} Tage eines")
        print("\nLetzte 5 Signale:")
        for zeit, r, sig in signale[-5:]:
            print(f"  {zeit}  {r.upper():<5}  Stop-Abstand {sig['stop_dist']:.5f}")
    else:
        print("  KEINE Signale — Logik laeuft, schlaegt hier aber nie an.")

    # Aktueller Marktzustand auf dem letzten Fenster
    letzte = df.iloc[-config.BARS_HISTORY:]
    st = strategy.market_status(letzte)
    print(f"\nZustand am Ende der Daten: {st}")


if __name__ == "__main__":
    main()
