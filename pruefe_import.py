"""
pruefe_import.py — Kontrolliert die frisch aus MT5 gelieferten CSV-Dateien,
BEVOR sie in data/ uebernommen werden.

Geprueft wird:
  1. Format: erwartete Spalten vorhanden?
  2. Zeitraum: wirklich zehn Jahre, oder heimlich weniger?
  3. Luecken: fehlen ganze Monate?
  4. Plausibilitaet: Kurse in sinnvoller Groessenordnung, High >= Low?
  5. Vergleich zu den bisherigen Daten: passen die Kurse zusammen?
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

NEU = Path("/tmp")
ALT = Path("/opt/data/tradingbot/data")

# Grobe Erwartung je Markt (Kurs-Groessenordnung heute)
ERWARTET = {
    "EURUSD": (0.9, 1.7), "GBPUSD": (1.0, 2.2), "USDJPY": (75, 200),
    "CHFJPY": (80, 200), "AUDUSD": (0.5, 1.2), "NZDUSD": (0.4, 1.0),
    "XAUUSD": (900, 60000), "XAGUSD": (10, 200), "XPTUSD": (500, 3000),
}


def pruefe(pfad: Path) -> dict:
    name = pfad.stem
    symbol = name.split("_")[0]
    ergebnis = {"datei": name, "fehler": []}

    try:
        df = pd.read_csv(pfad, index_col=0, parse_dates=True)
    except Exception as exc:
        ergebnis["fehler"].append(f"nicht lesbar: {exc}")
        return ergebnis

    noetig = {"Open", "High", "Low", "Close"}
    fehlend = noetig - set(df.columns)
    if fehlend:
        ergebnis["fehler"].append(f"Spalten fehlen: {fehlend}")
        return ergebnis

    df = df.dropna(subset=["Open", "High", "Low", "Close"])
    ergebnis["kerzen"] = len(df)
    if df.empty:
        ergebnis["fehler"].append("keine Daten")
        return ergebnis

    ergebnis["von"] = df.index.min().date()
    ergebnis["bis"] = df.index.max().date()
    ergebnis["jahre"] = (df.index.max() - df.index.min()).days / 365.25

    # High/Low-Logik
    kaputt = int((df["High"] < df["Low"]).sum())
    if kaputt:
        ergebnis["fehler"].append(f"{kaputt}x High < Low")
    ausserhalb = int(((df["Close"] > df["High"]) | (df["Close"] < df["Low"])).sum())
    if ausserhalb:
        ergebnis["fehler"].append(f"{ausserhalb}x Close ausserhalb High/Low")

    # Kurs-Groessenordnung
    if symbol in ERWARTET:
        lo, hi = ERWARTET[symbol]
        letzter = float(df["Close"].iloc[-1])
        ergebnis["letzter_kurs"] = letzter
        if not (lo <= letzter <= hi):
            ergebnis["fehler"].append(
                f"letzter Kurs {letzter:.2f} ausserhalb {lo}-{hi}")

    # Zeitliche Luecken: Monate ohne eine einzige Kerze
    monate = df.index.to_period("M").nunique()
    spanne_monate = ((df.index.max().year - df.index.min().year) * 12
                     + df.index.max().month - df.index.min().month + 1)
    ergebnis["monate"] = f"{monate}/{spanne_monate}"
    if monate < spanne_monate * 0.9:
        ergebnis["fehler"].append(
            f"nur {monate} von {spanne_monate} Monaten belegt")

    # Doppelte Zeitstempel
    dopp = int(df.index.duplicated().sum())
    if dopp:
        ergebnis["fehler"].append(f"{dopp} doppelte Zeitstempel")

    # Chronologie
    if not df.index.is_monotonic_increasing:
        ergebnis["fehler"].append("nicht chronologisch sortiert")

    return ergebnis


def vergleiche_mit_alt(symbol: str, tf: str) -> str | None:
    """Stimmen die neuen Kurse mit den bisherigen ueberein?"""
    p_neu = NEU / f"{symbol}_{tf}.csv"
    p_alt = ALT / f"{symbol}_{tf}.csv"
    if not p_neu.exists() or not p_alt.exists():
        return None
    try:
        a = pd.read_csv(p_alt, index_col=0, parse_dates=True)["Close"]
        n = pd.read_csv(p_neu, index_col=0, parse_dates=True)["Close"]
    except Exception:
        return None
    gemeinsam = a.index.intersection(n.index)
    if len(gemeinsam) < 50:
        return f"nur {len(gemeinsam)} gemeinsame Zeitpunkte"
    abw = ((n[gemeinsam] - a[gemeinsam]).abs() / a[gemeinsam]).median() * 100
    return f"{len(gemeinsam)} gemeinsame Punkte, mittlere Abweichung {abw:.3f} %"


def main():
    dateien = sorted(p for p in NEU.glob("*_[DH]_[0-9].csv"))
    if not dateien:
        print("Keine passenden CSV-Dateien in /tmp gefunden.")
        sys.exit(1)

    print("=" * 104)
    print(f"IMPORT-PRUEFUNG — {len(dateien)} Dateien")
    print("=" * 104)
    print(f"{'Datei':<18} {'Kerzen':>8} {'von':>12} {'bis':>12} "
          f"{'Jahre':>6} {'Monate':>10}  Befund")
    print("-" * 104)

    fehlerhaft = []
    for p in dateien:
        e = pruefe(p)
        if "kerzen" not in e:
            print(f"{e['datei']:<18} {'—':>8}  {'; '.join(e['fehler'])}")
            fehlerhaft.append(e["datei"])
            continue
        befund = "; ".join(e["fehler"]) if e["fehler"] else "ok"
        if e["fehler"]:
            fehlerhaft.append(e["datei"])
        print(f"{e['datei']:<18} {e['kerzen']:>8} {str(e['von']):>12} "
              f"{str(e['bis']):>12} {e['jahre']:>6.1f} {e['monate']:>10}  {befund}")

    print("-" * 104)
    print("\nVergleich mit den bisherigen Daten (gleiche Zeitpunkte):")
    for symbol in ("EURUSD", "XAUUSD", "XAGUSD", "USDJPY"):
        for tf in ("H_4", "D_1"):
            v = vergleiche_mit_alt(symbol, tf)
            if v:
                print(f"  {symbol} {tf}: {v}")

    print()
    if fehlerhaft:
        print(f"ACHTUNG: {len(fehlerhaft)} Datei(en) mit Auffaelligkeiten: "
              f"{', '.join(fehlerhaft)}")
    else:
        print("Alle Dateien unauffaellig.")


if __name__ == "__main__":
    main()
