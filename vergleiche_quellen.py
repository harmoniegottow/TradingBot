"""Passen neue MT5-Daten und alte cTrader-Daten zusammen?"""
import pandas as pd

for sym, tf in (("XAUUSD", "D_1"), ("EURUSD", "D_1"), ("XAUUSD", "H_4")):
    n = pd.read_csv(f"/tmp/{sym}_{tf}.csv", index_col=0, parse_dates=True)
    a = pd.read_csv(f"/opt/data/tradingbot/data/{sym}_{tf}.csv",
                    index_col=0, parse_dates=True)
    # Zeitzone abstreifen, damit die Indizes vergleichbar sind
    n.index = n.index.tz_localize(None) if n.index.tz else n.index
    a.index = a.index.tz_localize(None) if a.index.tz else a.index

    print(f"=== {sym} {tf} ===")
    print(f"  neu: {len(n)} Kerzen, {n.index.min()} bis {n.index.max()}")
    print(f"  alt: {len(a)} Kerzen, {a.index.min()} bis {a.index.max()}")

    gem = n.index.intersection(a.index)
    print(f"  gemeinsame Zeitstempel: {len(gem)}")
    if len(gem) > 20:
        abw = ((n.loc[gem, "Close"] - a.loc[gem, "Close"]).abs()
               / a.loc[gem, "Close"] * 100)
        print(f"    Abweichung Close: Median {abw.median():.4f} %, "
              f"max {abw.max():.3f} %")
    else:
        # Kein Treffer -> liegt es an der Uhrzeit?
        print(f"    Stunden neu: {sorted(set(n.index.hour))[:8]}")
        print(f"    Stunden alt: {sorted(set(a.index.hour))[:8]}")
        # Tagesweise vergleichen (Uhrzeit ignorieren)
        nt = n.copy(); nt["tag"] = nt.index.date
        at = a.copy(); at["tag"] = at.index.date
        nd = nt.groupby("tag")["Close"].last()
        ad = at.groupby("tag")["Close"].last()
        gt = nd.index.intersection(ad.index)
        print(f"    gemeinsame TAGE: {len(gt)}")
        if len(gt) > 20:
            abw = ((nd[gt] - ad[gt]).abs() / ad[gt] * 100)
            print(f"    Tagesschluss-Abweichung: Median {abw.median():.3f} %, "
                  f"max {abw.max():.2f} %")
    print()
