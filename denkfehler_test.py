"""
denkfehler_test.py — Zwei Fragen empirisch geprueft, statt behauptet.

FRAGE 1 (Spezialisierung / "das Beste aussuchen"):
  Wenn ich viele Strategien teste und die beste nehme - wie gut sieht die
  beste aus, wenn ALLE nur Zufall sind? Das ist die Messlatte, die jede
  Auswahl erst uebertreffen muss.

FRAGE 2 (Kombination / "zwei Faktoren muessen erfuellt sein"):
  Macht das UND-Verknuepfen von Filtern das Ergebnis sicherer? Gemessen
  wird nicht der Profitfaktor, sondern seine UNSICHERHEIT (Vertrauens-
  bereich per Bootstrap). Sicherheit heisst engerer Bereich, nicht
  hoehere Zahl.

Aufruf: .venv/bin/python denkfehler_test.py
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from backtesting import Backtest, Strategy

from strategien.indikatoren import atr, ema, rsi

KOSTEN = 0.0002
KAPITAL = 100_000


def lade(symbol="XAUUSD", tf="H_1"):
    df = pd.read_csv(
        f"/opt/data/tradingbot/data/{symbol}_{tf}.csv", index_col=0, parse_dates=True
    )
    return df[["Open", "High", "Low", "Close"]].dropna()


def _stats(df, klasse):
    return Backtest(
        df, klasse, cash=KAPITAL, commission=KOSTEN, finalize_trades=True
    ).run()


def bootstrap_pf(trades: pd.DataFrame, runden=2000, seed=1) -> tuple:
    """Vertrauensbereich des Profitfaktors per Bootstrap.

    Zieht die vorhandenen Trades mit Zurueecklegen neu und rechnet jedes Mal
    den Profitfaktor. Das Ergebnis zeigt, wie stark die Kennzahl allein
    durch die Auswahl der Trades schwankt.

    Ein Bereich, der die 1,0 einschliesst, bedeutet: mit diesen Daten ist
    nicht einmal entschieden, ob die Strategie ueberhaupt Gewinn macht.
    """
    if trades is None or len(trades) < 3:
        return (float("nan"), float("nan"), float("nan"))
    pnl = trades["PnL"].to_numpy(dtype=float)
    rng = np.random.default_rng(seed)
    werte = []
    for _ in range(runden):
        stich = rng.choice(pnl, size=len(pnl), replace=True)
        gewinn = stich[stich > 0].sum()
        verlust = -stich[stich < 0].sum()
        if verlust > 0:
            werte.append(gewinn / verlust)
    if not werte:
        return (float("nan"), float("nan"), float("nan"))
    arr = np.array(werte)
    return (
        float(np.percentile(arr, 5)),
        float(np.median(arr)),
        float(np.percentile(arr, 95)),
    )


# ---------------------------------------------------------------- Frage 1
def frage1_auswahl_illusion(df, anzahl=50):
    """Teste 'anzahl' reine ZUFALLS-Strategien und schau auf die beste."""
    print("=" * 78)
    print("FRAGE 1: Wenn ich viele Strategien teste und die beste nehme -")
    print("         wie gut sieht die beste aus, wenn ALLE nur Zufall sind?")
    print("=" * 78)
    print(f"Getestet werden {anzahl} Strategien mit ZUFAELLIGEN Einstiegen.")
    print("Keine davon kann eine echte Kante haben. Per Konstruktion.\n")

    ergebnisse = []
    for i in range(anzahl):
        rng = np.random.default_rng(1000 + i)
        wuerfel = rng.random(len(df) + 10)

        class Zufall(Strategy):
            def init(self):
                self.atr_wert = self.I(
                    atr, self.data.High, self.data.Low, self.data.Close, 14
                )

            def next(self):
                j = len(self.data.Close) - 1
                if self.position or j < 20:
                    return
                if wuerfel[j] >= 0.011:
                    return
                d = float(self.atr_wert[-1]) * 2.0
                if not (d > 0):
                    return
                k = self.data.Close[-1]
                self.buy(size=0.1, sl=k - d, tp=k + d * 2.0)

        st = _stats(df, Zufall)
        pf = st.get("Profit Factor", float("nan"))
        if pf == pf:
            ergebnisse.append((float(pf), int(st["# Trades"]), st["_trades"]))

    ergebnisse.sort(key=lambda x: -x[0])
    pfs = np.array([e[0] for e in ergebnisse])

    print(f"  Profitfaktor Mittelwert  : {pfs.mean():.2f}")
    print(f"  Profitfaktor Median      : {np.median(pfs):.2f}")
    print(f"  SCHLECHTESTE von {anzahl}     : {pfs.min():.2f}")
    print(f"  BESTE von {anzahl}            : {pfs.max():.2f}   <-- die haetten wir gewaehlt")
    print(f"  Anteil ueber PF 1,3      : {(pfs > 1.3).mean()*100:.0f} %")

    beste_pf, beste_trades, beste_tr = ergebnisse[0]
    u, m, o = bootstrap_pf(beste_tr)
    print(f"\n  Die 'Siegerstrategie' im Detail:")
    print(f"    Profitfaktor      : {beste_pf:.2f} bei {beste_trades} Trades")
    print(f"    Vertrauensbereich : {u:.2f} bis {o:.2f}  (90 %)")
    print(f"    -> Der Bereich schliesst 1,0 {'EIN' if u <= 1.0 <= o else 'NICHT ein'}.")
    print()
    print("  MERKE: Diese Siegerin ist NACHWEISLICH Zufall - sie wuerfelt.")
    print(f"  Wer aus {anzahl} Versuchen die beste aussucht, findet also auch bei")
    print(f"  reinem Rauschen einen Profitfaktor um {pfs.max():.2f}. Genau das ist die")
    print("  Huerde, die eine 'ausgewaehlte beste Strategie' erst schlagen muss.")
    return pfs.max()


# ---------------------------------------------------------------- Frage 2
class Basis(Strategy):
    """Trend-Pullback wie gehabt: EMA-Trend + RSI-Kreuzung."""

    stufe = 1

    def init(self):
        p = self.data.Close
        self.ema_trend = self.I(ema, p, 150)
        self.ema_lang = self.I(ema, p, 400)
        self.rsi_wert = self.I(rsi, p, 14)
        self.atr_wert = self.I(atr, self.data.High, self.data.Low, p, 14)
        self.atr_lang = self.I(atr, self.data.High, self.data.Low, p, 100)

    def next(self):
        if self.position:
            return
        kurs = self.data.Close[-1]
        if len(self.data.Close) < 420:
            return

        # Stufe 1: Trend + RSI-Kreuzung von unten
        if not (kurs > self.ema_trend[-1]):
            return
        if not (self.rsi_wert[-1] > 35 and self.rsi_wert[-2] <= 35):
            return

        # Stufe 2: zusaetzlich uebergeordneter Trend
        if self.stufe >= 2 and not (kurs > self.ema_lang[-1]):
            return

        # Stufe 3: zusaetzlich ruhige Marktphase
        if self.stufe >= 3 and not (self.atr_wert[-1] < self.atr_lang[-1]):
            return

        # Stufe 4: zusaetzlich Kerze im Plus
        if self.stufe >= 4 and not (kurs > self.data.Open[-1]):
            return

        d = float(self.atr_wert[-1]) * 2.0
        if not (d > 0):
            return
        self.buy(size=0.1, sl=kurs - d, tp=kurs + d * 2.0)


def frage2_kombination(df):
    print("\n" + "=" * 78)
    print("FRAGE 2: Macht 'mehrere Faktoren muessen erfuellt sein' das")
    print("         Ergebnis sicherer?")
    print("=" * 78)
    print("Gemessen wird die UNSICHERHEIT: der Vertrauensbereich des")
    print("Profitfaktors. Sicherer = ENGERER Bereich, nicht hoehere Zahl.\n")

    namen = {
        1: "Trend + RSI",
        2: "+ uebergeordneter Trend",
        3: "+ ruhige Phase",
        4: "+ Kerze im Plus",
    }
    print(f"  {'Filter':26s} {'Trades':>7s} {'PF':>6s} {'Vertrauensbereich':>22s} {'Breite':>8s}")
    zeilen = []
    for stufe in (1, 2, 3, 4):
        klasse = type("Stufe", (Basis,), {"stufe": stufe})
        st = _stats(df, klasse)
        n = int(st["# Trades"])
        pf = st.get("Profit Factor", float("nan"))
        pf = float(pf) if pf == pf else float("nan")
        u, m, o = bootstrap_pf(st["_trades"])
        breite = o - u if np.isfinite(u) and np.isfinite(o) else float("nan")
        bereich = f"{u:.2f} - {o:.2f}" if np.isfinite(u) else "zu wenig Trades"
        print(f"  {namen[stufe]:26s} {n:7d} {pf:6.2f} {bereich:>22s} {breite:8.2f}")
        zeilen.append((namen[stufe], n, pf, u, o, breite))

    print()
    erste, letzte = zeilen[0], zeilen[-1]
    print(f"  Von '{erste[0]}' zu '{letzte[0]}':")
    print(f"    Trades: {erste[1]} -> {letzte[1]}  ({(letzte[1]/erste[1]-1)*100:+.0f} %)")
    if np.isfinite(erste[5]) and np.isfinite(letzte[5]):
        print(f"    Profitfaktor: {erste[2]:.2f} -> {letzte[2]:.2f}")
        print(f"    Unsicherheit (Breite): {erste[5]:.2f} -> {letzte[5]:.2f}"
              f"  ({(letzte[5]/erste[5]-1)*100:+.0f} %)")
        if letzte[5] > erste[5]:
            print("\n  ERGEBNIS: Der Profitfaktor steigt vielleicht, aber der")
            print("  Vertrauensbereich wird BREITER. Das Ergebnis ist also")
            print("  UNSICHERER geworden, nicht sicherer.")
    return zeilen


def main():
    df = lade("XAUUSD", "H_1")
    print(f"Datenbasis: Gold H1, {len(df)} Kerzen, "
          f"{df.index.min().date()} bis {df.index.max().date()}\n")
    frage1_auswahl_illusion(df, anzahl=50)
    frage2_kombination(df)
    print("\n" + "=" * 78)


if __name__ == "__main__":
    main()
