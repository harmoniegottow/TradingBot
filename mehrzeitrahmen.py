#!/usr/bin/env python3
"""
mehrzeitrahmen.py - Trend auf D1 und H1 pruefen, Einstieg auf M15 oder M5.

Idee (Dominique, 05.10.2026): Die Richtung kommt aus den grossen
Zeitrahmen, der Zeitpunkt aus dem kleinen. Gehandelt wird nur, wenn D1 und
H1 in dieselbe Richtung zeigen.

  Trend D1   Tagesschluss ueber/unter EMA50 der Tagesschluesse
  Trend H1   Stundenschluss ueber/unter EMA200 der Stundenschluesse
  Erlaubt    Long nur bei D1 UND H1 aufwaerts, Short nur bei beiden abwaerts
  Einstieg   auf dem kleinen Zeitrahmen, zwei Arten zum Vergleich:
             "Ruecksetzer": RSI14 kreuzt zurueck ueber 40 (Short: unter 60)
             "Ausbruch":    Schluss ueber Hoch der letzten 20 Kerzen
                            (Short: unter Tief)
  Stop       zweifacher ATR14 des kleinen Zeitrahmens
  Ziel       CRV 1:2 und 1:3
  Uhrzeit    nur 07:00 bis 20:00 UTC (London und New York). Nachts sind die
             Spreads breit und die Bewegungen zufaellig.

KEIN BLICK IN DIE ZUKUNFT
Die grossen Zeitrahmen werden aus den kleinen Kerzen gebaut und erst dann
verwendet, wenn ihre Kerze abgeschlossen ist. Die H1-Kerze 10:00 bis 11:00
steht der M15-Kerze zur Verfuegung, die um 11:00 schliesst (also der Kerze
mit Startzeit 10:45), nicht frueher. Genauso der Tag erst nach Mitternacht
UTC. test_mehrzeitrahmen() unten prueft das an einem konstruierten Fall.

KOSTEN
Auf M15 und M5 sind die Kosten der entscheidende Posten, nicht die Signale.
Die Pauschale des Pruefstands (2 Basispunkte je Seite) waere hier falsch:
Sie ist fuer EURUSD rund dreimal so hoch wie der echte Spread. Deshalb
gemessene Spreads je Markt (MT5-Demokonto, 13.09.2026), halbiert je Seite,
plus 0,2 Pips Schlupf je Seite. Zusaetzlich ein Lauf mit DOPPELTEN Kosten
als Belastungsprobe: Was nur bei Idealkosten traegt, traegt nicht.

Daten: data-ctrader, echtes UTC.
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
from strategien.indikatoren import atr, ema, rsi  # noqa: E402

warnings.filterwarnings("ignore")
DATA = Path(__file__).parent / "data-ctrader"
KAPITAL = 100_000

# Spread in Kurseinheiten, gemessen am MT5-Demokonto (Punkte -> Kurs).
# CHFJPY stand bei der Messung auf 0 (kein Kurs) - angenommen 2,5 Pips,
# typisch fuer dieses Kreuz bei Pepperstone. ANNAHME, nicht gemessen.
SPREAD = {"EURUSD": 0.00013, "USDJPY": 0.016, "XAUUSD": 0.26,
          "CHFJPY": 0.025}
PIP = {"EURUSD": 0.0001, "USDJPY": 0.01, "XAUUSD": 0.1, "CHFJPY": 0.01}
SCHLUPF_PIPS = 0.2
MINUTEN = {"M_5": 5, "M_15": 15}


def lade(symbol, tf):
    pfad = DATA / f"{symbol}_{tf}.csv"
    if not pfad.exists():
        return None
    df = pd.read_csv(pfad, index_col=0, parse_dates=True)
    return df[["Open", "High", "Low", "Close"]].dropna()


def hoeher_einblenden(df, regel, minuten, ema_len):
    """Trendrichtung eines groesseren Zeitrahmens, nur abgeschlossene Kerzen.

    Rueckgabe je kleiner Kerze: +1, -1 oder 0 (noch keine Aussage).
    """
    gross = df["Close"].resample(regel, label="right", closed="left").last()
    gross = gross.dropna()
    # .to_numpy() ist Pflicht: ema() liefert eine Series mit Zaehlindex
    # 0..n. Haengt man die direkt an einen Zeitindex, richtet pandas nach
    # Index aus und alles wird NaN - der Filter waere dann stillschweigend
    # aus. Gefunden am 05.10.2026 durch test_mehrzeitrahmen().
    linie = pd.Series(np.asarray(ema(gross.to_numpy(), ema_len)),
                      index=gross.index)
    richtung = np.sign(gross - linie)
    richtung[linie.isna()] = 0
    # Schlusszeit jeder kleinen Kerze; nur grosse Kerzen, deren Ende davor
    # oder genau darauf liegt, sind bekannt.
    schluss = df.index + pd.Timedelta(minutes=minuten)
    links = pd.DataFrame({"t": schluss}).sort_values("t")
    rechts = pd.DataFrame({"t": richtung.index, "r": richtung.to_numpy()})
    zus = pd.merge_asof(links, rechts, on="t", direction="backward")
    return zus["r"].fillna(0).to_numpy()


def vorbereiten(df, minuten):
    df = df.copy()
    df["TrendD"] = hoeher_einblenden(df, "1D", minuten, 50)
    df["TrendH"] = hoeher_einblenden(df, "1h", minuten, 200)
    df["Stunde"] = df.index.hour
    return df


def _hoch(h, n):
    return pd.Series(h).rolling(n).max().shift(1).to_numpy()


def _tief(lo, n):
    return pd.Series(lo).rolling(n).min().shift(1).to_numpy()


def _wert(x):
    return np.asarray(x, dtype=float)


class Mehrzeitrahmen(Strategy):
    einstieg = "Ruecksetzer"
    rr_ratio = 2.0
    atr_mult = 2.0
    kanal = 20
    rsi_long = 40
    rsi_short = 60
    von_stunde = 7
    bis_stunde = 20
    long_an = True
    short_an = True
    filter_an = True

    def init(self):
        c = self.data.Close
        self.r = self.I(rsi, c, 14)
        self.a = self.I(atr, self.data.High, self.data.Low, c, 14)
        self.hoch = self.I(_hoch, self.data.High, self.kanal)
        self.tief = self.I(_tief, self.data.Low, self.kanal)
        self.td = self.I(_wert, self.data.TrendD)
        self.th = self.I(_wert, self.data.TrendH)
        self.std = self.I(_wert, self.data.Stunde)

    def next(self):
        if self.position:
            return
        s = self.std[-1]
        if not (self.von_stunde <= s < self.bis_stunde):
            return
        a = float(self.a[-1])
        if not (a > 0):
            return
        kurs = self.data.Close[-1]
        stop = a * self.atr_mult
        if self.filter_an:
            auf = self.td[-1] > 0 and self.th[-1] > 0
            ab = self.td[-1] < 0 and self.th[-1] < 0
        else:
            auf = ab = True

        if self.einstieg == "Ruecksetzer":
            sig_l = self.r[-2] <= self.rsi_long < self.r[-1]
            sig_s = self.r[-2] >= self.rsi_short > self.r[-1]
        else:
            sig_l = kurs > self.hoch[-1]
            sig_s = kurs < self.tief[-1]

        if auf and self.long_an and sig_l:
            self.buy(size=0.1, sl=kurs - stop, tp=kurs + stop * self.rr_ratio)
        elif ab and self.short_an and sig_s:
            self.sell(size=0.1, sl=kurs + stop, tp=kurs - stop * self.rr_ratio)


class OhneFilter(Mehrzeitrahmen):
    """Gegenprobe: gleicher Einstieg, aber D1/H1 werden ignoriert.

    Wenn der Filter etwas taugt, muss die gefilterte Fassung klar besser
    sein als diese. Sonst ist der Trendfilter Dekoration.
    """
    filter_an = False


def kosten_je_seite(symbol, kurs, faktor=1.0):
    preis = SPREAD[symbol] / 2 + SCHLUPF_PIPS * PIP[symbol]
    return preis * faktor / kurs


def lauf(df, klasse, kosten):
    st = Backtest(df, klasse, cash=KAPITAL, commission=kosten,
                  finalize_trades=True).run()
    return st


def test_mehrzeitrahmen():
    """Konstruierter Fall: die H1-Kerze 10:00 darf erst ab 10:45 wirken."""
    idx = pd.date_range("2026-01-05 00:00", periods=4 * 24 * 12, freq="15min")
    preis = np.where(idx < pd.Timestamp("2026-01-12 10:00"), 1.0, 2.0)
    df = pd.DataFrame({"Open": preis, "High": preis, "Low": preis,
                       "Close": preis}, index=idx)
    r = pd.Series(hoeher_einblenden(df, "1h", 15, 3), index=idx)
    assert r[pd.Timestamp("2026-01-12 10:30")] <= 0, "H1 zu frueh bekannt"
    assert r[pd.Timestamp("2026-01-12 10:45")] > 0, "H1 nicht uebernommen"
    print("Test Zeitversatz: bestanden (H1-Kerze wirkt ab 10:45, nicht frueher)")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--tf", default="M_15", choices=sorted(MINUTEN))
    p.add_argument("--symbole", nargs="+",
                   default=["EURUSD", "USDJPY", "CHFJPY", "XAUUSD"])
    a = p.parse_args()
    test_mehrzeitrahmen()
    minuten = MINUTEN[a.tf]
    zeilen = []
    for sym in a.symbole:
        roh = lade(sym, a.tf)
        if roh is None:
            print(f"\n{sym} {a.tf}: noch keine Daten")
            continue
        df = vorbereiten(roh, minuten)
        k1 = kosten_je_seite(sym, float(df.Close.iloc[-1]))
        print(f"\n=== {sym} {a.tf}  {df.index[0].date()} bis "
              f"{df.index[-1].date()}  {len(df)} Kerzen  "
              f"Kosten je Seite {k1 * 1e4:.2f} bp", flush=True)
        for einstieg in ("Ruecksetzer", "Ausbruch"):
            for rr in (2.0, 3.0):
                for name, basis in (("mit Filter", Mehrzeitrahmen),
                                    ("ohne Filter", OhneFilter)):
                    kl = type(f"{basis.__name__}_{einstieg}_{rr:g}", (basis,),
                              {"einstieg": einstieg, "rr_ratio": rr})
                    st = lauf(df, kl, k1)
                    tr = st["_trades"]
                    if tr.empty:
                        continue
                    st2 = lauf(df, kl, k1 * 2) if name == "mit Filter" \
                        else None
                    lang = tr[tr.Size > 0]
                    kurz = tr[tr.Size < 0]
                    z = {"Markt": sym, "TF": a.tf, "Einstieg": einstieg,
                         "CRV": rr, "Filter": name, "Trades": len(tr),
                         "je Jahr": len(tr) / ((df.index[-1] - df.index[0]).days / 365),
                         "PF": profitfaktor(tr.PnL),
                         "PF Long": profitfaktor(lang.PnL),
                         "PF Short": profitfaktor(kurz.PnL),
                         "Treffer %": (tr.PnL > 0).mean() * 100,
                         "PF 2x Kosten": float(st2["Profit Factor"])
                         if st2 is not None else np.nan,
                         "MaxDD %": float(st["Max. Drawdown [%]"])}
                    zeilen.append(z)
                    print(f"  {einstieg:11} 1:{rr:g} {name:11} "
                          f"n{z['Trades']:5} ({z['je Jahr']:4.0f}/J)  "
                          f"PF {z['PF']:.2f}  L {z['PF Long']:.2f}  "
                          f"S {z['PF Short']:.2f}  TQ {z['Treffer %']:.0f}%"
                          + (f"  2xKosten {z['PF 2x Kosten']:.2f}"
                             if st2 is not None else ""), flush=True)
    out = f"/tmp/mehrzeitrahmen_{a.tf}.csv"
    pd.DataFrame(zeilen).to_csv(out, index=False)
    print(f"\nGespeichert: {out}")


if __name__ == "__main__":
    main()
