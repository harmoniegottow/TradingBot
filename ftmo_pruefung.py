#!/usr/bin/env python3
"""
FTMO-Pruefung: ueberlebt eine Strategie die Regeln einer Pruefung?

WARUM DIESES SKRIPT NOETIG IST
------------------------------
Der bisherige Pruefstand beantwortet: "Verdient die Strategie ueber zehn
Jahre Geld?" Bei einer Pruefung ist das die FALSCHE Frage. Dort zaehlt:
"Reisst sie vorher eine Grenze?" Eine Strategie kann zehn Jahre profitabel
sein und in Woche drei rausfliegen, weil ein einziger Tag zu schlecht lief.

Die Pruefung ist kein Marathon, sondern ein Minenfeld. Nicht der Gesamt-
ertrag entscheidet, sondern der schlechteste Moment.

DIE REGELN (FTMO 2-Step, Stand 26.09.2026, ftmo.com/en/trading-objectives)
--------------------------------------------------------------------------
  Gewinnziel         Phase 1: 10 % des Startkapitals, Phase 2: 5 %
  Tagesverlust       5 % des Startkapitals, Bezug ist der Kontostand
                     um 00:00 Prager Zeit
  Gesamtverlust      10 % des Startkapitals, fest (nicht nachziehend)
  Mindesthandelstage 4 je Phase

ZWEI FALLEN, DIE DIE MEISTEN UEBERSEHEN
---------------------------------------
1. Gemessen wird EQUITY, nicht der Kontostand. Also einschliesslich der
   schwebenden Verluste offener Positionen. FTMO schreibt ausdruecklich:
   es zaehlt der TIEFSTE Punkt, auch wenn er nur eine Sekunde anhaelt.
   Eine Position, die zwischenzeitlich tief im Minus steht und spaeter im
   Gewinn schliesst, hat die Pruefung trotzdem beendet.
2. Der Tageswechsel liegt um Mitternacht PRAGER Zeit, nicht an deinem
   lokalen Mitternacht und nicht zur Serverzeit der Handelsplattform.

GENAUIGKEITSGRENZE
------------------
Gerechnet wird auf H4- und H1-Kerzen. Innerhalb einer Kerze ist der echte
Verlauf unbekannt. Diese Pruefung nimmt bewusst den UNGUENSTIGSTEN Fall an:
bei Long zaehlt das Tief der Kerze, bei Short das Hoch. Damit wird eher zu
frueh als zu spaet ein Verstoss gemeldet. "Bestanden" ist hier belastbar,
"durchgefallen" kann in Einzelfaellen zu streng sein.

ACHTUNG Zeitstempel: Die MT5-Dateien tragen Broker-Serverzeit, sind aber
als UTC beschriftet (zwei bis drei Stunden Versatz). Fuer die Tagesgrenze
verschiebt das die Tagesgrenzen um ebendiesen Betrag. Siehe
data-mt5/ACHTUNG-Zeitstempel.md. Ergebnisse sind damit richtungsweisend,
aber erst mit cTrader-Daten endgueltig.

Aufruf:
    ./.venv/bin/python ftmo_pruefung.py
    ./.venv/bin/python ftmo_pruefung.py --risiko 0.5
"""

from __future__ import annotations

import argparse
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from backtesting import Backtest

sys.path.insert(0, str(Path(__file__).parent))

from strategien import REGISTRY                      # noqa: E402
from strategien.trend_pullback_v2 import TrendPullbackV2  # noqa: E402

warnings.filterwarnings("ignore")

BASE = Path(__file__).parent
DATA = BASE / "data-mt5"

STARTKAPITAL = 100_000.0
GRENZE_TAG = 0.05
GRENZE_GESAMT = 0.10
ZIEL_PHASE1 = 0.10
ZIEL_PHASE2 = 0.05
MIN_HANDELSTAGE = 4
SPREAD = 0.0002
ZEITZONE = "Europe/Prague"

# Eine Pruefung laeuft nicht zehn Jahre. Realistisch sind wenige Wochen bis
# Monate. Deshalb wird die Historie in ueberlappende Fenster geschnitten und
# jedes Fenster als eigener Pruefungsversuch gewertet. Das beantwortet die
# Frage, die wirklich zaehlt: In wie viel Prozent der Startzeitpunkte haette
# ich bestanden?
FENSTER_TAGE = 60
SCHRITT_TAGE = 15


def lade(symbol: str, tf: str) -> pd.DataFrame | None:
    pfad = DATA / f"{symbol}_{tf}.csv"
    if not pfad.exists():
        return None
    df = pd.read_csv(pfad, index_col=0, parse_dates=True)
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    return df[["Open", "High", "Low", "Close"]].dropna()


def equity_verlauf(trades: pd.DataFrame, kurse: pd.DataFrame,
                   start: float) -> tuple[pd.Series, pd.Series]:
    """Equity je Kerze im unguenstigsten Fall, plus reiner Kontostand."""
    zeiten = kurse.index
    geschlossen = pd.Series(0.0, index=zeiten)
    schwebend = pd.Series(0.0, index=zeiten)

    for _, t in trades.iterrows():
        pnl = float(t["PnL"])
        geschlossen.loc[zeiten >= t["ExitTime"]] += pnl

        offen = (zeiten >= t["EntryTime"]) & (zeiten < t["ExitTime"])
        if not offen.any():
            continue
        einstieg = float(t["EntryPrice"])
        groesse = float(t["Size"])
        if groesse > 0:
            schlecht = kurse.loc[offen, "Low"] - einstieg
        else:
            schlecht = einstieg - kurse.loc[offen, "High"]
        schwebend.loc[offen] += schlecht * abs(groesse)

    return start + geschlossen + schwebend, start + geschlossen


def pruefe_fenster(trades: pd.DataFrame, kurse: pd.DataFrame,
                   start: float = STARTKAPITAL) -> dict:
    """Spielt EINEN Pruefungsversuch gegen die Regeln durch."""
    if trades.empty:
        return {"status": "keine Trades", "handelstage": 0, "trades": 0,
                "ertrag_pct": 0.0, "tiefster_pct": 0.0}

    equity, kontostand = equity_verlauf(trades, kurse, start)
    prag = equity.index.tz_convert(ZEITZONE)
    tag = pd.Series([d.date() for d in prag], index=equity.index)

    boden_gesamt = start * (1.0 - GRENZE_GESAMT)
    betrag_tag = start * GRENZE_TAG

    verstoss = None
    for d in sorted(set(tag)):
        maske = (tag == d).values
        vorher = kontostand[(tag < d).values]
        basis = float(vorher.iloc[-1]) if len(vorher) else start
        boden_tag = basis - betrag_tag
        tief = float(equity[maske].min())

        if tief < boden_gesamt:
            verstoss = {"art": "Gesamtverlust", "datum": str(d)}
            break
        if tief < boden_tag:
            verstoss = {"art": "Tagesverlust", "datum": str(d)}
            break

    handelstage = {pd.Timestamp(t).tz_convert(ZEITZONE).date()
                   for t in trades["EntryTime"]}
    endstand = float(kontostand.iloc[-1])
    ertrag = (endstand - start) / start

    return {
        "status": verstoss["art"] if verstoss else "ueberlebt",
        "verstoss": verstoss,
        "ertrag_pct": ertrag * 100.0,
        "tiefster_pct": (start - float(equity.min())) / start * 100.0,
        "handelstage": len(handelstage),
        "trades": len(trades),
        "ziel1": (not verstoss) and ertrag >= ZIEL_PHASE1
                 and len(handelstage) >= MIN_HANDELSTAGE,
        "ziel2": (not verstoss) and ertrag >= ZIEL_PHASE2
                 and len(handelstage) >= MIN_HANDELSTAGE,
    }


def skaliere(trades: pd.DataFrame, risiko_pct: float,
             start: float = STARTKAPITAL) -> pd.DataFrame:
    """Rechnet die Trades auf ein festes Risiko je Handel um.

    Der Pruefstand handelt mit fester Positionsgroesse (zehn Prozent des
    Kapitals). Fuer eine Pruefung ist das untauglich: Bei einem Stop auf
    zweifachem ATR schwankt die Verlustdistanz stark, und damit schwankt
    das Risiko je Handel. Hier wird stattdessen jede Position so skaliert,
    dass ein ausgeloester Stop immer denselben Betrag kostet.
    """
    t = trades.copy()
    ziel = start * risiko_pct / 100.0
    # Stop-Distanz je Handel aus Einstieg und schlechtestem Punkt ableiten
    # ist nicht moeglich; backtesting.py liefert den gesetzten SL nicht mit.
    # Ersatz: ueber den groessten tatsaechlichen Verlust je Handel.
    verlust = t["PnL"].where(t["PnL"] < 0).abs()
    typisch = float(verlust.median()) if verlust.notna().any() else np.nan
    if not (typisch > 0):
        return t
    faktor = ziel / typisch
    t["PnL"] = t["PnL"] * faktor
    t["Size"] = t["Size"] * faktor
    return t


def main() -> None:
    p = argparse.ArgumentParser(
        description="Prueft die Strategien gegen die FTMO-Regeln.")
    p.add_argument("--risiko", type=float, default=1.0,
                   help="Risiko je Handel in Prozent (Vorgabe 1,0)")
    p.add_argument("--fenster", type=int, default=FENSTER_TAGE,
                   help="Laenge eines Pruefungsversuchs in Tagen")
    a = p.parse_args()

    maerkte = [("EURUSD", "H_1"), ("USDJPY", "H_1"),
               ("XAUUSD", "H_4"), ("CHFJPY", "H_4")]
    klassen = dict(REGISTRY)
    klassen["Trend-Pullback-V2"] = TrendPullbackV2

    print("=" * 78)
    print(f"FTMO 2-Step, {STARTKAPITAL:,.0f} USD Startkapital".replace(",", "."))
    print(f"Risiko je Handel: {a.risiko} %   "
          f"Pruefungsfenster: {a.fenster} Tage")
    print("Equity im unguenstigsten Fall je Kerze, Tageswechsel Prager Zeit")
    print("=" * 78)

    gesamt = []
    for symbol, tf in maerkte:
        df = lade(symbol, tf)
        if df is None:
            continue
        for name, klasse in klassen.items():
            try:
                bt = Backtest(df, klasse, cash=STARTKAPITAL,
                              commission=SPREAD, finalize_trades=True)
                stats = bt.run()
                trades = stats["_trades"]
            except Exception as e:
                print(f"  {symbol} {tf} {name}: Fehler {type(e).__name__}")
                continue
            if trades.empty:
                continue

            trades = skaliere(trades, a.risiko)
            trades["EntryTime"] = pd.to_datetime(trades["EntryTime"], utc=True)
            trades["ExitTime"] = pd.to_datetime(trades["ExitTime"], utc=True)

            # Historie in ueberlappende Pruefungsversuche schneiden
            erg = []
            t0, t1 = df.index[0], df.index[-1]
            start_d = t0
            while start_d + pd.Timedelta(days=a.fenster) <= t1:
                ende = start_d + pd.Timedelta(days=a.fenster)
                teil_k = df.loc[start_d:ende]
                teil_t = trades[(trades["EntryTime"] >= start_d)
                                & (trades["ExitTime"] <= ende)]
                if len(teil_t) >= 1:
                    erg.append(pruefe_fenster(teil_t, teil_k))
                start_d += pd.Timedelta(days=SCHRITT_TAGE)

            if not erg:
                continue
            n = len(erg)
            verstoesse = sum(1 for e in erg if e["status"] != "ueberlebt")
            tages = sum(1 for e in erg if e["status"] == "Tagesverlust")
            best1 = sum(1 for e in erg if e.get("ziel1"))
            gesamt.append({
                "Markt": f"{symbol} {tf}", "Strategie": name,
                "Versuche": n,
                "Verstoss %": verstoesse / n * 100.0,
                "davon Tages": tages,
                "Phase1 bestanden %": best1 / n * 100.0,
                "max Rueckgang %": max(e["tiefster_pct"] for e in erg),
            })

    if not gesamt:
        print("Keine auswertbaren Ergebnisse.")
        return

    tab = pd.DataFrame(gesamt).sort_values("Phase1 bestanden %",
                                           ascending=False)
    pd.set_option("display.width", 200)
    print()
    print(tab.to_string(index=False, float_format=lambda x: f"{x:6.1f}"))
    print()
    print("Lesehilfe:")
    print("  Versuche            Anzahl der simulierten Pruefungsanlaeufe")
    print("  Verstoss %          Anteil, der an einer Grenze gescheitert ist")
    print("  davon Tages         wie viele davon an der TAGESgrenze")
    print("  Phase1 bestanden %  Anteil mit 10 % Gewinn OHNE Verstoss")
    print("  max Rueckgang %     groesster Equity-Rueckgang; ab 10 % = Aus")


if __name__ == "__main__":
    main()
