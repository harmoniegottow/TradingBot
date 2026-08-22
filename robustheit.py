"""
robustheit.py — Haelt das Ergebnis aus pruefung_quelle.py einer Belastung stand?

Vier Pruefungen, weil vierzig Trades wenig sind und ein Profitfaktor knapp
ueber 1,0 auch Zufall sein kann:

1. Out-of-Sample: erste Haelfte gegen zweite Haelfte des Zeitraums.
   Eine echte Kante wirkt in beiden Haelften, nicht nur in einer.
2. Parameter-Nachbarschaft: leicht andere Werte rundherum. Bricht das
   Ergebnis bei kleinen Aenderungen zusammen, war es Kurvenanpassung.
3. Kostenempfindlichkeit: wie viel Spanne haelt die Strategie aus, bevor
   der Profitfaktor unter 1,0 faellt.
4. Permutationstest: die Strategie gegen 200 Zufallseinstiege mit gleicher
   Trade-Anzahl und gleicher Stop/Ziel-Mechanik. Liefert eine Aussage, wie
   oft blosser Zufall mindestens so gut abschneidet.
"""
from pathlib import Path
import sys

import numpy as np
import pandas as pd
from backtesting import Backtest, Strategy

from strategien.indikatoren import atr
from strategien.trend_pullback import TrendPullback

DATA_DIR = Path(__file__).parent / "data"
KOSTEN = 0.0002


def lade(symbol, tf):
    df = pd.read_csv(DATA_DIR / f"{symbol}_{tf}.csv", index_col=0, parse_dates=True)
    return df[["Open", "High", "Low", "Close"]].dropna()


def pf(df, klasse=TrendPullback, kosten=KOSTEN, **kw):
    st = Backtest(df, klasse, cash=100_000, commission=kosten,
                  finalize_trades=True).run(**kw)
    return st.get("Profit Factor", float("nan")), int(st["# Trades"])


def teil1_oos(faelle):
    print("\n1) OUT-OF-SAMPLE  (Kante muss in BEIDEN Haelften wirken)")
    print(f"   {'Fall':12s} {'PF 1.Haelfte':>14s} {'PF 2.Haelfte':>14s} {'Trades 1/2':>12s}")
    for label, (sym, tf) in faelle.items():
        df = lade(sym, tf)
        h = len(df) // 2
        p1, t1 = pf(df.iloc[:h])
        p2, t2 = pf(df.iloc[h:])
        print(f"   {label:12s} {p1:14.2f} {p2:14.2f} {f'{t1}/{t2}':>12s}")


def teil2_parameter(faelle):
    print("\n2) PARAMETER-NACHBARSCHAFT  (robust = Werte rundherum aehnlich)")
    varianten = [
        ("Original 150/35/2.0", {}),
        ("EMA 100", {"trend_len": 100}),
        ("EMA 200", {"trend_len": 200}),
        ("RSI-Schwelle 30", {"rsi_oversold": 30}),
        ("RSI-Schwelle 40", {"rsi_oversold": 40}),
        ("Stop 1.5x ATR", {"atr_stop_mult": 1.5}),
        ("Stop 2.5x ATR", {"atr_stop_mult": 2.5}),
    ]
    kopf = "   " + f"{'Variante':22s}" + "".join(f"{k:>12s}" for k in faelle)
    print(kopf)
    for name, kw in varianten:
        zeile = f"   {name:22s}"
        for sym, tf in faelle.values():
            p, _ = pf(lade(sym, tf), **kw)
            zeile += f"{p:12.2f}"
        print(zeile)


def teil3_kosten(faelle):
    print("\n3) KOSTENEMPFINDLICHKEIT  (ab welcher Spanne faellt PF unter 1,0)")
    stufen = [0.0, 0.0001, 0.0002, 0.0003, 0.0005, 0.001]
    print("   " + f"{'Kosten':>10s}" + "".join(f"{k:>12s}" for k in faelle))
    for k in stufen:
        zeile = f"   {k*10000:8.1f}bp"
        for sym, tf in faelle.values():
            p, _ = pf(lade(sym, tf), kosten=k)
            zeile += f"{p:12.2f}"
        print(zeile)


def teil4_permutation(faelle, runden=200, seed=42):
    """Zufallseinstiege mit gleicher Haeufigkeit und gleicher Stop/Ziel-Logik."""
    print(f"\n4) PERMUTATIONSTEST  ({runden} Runden Zufallseinstiege je Fall)")
    print("   Frage: wie oft schlaegt blosser Zufall die Strategie?")
    print(f"   {'Fall':12s} {'PF Strategie':>13s} {'PF Zufall Median':>17s} {'Zufall >= Strat':>16s}")

    for label, (sym, tf) in faelle.items():
        df = lade(sym, tf)
        echt_pf, n_trades = pf(df)
        rng = np.random.default_rng(seed)
        wahrsch = n_trades / len(df)

        class Zufall(Strategy):
            def init(self):
                self.atr_wert = self.I(atr, self.data.High, self.data.Low,
                                       self.data.Close, 14)
                self.wuerfel = rng.random(len(self.data.Close))

            def next(self):
                if self.position or len(self.data.Close) < 20:
                    return
                if self.wuerfel[len(self.data.Close) - 1] >= wahrsch:
                    return
                d = float(self.atr_wert[-1]) * 2.0
                if not (d > 0):
                    return
                k = self.data.Close[-1]
                self.buy(size=0.1, sl=k - d, tp=k + d * 2.0)

        pfs = []
        for _ in range(runden):
            p, _t = pf(df, klasse=Zufall)
            if p == p:
                pfs.append(p)
        pfs = np.array(pfs)
        besser = float((pfs >= echt_pf).mean() * 100) if len(pfs) else float("nan")
        print(f"   {label:12s} {echt_pf:13.2f} {np.median(pfs):17.2f} {besser:15.1f}%")
    print("   Unter 5% = Ergebnis ist kaum durch Zufall erklaerbar.")
    print("   Ueber 20% = Zufall reicht als Erklaerung, keine belegte Kante.")


def main():
    faelle = {
        "XAUUSD H1": ("XAUUSD", "H_1"),
        "XAGUSD H1": ("XAGUSD", "H_1"),
        "USDJPY H4": ("USDJPY", "H_4"),
        "EURUSD H1": ("EURUSD", "H_1"),
    }
    print("=" * 92)
    print("ROBUSTHEITSPRUEFUNG  Trend-Pullback  (Kosten 2bp, sofern nicht anders)")
    print("=" * 92)
    teil1_oos(faelle)
    teil2_parameter(faelle)
    teil3_kosten(faelle)
    if "--schnell" not in sys.argv:
        teil4_permutation(faelle)
    print("=" * 92)


if __name__ == "__main__":
    main()
