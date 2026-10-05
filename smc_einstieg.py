#!/usr/bin/env python3
"""
smc_einstieg.py - Hammer, FVG/IFVG und ChoCh als Einstieg im Gold-Filter.

Stand 05.10.2026, Regeln nach Dominique:

  Filter     D1 und H1 zeigen in dieselbe Richtung (mehrzeitrahmen.py),
             Handel 07 bis 20 Uhr UTC. Der Filter allein ergab auf Gold M15
             mit gewuerfeltem Einstieg schon PF 1,045. Gesucht ist, ob die
             Einstiegssignale DARUEBER hinaus etwas leisten.

  Hammer     Fibonacci ueber die Kerze. Bullisch: 0 am Hoch, 1 am Tief,
             Koerper komplett zwischen 0 und 0,382. Baerisch gespiegelt.
             Strukturpunkt: Tief (bullisch) bzw. Hoch (baerisch) der Kerze.

  FVG        Bullisch: Tief der dritten Kerze ueber dem Hoch der ersten.
             Aktiv ab der Folgekerze. Signal beim ERSTEN Ruecklauf in die
             Zone, danach gilt sie als abgearbeitet. Mindestgroesse der
             Luecke: ein Spread, kleinere Luecken sind wirtschaftlich nichts.
             Strukturpunkt: Unterkante (bullisch) bzw. Oberkante.

  IFVG       Schliesst der Kurs durch ein FVG hindurch, kippt die Zone und
             wirkt in Gegenrichtung. Signal beim ersten Ruecklauf.

  ChoCh      Hochs und Tiefs: Kerze, deren Hoch die p Kerzen links und
             rechts uebertrifft. Erst nach p Kerzen bestaetigt, vorher
             unbekannt. Bullischer ChoCh: Schluss ueber dem letzten
             bestaetigten Hoch, waehrend die Struktur abwaerts lief. Keine
             Zeitgrenze fuer den Bruch. Der ChoCh bleibt als Bedingung gueltig,
             bis die Struktur wieder kippt oder ein Trade ihn verbraucht hat.
             Strukturpunkt: tiefster Punkt zwischen dem gebrochenen Hoch
             und dem Bruch. p wird mit 2, 3 und 5 gerechnet.

  Einstieg   Mindestens zwei der drei Bedingungen (FVG und IFVG zaehlen
             zusammen als eine) auf derselben Kerze, in Filterrichtung.
             Einstieg zum Schluss dieser Kerze.

  Stop       "Der ausschlaggebende Punkt": Sind mehrere Bedingungen
             beteiligt, gilt der weiteste Strukturpunkt, damit das ganze
             Setup geschuetzt ist. Abstand ein Spread darunter.

  Ziel       CRV 1:2 und 1:3.

BEWERTUNG IN R
Die Stops sind hier sehr unterschiedlich weit (Hammertief gegen ChoCh-Tief).
Mit fester Positionsgroesse wuerden Trades mit weitem Stop das Ergebnis
beherrschen. Ein echter Bot rechnet die Groesse aus dem Risiko. Deshalb wird
jeder Trade in R umgerechnet: Ergebnis geteilt durch das eingesetzte Risiko.
PF R ist der Profitfaktor bei gleichem Risiko je Trade.

KEIN BLICK IN DIE ZUKUNFT
test_ohne_zukunft() rechnet Struktur und FVG einmal auf allen Daten und
einmal auf abgeschnittenen. Bis zum Schnitt muessen beide gleich sein.
"""
from __future__ import annotations

import argparse
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from backtesting import Backtest, Strategy

sys.path.insert(0, str(Path(__file__).parent))
from kosten import profitfaktor  # noqa: E402
from mehrzeitrahmen import (KAPITAL, SPREAD, kosten_je_seite, lade,  # noqa: E402
                            vorbereiten)
from strategien.indikatoren import atr  # noqa: E402

warnings.filterwarnings("ignore")
FIB = 0.382
MAX_AKTIV = 30  # je Richtung nur die juengsten Zonen verfolgen (Rechenzeit)


# ----------------------------------------------------------------------
# Erkennung
# ----------------------------------------------------------------------
def hammer(o, h, l, c):
    r = h - l
    ok = r > 0
    bull = ok & (np.minimum(o, c) >= h - FIB * r)
    bear = ok & (np.maximum(o, c) <= l + FIB * r)
    return bull, bear


def struktur(h, l, c, p):
    """ChoCh-Ereignisse. Rueckgabe je Kerze:
    aktiv_l/aktiv_s  Kennung des gueltigen ChoCh (0 = keiner)
    punkt_l/punkt_s  Strukturpunkt dieses ChoCh
    """
    n = len(c)
    aktiv_l = np.zeros(n, np.int64)
    aktiv_s = np.zeros(n, np.int64)
    punkt_l = np.full(n, np.nan)
    punkt_s = np.full(n, np.nan)
    sh = sl = np.nan
    sh_i = sl_i = -1
    sh_offen = sl_offen = False
    zustand = 0
    kennung = 0
    lauf_l = lauf_s = 0
    lauf_pl = lauf_ps = np.nan
    for t in range(n):
        i = t - p  # Kandidat, der mit Kerze t bestaetigt wird
        if i - p >= 0:
            if h[i] > h[i - p:i].max() and h[i] >= h[i + 1:t + 1].max():
                sh, sh_i, sh_offen = h[i], i, True
            if l[i] < l[i - p:i].min() and l[i] <= l[i + 1:t + 1].min():
                sl, sl_i, sl_offen = l[i], i, True
        if sh_offen and c[t] > sh:
            sh_offen = False
            if zustand <= 0:
                kennung += 1
                lauf_l, lauf_pl = kennung, l[sh_i:t + 1].min()
                lauf_s = 0
            zustand = 1
        if sl_offen and c[t] < sl:
            sl_offen = False
            if zustand >= 0:
                kennung += 1
                lauf_s, lauf_ps = kennung, h[sl_i:t + 1].max()
                lauf_l = 0
            zustand = -1
        aktiv_l[t], punkt_l[t] = lauf_l, lauf_pl
        aktiv_s[t], punkt_s[t] = lauf_s, lauf_ps
    return aktiv_l, aktiv_s, punkt_l, punkt_s


def fvg(h, l, c, min_luecke):
    """Erster Ruecklauf in FVG oder IFVG. Art: 1 = FVG, 2 = IFVG."""
    n = len(c)
    sig_l = np.zeros(n, bool)
    sig_s = np.zeros(n, bool)
    pkt_l = np.full(n, np.nan)
    pkt_s = np.full(n, np.nan)
    art_l = np.zeros(n, np.int8)
    art_s = np.zeros(n, np.int8)
    stuetze, decke = [], []  # (unten, oben, art)
    for t in range(n):
        neu_decke, rest = [], []
        for u, o, art in stuetze:
            if c[t] < u:
                if art == 1:
                    neu_decke.append((u, o, 2))
            elif l[t] <= o:
                if not sig_l[t] or u < pkt_l[t]:
                    pkt_l[t], art_l[t] = u, art
                sig_l[t] = True
            else:
                rest.append((u, o, art))
        stuetze = rest
        neu_stuetze, rest = [], []
        for u, o, art in decke:
            if c[t] > o:
                if art == 1:
                    neu_stuetze.append((u, o, 2))
            elif h[t] >= u:
                if not sig_s[t] or o > pkt_s[t]:
                    pkt_s[t], art_s[t] = o, art
                sig_s[t] = True
            else:
                rest.append((u, o, art))
        decke = rest
        stuetze += neu_stuetze
        decke += neu_decke
        if t >= 2:
            if l[t] - h[t - 2] >= min_luecke:
                stuetze.append((h[t - 2], l[t], 1))
            if l[t - 2] - h[t] >= min_luecke:
                decke.append((h[t], l[t - 2], 1))
        stuetze = stuetze[-MAX_AKTIV:]
        decke = decke[-MAX_AKTIV:]
    return sig_l, sig_s, pkt_l, pkt_s, art_l, art_s


def anreichern(df, p, symbol="XAUUSD"):
    o, h, l, c = (df[x].to_numpy() for x in ("Open", "High", "Low", "Close"))
    d = df.copy()
    d["HL"], d["HS"] = hammer(o, h, l, c)
    d["AL"], d["AS"], d["APL"], d["APS"] = struktur(h, l, c, p)
    (d["BL"], d["BS"], d["BPL"], d["BPS"],
     d["BArtL"], d["BArtS"]) = fvg(h, l, c, SPREAD[symbol])
    d["ATR"] = np.asarray(atr(df.High, df.Low, df.Close, 14))
    return d


# ----------------------------------------------------------------------
# Strategie
# ----------------------------------------------------------------------
def _w(x):
    return np.asarray(x, dtype=float)


class Setup(Strategy):
    rr = 3.0
    mindestens = 2
    nur = None  # z. B. ("ChoCh", "FVG"): nur genau diese Kombination
    puffer = SPREAD["XAUUSD"]
    von_stunde, bis_stunde = 7, 20

    def init(self):
        for name in ("TrendD", "TrendH", "Stunde", "HL", "HS", "AL", "AS",
                     "APL", "APS", "BL", "BS", "BPL", "BPS", "BArtL",
                     "BArtS"):
            setattr(self, "_" + name, self.I(_w, getattr(self.data, name),
                                             plot=False))
        self.verbraucht = set()

    def _bedingungen(self, lang):
        if lang:
            ch = int(self._AL[-1])
            teile = {"ChoCh": (ch > 0 and ch not in self.verbraucht,
                               self._APL[-1]),
                     ("IFVG" if self._BArtL[-1] == 2 else "FVG"):
                         (self._BL[-1] > 0, self._BPL[-1]),
                     "Hammer": (self._HL[-1] > 0, self.data.Low[-1])}
            return teile, ch
        ch = int(self._AS[-1])
        teile = {"ChoCh": (ch > 0 and ch not in self.verbraucht,
                           self._APS[-1]),
                 ("IFVG" if self._BArtS[-1] == 2 else "FVG"):
                     (self._BS[-1] > 0, self._BPS[-1]),
                 "Hammer": (self._HS[-1] > 0, self.data.High[-1])}
        return teile, ch

    def _erlaubt(self):
        s = self._Stunde[-1]
        if not (self.von_stunde <= s < self.bis_stunde):
            return 0
        if self._TrendD[-1] > 0 and self._TrendH[-1] > 0:
            return 1
        if self._TrendD[-1] < 0 and self._TrendH[-1] < 0:
            return -1
        return 0

    def next(self):
        if self.position:
            return
        richtung = self._erlaubt()
        if richtung == 0:
            return
        lang = richtung > 0
        teile, ch = self._bedingungen(lang)
        dabei = {k: v[1] for k, v in teile.items() if v[0]}
        if len(dabei) < self.mindestens:
            return
        if self.nur is not None and set(dabei) != set(self.nur):
            return
        kurs = self.data.Close[-1]
        if lang:
            stop = min(dabei.values()) - self.puffer
            dist = kurs - stop
        else:
            stop = max(dabei.values()) + self.puffer
            dist = stop - kurs
        if not (dist > 0) or not np.isfinite(dist):
            return
        # Ziel unter null ist kein handelbares Setup (Stop mehr als ein
        # Drittel des Kurses entfernt, z. B. Platin im Maerz 2020).
        if not lang and kurs - dist * self.rr <= 0:
            return
        tag = "+".join(sorted(dabei)) + f"|{dist:.6f}|{dist / self.data.ATR[-1]:.4f}"
        if lang:
            self.buy(size=0.1, sl=stop, tp=kurs + dist * self.rr, tag=tag)
        else:
            self.sell(size=0.1, sl=stop, tp=kurs - dist * self.rr, tag=tag)
        if "ChoCh" in dabei:
            self.verbraucht.add(ch)


class ZufallSetup(Setup):
    """Gleicher Filter, gleiche Uhrzeit, Stopweiten aus den echten Trades
    (in ATR), gleiche Haeufigkeit - aber der Zeitpunkt ist gewuerfelt."""
    wahrsch = 0.01
    seed = 0
    stops_atr = (2.0,)

    def init(self):
        super().init()
        self.rng = np.random.default_rng(self.seed)

    def next(self):
        if self.position:
            return
        richtung = self._erlaubt()
        if richtung == 0 or self.rng.random() >= self.wahrsch:
            return
        a = float(self.data.ATR[-1])
        if not (a > 0):
            return
        dist = a * float(self.rng.choice(self.stops_atr))
        kurs = self.data.Close[-1]
        if richtung < 0 and kurs - dist * self.rr <= 0:
            return
        tag = f"Zufall|{dist:.6f}|0"
        if richtung > 0:
            self.buy(size=0.1, sl=kurs - dist, tp=kurs + dist * self.rr, tag=tag)
        else:
            self.sell(size=0.1, sl=kurs + dist, tp=kurs - dist * self.rr, tag=tag)


# ----------------------------------------------------------------------
# Auswertung
# ----------------------------------------------------------------------
def in_r(tr):
    dist = tr.Tag.str.split("|").str[1].astype(float)
    return tr.PnL / (tr.Size.abs() * dist)


def lauf(d, klasse, kosten):
    return Backtest(d, klasse, cash=KAPITAL, commission=kosten,
                    trade_on_close=True, finalize_trades=True).run()


def test_ohne_zukunft(df):
    h, l, c = (df[x].to_numpy() for x in ("High", "Low", "Close"))
    for p in (2, 5):
        voll = struktur(h, l, c, p)
        for m in (5_000, 20_000, 60_000):
            teil = struktur(h[:m], l[:m], c[:m], p)
            for a, b in zip(voll, teil):
                assert np.array_equal(a[:m], b, equal_nan=True), \
                    f"Struktur sieht in die Zukunft (p={p}, m={m})"
    voll = fvg(h, l, c, 0.26)
    for m in (5_000, 20_000, 60_000):
        teil = fvg(h[:m], l[:m], c[:m], 0.26)
        for a, b in zip(voll, teil):
            assert np.array_equal(a[:m], b, equal_nan=True), \
                f"FVG sieht in die Zukunft (m={m})"
    print("Test ohne Zukunft: bestanden (Struktur p=2/5 und FVG, je drei Schnitte)")


def bericht(name, tr):
    if tr.empty:
        print(f"  {name}: keine Trades")
        return
    r = in_r(tr)
    jahre = pd.to_datetime(tr.EntryTime).dt.year
    je_jahr = {y: profitfaktor(r[jahre == y]) for y in sorted(jahre.unique())}
    ueber = sum(v > 1 for v in je_jahr.values())
    print(f"  {name}: n {len(tr)} ({len(tr) / jahre.nunique():.0f}/J)  "
          f"PF R {profitfaktor(r):.3f}  Treffer {(tr.PnL > 0).mean() * 100:.0f} %  "
          f"Jahre ueber 1,0: {ueber} von {len(je_jahr)}  "
          f"Long {profitfaktor(r[tr.Size > 0]):.2f}  "
          f"Short {profitfaktor(r[tr.Size < 0]):.2f}", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runden", type=int, default=30)
    a = ap.parse_args()
    roh = lade("XAUUSD", "M_15")
    test_ohne_zukunft(roh)
    basis = vorbereiten(roh, 15)
    k = kosten_je_seite("XAUUSD", float(basis.Close.iloc[-1]))
    print(f"XAUUSD M15 {basis.index[0].date()} bis {basis.index[-1].date()}, "
          f"Kosten je Seite {k * 1e4:.2f} bp\n")

    referenz = None
    for p in (2, 3, 5):
        d = anreichern(basis, p)
        print(f"--- Hoch/Tief mit {p} Kerzen links und rechts ---")
        print(f"  Hammer bullisch {d.HL.mean() * 100:.1f} %, FVG-Ruecklaeufe "
              f"long {int(d.BL.sum())}, ChoCh {int(d.AL.max() + d.AS.max())} "
              f"Kennungen", flush=True)
        for rr in (2.0, 3.0):
            kl = type(f"S{p}_{rr:g}", (Setup,), {"rr": rr})
            tr = lauf(d, kl, k)["_trades"]
            bericht(f"mind. zwei, 1:{rr:g}", tr)
            if p == 3 and rr == 3.0:
                referenz = (d, tr)
                kombi = tr.Tag.str.split("|").str[0]
                for name in sorted(kombi.unique()):
                    bericht(f"    davon {name}", tr[kombi == name])
        print()

    d, tr = referenz
    r_echt = profitfaktor(in_r(tr))
    stops = tuple(tr.Tag.str.split("|").str[2].astype(float))
    stunde_ok = (d.Stunde >= 7) & (d.Stunde < 20)
    filt = stunde_ok & (((d.TrendD > 0) & (d.TrendH > 0))
                        | ((d.TrendD < 0) & (d.TrendH < 0)))
    st = lauf(d, type("S3_3", (Setup,), {"rr": 3.0}), k)
    frei = 1 - float(st["Exposure Time [%]"]) / 100
    wahrsch = len(tr) / max(1.0, filt.sum() * frei)
    werte, anz = [], []
    for s in range(a.runden):
        kl = type(f"Z{s}", (ZufallSetup,), {"rr": 3.0, "seed": s,
                                            "wahrsch": wahrsch,
                                            "stops_atr": stops})
        z = lauf(d, kl, k)["_trades"]
        werte.append(profitfaktor(in_r(z)))
        anz.append(len(z))
    w = np.array(werte)
    print(f"Zufallsvergleich (p=3, 1:3): {a.runden} Laeufe, im Mittel "
          f"{np.mean(anz):.0f} Trades, PF R Median {np.median(w):.3f}, "
          f"bester {w.max():.3f}. Setup {r_echt:.3f}. "
          f"Zufall mindestens so gut in {(w >= r_echt).mean() * 100:.0f} %")


if __name__ == "__main__":
    main()
