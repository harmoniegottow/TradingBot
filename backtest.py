"""
backtest.py — Testet die Strategie "zwei gleitende Durchschnitte" auf
historischen EUR/USD-Daten. Rechnet realistische Kosten ein.

Strategie (bewusst einfach, Etappe 3 des Plans):
- Zwei gleitende Durchschnitte: ein kurzer (schnell), ein langer (traege).
- Kurzer kreuzt langen von unten nach oben  -> kaufen (long).
- Kurzer kreuzt langen von oben nach unten  -> Position schliessen / short.
Diese Strategie folgt Trends. Sie ist KEIN Gewinnversprechen, sondern der
einfachste sinnvolle Ausgangspunkt, um das Vorgehen zu lernen und zu pruefen.

Aufruf:
    python backtest.py
"""
from pathlib import Path
import pandas as pd
from backtesting import Backtest, Strategy
from backtesting.lib import crossover

DATA_DIR = Path(__file__).parent / "data"


def sma(werte, fenster):
    """Einfacher gleitender Durchschnitt (Simple Moving Average)."""
    return pd.Series(werte).rolling(int(fenster)).mean()


class ZweiDurchschnitte(Strategy):
    # Fensterlaengen in Handelstagen; koennen beim Optimieren variiert werden.
    kurz = 20
    lang = 50

    def init(self):
        preis = self.data.Close
        self.ma_kurz = self.I(sma, preis, self.kurz)
        self.ma_lang = self.I(sma, preis, self.lang)

    def next(self):
        # Kurzer kreuzt langen nach oben -> Aufwaertstrend -> kaufen
        if crossover(self.ma_kurz, self.ma_lang):
            self.position.close()
            self.buy(size=0.1)   # nur 10% des Kapitals pro Position (konservativ)
        # Kurzer kreuzt langen nach unten -> Abwaertstrend -> verkaufen (short)
        elif crossover(self.ma_lang, self.ma_kurz):
            self.position.close()
            self.sell(size=0.1)


def lade_csv(symbol: str = "EURUSD") -> pd.DataFrame:
    pfad = DATA_DIR / f"{symbol}_1d.csv"
    if not pfad.exists():
        raise SystemExit(f"Datei fehlt: {pfad}. Erst 'python daten_laden.py' ausfuehren.")
    df = pd.read_csv(pfad, index_col=0, parse_dates=True)
    df = df[["Open", "High", "Low", "Close"]].dropna()
    return df


def main():
    df = lade_csv("EURUSD")

    # Kosten realistisch ansetzen:
    # - commission: typischer Spread/Kommission pro Trade. 0.0002 = 2 Pips
    #   (grosszuegig fuer EUR/USD; lieber zu teuer rechnen als zu billig).
    # - spread frisst bei jedem Ein- und Ausstieg Rendite.
    bt = Backtest(
        df,
        ZweiDurchschnitte,
        cash=100000,        # grosszuegiges Backtest-Kapital, damit Positionsgroessen
                            # sauber rechnen (Ergebnis in % ist unabhaengig davon)
        commission=0.0002,  # ~2 Pips pro Trade als Kostenannahme
        finalize_trades=True,
    )
    stats = bt.run()

    print("=" * 55)
    print("BACKTEST-ERGEBNIS  Strategie: zwei gleitende Durchschnitte")
    print(f"Paar: EUR/USD  Kurz: {ZweiDurchschnitte.kurz}  Lang: {ZweiDurchschnitte.lang}")
    print("=" * 55)
    for kennzahl in [
        "Start", "End", "Duration",
        "Return [%]", "Buy & Hold Return [%]",
        "Return (Ann.) [%]", "Volatility (Ann.) [%]",
        "Sharpe Ratio", "Max. Drawdown [%]",
        "# Trades", "Win Rate [%]", "Profit Factor",
    ]:
        if kennzahl in stats.index:
            print(f"  {kennzahl:26s}: {stats[kennzahl]}")
    print("=" * 55)
    print("Hinweis: Return = Gesamtergebnis nach Kosten. Max. Drawdown =")
    print("groesster zwischenzeitlicher Verlust vom Hoch. Beides ehrlich")
    print("betrachten, nicht nur den Endgewinn.")
    return stats


if __name__ == "__main__":
    main()
