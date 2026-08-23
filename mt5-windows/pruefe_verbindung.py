"""
pruefe_verbindung.py — Erster Schritt auf dem Windows-Rechner.

Prueft, ob alles bereit ist, und findet heraus, wie DEIN Broker die
Maerkte tatsaechlich nennt. HANDELT NICHT und aendert nichts.

Hintergrund: Pepperstone haengt je nach Kontotyp ein Kuerzel an den
Symbolnamen (z. B. "EURUSD.a" statt "EURUSD"). Welches, haengt vom
Konto ab — deshalb wird es hier gesucht statt geraten.

Aufruf (Eingabeaufforderung in diesem Ordner):

    python pruefe_verbindung.py

Am Ende steht eine fertige MARKETS-Zeile, die man in die config.py
eines Bots kopieren kann.
"""
from __future__ import annotations

import sys

try:
    import MetaTrader5 as mt5
except ImportError:
    print("FEHLER: Das Paket MetaTrader5 fehlt.")
    print("Installieren mit:  pip install MetaTrader5 pandas")
    print("Hinweis: Das geht nur unter Windows.")
    sys.exit(1)

# Maerkte, die uns interessieren — ohne Kuerzel, das wird gesucht.
GESUCHT = [
    "XAUUSD", "XAGUSD", "XPTUSD",
    "EURUSD", "GBPUSD", "USDJPY", "CHFJPY",
    "AUDUSD", "NZDUSD",
]

# Uebliche Alternativnamen, falls der Grundname nicht vorkommt.
ALTERNATIVEN = {
    "XAUUSD": ["GOLD", "GOLDUSD"],
    "XAGUSD": ["SILVER", "SILVERUSD"],
    "XPTUSD": ["PLATINUM"],
}


def trenner(text: str = "") -> None:
    print("\n" + "=" * 70)
    if text:
        print(text)
        print("=" * 70)


def main():
    trenner("SCHRITT 1 — Verbindung zum MT5-Terminal")

    if not mt5.initialize():
        print(f"FEHLGESCHLAGEN: {mt5.last_error()}")
        print("\nBitte pruefen:")
        print("  - Laeuft das MT5-Terminal?")
        print("  - Bist du eingeloggt?")
        sys.exit(1)

    acc = mt5.account_info()
    if acc is None:
        print("FEHLGESCHLAGEN: Kein Konto gefunden.")
        print("Bitte im MT5-Terminal einloggen.")
        mt5.shutdown()
        sys.exit(1)

    ist_demo = acc.trade_mode == mt5.ACCOUNT_TRADE_MODE_DEMO
    print(f"  Konto:    {acc.login}")
    print(f"  Server:   {acc.server}")
    print(f"  Art:      {'DEMOKONTO' if ist_demo else '*** ECHTGELDKONTO ***'}")
    print(f"  Kapital:  {acc.balance:.2f} {acc.currency}")
    print(f"  Hebel:    1:{acc.leverage}")

    if not ist_demo:
        print("\n  ACHTUNG: Das ist KEIN Demokonto. Fuer die Testphase")
        print("  unbedingt ein Demokonto verwenden.")

    trenner("SCHRITT 2 — Wie nennt dein Broker die Maerkte?")

    alle = mt5.symbols_get()
    if alle is None:
        print("Keine Symbolliste erhalten.")
        mt5.shutdown()
        sys.exit(1)
    namen = [s.name for s in alle]
    print(f"  Der Broker bietet insgesamt {len(namen)} Maerkte an.\n")

    gefunden: dict[str, str] = {}
    for basis in GESUCHT:
        kandidaten = [basis] + ALTERNATIVEN.get(basis, [])
        treffer = []
        for k in kandidaten:
            # Exakter Name oder Name mit Kuerzel (EURUSD.a, EURUSD.m, ...)
            treffer += [n for n in namen
                        if n == k or (n.startswith(k) and len(n) <= len(k) + 5)]
        # Kuerzeste Fassung bevorzugen: das ist meist das Hauptsymbol.
        treffer = sorted(set(treffer), key=len)
        if treffer:
            gefunden[basis] = treffer[0]
            weitere = f"   (auch: {', '.join(treffer[1:])})" if len(treffer) > 1 else ""
            print(f"  {basis:<8} -> {treffer[0]}{weitere}")
        else:
            print(f"  {basis:<8} -> NICHT GEFUNDEN")

    trenner("SCHRITT 3 — Handelbarkeit und Kosten")

    print(f"  {'Markt':<12} {'Spread':>8} {'Min-Lot':>9} {'Schritt':>9}  Handel")
    for basis, name in gefunden.items():
        info = mt5.symbol_info(name)
        if info is None:
            continue
        if not info.visible:
            mt5.symbol_select(name, True)
            info = mt5.symbol_info(name)
        offen = info.trade_mode == mt5.SYMBOL_TRADE_MODE_FULL
        print(f"  {name:<12} {info.spread:>8} {info.volume_min:>9} "
              f"{info.volume_step:>9}  {'ja' if offen else 'derzeit nein'}")

    trenner("SCHRITT 4 — Reicht die Historie?")

    if gefunden:
        probe = gefunden.get("EURUSD") or list(gefunden.values())[0]
        for name_tf, tf in (("H1", mt5.TIMEFRAME_H1),
                            ("H4", mt5.TIMEFRAME_H4),
                            ("D1", mt5.TIMEFRAME_D1)):
            rates = mt5.copy_rates_from_pos(probe, tf, 0, 100_000)
            if rates is None or len(rates) == 0:
                print(f"  {probe} {name_tf}: keine Daten")
                continue
            import pandas as pd
            erste = pd.to_datetime(rates[0]["time"], unit="s")
            print(f"  {probe} {name_tf}: {len(rates)} Kerzen, "
                  f"ab {erste.date()}")
        print("\n  Hinweis: Falls die Zahlen klein wirken — im MT5-Terminal")
        print("  einmal den Chart oeffnen und weit nach links scrollen, dann")
        print("  laedt das Terminal mehr Historie nach.")

    trenner("ERGEBNIS — zum Kopieren in die config.py eines Bots")

    if gefunden:
        print("MARKETS = {")
        for basis, name in gefunden.items():
            tf = "H4" if basis in ("XAUUSD", "XPTUSD", "CHFJPY") else "H1"
            print(f'    "{name}": "{tf}",')
        print("}")
    else:
        print("Keine der gesuchten Maerkte gefunden.")

    mt5.shutdown()
    print("\nVerbindung geschlossen. Es wurde nichts gehandelt und nichts geaendert.")


if __name__ == "__main__":
    main()
