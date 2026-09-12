"""
hole_historie.py — Holt Kursdaten aus MetaTrader 5 als CSV.

LAEUFT NUR AUF WINDOWS, mit gestartetem und eingeloggtem MT5-Terminal.
Auf dem Linux-Server ist das Paket MetaTrader5 nicht installierbar
(es gibt es nur als win32/win_amd64).

Dieses Skript HANDELT NICHT. Es liest ausschliesslich Kurse und
schreibt CSV-Dateien im selben Format wie unsere data/-Dateien
(Spalten: Zeit, Open, High, Low, Close, Volume), damit sie direkt in
den Pruefstand passen.

ZEITSTEMPEL (wichtig, seit 12.09.2026)
--------------------------------------
MT5 liefert Kerzenzeiten in BROKER-SERVERZEIT, nicht in UTC. Frueher hat
dieses Skript sie unveraendert mit dem Suffix "+00:00" geschrieben - die
Dateien in data-mt5/ sind deshalb um zwei bis drei Stunden falsch
beschriftet (siehe data-mt5/ACHTUNG-Zeitstempel.md).

Jetzt wird umgerechnet: Serverzeit ist UTC+2 im Winter und UTC+3 im
Sommer, umgeschaltet zu den US-Terminen (zweiter Sonntag im Maerz, erster
Sonntag im November). Diese Regel wurde gegen die cTrader Open API ueber
zehn Jahre geprueft und stimmte in 18 von 20 Wechseln.

Sie ist NICHT unfehlbar: Im Winter 2017/18 hat der Broker den Herbstwechsel
ausgelassen. Deshalb misst dieses Skript beim Start den tatsaechlichen
Versatz am Terminal und bricht ab, wenn er nicht zur Regel passt.

Hauptdatenquelle des Projekts ist inzwischen cTrader (data-ctrader/,
lade_ctrader_voll.py). Dieses Skript ist die Zweitquelle.

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


def nter_sonntag(jahr: int, monat: int, nummer: int) -> datetime:
    """n-ter Sonntag eines Monats - die US-Umstellungstermine."""
    tag = datetime(jahr, monat, 1, tzinfo=timezone.utc)
    tag += timedelta(days=(6 - tag.weekday()) % 7)
    return tag + timedelta(weeks=nummer - 1)


def ist_us_sommerzeit(zeitpunkt: datetime) -> bool:
    """Zweiter Sonntag im Maerz bis erster Sonntag im November.

    Der Vergleich laeuft auf der Serverzeit selbst. Am Umschaltpunkt waere
    das mehrdeutig - dort ist der Markt aber geschlossen, es gibt also keine
    Kerze, die in die Luecke fallen koennte.
    """
    beginn = nter_sonntag(zeitpunkt.year, 3, 2)
    ende = nter_sonntag(zeitpunkt.year, 11, 1)
    return beginn <= zeitpunkt.replace(tzinfo=timezone.utc) < ende


def versatz_stunden(zeitpunkt: datetime) -> int:
    return 3 if ist_us_sommerzeit(zeitpunkt) else 2


def server_versatz_messen(symbol: str):
    """Misst den tatsaechlichen Versatz am Terminal, statt ihn zu glauben."""
    tick = mt5.symbol_info_tick(symbol)
    if tick is None or not tick.time:
        return None
    serverzeit = datetime.fromtimestamp(tick.time, tz=timezone.utc)
    abstand = (serverzeit - datetime.now(timezone.utc)).total_seconds()
    return round(abstand / 3600)


def versatz_pruefen(symbol: str) -> None:
    """Bricht ab, wenn der gemessene Versatz nicht zur Regel passt.

    ACHTUNG, Reichweite dieser Pruefung: Sie misst den Versatz NUR fuer den
    aktuellen Zeitpunkt. Ueber die Richtigkeit der historischen Umrechnung
    sagt ein bestandener Test nichts, sobald der abgefragte Zeitraum in einer
    anderen Sommerzeit-Periode liegt oder eine Umstellung ueberspannt - und
    bei --jahre 10 ist beides immer der Fall.

    Belegter Praezedenzfall: Im Winter 2017/18 hat der Broker den
    Herbstwechsel ausgelassen und lief vom 06.11.2017 bis zum 26.02.2018
    durchgehend auf UTC+3 statt UTC+2; der Maerzwechsel 2018 kam dann einen
    Tag zu spaet. Ein Export im Januar 2018 haette diese Pruefung bestanden
    und die Kerzen trotzdem um eine Stunde falsch umgerechnet.

    Fuer lange Zeitraeume ist deshalb cTrader die Quelle (data-ctrader/,
    lade_ctrader_voll.py) - dort sind die Zeitstempel von vornherein UTC und
    brauchen keine Umrechnung. Einzelheiten in data-mt5/ACHTUNG-Zeitstempel.md.
    """
    gemessen = server_versatz_messen(symbol)
    erwartet = versatz_stunden(datetime.now(timezone.utc))
    if gemessen is None:
        print(f"WARNUNG: Versatz nicht messbar ({symbol} liefert keinen Tick).")
        print(f"         Es wird mit der Regel gerechnet: UTC+{erwartet}.")
        return
    print(f"Server-Versatz gemessen: UTC+{gemessen}, nach Regel erwartet:"
          f" UTC+{erwartet}.")
    if gemessen != erwartet:
        print("\nFEHLER: Der Broker haelt sich gerade nicht an die Regel.")
        print("Genau das ist im Winter 2017/18 passiert. Eine Umrechnung nach")
        print("Regel waere jetzt falsch. Bitte den Versatz von Hand pruefen und")
        print("die Umrechnung in diesem Skript anpassen, bevor exportiert wird.")
        sys.exit(1)
    print("Regel bestaetigt - Zeitstempel werden nach UTC umgerechnet.\n")


def hole(symbol: str, name: str, tf, von: datetime, bis: datetime):
    # Grosszuegiger Rand: die Bereichsgrenzen liest MT5 in Serverzeit, der
    # Zuschnitt auf den gewuenschten Zeitraum passiert nach der Umrechnung.
    rates = mt5.copy_rates_range(symbol, tf, von - timedelta(days=1),
                                 bis + timedelta(days=1))
    if rates is None or len(rates) == 0:
        print(f"  {symbol} {name}: keine Daten ({mt5.last_error()})")
        return None

    df = pd.DataFrame(rates)
    # MT5 liefert Serverzeit. Erst als naive Zeit lesen, dann den Versatz
    # abziehen - so entsteht echtes UTC statt einer falschen Beschriftung.
    serverzeit = pd.to_datetime(df["time"], unit="s")
    versatz = serverzeit.map(versatz_stunden)
    df["time"] = (serverzeit - pd.to_timedelta(versatz, unit="h")).dt.tz_localize(
        timezone.utc)
    df = df.set_index("time")
    df = df[(df.index >= von) & (df.index <= bis)]
    if df.empty:
        print(f"  {symbol} {name}: nach Zuschnitt keine Kerzen uebrig.")
        return None

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
    versatz_pruefen(symbole[0])

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
