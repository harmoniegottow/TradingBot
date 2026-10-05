#!/usr/bin/env python3
"""
short_pruefung.py - Taugt Short wirklich nichts, oder nur die Spiegelregel?

Drei Fragen, ein Lauf (05.10.2026):

  1. SWAP: Haengt das alte Urteil "nur Long ist besser" an den
     Uebernachtkosten? Der damalige Vergleich (pruefe_v2.py) lief OHNE Swap.
     Hier jede Variante ohne und mit Swap.
  2. DRIFT: Gold hat sich im Zeitraum vervielfacht, USDJPY ist stark
     gestiegen. Jede Short-Regel verliert dann gegen den Grundtrend. Deshalb
     getrennt nach Aufwaerts- und Abwaertsphasen (Kurs ueber/unter dem Stand
     von vor einem Jahr, nur rueckblickend) und zusaetzlich drift-bereinigt:
     von jedem Trade wird abgezogen, was der Grundtrend allein in der
     Haltedauer gebracht haette.
  3. EIGENE SHORT-REGEL: Ausbruch nach unten (strategien/ausbruch.py) statt
     gespiegeltem Ruecksetzer, mit gleich gebauter Long-Fassung zum Vergleich.

Daten: data-ctrader (echtes UTC, ab 2010). Kosten: Spread wie im
Pruefstand, Swap mit den HEUTIGEN Saetzen - in der Nullzinsphase waren sie
kleiner, die Swapzeilen sind also eher zu streng.
"""
from __future__ import annotations

import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from backtesting import Backtest

sys.path.insert(0, str(Path(__file__).parent))
from kosten import SWAP_SAETZE, profitfaktor, swap_je_trade  # noqa: E402
from pruefstand import KAPITAL, KOSTEN_STANDARD  # noqa: E402
from strategien.ausbruch import Ausbruch  # noqa: E402
from strategien.trend_pullback_v2 import TrendPullbackV2  # noqa: E402

warnings.filterwarnings("ignore")
DATA = Path(__file__).parent / "data-ctrader"
MAERKTE = [("EURUSD", "H_1"), ("USDJPY", "H_1"),
           ("CHFJPY", "H_4"), ("XAUUSD", "H_4")]


def lade(symbol, tf):
    df = pd.read_csv(DATA / f"{symbol}_{tf}.csv", index_col=0,
                     parse_dates=True)
    return df[["Open", "High", "Low", "Close"]].dropna()


def variante(klasse, **attr):
    return type(klasse.__name__ + "_" + "_".join(
        f"{k}{v}" for k, v in attr.items()), (klasse,), attr)


def laufen(df, klasse):
    st = Backtest(df, klasse, cash=KAPITAL, commission=KOSTEN_STANDARD,
                  finalize_trades=True).run()
    return st["_trades"].copy()


def phase_je_trade(df, trades):
    """+1 Aufwaertsphase, -1 Abwaertsphase - nur aus der Vergangenheit."""
    tag = df["Close"].resample("1D").last().dropna()
    vorjahr = tag.shift(252)
    richtung = np.sign(tag - vorjahr)
    # Wert des VORtags nehmen: am Einstiegstag ist der Tagesschluss unbekannt
    richtung = richtung.shift(1)
    tage = pd.to_datetime(trades["EntryTime"]).dt.normalize()
    return tage.map(richtung).fillna(0).to_numpy()


def drift_je_trade(df, trades):
    """Was der Grundtrend allein in der Haltedauer gebracht haette."""
    stunden_gesamt = (df.index[-1] - df.index[0]).total_seconds() / 3600
    mu = np.log(df["Close"].iloc[-1] / df["Close"].iloc[0]) / stunden_gesamt
    h = (pd.to_datetime(trades["ExitTime"]) - pd.to_datetime(
        trades["EntryTime"])).dt.total_seconds() / 3600
    return trades["Size"] * trades["EntryPrice"] * (np.exp(mu * h) - 1)


def kennzahlen(name, df, trades, swapsatz):
    if trades.empty:
        return {"Variante": name, "Trades": 0}
    swap = swap_je_trade(trades, swapsatz) if swapsatz else 0.0
    if swapsatz:
        # Der Satz gilt in Pips zum HEUTIGEN Kurs. Ein Trade von 2010 auf
        # Gold zu 1.200 Dollar zahlt bei gleichem Zinsabstand nur ein
        # Drittel davon. Ohne diese Skalierung ist die Swapzeile fuer alte
        # Jahre um den Faktor des Kursanstiegs ueberzeichnet.
        swap = swap * (trades["EntryPrice"] / df["Close"].iloc[-1])
    mit = trades["PnL"] + swap
    phase = phase_je_trade(df, trades)
    drift = drift_je_trade(df, trades)
    z = {
        "Variante": name,
        "Trades": len(trades),
        "PF roh": profitfaktor(trades["PnL"]),
        "PF Swap": profitfaktor(mit),
        "PF Auf": profitfaktor(mit[phase > 0]),
        "PF Ab": profitfaktor(mit[phase < 0]),
        "n Ab": int((phase < 0).sum()),
        "PF ohne Drift": profitfaktor(mit - drift),
        "Swap %": float(np.sum(swap)) / KAPITAL * 100,
    }
    return z


def main():
    v2 = TrendPullbackV2
    varianten = {
        "V2 nur Long": variante(v2, trade_short=False),
        "V2 nur Short": variante(v2, trade_long=False),
        "V2 Long+Short": v2,
        "Ausbruch Long": variante(Ausbruch, trade_long=True,
                                  trade_short=False),
        "Ausbruch Short": Ausbruch,
    }
    alle = []
    for symbol, tf in MAERKTE:
        df = lade(symbol, tf)
        satz = SWAP_SAETZE.get(symbol)
        print(f"\n=== {symbol} {tf}  {df.index[0].date()} bis "
              f"{df.index[-1].date()}  Kauf+Halten "
              f"{(df.Close.iloc[-1] / df.Close.iloc[0] - 1) * 100:+.0f} %",
              flush=True)
        for name, klasse in varianten.items():
            z = kennzahlen(name, df, laufen(df, klasse), satz)
            z["Markt"] = f"{symbol} {tf}"
            alle.append(z)
            if z["Trades"]:
                print(f"  {name:15} n{z['Trades']:5}  roh {z['PF roh']:.2f}"
                      f"  Swap {z['PF Swap']:.2f}  Auf {z['PF Auf']:.2f}"
                      f"  Ab {z['PF Ab']:.2f} (n{z['n Ab']})"
                      f"  ohneDrift {z['PF ohne Drift']:.2f}"
                      f"  Swap {z['Swap %']:+.1f}%", flush=True)
    pd.DataFrame(alle).to_csv("/tmp/short_pruefung.csv", index=False)
    print("\nGespeichert: /tmp/short_pruefung.csv")


if __name__ == "__main__":
    main()
