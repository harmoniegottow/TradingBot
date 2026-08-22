"""
pruefstand.py — Der ehrliche Massstab. Jede Strategie muss hier durch.

Warum es dieses Modul gibt
--------------------------
Ein Profitfaktor ueber 1,0 beweist NICHTS. Am 22.08.2026 sah der
Trend-Pullback auf Gold H1 mit PF 1,42 gut aus. Dann zeigte sich:

  - Blosse Zufallseinstiege erreichten im Mittel PF 1,15 und schlugen die
    Strategie in 27,5 % der Faelle.
  - Gold selbst stieg im Zeitraum um 83,7 %. Die Strategie machte 0,94 %.

Der Profitfaktor kam also vom Aufwaertstrend, nicht von der Strategie. Ein
reines Long-System liegt in einem steigenden Markt IMMER ueber 1,0. Ohne die
beiden Vergleiche unten faellt man darauf jedes Mal herein.

Die drei Fragen, die dieses Modul stellt
----------------------------------------
1. Schlaegt die Strategie den Zufall?          -> permutationstest()
2. Schlaegt sie einfaches Kaufen und Halten?   -> kaufen_und_halten()
3. Sind ueberhaupt genug Trades da?            -> Trades und Ampel

Erst wenn alle drei mit Ja beantwortet sind, lohnt das Weiterdenken.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from backtesting import Backtest, Strategy

from strategien.indikatoren import atr

# Standardkosten: 2 Basispunkte, entspricht bei EURUSD etwa 2 Pips je Trade.
KOSTEN_STANDARD = 0.0002
KAPITAL = 100_000

# Ab wie vielen Trades reden wir ueberhaupt von Statistik.
MIN_TRADES = 30
# Ab welchem Zufallsanteil gilt das Ergebnis als nicht belegt.
ZUFALL_GRENZE = 20.0


def _lauf(df, klasse, kosten, **kw):
    return Backtest(
        df, klasse, cash=KAPITAL, commission=kosten, finalize_trades=True
    ).run(**kw)


def kaufen_und_halten(df: pd.DataFrame) -> float:
    """Was haette blosses Kaufen und Liegenlassen gebracht (in Prozent)."""
    return (df["Close"].iloc[-1] / df["Close"].iloc[0] - 1.0) * 100.0


def _einsatz_anteil(stats, anzahl_bars: int, groesse: float = 0.1) -> float:
    """Wie viel Kapital war ueber die Zeit wirklich im Risiko (in Prozent).

    WICHTIGE EINSCHRAENKUNG des Vergleichs 'vs K+H':
    Kaufen-und-Halten setzt 100 % des Kapitals 100 % der Zeit ein. Unsere
    Strategien stehen mit 10 % Positionsgroesse und oft nur 8 % der Zeit im
    Markt. Ein direkter Vergleich der absoluten Prozente ist deshalb unfair
    und wuerde jede selektive Strategie kleinreden.

    Diese Funktion liefert 'Zeit im Markt x Positionsgroesse'. Damit laesst
    sich das Ergebnis je eingesetztem Kapital vergleichen - der eigentlich
    faire Massstab.
    """
    try:
        trades = stats["_trades"]
        bars_im_markt = float((trades["ExitBar"] - trades["EntryBar"]).sum())
    except (KeyError, TypeError, AttributeError):
        return float("nan")
    if anzahl_bars <= 0:
        return float("nan")
    return (bars_im_markt / anzahl_bars) * groesse * 100.0


def _zufalls_klasse(anzahl_bars, trade_wahrsch, atr_mult, rr, seed):
    """Baut eine Strategie, die zu gleicher Haeufigkeit blind einsteigt.

    Gleiche Trade-Frequenz, gleicher ATR-Stop, gleiches Ziel, nur der
    ZEITPUNKT ist gewuerfelt. Damit misst der Vergleich genau eines:
    steckt im Einstiegssignal Information oder nicht.
    """
    rng = np.random.default_rng(seed)
    wuerfel = rng.random(anzahl_bars)

    class Zufall(Strategy):
        def init(self):
            self.atr_wert = self.I(
                atr, self.data.High, self.data.Low, self.data.Close, 14
            )

        def next(self):
            i = len(self.data.Close) - 1
            if self.position or i < 20 or i >= len(wuerfel):
                return
            if wuerfel[i] >= trade_wahrsch:
                return
            dist = float(self.atr_wert[-1]) * atr_mult
            if not (dist > 0):
                return
            kurs = self.data.Close[-1]
            self.buy(size=0.1, sl=kurs - dist, tp=kurs + dist * rr)

    return Zufall


def permutationstest(
    df: pd.DataFrame,
    trades_echt: int,
    pf_echt: float,
    runden: int = 200,
    kosten: float = KOSTEN_STANDARD,
    atr_mult: float = 2.0,
    rr: float = 2.0,
    seed: int = 42,
) -> dict:
    """Wie oft erreicht blosser Zufall denselben Profitfaktor?

    Rueckgabe: Median der Zufalls-Profitfaktoren und der Anteil der Runden,
    in denen Zufall mindestens so gut war wie die Strategie (in Prozent).
    Dieser Anteil ist die entscheidende Zahl: unter 5 % ist das Ergebnis
    kaum durch Zufall erklaerbar, ueber 20 % reicht Zufall als Erklaerung.
    """
    if trades_echt < 1 or not np.isfinite(pf_echt):
        return {"zufall_median": float("nan"), "zufall_besser_pct": float("nan")}

    wahrsch = trades_echt / len(df)
    werte = []
    for runde in range(runden):
        klasse = _zufalls_klasse(
            len(df) + 5, wahrsch, atr_mult, rr, seed + runde
        )
        p = _lauf(df, klasse, kosten).get("Profit Factor", float("nan"))
        if np.isfinite(p):
            werte.append(float(p))

    if not werte:
        return {"zufall_median": float("nan"), "zufall_besser_pct": float("nan")}

    arr = np.array(werte)
    return {
        "zufall_median": float(np.median(arr)),
        "zufall_besser_pct": float((arr >= pf_echt).mean() * 100.0),
    }


def bewerte(
    df: pd.DataFrame,
    klasse,
    kosten: float = KOSTEN_STANDARD,
    runden: int = 200,
    mit_permutation: bool = True,
) -> dict:
    """Volle ehrliche Bewertung einer Strategie auf einem Datensatz."""
    stats = _lauf(df, klasse, kosten)
    trades = int(stats["# Trades"])
    pf = stats.get("Profit Factor", float("nan"))
    pf = float(pf) if pf == pf else float("nan")
    ergebnis = float(stats["Return [%]"])
    bnh = kaufen_und_halten(df)
    einsatz = _einsatz_anteil(stats, len(df))

    # Fairer Vergleich: Ergebnis je eingesetztem Kapital. Kaufen-und-Halten
    # laeuft mit 100 % Einsatz, die Strategie mit einem Bruchteil.
    if np.isfinite(einsatz) and einsatz > 0.01:
        je_einsatz = ergebnis / (einsatz / 100.0)
    else:
        je_einsatz = float("nan")

    zeile = {
        "Trades": trades,
        "PF": round(pf, 2) if np.isfinite(pf) else float("nan"),
        "Ergebnis %": round(ergebnis, 2),
        "Einsatz %": round(einsatz, 2) if np.isfinite(einsatz) else float("nan"),
        "je Einsatz %": round(je_einsatz, 1) if np.isfinite(je_einsatz) else float("nan"),
        "Kaufen+Halten %": round(bnh, 1),
        "vs K+H fair": (
            round(je_einsatz - bnh, 1) if np.isfinite(je_einsatz) else float("nan")
        ),
        "Ruecklauf %": round(float(stats["Max. Drawdown [%]"]), 2),
    }

    if mit_permutation:
        perm = permutationstest(df, trades, pf, runden=runden, kosten=kosten)
        zeile["Zufall PF"] = (
            round(perm["zufall_median"], 2)
            if np.isfinite(perm["zufall_median"])
            else float("nan")
        )
        zeile["Zufall besser %"] = (
            round(perm["zufall_besser_pct"], 1)
            if np.isfinite(perm["zufall_besser_pct"])
            else float("nan")
        )
    zeile["Urteil"] = urteil(zeile)
    return zeile


def urteil(zeile: dict) -> str:
    """Ein Wort Klartext statt Zahlendeuten."""
    pf = zeile.get("PF", float("nan"))
    if not np.isfinite(pf) or pf <= 1.0:
        return "verliert"

    zufall = zeile.get("Zufall besser %", float("nan"))
    if np.isfinite(zufall) and zufall > ZUFALL_GRENZE:
        return "= Zufall"

    if zeile.get("vs K+H fair", 0) < 0:
        return "< Halten"

    if zeile.get("Trades", 0) < MIN_TRADES:
        return "zu wenig Trades"

    return "PRUEFEN"


def lesehilfe() -> str:
    return "\n".join(
        [
            "Spalten:",
            "  PF               Profitfaktor. Ueber 1,0 = Gewinn. Allein aber wertlos.",
            "  Einsatz %        Zeit im Markt x Positionsgroesse. Wie viel Kapital",
            "                   wirklich im Risiko stand. Oft nur unter 1 %!",
            "  je Einsatz %     Ergebnis hochgerechnet auf vollen Kapitaleinsatz.",
            "                   NUR so ist der Vergleich mit Kaufen-und-Halten fair,",
            "                   denn das laeuft mit 100 % Einsatz 100 % der Zeit.",
            "  Kaufen+Halten %  Was der Markt selbst gemacht hat. Die echte Huerde.",
            "  vs K+H fair      je Einsatz minus Kaufen-und-Halten. Negativ = auch",
            "                   bei gleichem Kapitaleinsatz schlechter als liegen lassen.",
            "  Zufall PF        Profitfaktor blinder Zufallseinstiege (Median).",
            "  Zufall besser %  Anteil der Zufallslaeufe, die die Strategie erreichen",
            f"                   oder schlagen. Unter 5 % = Beleg. Ueber {ZUFALL_GRENZE:.0f} % = kein Beleg.",
            "",
            "Achtung zur Spalte 'je Einsatz %': das Hochrechnen unterstellt, dass",
            "die Strategie mit vollem Einsatz genauso funktioniert. Das stimmt nur",
            "ohne Hebel und ohne Nachschusspflicht. Es ist ein Vergleichsmassstab,",
            "keine Renditeprognose.",
            "",
            "Urteil:",
            "  verliert          PF unter 1,0.",
            "  = Zufall          Wuerfeln ist genauso gut. Keine Kante.",
            "  < Halten          schlechter als der Markt selbst.",
            f"  zu wenig Trades   unter {MIN_TRADES} Trades, statistisch keine Aussage.",
            "  PRUEFEN           haelt allen drei Pruefungen stand. Genauer ansehen!",
        ]
    )
