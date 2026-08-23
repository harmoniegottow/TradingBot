"""
richtungstest.py — Warum wirkt die Divergenz nur in EINER Richtung?

Der Fund haelt auf zehn Jahren allen Pruefungen stand, ABER: Gold mit
Silber als Referenz ergibt Profitfaktor 1,95, umgekehrt nur 0,97.
Ein reiner Ausgleichsmechanismus muesste in beide Richtungen wirken.

Zwei konkurrierende Erklaerungen, hier gegeneinander geprueft:

  A) Es ist gar kein Divergenz-Effekt, sondern der EMA150-Trendfilter
     auf Gold. Gold stieg im Zeitraum stark — ein Long-only-Filter in
     einem Bullenmarkt sieht immer gut aus.
     -> Test: Divergenz-Signal durch ZUFALLS-Signale gleicher Anzahl
        ersetzen, Trendfilter behalten. Bleibt das Ergebnis, war es
        der Trendfilter.

  B) Der Effekt ist echt, aber asymmetrisch: Silber ist volatiler und
     laeuft Gold voraus, nicht umgekehrt.
     -> Test: Wenn A widerlegt ist, ist B die verbleibende Erklaerung.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from backtesting import Strategy

from pruefstand import bewerte
from strategien.indikatoren import ema, atr
from strategien.divergenz_gold_silber import (
    DivergenzGoldSilber, divergenz_vorbereiten)
from divergenz_zehnjahre import lade


def nur_trendfilter_klasse(anzahl_signale: int, bars: int, seed: int):
    """Gleiche Trade-Frequenz, gleicher Trendfilter, ZUFAELLIGE Einstiege."""
    wahrsch = anzahl_signale / bars

    class NurTrend(Strategy):
        trend_len = 150
        atr_len = 14
        atr_stop_mult = 2.0
        rr_ratio = 2.0

        def init(self):
            self.ema_trend = self.I(ema, self.data.Close, self.trend_len)
            self.atr_wert = self.I(atr, self.data.High, self.data.Low,
                                   self.data.Close, self.atr_len)
            self.rng = np.random.default_rng(seed)

        def next(self):
            if self.position:
                return
            kurs = self.data.Close[-1]
            if not (kurs > self.ema_trend[-1]):
                return
            if self.rng.random() > wahrsch:
                return
            dist = float(self.atr_wert[-1]) * self.atr_stop_mult
            if not (dist > 0):
                return
            self.buy(size=0.1, sl=kurs - dist, tp=kurs + dist * self.rr_ratio)

    return NurTrend


def main():
    gold = lade("XAUUSD", "H_4")
    silber = lade("XAGUSD", "H_4")
    kombi = divergenz_vorbereiten(gold, silber)
    signale = int(kombi["DivSignal"].sum())

    print("=" * 100)
    print("RICHTUNGSTEST — ist es die Divergenz oder nur der Trendfilter?")
    print("=" * 100)

    echt = bewerte(kombi, DivergenzGoldSilber, runden=150)
    print(f"\nEchte Divergenz auf Gold: PF {echt['PF']}, "
          f"{echt['Trades']} Trades, Urteil {echt['Urteil']}")

    print(f"\nZum Vergleich: gleiche Anzahl ZUFALLS-Einstiege, aber MIT "
          f"demselben EMA150-Trendfilter ({signale} Signale erwartet):")
    pfs = []
    for seed in range(30):
        klasse = nur_trendfilter_klasse(signale, len(kombi), seed)
        z = bewerte(kombi, klasse, mit_permutation=False)
        pfs.append(z["PF"])
    pfs = [p for p in pfs if p == p]
    arr = np.array(pfs)
    print(f"  30 Laeufe: PF Median {np.median(arr):.2f}, "
          f"Spanne {arr.min():.2f} bis {arr.max():.2f}")
    besser = (arr >= echt["PF"]).mean() * 100
    print(f"  Anteil, der die echte Divergenz erreicht oder schlaegt: "
          f"{besser:.1f} %")

    if besser > 20:
        print("\n  -> Der Trendfilter allein erklaert das Ergebnis. "
              "Die Divergenz traegt nichts bei.")
    elif besser < 5:
        print("\n  -> Der Trendfilter allein erklaert es NICHT. "
              "Das Divergenz-Signal traegt eigenstaendig bei.")
    else:
        print("\n  -> Unklar, im Graubereich.")

    # Zusatz: Wie stark ist Gold im Zeitraum ueberhaupt gestiegen?
    g_start, g_ende = float(gold["Close"].iloc[0]), float(gold["Close"].iloc[-1])
    s_start, s_ende = float(silber["Close"].iloc[0]), float(silber["Close"].iloc[-1])
    print(f"\nZum Einordnen des Zeitraums:")
    print(f"  Gold:   {g_start:.0f} -> {g_ende:.0f} "
          f"({(g_ende / g_start - 1) * 100:+.0f} %)")
    print(f"  Silber: {s_start:.2f} -> {s_ende:.2f} "
          f"({(s_ende / s_start - 1) * 100:+.0f} %)")


if __name__ == "__main__":
    main()
