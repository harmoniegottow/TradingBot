"""
portfolio.py — Ein Mechanismus, viele Maerkte. Bewertung auf Portfolioebene.

Warum ueberhaupt neu
--------------------
pruefstand.py bewertet je Instrument einzeln. Eine Portfoliokante kann er
strukturell nicht finden: Time-Series-Momentum (Moskowitz/Ooi/Pedersen 2012,
Journal of Financial Economics, 58 Terminkontrakte) ist je Instrument schwach
und entsteht erst in der Summe. Genau das prueft dieses Modul.

Der Mechanismus (bewusst EINER, nicht viele)
--------------------------------------------
Time-Series-Momentum, so nah am Original wie moeglich:
  - Rendite der letzten N Handelstage anschauen (Rueckblick).
  - Positiv  -> long, negativ -> short. Kein Indikator, keine Schwelle.
  - Position invers zur Schwankungsbreite gewichten, damit ein ruhiges
    und ein wildes Instrument gleich viel Risiko tragen.
  - Monatlich neu ausrichten, nicht taeglich. Das spart Kosten.
  - Gleichgewichtet ueber alle Instrumente.

Ehrlichkeitsregeln, die hier eingebaut sind
-------------------------------------------
1. KEIN Blick in die Zukunft: das Signal von heute wird auf die Rendite von
   MORGEN angewendet (shift). Ein haeufiger, stiller Backtest-Fehler.
2. Kosten fallen nur bei tatsaechlicher Positionsaenderung an, nicht taeglich.
3. Der Permutationstest wuerfelt die VORZEICHEN der Signale, behaelt aber
   Gewichte, Zeitpunkte und Instrumente. Damit wird genau eine Frage
   gestellt: steckt in der Richtungsvorhersage Information?
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

DATA_DIR = Path("/opt/data/tradingbot/data")

# Kosten je Positionsaenderung, in Anteilen des gehandelten Volumens.
# 5 Basispunkte sind fuer Tagesdaten und Retail-Spanne bewusst konservativ.
KOSTEN_JE_WECHSEL = 0.0005
HANDELSTAGE_JAHR = 252


def lade_kurse(mindest_bars=600) -> pd.DataFrame:
    """Alle Tagesschlusskurse als eine Tabelle: Zeilen Datum, Spalten Symbol."""
    reihen = {}
    for pfad in sorted(DATA_DIR.glob("*_D_1.csv")):
        name = pfad.stem.replace("_D_1", "")
        df = pd.read_csv(pfad, parse_dates=["Zeit"]).set_index("Zeit")
        if len(df) < mindest_bars:
            continue
        reihen[name] = df["Close"]
    if not reihen:
        raise SystemExit(
            "Keine Tagesdaten gefunden. Erst 'python3 lade_portfolio.py 5' laufen lassen."
        )
    kurse = pd.DataFrame(reihen).sort_index()
    # Luecken (Feiertage je Markt) vorwaerts fuellen, aber nicht erfinden:
    # nur innerhalb der bekannten Historie des Instruments.
    return kurse.ffill()


def signale(kurse: pd.DataFrame, rueckblick: int, halten: int) -> pd.DataFrame:
    """+1 long, -1 short, je Instrument. Neuausrichtung alle 'halten' Tage."""
    rendite_rueck = kurse.pct_change(rueckblick, fill_method=None)
    roh = pd.DataFrame(
        np.sign(rendite_rueck.to_numpy()),
        index=rendite_rueck.index,
        columns=rendite_rueck.columns,
    )
    # Nur an Neuausrichtungstagen ein neues Signal, sonst halten.
    maske = np.zeros(len(kurse), dtype=bool)
    maske[::halten] = True
    gehalten = roh.where(pd.Series(maske, index=kurse.index), axis=0).ffill()
    return gehalten.fillna(0.0)


def gewichte(kurse: pd.DataFrame, sig: pd.DataFrame, vola_fenster=60) -> pd.DataFrame:
    """Inverse Schwankungsbreite: ruhige Instrumente bekommen mehr Gewicht."""
    tagesrendite = kurse.pct_change(fill_method=None)
    vola = tagesrendite.rolling(vola_fenster).std()
    ziel_vola = 0.10 / np.sqrt(HANDELSTAGE_JAHR)   # 10 % pro Jahr je Position
    g = (ziel_vola / vola).replace([np.inf, -np.inf], np.nan)
    g = g.clip(upper=5.0)                          # kein Hebelexzess
    return (sig * g).fillna(0.0)


def rendite_reihe(kurse: pd.DataFrame, pos: pd.DataFrame,
                  kosten=KOSTEN_JE_WECHSEL) -> pd.Series:
    """Tagesrendite des Portfolios, gleichgewichtet, nach Kosten.

    WICHTIG: pos wird um einen Tag versetzt. Das Signal von heute wirkt auf
    die Rendite von morgen. Ohne diesen Versatz blickt der Backtest in die
    Zukunft und jedes Ergebnis ist falsch.
    """
    tagesrendite = kurse.pct_change(fill_method=None).fillna(0.0)
    pos_wirksam = pos.shift(1).fillna(0.0)

    brutto = (pos_wirksam * tagesrendite).sum(axis=1)
    wechsel = pos_wirksam.diff().abs().fillna(0.0).sum(axis=1)
    anzahl = max(int((pos_wirksam != 0).any().sum()), 1)

    return (brutto - wechsel * kosten) / anzahl


def kennzahlen(r: pd.Series) -> dict:
    """Die ueblichen Kennzahlen, plus die, die wirklich zaehlen."""
    r = r.dropna()
    if len(r) < 30:
        return {}
    kapital = (1 + r).cumprod()
    jahre = len(r) / HANDELSTAGE_JAHR
    gesamt = float(kapital.iloc[-1] - 1)
    cagr = float(kapital.iloc[-1] ** (1 / jahre) - 1) if jahre > 0 else float("nan")
    vola = float(r.std() * np.sqrt(HANDELSTAGE_JAHR))
    sharpe = float(r.mean() / r.std() * np.sqrt(HANDELSTAGE_JAHR)) if r.std() > 0 else float("nan")
    hoch = kapital.cummax()
    rueck = float(((kapital - hoch) / hoch).min())
    gewinn = float(r[r > 0].sum())
    verlust = float(-r[r < 0].sum())
    return {
        "Jahre": round(jahre, 1),
        "Gesamt %": round(gesamt * 100, 1),
        "pro Jahr %": round(cagr * 100, 2),
        "Schwankung %": round(vola * 100, 1),
        "Sharpe": round(sharpe, 2),
        "Ruecklauf %": round(rueck * 100, 1),
        "PF": round(gewinn / verlust, 2) if verlust > 0 else float("nan"),
    }


def kaufen_und_halten(kurse: pd.DataFrame) -> dict:
    """Gleichgewichtet alles kaufen und liegen lassen. Die echte Huerde."""
    tagesrendite = kurse.pct_change(fill_method=None).fillna(0.0)
    return kennzahlen(tagesrendite.mean(axis=1))


def permutationstest(kurse, sig, gew, runden=300, seed=42,
                     kosten=KOSTEN_JE_WECHSEL, halten=21):
    """Wuerfelt die VORZEICHEN der Signale, behaelt alles andere.

    Gleiche Handelszeitpunkte, gleiche Gewichte, gleiche Instrumente, gleiche
    Kosten. Nur die Richtung ist geraten. Damit misst der Test genau eines:
    steckt in der Richtungsvorhersage Information oder nicht.

    ACHTUNG, hier lag zuerst ein Fehler: wuerfelt man das Vorzeichen fuer
    JEDEN TAG neu, dreht die Zufallsposition taeglich und erzeugt dadurch ein
    Vielfaches der Handelskosten. Der Zufall sieht dann kuenstlich schlecht
    aus und die eigene Strategie kuenstlich gut. Das Vorzeichen muss deshalb
    je NEUAUSRICHTUNGSBLOCK gewuerfelt werden, genau wie das echte Signal,
    damit beide dieselbe Handelshaeufigkeit haben.
    """
    echt = kennzahlen(rendite_reihe(kurse, gew, kosten))
    if not echt:
        return {}
    rng = np.random.default_rng(seed)
    betrag = gew.abs()

    # Blocknummer je Zeile: innerhalb eines Blocks bleibt das Vorzeichen gleich.
    block_nr = np.arange(len(sig)) // halten
    n_blocks = int(block_nr.max()) + 1

    sharpes, jahre, umschlag = [], [], []
    for _ in range(runden):
        # ein Vorzeichen je Block und Instrument
        vz_block = rng.choice([-1.0, 1.0], size=(n_blocks, sig.shape[1]))
        vz = pd.DataFrame(
            vz_block[block_nr], index=sig.index, columns=sig.columns
        )
        zufalls_pos = betrag * vz
        k = kennzahlen(rendite_reihe(kurse, zufalls_pos, kosten))
        if k:
            sharpes.append(k["Sharpe"])
            jahre.append(k["pro Jahr %"])
            umschlag.append(
                float(zufalls_pos.shift(1).fillna(0.0).diff().abs().sum().sum())
            )
    if not sharpes:
        return {}
    arr = np.array(sharpes, dtype=float)
    arr = arr[np.isfinite(arr)]
    echt_umschlag = float(gew.shift(1).fillna(0.0).diff().abs().sum().sum())
    return {
        "Sharpe echt": echt["Sharpe"],
        "Sharpe Zufall Median": round(float(np.median(arr)), 2),
        "Zufall besser %": round(float((arr >= echt["Sharpe"]).mean() * 100), 1),
        "pro Jahr Zufall Median %": round(float(np.median(jahre)), 2),
        # Kontrollzahl: muss aehnlich sein, sonst ist der Vergleich unfair
        "Umschlag echt": round(echt_umschlag, 1),
        "Umschlag Zufall": round(float(np.median(umschlag)), 1),
    }
