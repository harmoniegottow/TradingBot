"""
backtest.py — Testet die Trend-Pullback-Strategie auf historischen Daten und
rechnet realistische Kosten ein.

Strategie (uebernommen aus dem Beispiel-Bot beispiel-mt5-bot/strategy.py,
hier broker-neutral fuer den Backtest nachgebaut):

Long-Signal, wenn auf der ZULETZT GESCHLOSSENEN Kerze gilt:
  1. Schlusskurs ueber EMA(TREND_LEN)          -> Aufwaertstrend
  2. RSI(RSI_LEN) kreuzt von unten ueber RSI_OVERSOLD -> Pullback endet

Stop und Ziel:
  - Stop-Abstand = ATR(ATR_LEN) * ATR_STOP_MULT unter dem Einstieg
  - Take-Profit  = Stop-Abstand * RR_RATIO ueber dem Einstieg (Chance-Risiko 2:1)

Diese Strategie ist KEIN Gewinnversprechen. Der Backtest dient dazu, die im
Beispiel-Bot BEHAUPTETEN Profitfaktoren mit echten Daten selbst nachzurechnen,
statt sie zu glauben.

WICHTIG zum Zeitrahmen:
  Die Strategie ist fuer Stunden- und Vier-Stunden-Kerzen (H1/H4) auf Metallen
  und ausgewaehlten Waehrungspaaren gebaut. Laeuft dieses Skript auf
  EUR/USD-TAGESdaten, ist das nur ein technischer Funktionsnachweis, NICHT der
  validierte Zeitrahmen. Das Skript weist am Ende ausdruecklich darauf hin.

Aufruf:
    python backtest.py                 # Standard: EURUSD, Tagesdaten
    python backtest.py XAUUSD 1h        # anderes Symbol / Intervall (falls CSV da)
"""
from pathlib import Path
import sys
import numpy as np
import pandas as pd
from backtesting import Backtest, Strategy

DATA_DIR = Path(__file__).parent / "data"

# --- Strategie-Parameter (die NEUTRALEN Werte aus dem Beispiel-Bot,
#     NICHT pro Markt ueberoptimiert) ---
TREND_LEN = 150
RSI_LEN = 14
RSI_OVERSOLD = 35
ATR_LEN = 14
ATR_STOP_MULT = 2.0
RR_RATIO = 2.0

RISK_FRACTION = 0.01   # 1 % des Kapitals pro Trade riskiert (wie im Beispiel)


# --------------------------------------------------------------------------
# Indikatoren — bewusst identisch zur Beispiel-strategy.py, damit der Backtest
# genau das misst, was der Live-Bot spaeter rechnen wuerde.
# --------------------------------------------------------------------------
def ema(werte, laenge):
    return pd.Series(werte).ewm(span=laenge, adjust=False).mean()


def rsi(werte, laenge):
    serie = pd.Series(werte)
    delta = serie.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1 / laenge, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / laenge, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    out = 100 - (100 / (1 + rs))
    return out.fillna(50.0)


def atr(high, low, close, laenge):
    high = pd.Series(high)
    low = pd.Series(low)
    close = pd.Series(close)
    prev_close = close.shift(1)
    tr = pd.concat(
        [
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1 / laenge, adjust=False).mean()


class TrendPullback(Strategy):
    trend_len = TREND_LEN
    rsi_len = RSI_LEN
    rsi_oversold = RSI_OVERSOLD
    atr_len = ATR_LEN
    atr_stop_mult = ATR_STOP_MULT
    rr_ratio = RR_RATIO

    def init(self):
        preis = self.data.Close
        self.ema_trend = self.I(ema, preis, self.trend_len)
        self.rsi_wert = self.I(rsi, preis, self.rsi_len)
        self.atr_wert = self.I(
            atr, self.data.High, self.data.Low, self.data.Close, self.atr_len
        )

    def next(self):
        # Nur eine Position gleichzeitig im Backtest halten.
        if self.position:
            return

        kurs = self.data.Close[-1]
        up_trend = kurs > self.ema_trend[-1]
        cross_up = (
            self.rsi_wert[-1] > self.rsi_oversold
            and self.rsi_wert[-2] <= self.rsi_oversold
        )
        if not (up_trend and cross_up):
            return

        stop_dist = float(self.atr_wert[-1]) * self.atr_stop_mult
        if not np.isfinite(stop_dist) or stop_dist <= 0:
            return

        sl = kurs - stop_dist
        tp = kurs + stop_dist * self.rr_ratio
        # Positionsgroesse konservativ; die genaue Lot-Berechnung macht spaeter
        # der Live-Bot broker-abhaengig. Hier reicht ein fester kleiner Anteil.
        self.buy(size=0.1, sl=sl, tp=tp)


def lade_csv(symbol: str, intervall: str) -> pd.DataFrame:
    pfad = DATA_DIR / f"{symbol}_{intervall}.csv"
    if not pfad.exists():
        raise SystemExit(
            f"Datei fehlt: {pfad}. Erst 'python daten_laden.py' ausfuehren."
        )
    df = pd.read_csv(pfad, index_col=0, parse_dates=True)
    df = df[["Open", "High", "Low", "Close"]].dropna()
    return df


def main():
    symbol = sys.argv[1] if len(sys.argv) > 1 else "EURUSD"
    intervall = sys.argv[2] if len(sys.argv) > 2 else "1d"

    df = lade_csv(symbol, intervall)

    bt = Backtest(
        df,
        TrendPullback,
        cash=100000,
        commission=0.0002,   # ~2 Pips pro Trade als Kostenannahme (grosszuegig)
        finalize_trades=True,
    )
    stats = bt.run()

    print("=" * 60)
    print("BACKTEST-ERGEBNIS  Strategie: Trend-Pullback (EMA + RSI + ATR)")
    print(f"Symbol: {symbol}  Intervall: {intervall}")
    print(f"Trend-EMA: {TREND_LEN}  RSI: {RSI_LEN}/{RSI_OVERSOLD}  "
          f"ATR-Stop: {ATR_STOP_MULT}x  Chance-Risiko: {RR_RATIO}:1")
    print("=" * 60)
    for kennzahl in [
        "Start", "End", "Duration",
        "Return [%]", "Buy & Hold Return [%]",
        "Return (Ann.) [%]", "Volatility (Ann.) [%]",
        "Sharpe Ratio", "Max. Drawdown [%]",
        "# Trades", "Win Rate [%]", "Profit Factor",
    ]:
        if kennzahl in stats.index:
            print(f"  {kennzahl:26s}: {stats[kennzahl]}")
    print("=" * 60)
    if intervall == "1d" and symbol == "EURUSD":
        print("WARNUNG: Dies ist NUR ein technischer Funktionsnachweis.")
        print("EUR/USD-TAGESdaten sind NICHT der validierte Zeitrahmen dieser")
        print("Strategie (gebaut fuer H1/H4 auf Metallen und CHFJPY/USDJPY).")
        print("Die Zahlen hier sagen NICHTS ueber die echte Guete der Strategie")
        print("aus. Naechster Schritt: echte H1/H4-Historie beschaffen.")
    print("Hinweis: Return = Gesamtergebnis nach Kosten. Max. Drawdown =")
    print("groesster zwischenzeitlicher Verlust vom Hoch. Beides ehrlich")
    print("betrachten, nicht nur den Endgewinn.")
    return stats


if __name__ == "__main__":
    main()
