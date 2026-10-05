#!/usr/bin/env python3
"""
session_pruefung.py - ChoCh + FVG nur in den Hauptsitzungen, ohne Uebernacht.

Vorgabe Dominique (05.10.2026):
  Einstieg nur in zwei Fenstern, deutsche Zeit (Europe/Berlin, mit
  Sommer- und Winterzeit):
      Tokio      06:30 bis 09:00
      New York   15:30 bis 18:00
  Kein Trade ueber Nacht.

Umsetzung:
  - Einstieg zum Schluss einer M15-Kerze, die komplett im Fenster liegt
    (Kerzenbeginn 15:30 bis 17:45, Schluss spaetestens 18:00).
  - Struktur (ChoCh) und FVG werden weiter auf ALLEN Kerzen erkannt.
    Nur der Einstieg ist zeitlich begrenzt.
  - Ausstieg spaetestens 21:45 deutscher Zeit. Das liegt vor dem
    Rollover des Brokers (21:00 UTC = 22:00 Winter, 23:00 Sommer), es
    faellt also nie Swap an. Zusaetzlich glattstellen, falls der Tag
    wechselt (Datenluecke).
  - Variante "bis Sitzungsende": glattstellen um 09:00 bzw. 18:00.

Regeln sonst unveraendert: ChoCh + FVG (genau diese Kombination), Hoch/Tief
mit drei Kerzen, D1/H1-Filter, CRV 1:3, Stop am Strukturpunkt plus Spread,
Bewertung in R.

Vergleich:
  Basis       wie bisher: Einstieg 07-20 Uhr UTC, Halten ueber Nacht erlaubt
              (ohne Swap gerechnet, also eher zu guenstig)
  Sitzung     Fenster wie oben, raus spaetestens 21:45
  Sitzungsende Fenster wie oben, raus am Fensterende
  Zufall      gleiche Fenster, gleicher Ausstieg, gleiche Haeufigkeit und
              Stopweiten, Zeitpunkt gewuerfelt (20 Laeufe)

    .venv/bin/python session_pruefung.py XAUUSD
"""
from __future__ import annotations

import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from kosten import profitfaktor  # noqa: E402
from mehrzeitrahmen import SPREAD, kosten_je_seite, lade, vorbereiten  # noqa: E402
from neue_maerkte import bt, drift  # noqa: E402
from smc_einstieg import Setup, ZufallSetup, _w, anreichern, in_r  # noqa: E402

warnings.filterwarnings("ignore")
RUNDEN = 20
TOKIO = (6 * 60 + 30, 9 * 60)
NEW_YORK = (15 * 60 + 30, 18 * 60)
SCHLUSS = 21 * 60 + 45


def zeit_spalten(d):
    berlin = d.index.tz_localize("UTC").tz_convert("Europe/Berlin")
    d = d.copy()
    d["MinB"] = berlin.hour * 60 + berlin.minute
    d["TagB"] = np.array([t.toordinal() for t in berlin.date])
    # Letzte Kerze des Handelstags. Nutzt das Wissen, wann der Markt an
    # diesem Tag schliesst - an Feiertagen mit verkuerztem Handel (Labor Day,
    # Black Friday) vor 21:45. Ein echter Bot kennt den Feiertagskalender im
    # Voraus, das ist also kein Blick in die Zukunft.
    tag = d["TagB"].to_numpy()
    d["LetzteB"] = np.append(tag[1:] != tag[:-1], True).astype(float)
    return d


class SitzungMixin:
    fenster = (TOKIO, NEW_YORK)
    bis_fensterende = False

    def init(self):
        super().init()
        self._MinB = self.I(_w, self.data.MinB, plot=False)
        self._TagB = self.I(_w, self.data.TagB, plot=False)
        self._LetzteB = self.I(_w, self.data.LetzteB, plot=False)
        self.ende = None
        self.tag = None

    def _fenster_jetzt(self):
        m = self._MinB[-1]
        for a, b in self.fenster:
            if a <= m and m + 15 <= b:
                return b
        return None

    def _erlaubt(self):
        if self._fenster_jetzt() is None:
            return 0
        if self._TrendD[-1] > 0 and self._TrendH[-1] > 0:
            return 1
        if self._TrendD[-1] < 0 and self._TrendH[-1] < 0:
            return -1
        return 0

    def next(self):
        m_schluss = self._MinB[-1] + 15
        if self.position:
            if (self._TagB[-1] != self.tag or m_schluss >= self.ende
                    or self._LetzteB[-1] > 0):
                self.position.close()
            return
        vorher = len(self.orders)
        b = self._fenster_jetzt()
        if self._LetzteB[-1] > 0:
            return
        super().next()
        if len(self.orders) > vorher:
            self.ende = b if self.bis_fensterende else SCHLUSS
            self.tag = self._TagB[-1]


class Sitzung(SitzungMixin, Setup):
    pass


class ZufallSitzung(SitzungMixin, ZufallSetup):
    pass


def ausstiegsart(tr):
    tol = (tr.SL - tr.EntryPrice).abs() * 1e-6 + 1e-9
    sl = (tr.ExitPrice - tr.SL).abs() <= tol * 1e3
    tp = (tr.ExitPrice - tr.TP).abs() <= tol * 1e3
    return sl, tp


def zeile(name, d, tr):
    if tr.empty:
        print(f"  {name:22} keine Trades", flush=True)
        return float("nan")
    r = in_r(tr)
    dist = tr.Tag.str.split("|").str[1].astype(float)
    rd = r - drift(d, tr) / (tr.Size.abs() * dist)
    j = pd.to_datetime(tr.EntryTime).dt.year
    pfj = [profitfaktor(r[j == y]) for y in sorted(j.unique())]
    sl, tp = ausstiegsart(tr)
    pf = profitfaktor(r)
    print(f"  {name:22} n {len(tr):4} ({len(tr) / j.nunique():3.0f}/J)  "
          f"PF R {pf:.3f}  ohne Drift {profitfaktor(rd):.3f}  "
          f"Long {profitfaktor(r[tr.Size > 0]):.2f}  "
          f"Short {profitfaktor(r[tr.Size < 0]):.2f}  "
          f"Jahre {sum(p > 1 for p in pfj)}/{len(pfj)}  "
          f"Ausstieg Stop {sl.mean() * 100:.0f} % Ziel {tp.mean() * 100:.0f} % "
          f"Zeit {(~sl & ~tp).mean() * 100:.0f} %", flush=True)
    return pf


def nach_fenster(d, tr):
    t = pd.to_datetime(tr.EntryTime).dt.tz_localize("UTC").dt.tz_convert(
        "Europe/Berlin")
    m = t.dt.hour * 60 + t.dt.minute
    r = in_r(tr)
    for name, (a, b) in (("Tokio", TOKIO), ("New York", NEW_YORK)):
        # EntryTime ist der Kerzenbeginn der Folgekerze bzw. die Schlusszeit
        maske = (m >= a) & (m <= b)
        print(f"      davon {name:9} n {int(maske.sum()):4}  "
              f"PF R {profitfaktor(r[maske]):.3f}  "
              f"Long {profitfaktor(r[maske & (tr.Size > 0)]):.2f}  "
              f"Short {profitfaktor(r[maske & (tr.Size < 0)]):.2f}", flush=True)


def main():
    sym = sys.argv[1]
    d = vorbereiten(lade(sym, "M_15"), 15)
    k = kosten_je_seite(sym, float(d.Close.iloc[-1]))
    da = zeit_spalten(anreichern(d, 3, sym))
    print(f"=== {sym} M15  {da.index[0].date()} bis {da.index[-1].date()}  "
          f"Kosten je Seite {k * 1e4:.2f} bp", flush=True)
    gemein = {"rr": 3.0, "nur": ("ChoCh", "FVG"), "puffer": SPREAD[sym]}

    zeile("Basis (wie bisher)", da,
          bt(da, type("Ba", (Setup,), gemein), k, close=True)["_trades"])

    st = bt(da, type("Si", (Sitzung,), gemein), k, close=True)
    tr = st["_trades"]
    pf = zeile("Sitzung, raus 21:45", da, tr)
    if not tr.empty:
        nach_fenster(da, tr)

    zeile("Sitzung, raus Fensterende", da,
          bt(da, type("Se", (Sitzung,), {**gemein, "bis_fensterende": True}),
             k, close=True)["_trades"])

    if tr.empty:
        return
    im_fenster = np.zeros(len(da), bool)
    for a, b in (TOKIO, NEW_YORK):
        im_fenster |= (da.MinB >= a).to_numpy() & (da.MinB + 15 <= b).to_numpy()
    filt = im_fenster & ((((da.TrendD > 0) & (da.TrendH > 0))
                          | ((da.TrendD < 0) & (da.TrendH < 0))).to_numpy())
    frei = 1 - float(st["Exposure Time [%]"]) / 100
    p = len(tr) / max(1.0, filt.sum() * frei)
    stops = tuple(tr.Tag.str.split("|").str[2].astype(float))
    w = []
    for s in range(RUNDEN):
        z = bt(da, type(f"Z{s}", (ZufallSitzung,), {
            "rr": 3.0, "seed": s, "wahrsch": p, "stops_atr": stops,
            "puffer": SPREAD[sym]}), k, close=True)["_trades"]
        w.append(profitfaktor(in_r(z)))
    w = np.array(w)
    print(f"  Zufall gleiche Fenster  Median {np.median(w):.3f}  bester "
          f"{w.max():.3f}  Sitzung schlaegt ihn in {(w < pf).mean() * 100:.0f} %",
          flush=True)


if __name__ == "__main__":
    main()
