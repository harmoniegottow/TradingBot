#!/usr/bin/env python3
"""lade_portfolio.py — Tagesdaten fuer den ganzen Instrumentenkorb laden.

Warum parallel: der Server deckelt jeden Aufruf auf 720 Stunden, bei
Tageskerzen also rund 19 Bars. Fuenf Jahre pro Instrument sind damit etwa
75 Aufrufe, bei 29 Instrumenten ueber 2000. Die Serveranleitung sagt
ausdruecklich, dass diese Aufrufe unabhaengig sind und parallel laufen
duerfen.

Der Token wird aus der Datei gelesen, niemals in eine Kommandozeile
geschrieben.

Aufruf:  python3 lade_portfolio.py [jahre]
"""
from __future__ import annotations

import csv
import datetime as dt
import json
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, "/opt/data/tradingbot")
from mcp_client import Client

DATA_DIR = Path("/opt/data/tradingbot/data")
KORB = Path("/opt/data/tradingbot/korb.json")
TEILER = 100000.0
FENSTER_TAGE = 28          # unter der 30-Tage-Grenze des Servers
ARBEITER = 6               # gleichzeitige Verbindungen, bewusst moderat
drucksperre = threading.Lock()


def _entpacke(res):
    for item in res.get("content", []):
        text = item.get("text")
        if not text:
            continue
        try:
            return json.JSONDecoder().raw_decode(text.lstrip())[0]
        except ValueError:
            continue
    return {}


def lade_symbol(name: str, sid: int, jahre: int) -> tuple:
    """Laedt ein Instrument komplett. Eigener Client je Thread."""
    cli = Client()
    cli.connect()
    jetzt = dt.datetime.now(dt.timezone.utc)
    start = jetzt - dt.timedelta(days=int(jahre * 365.25))
    alle, cursor, fehler = {}, start, 0

    while cursor < jetzt:
        ende = min(cursor + dt.timedelta(days=FENSTER_TAGE), jetzt)
        try:
            res = _entpacke(
                cli.call(
                    "get_trendbars",
                    {
                        "symbolId": sid,
                        "period": "D_1",
                        "fromTimestamp": str(int(cursor.timestamp() * 1000)),
                        "toTimestamp": str(int(ende.timestamp() * 1000)),
                        "count": 1000,
                    },
                )
            )
            if "error" in res:
                fehler += 1
            for bar in res.get("trendbars", []):
                alle[bar["timestamp"]] = bar
        except Exception:
            fehler += 1
        cursor = ende

    bars = [alle[k] for k in sorted(alle)]
    if bars:
        pfad = DATA_DIR / f"{name}_D_1.csv"
        with open(pfad, "w", newline="") as fh:
            wr = csv.writer(fh)
            wr.writerow(["Zeit", "Open", "High", "Low", "Close", "Volume"])
            for b in bars:
                zeit = dt.datetime.fromtimestamp(b["timestamp"] / 1000, dt.timezone.utc)
                wr.writerow([
                    zeit.strftime("%Y-%m-%d"),
                    f"{b['open'] / TEILER:.5f}",
                    f"{b['high'] / TEILER:.5f}",
                    f"{b['low'] / TEILER:.5f}",
                    f"{b['close'] / TEILER:.5f}",
                    b.get("volume", 0),
                ])
    with drucksperre:
        spanne = ""
        if bars:
            a = dt.datetime.fromtimestamp(bars[0]["timestamp"] / 1000, dt.timezone.utc)
            e = dt.datetime.fromtimestamp(bars[-1]["timestamp"] / 1000, dt.timezone.utc)
            spanne = f"{a:%Y-%m-%d} bis {e:%Y-%m-%d}"
        print(f"  {name:9s} {len(bars):5d} Bars  {spanne}"
              f"{f'  ({fehler} Fehler)' if fehler else ''}", flush=True)
    return name, len(bars), fehler


def main():
    jahre = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    korb = json.loads(KORB.read_text())
    print(f"Lade {len(korb)} Instrumente, Tageskerzen, {jahre} Jahre, "
          f"{ARBEITER} parallel\n")

    ergebnis = []
    with ThreadPoolExecutor(max_workers=ARBEITER) as pool:
        futures = {
            pool.submit(lade_symbol, nm, sid, jahre): nm for nm, sid in korb.items()
        }
        for fut in as_completed(futures):
            try:
                ergebnis.append(fut.result())
            except Exception as exc:
                print(f"  FEHLER bei {futures[fut]}: {exc}", flush=True)

    ok = [e for e in ergebnis if e[1] > 100]
    print(f"\nFertig: {len(ok)} von {len(korb)} Instrumenten brauchbar geladen")
    duenn = [e for e in ergebnis if e[1] <= 100]
    if duenn:
        print(f"Zu wenig Daten (aussortiert): {', '.join(e[0] for e in duenn)}")


if __name__ == "__main__":
    main()
