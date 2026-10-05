#!/usr/bin/env python3
"""CRV-Vergleich, Teil 2: Trefferquote und Haltedauer.

Der Profitfaktor allein erklaert nicht, WARUM ein Ziel besser abschneidet.
Entscheidend ist das Zusammenspiel: Wie stark faellt die Trefferquote,
wenn das Ziel weiter weg rueckt, und reicht der groessere Gewinn je
Treffer aus, um das auszugleichen?

Dazu die Gewinnschwelle: 1:2 braucht 33,3 %, 1:3 braucht 25,0 %,
1:5 braucht 16,7 % Trefferquote. Liegt die gemessene Quote darueber,
traegt das Ziel; liegt sie darunter, nicht.

Ohne Zufallsvergleich (deshalb schnell) - der steht im Hauptlauf.
"""
from __future__ import annotations

import sys
import warnings
from pathlib import Path

import pandas as pd
from backtesting import Backtest

sys.path.insert(0, str(Path(__file__).parent))

from strategien import REGISTRY                           # noqa: E402
from strategien.trend_pullback_v2 import TrendPullbackV2   # noqa: E402

warnings.filterwarnings("ignore")

DATA = Path(__file__).parent / "data-mt5"
KAPITAL = 100_000
SPREAD = 0.0002
CRV_WERTE = [2.0, 3.0, 5.0]
SCHWELLE = {2.0: 33.3, 3.0: 25.0, 5.0: 16.7}
AUSGESCHLOSSEN = {"ORB"}


def lade(symbol, tf):
    p = DATA / f"{symbol}_{tf}.csv"
    if not p.exists():
        return None
    df = pd.read_csv(p, index_col=0, parse_dates=True)
    if df.index.tz is not None:
        df.index = df.index.tz_localize(None)
    return df[["Open", "High", "Low", "Close"]].dropna()


def mit_crv(k, c):
    return type(f"{k.__name__}_{c:g}", (k,), {"rr_ratio": c})


def main():
    maerkte = [("EURUSD", "H_1"), ("USDJPY", "H_1"),
               ("XAUUSD", "H_4"), ("CHFJPY", "H_4")]
    klassen = {k: v for k, v in REGISTRY.items() if k not in AUSGESCHLOSSEN}
    klassen["Trend-Pullback-V2"] = TrendPullbackV2

    zeilen = []
    for symbol, tf in maerkte:
        df = lade(symbol, tf)
        if df is None:
            continue
        print(f"--- {symbol} {tf} ---", flush=True)
        for name, basis in klassen.items():
            z = {"Markt": f"{symbol} {tf}", "Strategie": name}
            for crv in CRV_WERTE:
                try:
                    st = Backtest(df, mit_crv(basis, crv), cash=KAPITAL,
                                  commission=SPREAD,
                                  finalize_trades=True).run()
                    tr = st["_trades"]
                    n = len(tr)
                    quote = float((tr["PnL"] > 0).mean() * 100) if n else 0.0
                    dauer = float(
                        (pd.to_datetime(tr["ExitTime"])
                         - pd.to_datetime(tr["EntryTime"])
                         ).dt.total_seconds().mean() / 3600) if n else 0.0
                    gew = tr.loc[tr["PnL"] > 0, "PnL"].sum()
                    ver = abs(tr.loc[tr["PnL"] < 0, "PnL"].sum())
                    z[f"PF{crv:g}"] = gew / ver if ver else float("nan")
                    z[f"TQ{crv:g}"] = quote
                    z[f"N{crv:g}"] = n
                    z[f"H{crv:g}"] = dauer
                except Exception as e:
                    print(f"   {name} 1:{crv:g} Fehler {type(e).__name__}")
                    for s in ("PF", "TQ", "N", "H"):
                        z[f"{s}{crv:g}"] = float("nan")
            zeilen.append(z)
            print(f"  {name:20} "
                  + " ".join(f"1:{c:g} PF{z[f'PF{c:g}']:5.2f}"
                             f" TQ{z[f'TQ{c:g}']:4.1f}%"
                             f" n{int(z[f'N{c:g}']):4}"
                             for c in CRV_WERTE), flush=True)

    tab = pd.DataFrame(zeilen)
    tab.to_csv("/tmp/crv_detail.csv", index=False)

    print("\n" + "=" * 94)
    print("TREFFERQUOTE gegen GEWINNSCHWELLE")
    print("Schwelle: 1:2 = 33,3 %   1:3 = 25,0 %   1:5 = 16,7 %")
    print("=" * 94)
    for c in CRV_WERTE:
        tq = tab[f"TQ{c:g}"].dropna()
        ueber = int((tq > SCHWELLE[c]).sum())
        print(f"  1:{c:g}  mittlere Trefferquote {tq.mean():5.1f} %   "
              f"ueber der Schwelle in {ueber:2} von {len(tq)} Faellen")

    print("\nMITTLERE HALTEDAUER (Stunden) - laenger = mehr Zeit im Risiko")
    for c in CRV_WERTE:
        print(f"  1:{c:g}  {tab[f'H{c:g}'].mean():7.1f} h   "
              f"Trades gesamt {int(tab[f'N{c:g}'].sum()):5}")

    print("\nMITTLERER PROFITFAKTOR")
    for c in CRV_WERTE:
        s = tab[f"PF{c:g}"].dropna()
        print(f"  1:{c:g}  {s.mean():.3f}   ueber 1,0: {int((s>1).sum())} von {len(s)}")

    print("\nSieger je Kombination:")
    sieg = {c: 0 for c in CRV_WERTE}
    for _, r in tab.iterrows():
        w = {c: r[f"PF{c:g}"] for c in CRV_WERTE if r[f"PF{c:g}"] == r[f"PF{c:g}"]}
        if w:
            sieg[max(w, key=w.get)] += 1
    for c, n in sieg.items():
        print(f"  1:{c:g}  gewinnt {n:2} von {len(tab)}")
    print("\nGespeichert: /tmp/crv_detail.csv")


if __name__ == "__main__":
    main()
