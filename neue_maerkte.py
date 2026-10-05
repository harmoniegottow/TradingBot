#!/usr/bin/env python3
"""
neue_maerkte.py - Unabhaengige Pruefung der Gold-Befunde (05.10.2026).

VORHER FESTGELEGT, danach nicht mehr veraendert:
Die Regeln stammen unveraendert aus den Gold-Laeufen. Auf NAS100, XAGUSD
und XPTUSD wird NICHTS nachjustiert. Nur so ist das ein echter Test: Was
auf Gold aus vielen Varianten herausgesucht wurde, muss hier ohne Anpassung
bestehen.

  A  Filter allein: D1 EMA50 + H1 EMA200 gleichgerichtet, 07-20 Uhr UTC,
     Einstieg gewuerfelt, ATR-Stop x2, CRV 1:3.
     Gegenprobe: dasselbe mit gewuerfelter Richtung (ohne Filter).
  B  Ausbruch 1:3 im Filter (mehrzeitrahmen.py)
  C  Hammer/FVG/ChoCh, mindestens zwei, Hoch/Tief mit 3 Kerzen, 1:3, in R
  D  nur ChoCh + FVG, sonst wie C - der nachtraeglich gefundene Kandidat

Bestanden gilt, was den Zufall MIT Filter in hoechstens 10 Prozent der Laeufe
unterliegt (also in mindestens 90 Prozent schlaegt) und auch drift-bereinigt
ueber 1,0 bleibt.

    .venv/bin/python neue_maerkte.py XAGUSD
"""
from __future__ import annotations

import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from backtesting import Backtest

sys.path.insert(0, str(Path(__file__).parent))
from gold_m15_pruefung import Zufall  # noqa: E402
from kosten import profitfaktor  # noqa: E402
from mehrzeitrahmen import (KAPITAL, SPREAD, Mehrzeitrahmen,  # noqa: E402
                            kosten_je_seite, lade, vorbereiten)
from smc_einstieg import Setup, ZufallSetup, anreichern, in_r  # noqa: E402

warnings.filterwarnings("ignore")
RUNDEN = 20


def bt(d, kl, k, close=False):
    # Kapital so hoch, dass zehn Prozent davon immer mindestens 100 Einheiten
    # sind. backtesting.py rundet Bruchteile auf ganze Einheiten AB: Bei
    # NAS100 ueber 10.000 Punkten waeren 10 % von 100.000 weniger als ein
    # Kontrakt, der Trade fiele stillschweigend weg (gefunden 05.10.2026,
    # ab Mitte 2020 fehlten alle NAS100-Trades). Profitfaktor und R sind
    # Verhaeltniszahlen und haengen nicht an der Kapitalhoehe.
    cash = max(KAPITAL, float(d.High.max()) * 1000)
    return Backtest(d, kl, cash=cash, commission=k, trade_on_close=close,
                    finalize_trades=True).run()


def drift(d, tr):
    std = (d.index[-1] - d.index[0]).total_seconds() / 3600
    mu = np.log(d.Close.iloc[-1] / d.Close.iloc[0]) / std
    h = (pd.to_datetime(tr.ExitTime) - pd.to_datetime(tr.EntryTime)
         ).dt.total_seconds() / 3600
    return tr.Size * tr.EntryPrice * (np.exp(mu * h) - 1)


def jahre(werte, zeiten):
    j = pd.to_datetime(zeiten).dt.year
    pf = [profitfaktor(werte[j == y]) for y in sorted(j.unique())]
    return sum(p > 1 for p in pf), len(pf)


def zeile(name, tr, werte, ohne_drift=None):
    u, n = jahre(werte, tr.EntryTime)
    t = (f"  {name:24} n {len(tr):5}  PF {profitfaktor(werte):.3f}  "
         f"Long {profitfaktor(werte[tr.Size > 0]):.2f}  "
         f"Short {profitfaktor(werte[tr.Size < 0]):.2f}  Jahre {u}/{n}")
    if ohne_drift is not None:
        t += f"  ohne Drift {profitfaktor(ohne_drift):.3f}"
    print(t, flush=True)


def main():
    sym = sys.argv[1]
    roh = lade(sym, "M_15")
    if roh is None:
        sys.exit(f"{sym}: keine M15-Daten")
    d = vorbereiten(roh, 15)
    k = kosten_je_seite(sym, float(d.Close.iloc[-1]))
    print(f"=== {sym} M15  {d.index[0].date()} bis {d.index[-1].date()}  "
          f"Kauf+Halten {(d.Close.iloc[-1] / d.Close.iloc[0] - 1) * 100:+.0f} %"
          f"  Kosten je Seite {k * 1e4:.2f} bp", flush=True)

    stunde = (d.Stunde >= 7) & (d.Stunde < 20)
    filt = stunde & (((d.TrendD > 0) & (d.TrendH > 0))
                     | ((d.TrendD < 0) & (d.TrendH < 0)))

    # B  Ausbruch
    kl = type("B", (Mehrzeitrahmen,), {"einstieg": "Ausbruch", "rr_ratio": 3.0})
    st = bt(d, kl, k)
    trb = st["_trades"]
    zeile("B Ausbruch 1:3", trb, trb.PnL, trb.PnL - drift(d, trb))

    # A  Filter allein: Zufall mit und ohne Filter, gleiche Haeufigkeit wie B
    frei = 1 - float(st["Exposure Time [%]"]) / 100
    for mit in (True, False):
        maske = filt if mit else stunde
        p = len(trb) / max(1.0, maske.sum() * frei)
        w = []
        for r in range(RUNDEN):
            z = bt(d, type(f"Z{r}", (Zufall,), {"wahrsch": p, "seed": r,
                                                 "mit_filter": mit}), k)["_trades"]
            w.append(profitfaktor(z.PnL))
        w = np.array(w)
        name = "A Zufall MIT Filter" if mit else "A Zufall OHNE Filter"
        print(f"  {name:24} Median {np.median(w):.3f}  bester {w.max():.3f}  "
              f"Ausbruch schlaegt ihn in {(w < profitfaktor(trb.PnL)).mean() * 100:.0f} %",
              flush=True)

    # C und D  Struktur-Einstieg
    da = anreichern(d, 3, sym)
    for name, nur in (("C mind. zwei", None), ("D nur ChoCh+FVG", ("ChoCh", "FVG"))):
        kl = type(name[0], (Setup,), {"rr": 3.0, "nur": nur,
                                      "puffer": SPREAD[sym]})
        st = bt(da, kl, k, close=True)
        tr = st["_trades"]
        if tr.empty:
            print(f"  {name}: keine Trades")
            continue
        r = in_r(tr)
        dist = tr.Tag.str.split("|").str[1].astype(float)
        zeile(name + " (R)", tr, r, r - drift(da, tr) / (tr.Size.abs() * dist))
        stops = tuple(tr.Tag.str.split("|").str[2].astype(float))
        frei = 1 - float(st["Exposure Time [%]"]) / 100
        p = len(tr) / max(1.0, filt.sum() * frei)
        w = []
        for s in range(RUNDEN):
            z = bt(da, type(f"ZS{s}", (ZufallSetup,), {
                "rr": 3.0, "seed": s, "wahrsch": p, "stops_atr": stops}),
                k, close=True)["_trades"]
            w.append(profitfaktor(in_r(z)))
        w = np.array(w)
        print(f"  {'  Zufall mit Filter':24} Median {np.median(w):.3f}  "
              f"bester {w.max():.3f}  Setup schlaegt ihn in "
              f"{(w < profitfaktor(r)).mean() * 100:.0f} %", flush=True)


if __name__ == "__main__":
    main()
