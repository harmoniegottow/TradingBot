#!/usr/bin/env python3
"""H1/H4-Historie ueber den cTrader Remote MCP Server laden.

Schliesst die Datenluecke von yfinance (dort nur ein bis zwei Monate Intraday).
Quelle ist der Broker selbst, also dieselben Daten wie im Livebetrieb.

Serverseitige Grenzen (gemessen, nicht geraten):
  - fromTimestamp UND toTimestamp sind Pflicht; count allein reicht nicht.
  - Zeitfenster maximal 720 Stunden (30 Tage) pro Aufruf.
  - count maximal 1000.
Deshalb wird in 25-Tage-Scheiben geblaettert.

Aufruf:
    python3 daten_mcp.py EURUSD H_1 730
"""
import csv
import datetime as dt
import json
import sys
import time

sys.path.insert(0, "/opt/data/tradingbot")
from mcp_client import Client

FENSTER_TAGE = 25
MAX_COUNT = 1000
PREIS_TEILER = 100000.0  # Rohpreise sind Integer, siehe unten


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


def symbol_id(cli, name):
    daten = _entpacke(cli.call("get_symbols", {}))
    for sym in daten.get("symbols", []):
        if (sym.get("symbolName") or sym.get("name") or "").upper() == name.upper():
            return sym["symbolId"]
    raise SystemExit(f"Symbol {name} nicht gefunden")


def lade(cli, sid, periode, tage_zurueck):
    jetzt = dt.datetime.now(dt.timezone.utc)
    start = jetzt - dt.timedelta(days=tage_zurueck)
    alle, cursor = {}, start
    while cursor < jetzt:
        ende = min(cursor + dt.timedelta(days=FENSTER_TAGE), jetzt)
        res = _entpacke(
            cli.call(
                "get_trendbars",
                {
                    "symbolId": sid,
                    "period": periode,
                    "fromTimestamp": str(int(cursor.timestamp() * 1000)),
                    "toTimestamp": str(int(ende.timestamp() * 1000)),
                    "count": MAX_COUNT,
                },
            )
        )
        if "error" in res:
            print(f"  ! {cursor:%Y-%m-%d}: {res['error'].get('message')}")
        for bar in res.get("trendbars", []):
            alle[bar["timestamp"]] = bar  # dedupliziert Fenster-Ueberlappungen
        print(f"  {cursor:%Y-%m-%d} bis {ende:%Y-%m-%d}: {len(alle):6d} Bars gesamt")
        cursor = ende
        time.sleep(0.25)
    return [alle[k] for k in sorted(alle)]


def schreibe(bars, pfad, teiler):
    with open(pfad, "w", newline="") as fh:
        wr = csv.writer(fh)
        wr.writerow(["Zeit", "Open", "High", "Low", "Close", "Volume"])
        for b in bars:
            zeit = dt.datetime.fromtimestamp(b["timestamp"] / 1000, dt.timezone.utc)
            wr.writerow(
                [
                    zeit.strftime("%Y-%m-%d %H:%M:%S"),
                    f"{b['open'] / teiler:.5f}",
                    f"{b['high'] / teiler:.5f}",
                    f"{b['low'] / teiler:.5f}",
                    f"{b['close'] / teiler:.5f}",
                    b.get("volume", 0),
                ]
            )


def main():
    name = sys.argv[1] if len(sys.argv) > 1 else "EURUSD"
    periode = sys.argv[2] if len(sys.argv) > 2 else "H_1"
    tage = int(sys.argv[3]) if len(sys.argv) > 3 else 730
    teiler = float(sys.argv[4]) if len(sys.argv) > 4 else PREIS_TEILER

    cli = Client()
    cli.connect()
    sid = symbol_id(cli, name)
    print(f"{name} (id {sid}), {periode}, {tage} Tage zurueck")

    bars = lade(cli, sid, periode, tage)
    if not bars:
        raise SystemExit("Keine Daten erhalten")

    pfad = f"/opt/data/tradingbot/data/{name}_{periode}.csv"
    schreibe(bars, pfad, teiler)
    erste = dt.datetime.fromtimestamp(bars[0]["timestamp"] / 1000, dt.timezone.utc)
    letzte = dt.datetime.fromtimestamp(bars[-1]["timestamp"] / 1000, dt.timezone.utc)
    print(f"\n{len(bars)} Bars: {erste:%Y-%m-%d %H:%M} bis {letzte:%Y-%m-%d %H:%M}")
    print(f"Gespeichert: {pfad}")


if __name__ == "__main__":
    main()
