#!/usr/bin/env python3
"""
gold_m15_pruefung.py - Ist der Gold-Fund auf M15 echt? (05.10.2026)

Kandidat: mehrzeitrahmen.py, XAUUSD M15, Ausbruch, CRV 1:3, mit D1/H1-Filter.
PF 1,08, zehn von zwoelf Jahren ueber 1,0.

Zwei Gegenproben:
  1. DRIFT: Gold stieg im Zeitraum stark. Von jedem Trade wird abgezogen,
     was der Grundtrend allein in der Haltedauer gebracht haette.
  2. ZUFALL: Gleicher Filter, gleiche Uhrzeiten, gleicher Stop und gleiches
     Ziel, gleiche Handelshaeufigkeit - aber der Einstiegszeitpunkt ist
     gewuerfelt. Schlaegt der Zufall den echten Wert oft, misst der
     Ausbruch nichts, und der Vorsprung kommt allein vom Filter (oder vom
     Goldanstieg).
     Zusaetzlich mit Zufall OHNE Filter: Dann ist auch die Richtung
     gewuerfelt (Long/Short je halb).
"""
from __future__ import annotations

import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from backtesting import Backtest

sys.path.insert(0, str(Path(__file__).parent))
from kosten import profitfaktor  # noqa: E402
from mehrzeitrahmen import (KAPITAL, Mehrzeitrahmen, kosten_je_seite,  # noqa: E402
                            lade, vorbereiten)

warnings.filterwarnings("ignore")
RUNDEN = 40


class Kandidat(Mehrzeitrahmen):
    einstieg = "Ausbruch"
    rr_ratio = 3.0


class Zufall(Kandidat):
    wahrsch = 0.01
    seed = 0
    mit_filter = True

    def init(self):
        super().init()
        self.rng = np.random.default_rng(self.seed)

    def next(self):
        if self.position:
            return
        if not (self.von_stunde <= self.std[-1] < self.bis_stunde):
            return
        a = float(self.a[-1])
        if not (a > 0) or self.rng.random() >= self.wahrsch:
            return
        kurs = self.data.Close[-1]
        stop = a * self.atr_mult
        if self.mit_filter:
            if self.td[-1] > 0 and self.th[-1] > 0:
                richtung = 1
            elif self.td[-1] < 0 and self.th[-1] < 0:
                richtung = -1
            else:
                return
        else:
            richtung = 1 if self.rng.random() < 0.5 else -1
        if richtung > 0:
            self.buy(size=0.1, sl=kurs - stop, tp=kurs + stop * self.rr_ratio)
        else:
            self.sell(size=0.1, sl=kurs + stop, tp=kurs - stop * self.rr_ratio)


def drift_bereinigt(df, tr):
    std = (df.index[-1] - df.index[0]).total_seconds() / 3600
    mu = np.log(df.Close.iloc[-1] / df.Close.iloc[0]) / std
    h = (pd.to_datetime(tr.ExitTime) - pd.to_datetime(tr.EntryTime)
         ).dt.total_seconds() / 3600
    return tr.PnL - tr.Size * tr.EntryPrice * (np.exp(mu * h) - 1)


def main():
    df = vorbereiten(lade("XAUUSD", "M_15"), 15)
    k = kosten_je_seite("XAUUSD", float(df.Close.iloc[-1]))
    st = Backtest(df, Kandidat, cash=KAPITAL, commission=k,
                  finalize_trades=True).run()
    tr = st["_trades"]
    pf = profitfaktor(tr.PnL)
    print(f"Kandidat: {len(tr)} Trades, PF {pf:.3f}")
    print(f"  drift-bereinigt PF {profitfaktor(drift_bereinigt(df, tr)):.3f}")
    print(f"  Long {profitfaktor(tr.PnL[tr.Size > 0]):.3f}"
          f"  drift-bereinigt {profitfaktor(drift_bereinigt(df, tr[tr.Size > 0])):.3f}")
    print(f"  Short {profitfaktor(tr.PnL[tr.Size < 0]):.3f}"
          f"  drift-bereinigt {profitfaktor(drift_bereinigt(df, tr[tr.Size < 0])):.3f}",
          flush=True)

    # Wahrscheinlichkeit so kalibrieren, dass der Zufall etwa gleich oft
    # handelt: Einstiege je erlaubter, positionsfreier Kerze.
    stunde_ok = (df.Stunde >= 7) & (df.Stunde < 20)
    frei = 1 - float(st["Exposure Time [%]"]) / 100
    for mit_filter in (True, False):
        erlaubt = stunde_ok & (((df.TrendD > 0) & (df.TrendH > 0))
                               | ((df.TrendD < 0) & (df.TrendH < 0))) \
            if mit_filter else stunde_ok
        p = len(tr) / max(1.0, erlaubt.sum() * frei)
        werte, anz = [], []
        for r in range(RUNDEN):
            kl = type(f"Z{r}", (Zufall,), {"wahrsch": p, "seed": r,
                                           "mit_filter": mit_filter})
            z = Backtest(df, kl, cash=KAPITAL, commission=k,
                         finalize_trades=True).run()["_trades"]
            werte.append(profitfaktor(z.PnL))
            anz.append(len(z))
        w = np.array(werte)
        name = "Zufall MIT Filter" if mit_filter else "Zufall OHNE Filter"
        print(f"{name}: {RUNDEN} Laeufe, im Mittel {np.mean(anz):.0f} Trades,"
              f" PF Median {np.median(w):.3f}, bester {w.max():.3f},"
              f" Zufall >= Kandidat in {(w >= pf).mean() * 100:.0f} %",
              flush=True)


if __name__ == "__main__":
    main()
