"""
hole_historie.py — Holt Kursdaten aus MetaTrader 5 als CSV.

LAEUFT NUR AUF WINDOWS, mit gestartetem und eingeloggtem MT5-Terminal.
Auf dem Linux-Server ist das Paket MetaTrader5 nicht installierbar
(es gibt es nur als win32/win_amd64).

Dieses Skript HANDELT NICHT. Es liest ausschliesslich Kurse und
schreibt CSV-Dateien im selben Format wie unsere data/-Dateien
(Spalten: Zeit, Open, High, Low, Close, Volume), damit sie direkt in
den Pruefstand passen.

Aufruf (Eingabeaufforderung im Ordner dieses Skripts):

    python hole_historie.py                    -> Standardliste, H1 und H4
    python hole_historie.py XAUUSD XAGUSD      -> nur diese Symbole
    python hole_historie.py --jahre 10         -> Zeitraum festlegen

Die fertigen CSV-Dateien liegen danach im Unterordner "data" und
koennen auf den Server kopiert werden.
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timedelta, timezone

try:
    import MetaTrader5 as mt5
except ImportError:
    print("FEHLER: Das Paket MetaTrader5 fehlt.")
    print("Installieren mit:  pip install MetaTrader5 pandas")
    print("Hinweis: Das geht nur unter Windows.")
    sys.exit(1)

import pandas as pd

# Symbole, die fuer unsere bisherigen Tests relevant sind.
STANDARD_SYMBOLE = [
    "XAUUSD", "XAGUSD", "XPTUSD",
    "EURUSD", "GBPUSD", "USDJPY", "CHFJPY",
    "AUDUSD", "NZDUSD",
]

# Name im Dateinamen -> MT5-Zeitrahmen
ZEITRAHMEN = {
    "H_1": mt5.TIMEFRAME_H1,
    "H_4": mt5.TIMEFRAME_H4,
    "D_1": mt5.TIMEFRAME_D1,
}


def verbinden() -> None:
    if not mt5.initialize():
        print(f"FEHLER: MT5-Initialisierung fehlgeschlagen: {mt5.last_error()}")
        print("Ist das MT5-Terminal gestartet und eingeloggt?")
        sys.exit(1)
    acc = mt5.account_info()
    if acc is None:
        print("FEHLER: Kein Konto gefunden — im MT5-Terminal einloggen.")
        mt5.shutdown()
        sys.exit(1)
    art = "DEMO" if acc.trade_mode == mt5.ACCOUNT_TRADE_MODE_DEMO else "ECHTGELD"
    print(f"Verbunden: Konto {acc.login} ({acc.server}), {art}")
    print("Dieses Skript liest nur Kurse und handelt nicht.\n")


def symbol_bereit(symbol: str) -> bool:
    info = mt5.symbol_info(symbol)
    if info is None:
        return False
    if not info.visible:
        mt5.symbol_select(symbol, True)
    return True


def hole(symbol: str, name: str, tf, von: datetime, bis: datetime):
    rates = mt5.copy_rates_range(symbol, tf, von, bis)
    if rates is None or len(rates) == 0:
        print(f"  {symbol} {name}: keine Daten ({mt5.last_error()})")
        return None

    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
    df = df.set_index("time")

    spalten = {"open": "Open", "high": "High", "low": "Low", "close": "Close"}
    volumen = "tick_volume" if "tick_volume" in df.columns else None
    if volumen:
        spalten[volumen] = "Volume"
    df = df[list(spalten)].rename(columns=spalten)
    df.index.name = "Zeit"

    # Letzte Zeile kann die noch laufende Kerze sein — abschneiden.
    df = df.iloc[:-1]
    return df if not df.empty else None


def main():
    p = argparse.ArgumentParser(description="Holt MT5-Kurse als CSV.")
    p.add_argument("symbole", nargs="*", default=None)
    p.add_argument("--jahre", type=int, default=10)
    p.add_argument("--zeitrahmen", nargs="*", default=["H_1", "H_4", "D_1"])
    p.add_argument("--ordner", default="data")
    args = p.parse_args()

    symbole = args.symbole or STANDARD_SYMBOLE
    os.makedirs(args.ordner, exist_ok=True)

    verbinden()

    bis = datetime.now(timezone.utc)
    von = bis - timedelta(days=365 * args.jahre)
    print(f"Zeitraum: {von.date()} bis {bis.date()} ({args.jahre} Jahre)")
    print(f"Symbole: {', '.join(symbole)}")
    print(f"Zeitrahmen: {', '.join(args.zeitrahmen)}\n")

    geschrieben = 0
    for symbol in symbole:
        if not symbol_bereit(symbol):
            print(f"  {symbol}: beim Broker nicht gefunden — uebersprungen.")
            print(f"     (Namen im MT5-Marktfenster pruefen, z.B. GOLD statt XAUUSD)")
            continue
        for name in args.zeitrahmen:
            tf = ZEITRAHMEN.get(name)
            if tf is None:
                print(f"  Unbekannter Zeitrahmen '{name}' — uebersprungen.")
                continue
            df = hole(symbol, name, tf, von, bis)
            if df is None:
                continue
            pfad = os.path.join(args.ordner, f"{symbol}_{name}.csv")
            df.to_csv(pfad)
            spanne = f"{df.index.min().date()} bis {df.index.max().date()}"
            print(f"  {symbol} {name}: {len(df)} Kerzen, {spanne} -> {pfad}")
            geschrieben += 1

    mt5.shutdown()
    print(f"\nFertig. {geschrieben} Datei(en) im Ordner '{args.ordner}'.")
    print("Diese Dateien auf den Server nach tradingbot/data/ kopieren.")


if __name__ == "__main__":
    main()
