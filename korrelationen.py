"""Korrelationen der Tagesrenditen — Grundlage fuer die Paar-Auswahl."""
import itertools
import os

import pandas as pd

d = "/opt/data/tradingbot/data/"
syms = sorted(set(f.replace("_D_1.csv", "") for f in os.listdir(d)
                  if f.endswith("_D_1.csv")))
ser = {}
for s in syms:
    df = pd.read_csv(d + f"{s}_D_1.csv", index_col=0, parse_dates=True)
    ser[s] = df["Close"]
px = pd.DataFrame(ser).dropna(how="all")
ret = px.pct_change(fill_method=None)

res = []
for a, b in itertools.combinations(syms, 2):
    j = ret[[a, b]].dropna()
    if len(j) < 1500:
        continue
    res.append((j[a].corr(j[b]), a, b, len(j)))
res.sort(reverse=True)

print("Top-20 positiv korrelierte Paare (Tagesrenditen):")
for c, a, b, n in res[:20]:
    print(f"  {c:.3f}  {a:<8} / {b:<8}  ({n} gemeinsame Tage)")
print()
for c, a, b, n in res:
    if {a, b} == {"XAUUSD", "XAGUSD"}:
        print(f"Referenz Gold/Silber: {c:.3f} ({n} Tage)")
