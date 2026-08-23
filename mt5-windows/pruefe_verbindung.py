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
from datetime import datetime, timedelta, timezone

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
        # Varianten wie "XAUUSD-F" (Future) oder "GOLD-PERP" aussortieren:
        # andere Kontraktgroesse, anderer Verfall — nicht der Kassamarkt.
        aussortiert = [n for n in set(treffer)
                       if any(t in n.upper() for t in ("-F", "PERP", "FUT", "-C"))]
        treffer = [n for n in treffer if n not in aussortiert]
        # Kuerzeste Fassung bevorzugen: das ist meist das Hauptsymbol.
        treffer = sorted(set(treffer), key=len)
        if treffer:
            gefunden[basis] = treffer[0]
            hinweise = []
            if len(treffer) > 1:
                hinweise.append(f"auch: {', '.join(treffer[1:])}")
            if aussortiert:
                hinweise.append(f"ignoriert: {', '.join(sorted(aussortiert))}")
            zusatz = f"   ({'; '.join(hinweise)})" if hinweise else ""
            print(f"  {basis:<8} -> {treffer[0]}{zusatz}")
        else:
            print(f"  {basis:<8} -> NICHT GEFUNDEN")

    print("\n  'ignoriert' sind Futures oder Dauerkontrakte (-F, -PERP).")
    print("  Die haben andere Kontraktgroessen und einen Verfall — wir")
    print("  handeln den normalen Kassamarkt.")

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
        import pandas as pd

        probe = gefunden.get("EURUSD") or list(gefunden.values())[0]
        print(f"  Probe am Beispiel {probe}:\n")

        for name_tf, tf in (("H1", mt5.TIMEFRAME_H1),
                            ("H4", mt5.TIMEFRAME_H4),
                            ("D1", mt5.TIMEFRAME_D1)):
            # Ein frisch installiertes Terminal hat die Historie noch nicht
            # heruntergeladen. Eine Abfrage ueber sehr viele Kerzen schlaegt
            # dann komplett fehl. Deshalb absteigend versuchen: die erste
            # Menge, die klappt, zeigt was wirklich da ist.
            ergebnis = None
            for menge in (200_000, 50_000, 10_000, 2_000, 500, 100):
                rates = mt5.copy_rates_from_pos(probe, tf, 0, menge)
                if rates is not None and len(rates) > 0:
                    ergebnis = rates
                    break

            if ergebnis is None:
                # Zweiter Versuch ueber einen Zeitraum — das stoesst bei
                # manchen Brokern den Download ueberhaupt erst an.
                bis = datetime.now(timezone.utc)
                von = bis - timedelta(days=365 * 10)
                rates = mt5.copy_rates_range(probe, tf, von, bis)
                if rates is not None and len(rates) > 0:
                    ergebnis = rates

            if ergebnis is None:
                print(f"  {probe} {name_tf}: keine Daten ({mt5.last_error()})")
                continue

            erste = pd.to_datetime(ergebnis[0]["time"], unit="s")
            letzte = pd.to_datetime(ergebnis[-1]["time"], unit="s")
            jahre = (letzte - erste).days / 365.25
            print(f"  {probe} {name_tf}: {len(ergebnis)} Kerzen, "
                  f"{erste.date()} bis {letzte.date()} ({jahre:.1f} Jahre)")

        print("\n  Wenn hier 'keine Daten' steht oder die Zeitraeume kurz sind:")
        print("  Im MT5-Terminal den Chart des Marktes oeffnen, auf den")
        print("  gewuenschten Zeitrahmen stellen und weit nach links scrollen")
        print("  (oder Pos1 druecken). Das Terminal laedt die Historie erst")
        print("  beim Ansehen nach. Danach dieses Skript erneut ausfuehren.")

    trenner("SCHRITT 5 — Reicht das Kapital fuer das kleinste Lot?")

    print("  Das Mindest-Lot betraegt ueberall 0,01. Riskiert schon dieses")
    print("  kleinste Lot mehr als das Zielrisiko, ist der Markt mit kleinem")
    print("  Konto nicht handelbar — der Bot muesste jeden Trade ablehnen.\n")

    acc = mt5.account_info()
    kapital = acc.equity if acc else 0.0
    for risiko_pct in (0.5,):
        ziel = kapital * risiko_pct / 100
        print(f"  Bei {kapital:.0f} {acc.currency if acc else ''} Kapital und "
              f"{risiko_pct} % Risiko: {ziel:.2f} je Trade\n")

    print(f"  {'Markt':<10} {'Stop (ATR-Schaetzung)':>22} {'Risiko 0.01 Lot':>17}  Urteil")
    for basis, name in gefunden.items():
        info = mt5.symbol_info(name)
        tick = mt5.symbol_info_tick(name)
        if info is None or tick is None or tick.ask <= 0:
            continue

        # Grobe Stop-Schaetzung aus den letzten Tageskerzen (ATR14 x 1,5).
        rates = mt5.copy_rates_from_pos(name, mt5.TIMEFRAME_D1, 0, 30)
        if rates is None or len(rates) < 15:
            print(f"  {name:<10} {'keine Kursdaten':>22}")
            continue
        spannen = [float(r["high"] - r["low"]) for r in rates]
        stop = (sum(spannen) / len(spannen)) * 1.5

        sl = tick.ask - stop
        verlust = mt5.order_calc_profit(mt5.ORDER_TYPE_BUY, name,
                                        info.volume_min, tick.ask, sl)
        if verlust is None:
            print(f"  {name:<10} {stop:>22.4f} {'nicht berechenbar':>17}")
            continue
        verlust = abs(verlust)

        if kapital > 0:
            ziel = kapital * 0.5 / 100
            urteil = ("handelbar" if verlust <= ziel
                      else f"{verlust / ziel:.0f}x ueber dem Ziel")
        else:
            urteil = "?"
        print(f"  {name:<10} {stop:>22.4f} {verlust:>13.2f} EUR  {urteil}")

    print("\n  Hinweis: Fuer ein spaeteres Echtgeldkonto mit 1.000 EUR waeren")
    print("  0,5 % nur 5 EUR je Trade. Metalle (Gold, Silber, Platin) sind")
    print("  dann rechnerisch nicht handelbar — dort kostet das kleinste Lot")
    print("  ein Vielfaches davon. Das ist kein Fehler, sondern eine Grenze")
    print("  des Kontos, die man vorher kennen sollte.")

    trenner("ERGEBNIS — zum Kopieren in die config.py eines Bots")

    if gefunden:
        # Zeitrahmen wie in unseren Backtests: FX auf H1, Metalle auf H4
        # (Metalle schwanken staerker, dort ist H1 zu unruhig).
        METALLE = ("XAUUSD", "XAGUSD", "XPTUSD")
        print("MARKETS = {")
        for basis, name in gefunden.items():
            tf = "H4" if basis in METALLE else "H1"
            print(f'    "{name}": "{tf}",')
        print("}")
        print("\nHinweis: Diese Liste ist die TECHNISCH moegliche Auswahl.")
        print("Welche Maerkte tatsaechlich sinnvoll sind, entscheidet Schritt 5")
        print("zusammen mit der Kapitalgroesse.")
    else:
        print("Keine der gesuchten Maerkte gefunden.")

    mt5.shutdown()
    print("\nVerbindung geschlossen. Es wurde nichts gehandelt und nichts geaendert.")


if __name__ == "__main__":
    main()
