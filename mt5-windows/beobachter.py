"""
beobachter.py — Bot im BEOBACHTUNGSMODUS.

Erkennt Signale, rechnet aus, WAS er handeln wuerde, und schreibt alles
ins Journal. **Sendet niemals einen Auftrag.** Es gibt in dieser Datei
keinen einzigen Aufruf von order_send() — das ist Absicht und der
gesamte Zweck des Skripts.

Warum ueberhaupt beobachten statt Demo zu handeln?
Die Strategien der Beispiel-Bots haben unseren Pruefstand nicht
bestanden (zehn von zwoelf Laeufen verlieren Geld). Demo-Handel wuerde
Wochen kosten und uns nichts sagen, was wir nicht schon wissen.
Der Beobachtungsmodus dagegen prueft genau das, was der Backtest NICHT
pruefen kann:

  - Stimmen die Symbolnamen beim Broker?
  - Kommen die Signale zur erwarteten Zeit?
  - Rechnet die broker-eigene Lot-Berechnung plausible Groessen aus?
  - Wie hoch sind Spread und Kosten in echt?

Das sind reale Erkenntnisse ohne jedes Risiko und ohne Scheinsicherheit.

Aufruf (Eingabeaufforderung in diesem Ordner):

    python beobachter.py

Beenden mit Strg+C. Laeuft der Rechner durch, laeuft der Beobachter durch.
"""
from __future__ import annotations

import csv
import json
import logging
import math
import os
import sys
import time
from datetime import datetime, timezone

try:
    import MetaTrader5 as mt5
except ImportError:
    print("FEHLER: Das Paket MetaTrader5 fehlt.")
    print("Installieren mit:  pip install MetaTrader5 pandas")
    print("Hinweis: Das geht nur unter Windows.")
    sys.exit(1)

import pandas as pd

# ----------------------------------------------------------------------
# Einstellungen
# ----------------------------------------------------------------------
# Grundnamen ohne Broker-Kuerzel. Das Kuerzel (.a, .m, ...) wird beim
# Start automatisch gesucht — siehe finde_symbole().
#
# AUSWAHL BEGRUENDET: Das Demokonto hat 50.000 EUR, das spaetere
# Echtgeldkonto soll 500 bis 1.000 EUR haben. Das kleinste handelbare Lot
# ist ueberall 0,01 und laesst sich nicht unterschreiten. Bei 1.000 EUR
# und 0,5 % Risiko (= 5 EUR je Trade) riskiert 0,01 Lot:
#     EURUSD  1,76 EUR   -> passt
#     USDJPY  2,01 EUR   -> passt
#     CHFJPY  4,38 EUR   -> passt knapp
#     GBPUSD 15,75 EUR   -> 3x zu gross
#     XAUUSD 35,22 EUR   -> 7x zu gross
# Deshalb stehen hier die Maerkte, die auch mit kleinem Konto
# funktionieren. Gold laeuft als BEOBACHTUNG mit (der Beobachter handelt
# ohnehin nicht) — im Journal steht dann, dass es real nicht ginge.
# Sonst gaukelt das grosse Demokonto eine Auswahl vor, die das echte
# Konto spaeter nicht hat.
MAERKTE = {
    "EURUSD": "H1",
    "USDJPY": "H1",
    "CHFJPY": "H4",
    "XAUUSD": "H4",   # nur zur Beobachtung, mit 1.000 EUR nicht handelbar
}

ALTERNATIVEN = {
    "XAUUSD": ["GOLD", "GOLDUSD"],
    "XAGUSD": ["SILVER", "SILVERUSD"],
}

# ----------------------------------------------------------------------
# Strategie 2: Divergenz Gold gegen Silber
# ----------------------------------------------------------------------
# Das ist der EINZIGE Fund, der unseren Pruefstand bestanden hat —
# geprueft auf zehn Jahren echten Broker-Daten (15447 H4-Kerzen):
#   Gesamt   136 Trades, Profitfaktor 1,95, Zufall besser in 0,5 %
#   TEST-Fenster (nie fuer die Parameterwahl benutzt): PF 2,84
#   Parameter-Nachbarschaft: 11 von 15 Einstellungen bestehen
#   Kosten: bis 5-fach unauffaellig (PF 1,58)
#   Gegen Zufall MIT gleichem Trendfilter: 0 von 30 Laeufen erreichen ihn
#
# Idee: Gold und Silber laufen normalerweise zusammen. Faellt Gold
# gegenueber Silber deutlich zurueck (Momentum-Differenz unter ein
# -1,5-Sigma-Band) und holt dann wieder auf (Differenz kreuzt zurueck
# darueber), gilt das als Kaufsignal fuer Gold. Zusaetzlich muss Gold
# ueber seiner EMA150 stehen.
#
# ACHTUNG: Braucht ZWEI Kurse. Gehandelt wird nur Gold, Silber ist reine
# Referenz. Und: Mit 1.000 EUR Echtgeld waere Gold NICHT handelbar
# (0,01 Lot riskiert rund 35 EUR). Hier laeuft es zur Beobachtung mit,
# das Journal haelt fest, dass es real nicht ginge.
DIVERGENZ_AN = True
DIV_SYMBOL = "XAUUSD"        # wird gehandelt
DIV_REFERENZ = "XAGUSD"      # nur Referenz, wird NICHT gehandelt
DIV_TIMEFRAME = "H4"
DIV_TREND_LEN = 150
DIV_ATR_LEN = 14
DIV_ATR_STOP_MULT = 2.0
DIV_RR_RATIO = 2.0
DIV_RET_LEN = 20             # Kerzen fuer die Renditeberechnung
DIV_BAND_LOOKBACK = 100      # Kerzen fuer Mittelwert/Streuung der Differenz
DIV_BAND_MULT = 1.5          # -1,5-Sigma-Band

# Strategie-Parameter (wie David-V2, aber NUR LONG).
# Begruendung: Auf unseren Daten war "nur Long" auf allen drei getesteten
# Maerkten besser als Long+Short (Gold PF 1.59 gegen 1.48).
TREND_LEN = 200
RSI_LEN = 14
RSI_OVERSOLD = 35
ATR_LEN = 14
ATR_STOP_MULT = 1.5
RR_RATIO = 2.0
TREND_BUFFER_ATR = 0.25
TRADE_LONG = True
TRADE_SHORT = False

RISK_PERCENT = 0.5      # nur zur Berechnung — es wird nichts gesendet
BARS_HISTORY = 600
POLL_SECONDS = 30
HEARTBEAT_MINUTES = 30

JOURNAL_FILE = "beobachtung.csv"
STATE_FILE = "beobachter_state.json"
LOG_FILE = "beobachter.log"

TIMEFRAMES = {
    "M15": mt5.TIMEFRAME_M15, "M30": mt5.TIMEFRAME_M30,
    "H1": mt5.TIMEFRAME_H1, "H4": mt5.TIMEFRAME_H4,
    "D1": mt5.TIMEFRAME_D1,
}

JOURNAL_COLS = [
    "zeit", "strategie", "kerze", "symbol", "timeframe", "richtung", "kurs",
    "sl", "tp", "lots_berechnet", "risiko_waehrung", "spread_punkte",
    "spread_anteil_stop", "rsi", "atr", "grund", "kapital", "haette_gehandelt",
]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.FileHandler(LOG_FILE, encoding="utf-8"),
              logging.StreamHandler()],
)
log = logging.getLogger("beobachter")


# ----------------------------------------------------------------------
# Indikatoren (reines pandas, gleiche Formeln wie im Backtest)
# ----------------------------------------------------------------------
def ema(series: pd.Series, length: int) -> pd.Series:
    return series.ewm(span=length, adjust=False, min_periods=length).mean()


def rsi(close: pd.Series, length: int) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)
    avg_gain = gain.ewm(alpha=1.0 / length, adjust=False, min_periods=length).mean()
    avg_loss = loss.ewm(alpha=1.0 / length, adjust=False, min_periods=length).mean()
    rs = avg_gain.divide(avg_loss.where(avg_loss > 0))
    out = 100.0 - 100.0 / (1.0 + rs)
    flach = avg_loss.eq(0)
    out = out.mask(flach & avg_gain.gt(0), 100.0)
    out = out.mask(flach & avg_gain.eq(0), 50.0)
    return out


def atr(df: pd.DataFrame, length: int) -> pd.Series:
    vorher = df["close"].shift(1)
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - vorher).abs(),
        (df["low"] - vorher).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1.0 / length, adjust=False, min_periods=length).mean()


MIN_BARS = max(TREND_LEN * 2, RSI_LEN + 1, ATR_LEN + 1) + 2


def zustand(df: pd.DataFrame) -> dict | None:
    """Indikatorwerte der letzten geschlossenen Kerze."""
    if df is None or len(df) < MIN_BARS:
        return None
    close = df["close"]
    e = ema(close, TREND_LEN)
    r = rsi(close, RSI_LEN)
    a = atr(df, ATR_LEN)

    werte = (close.iloc[-1], e.iloc[-1], r.iloc[-1], r.iloc[-2], a.iloc[-1])
    if any(pd.isna(v) for v in werte):
        return None
    c, e_jetzt, r_jetzt, r_vor, a_jetzt = (float(v) for v in werte)

    puffer = a_jetzt * TREND_BUFFER_ATR
    if c > e_jetzt + puffer:
        trend = "up"
    elif c < e_jetzt - puffer:
        trend = "down"
    else:
        trend = "neutral"

    return {"close": c, "ema": e_jetzt, "rsi": r_jetzt, "rsi_vor": r_vor,
            "atr": a_jetzt, "trend": trend}


def signal(df: pd.DataFrame) -> tuple[dict | None, str]:
    """Gibt (Signal oder None, Begruendung) zurueck."""
    s = zustand(df)
    if s is None:
        return None, "zu wenige Kerzen"
    if s["trend"] == "neutral":
        return None, "Kurs zu nah an der EMA (Neutralzone)"

    stop_dist = s["atr"] * ATR_STOP_MULT
    if stop_dist <= 0:
        return None, "Stop-Abstand nicht berechenbar"

    ueberkauft = 100.0 - RSI_OVERSOLD

    if s["trend"] == "up":
        if not TRADE_LONG:
            return None, "Aufwaertstrend, aber Long abgeschaltet"
        if s["rsi_vor"] <= RSI_OVERSOLD < s["rsi"]:
            return ({"dir": "long", "rsi": s["rsi"], "atr": s["atr"],
                     "stop_dist": stop_dist}, "Long-Signal")
        if s["rsi"] <= RSI_OVERSOLD:
            return None, f"LONG: RSI {s['rsi']:.0f} in der Zone, noch kein Kreuz"
        return None, (f"LONG: RSI {s['rsi']:.0f} — noch "
                      f"{s['rsi'] - RSI_OVERSOLD:.0f} Punkte bis zur Zone")

    if not TRADE_SHORT:
        return None, "Abwaertstrend, Short bewusst abgeschaltet"
    if s["rsi_vor"] >= ueberkauft > s["rsi"]:
        return ({"dir": "short", "rsi": s["rsi"], "atr": s["atr"],
                 "stop_dist": stop_dist}, "Short-Signal")
    return None, f"SHORT: RSI {s['rsi']:.0f}, kein Kreuz"


# ----------------------------------------------------------------------
# Divergenz Gold/Silber — dieselbe Rechnung wie im Backtest
# (strategien/divergenz_gold_silber.py). Wird gegen diese Referenz
# getestet, siehe test_beobachter.py.
# ----------------------------------------------------------------------
def _div_differenz(df_gold: pd.DataFrame, df_silber: pd.DataFrame):
    """Momentum-Differenz Gold minus Silber und ihr unteres Band.

    Silber wird per ffill auf den Gold-Index gelegt: immer der letzte
    bekannte Silberkurs AUF ODER VOR dem Gold-Zeitstempel, nie ein
    spaeterer. Ein spaeterer waere ein Blick in die Zukunft.
    """
    y = df_silber["close"].reindex(df_gold.index, method="ffill")
    if y.isna().all():
        return None, None

    ret_x = df_gold["close"] / df_gold["close"].shift(DIV_RET_LEN) - 1.0
    ret_y = y / y.shift(DIV_RET_LEN) - 1.0
    d = ret_x - ret_y

    mittel = d.rolling(DIV_BAND_LOOKBACK, min_periods=DIV_BAND_LOOKBACK).mean()
    streuung = d.rolling(DIV_BAND_LOOKBACK, min_periods=DIV_BAND_LOOKBACK).std()
    return d, mittel - DIV_BAND_MULT * streuung


DIV_MIN_BARS = max(DIV_TREND_LEN * 2,
                   DIV_RET_LEN + DIV_BAND_LOOKBACK,
                   DIV_ATR_LEN) + 5


def divergenz_signal(df_gold: pd.DataFrame,
                     df_silber: pd.DataFrame) -> tuple[dict | None, str]:
    """Prueft die letzte geschlossene Gold-Kerze auf ein Divergenz-Signal."""
    if df_gold is None or df_silber is None:
        return None, "Kursdaten fehlen"
    if len(df_gold) < DIV_MIN_BARS or len(df_silber) < DIV_MIN_BARS:
        return None, (f"zu wenige Kerzen ({len(df_gold)}/{len(df_silber)}, "
                      f"noetig {DIV_MIN_BARS})")

    d, band = _div_differenz(df_gold, df_silber)
    if d is None:
        return None, "Silberkurse passen nicht zum Gold-Zeitraster"
    if any(pd.isna(v) for v in (d.iloc[-1], d.iloc[-2],
                                band.iloc[-1], band.iloc[-2])):
        return None, "Band noch nicht berechenbar"

    jetzt_unter = bool(d.iloc[-1] <= band.iloc[-1])
    vorher_unter = bool(d.iloc[-2] <= band.iloc[-2])
    kreuzung = vorher_unter and not jetzt_unter

    ema_trend = ema(df_gold["close"], DIV_TREND_LEN)
    atr_wert = atr(df_gold, DIV_ATR_LEN)
    if pd.isna(ema_trend.iloc[-1]) or pd.isna(atr_wert.iloc[-1]):
        return None, "Indikatoren noch nicht eingeschwungen"

    im_trend = bool(df_gold["close"].iloc[-1] > ema_trend.iloc[-1])
    abstand = float(d.iloc[-1] - band.iloc[-1])

    if not kreuzung:
        if jetzt_unter:
            return None, (f"Gold haengt zurueck (Differenz {d.iloc[-1]:+.4f} "
                          f"unter Band {band.iloc[-1]:+.4f}) — warte auf "
                          f"Rueckkreuzung")
        return None, (f"kein Uebergang (Differenz {d.iloc[-1]:+.4f}, "
                      f"Abstand zum Band {abstand:+.4f})")

    if not im_trend:
        return None, ("Rueckkreuzung da, aber Gold unter der "
                      f"EMA{DIV_TREND_LEN} — kein Kauf im Abwaertstrend")

    stop_dist = float(atr_wert.iloc[-1]) * DIV_ATR_STOP_MULT
    if stop_dist <= 0:
        return None, "Stop-Abstand nicht berechenbar"

    return ({"dir": "long", "rsi": float(d.iloc[-1]), "atr": float(atr_wert.iloc[-1]),
             "stop_dist": stop_dist, "rr": DIV_RR_RATIO}, "Divergenz-Signal")


# ----------------------------------------------------------------------
# Verbindung und Symbole
# ----------------------------------------------------------------------
def verbinden() -> None:
    # Auf dem VPS laufen zwei Terminals (Admin- und Bot-Sitzung). Ueber
    # MT5_PFAD laesst sich festlegen, welches gemeint ist.
    pfad = os.environ.get("MT5_PFAD")
    ok = mt5.initialize(path=pfad, timeout=60000) if pfad else mt5.initialize()
    if not ok:
        log.error(f"MT5-Initialisierung fehlgeschlagen: {mt5.last_error()}")
        log.error("Ist das MT5-Terminal gestartet und eingeloggt?")
        sys.exit(1)
    acc = mt5.account_info()
    if acc is None:
        log.error("Kein Konto gefunden — im MT5-Terminal einloggen.")
        mt5.shutdown()
        sys.exit(1)
    ist_demo = acc.trade_mode == mt5.ACCOUNT_TRADE_MODE_DEMO
    log.info(f"Verbunden: Konto {acc.login} ({acc.server}), "
             f"{'DEMO' if ist_demo else 'ECHTGELD'}, "
             f"{acc.balance:.2f} {acc.currency}")
    if not ist_demo:
        log.warning("Das ist ein ECHTGELDKONTO. Dieser Beobachter handelt "
                    "zwar nicht, trotzdem besser ein Demokonto verwenden.")


def _passende_namen(basis: str, namen: list[str]) -> list[str]:
    """Broker-Namen zu einem Grundnamen, Futures aussortiert.

    Beruecksichtigt Kuerzel wie '.a' oder '.m' und uebliche
    Alternativbezeichnungen (GOLD statt XAUUSD). Varianten wie
    'XAUUSD-F' oder 'GOLD-PERP' fliegen raus: das sind andere
    Instrumente mit anderer Kontraktgroesse und Verfall.
    """
    treffer = []
    for k in [basis] + ALTERNATIVEN.get(basis, []):
        treffer += [n for n in namen
                    if n == k or (n.startswith(k) and len(n) <= len(k) + 5)]
    treffer = [n for n in treffer
               if not any(t in n.upper() for t in ("-F", "PERP", "FUT", "-C"))]
    return sorted(set(treffer), key=len)


def finde_einzeln(basisnamen: list[str]) -> dict[str, str]:
    """Sucht einzelne Symbole und aktiviert sie im Terminal.

    Rueckgabe: Grundname -> echter Broker-Name. Fehlende fehlen im Dict.
    Wird fuer die Divergenz gebraucht, weil dort auch ein Symbol noetig
    ist, das gar nicht gehandelt wird (Silber als reine Referenz).
    """
    alle = mt5.symbols_get()
    namen = [s.name for s in alle] if alle else []
    ergebnis: dict[str, str] = {}
    for basis in basisnamen:
        treffer = _passende_namen(basis, namen)
        if not treffer:
            log.warning(f"{basis}: beim Broker nicht gefunden.")
            continue
        name = treffer[0]
        info = mt5.symbol_info(name)
        if info is not None and not info.visible:
            mt5.symbol_select(name, True)
        ergebnis[basis] = name
    return ergebnis


def finde_symbole() -> dict[str, str]:
    """Sucht die echten Broker-Namen (mit eventuellem Kuerzel wie '.a')."""
    alle = mt5.symbols_get()
    namen = [s.name for s in alle] if alle else []
    ergebnis: dict[str, str] = {}

    for basis, tf in MAERKTE.items():
        treffer = _passende_namen(basis, namen)
        if not treffer:
            log.warning(f"{basis}: beim Broker nicht gefunden — uebersprungen.")
            continue
        name = treffer[0]
        info = mt5.symbol_info(name)
        if info is not None and not info.visible:
            mt5.symbol_select(name, True)
        ergebnis[name] = tf
        zusatz = f"  (gefunden als '{name}')" if name != basis else ""
        log.info(f"{basis}: aktiv ({tf}){zusatz}")

    if not ergebnis:
        log.error("Keiner der konfigurierten Maerkte verfuegbar — Abbruch.")
        mt5.shutdown()
        sys.exit(1)
    return ergebnis


def geschlossene_kerzen(symbol: str, tf_name: str) -> pd.DataFrame | None:
    tf = TIMEFRAMES.get(tf_name)
    if tf is None:
        log.error(f"{symbol}: unbekannter Zeitrahmen '{tf_name}'.")
        return None
    try:
        rates = mt5.copy_rates_from_pos(symbol, tf, 0, BARS_HISTORY)
    except Exception as exc:
        log.warning(f"{symbol}: Kursabruf fehlgeschlagen: {exc}")
        return None
    if rates is None or len(rates) < 2:
        return None
    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
    df = df.set_index("time")[["open", "high", "low", "close"]]
    df = df.iloc[:-1]          # laufende Kerze weg
    return df if not df.empty else None


# ----------------------------------------------------------------------
# Was WUERDE der Bot handeln? (rechnen, nicht senden)
# ----------------------------------------------------------------------
def wuerde_handeln(symbol: str, sig: dict) -> dict:
    """
    Berechnet Einstieg, Stop, Ziel und Lot-Groesse — genau wie ein echter
    Bot es taete. Sendet NICHTS. Prueft damit vor allem, ob die
    broker-eigene Lot-Berechnung plausible Werte liefert.
    """
    ergebnis: dict = {"moeglich": False, "grund": ""}

    info = mt5.symbol_info(symbol)
    tick = mt5.symbol_info_tick(symbol)
    acc = mt5.account_info()
    if info is None or tick is None or acc is None:
        ergebnis["grund"] = "keine Symbol- oder Kontodaten"
        return ergebnis

    ist_long = sig["dir"] == "long"
    kurs = tick.ask if ist_long else tick.bid
    if kurs <= 0:
        ergebnis["grund"] = "kein gueltiger Kurs"
        return ergebnis

    spread = tick.ask - tick.bid
    stop_dist = sig["stop_dist"]
    ergebnis["spread_punkte"] = spread / info.point if info.point else 0
    ergebnis["spread_anteil_stop"] = spread / stop_dist if stop_dist > 0 else 0

    # Mindestabstand des Brokers beachten
    stops_level = getattr(info, "trade_stops_level", 0) or 0
    min_abstand = max(stops_level * info.point, spread * 2)
    eff_stop = max(stop_dist, min_abstand * 1.1)

    digits = info.digits
    if ist_long:
        sl = round(kurs - eff_stop, digits)
        tp = round(kurs + eff_stop * RR_RATIO, digits)
        order_type = mt5.ORDER_TYPE_BUY
    else:
        sl = round(kurs + eff_stop, digits)
        tp = round(kurs - eff_stop * RR_RATIO, digits)
        order_type = mt5.ORDER_TYPE_SELL

    ergebnis.update({"kurs": kurs, "sl": sl, "tp": tp})

    # Lot-Groesse ueber die BROKER-EIGENE Rechnung, nicht selbst gebastelt.
    risiko_geld = acc.equity * (RISK_PERCENT / 100)
    verlust_je_lot = mt5.order_calc_profit(order_type, symbol, 1.0, kurs, sl)
    if verlust_je_lot is None or abs(verlust_je_lot) <= 0:
        ergebnis["grund"] = f"order_calc_profit fehlgeschlagen ({mt5.last_error()})"
        return ergebnis
    verlust_je_lot = abs(verlust_je_lot)

    roh = risiko_geld / verlust_je_lot
    schritt = info.volume_step or 0.01
    lots = round(math.floor(roh / schritt) * schritt, 8)   # ABRUNDEN

    if lots > info.volume_max:
        lots = info.volume_max
    if lots < info.volume_min:
        min_risiko = mt5.order_calc_profit(order_type, symbol,
                                           info.volume_min, kurs, sl)
        min_risiko = abs(min_risiko) if min_risiko is not None else None
        if min_risiko is None or min_risiko > 2 * risiko_geld:
            ergebnis["grund"] = (f"Mindest-Lot {info.volume_min} riskiert zu viel "
                                 f"(Ziel {risiko_geld:.2f})")
            return ergebnis
        lots = info.volume_min

    echtes_risiko = mt5.order_calc_profit(order_type, symbol, lots, kurs, sl)
    echtes_risiko = abs(echtes_risiko) if echtes_risiko is not None else float("nan")

    ergebnis.update({
        "moeglich": True, "lots": lots, "risiko": echtes_risiko,
        "risiko_ziel": risiko_geld, "kapital": acc.equity,
    })

    # Spread-Schutz wie im Original: ueber 15 % des Stops nicht handeln.
    if spread > stop_dist * 0.15:
        ergebnis["moeglich"] = False
        ergebnis["grund"] = (f"Spread {spread / info.point:.0f} Punkte zu hoch "
                             f"(ueber 15 % des Stop-Abstands)")
    return ergebnis


# ----------------------------------------------------------------------
# Journal und Zustand
# ----------------------------------------------------------------------
def journal(zeile: dict) -> None:
    try:
        neu = not os.path.exists(JOURNAL_FILE)
        with open(JOURNAL_FILE, "a", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=JOURNAL_COLS, delimiter=";",
                               extrasaction="ignore", restval="")
            if neu:
                w.writeheader()
            w.writerow(zeile)
    except OSError as exc:
        log.error(f"Journal nicht schreibbar: {exc}")


def state_laden() -> dict:
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def state_speichern(daten: dict) -> None:
    try:
        tmp = STATE_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(daten, f)
        os.replace(tmp, STATE_FILE)   # atomar
    except OSError as exc:
        log.warning(f"Zustand nicht speicherbar: {exc}")


# ----------------------------------------------------------------------
def melde_signal(strategie: str, symbol: str, tf: str, kerze: str,
                 sig: dict, grund: str, wert_name: str = "RSI") -> None:
    """Protokolliert ein Signal und was daraus geworden WAERE.

    Von beiden Strategien genutzt, damit Log und Journal identisch
    aufgebaut sind und die Logik nur an einer Stelle steht.
    """
    plan = wuerde_handeln(symbol, sig)

    log.info("-" * 64)
    log.info(f"SIGNAL {sig['dir'].upper()} [{strategie}]: {symbol} ({tf}) "
             f"@ Kerze {kerze}")
    log.info(f"   {wert_name} {sig['rsi']:.4f}, ATR {sig['atr']:.5f}")
    if plan.get("moeglich"):
        log.info(f"   WUERDE handeln: {plan['lots']} Lots @ {plan['kurs']}")
        log.info(f"   SL {plan['sl']}  TP {plan['tp']}")
        log.info(f"   Risiko laut Broker: {plan['risiko']:.2f} "
                 f"(Ziel {plan['risiko_ziel']:.2f})")
        log.info(f"   Spread: {plan.get('spread_punkte', 0):.0f} Punkte "
                 f"= {plan.get('spread_anteil_stop', 0) * 100:.1f} % "
                 f"des Stop-Abstands")
        # Waere dieser Trade auch mit einem kleinen Echtgeldkonto moeglich?
        for kap in (1000, 5000):
            ziel = kap * RISK_PERCENT / 100
            if plan["risiko"] > ziel:
                log.info(f"   Hinweis: mit {kap} EUR Kapital NICHT handelbar "
                         f"(kleinstes Lot riskiert {plan['risiko']:.2f}, "
                         f"Ziel waere {ziel:.2f})")
                break
    else:
        log.info(f"   WUERDE NICHT handeln: {plan.get('grund', '?')}")
    log.info("   (Es wurde nichts gesendet — Beobachtungsmodus.)")
    log.info("-" * 64)

    journal({
        "zeit": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "strategie": strategie,
        "kerze": kerze, "symbol": symbol, "timeframe": tf,
        "richtung": sig["dir"].upper(),
        "kurs": plan.get("kurs", ""),
        "sl": plan.get("sl", ""), "tp": plan.get("tp", ""),
        "lots_berechnet": plan.get("lots", ""),
        "risiko_waehrung": (f"{plan['risiko']:.2f}"
                            if plan.get("risiko") is not None
                            and plan.get("moeglich") else ""),
        "spread_punkte": f"{plan.get('spread_punkte', 0):.1f}",
        "spread_anteil_stop": f"{plan.get('spread_anteil_stop', 0):.3f}",
        "rsi": f"{sig['rsi']:.4f}", "atr": f"{sig['atr']:.5f}",
        "grund": plan.get("grund", "") or grund,
        "kapital": (f"{plan['kapital']:.2f}" if plan.get("kapital") else ""),
        "haette_gehandelt": "ja" if plan.get("moeglich") else "nein",
    })


def main() -> None:
    log.info("=" * 64)
    log.info("BEOBACHTUNGSMODUS — dieser Bot sendet KEINE Auftraege.")
    log.info("Strategie 1 — Trend+Pullback:")
    log.info(f"   EMA{TREND_LEN} (Puffer {TREND_BUFFER_ATR} ATR), "
             f"RSI{RSI_LEN} @ {RSI_OVERSOLD}, ATR{ATR_LEN}x{ATR_STOP_MULT}, "
             f"RR {RR_RATIO}")
    log.info(f"   Richtung: {'Long' if TRADE_LONG else ''}"
             f"{' + Short' if TRADE_SHORT else '  (Short bewusst aus)'}")
    if DIVERGENZ_AN:
        log.info("Strategie 2 — Divergenz Gold/Silber (der gepruefte Fund):")
        log.info(f"   {DIV_SYMBOL} gehandelt, {DIV_REFERENZ} als Referenz, "
                 f"{DIV_TIMEFRAME}")
        log.info(f"   Rendite ueber {DIV_RET_LEN} Kerzen, Band "
                 f"{DIV_BAND_LOOKBACK}/-{DIV_BAND_MULT} Sigma, "
                 f"EMA{DIV_TREND_LEN}, ATR{DIV_ATR_LEN}x{DIV_ATR_STOP_MULT}")
        log.info("   Auf zehn Jahren geprueft: 136 Trades, Profitfaktor 1,95")
    log.info("=" * 64)

    verbinden()
    maerkte = finde_symbole()

    # Fuer die Divergenz zusaetzlich Gold UND Silber bereitstellen.
    div_gold = div_silber = None
    if DIVERGENZ_AN:
        gefunden = finde_einzeln([DIV_SYMBOL, DIV_REFERENZ])
        div_gold = gefunden.get(DIV_SYMBOL)
        div_silber = gefunden.get(DIV_REFERENZ)
        if div_gold and div_silber:
            log.info(f"Divergenz aktiv: {div_gold} gegen {div_silber} "
                     f"({DIV_TIMEFRAME})")
        else:
            log.warning("Divergenz abgeschaltet — Gold oder Silber beim "
                        "Broker nicht gefunden.")
            div_gold = div_silber = None

    gespeichert = state_laden()
    letzte_kerze: dict[str, str] = gespeichert.get("bars", {})
    if letzte_kerze:
        log.info(f"Zustand geladen: {len(letzte_kerze)} Eintrag/Eintraege aus "
                 f"vorheriger Sitzung.")

    log.info(f"Journal: {JOURNAL_FILE}   Protokoll: {LOG_FILE}")
    log.info("Warte auf neue Kerzen... (Beenden mit Strg+C)")

    letzter_herzschlag = time.monotonic()
    signale_gesamt = 0

    try:
        while True:
            if mt5.account_info() is None:
                log.error("Verbindung verloren — neuer Versuch in 30 s.")
                mt5.shutdown()
                time.sleep(30)
                try:
                    verbinden()
                except SystemExit:
                    time.sleep(60)
                continue

            if time.monotonic() - letzter_herzschlag >= HEARTBEAT_MINUTES * 60:
                acc = mt5.account_info()
                kapital = f", Kapital {acc.equity:.2f}" if acc else ""
                log.info(f"Beobachter laeuft, {len(maerkte)} Maerkte, "
                         f"{signale_gesamt} Signal(e) bisher{kapital}.")
                for sym, tf in maerkte.items():
                    df = geschlossene_kerzen(sym, tf)
                    s = zustand(df) if df is not None else None
                    if s:
                        log.info(f"   {sym} ({tf}): Trend {s['trend']}, "
                                 f"RSI {s['rsi']:.0f}")
                if div_gold and div_silber:
                    dg = geschlossene_kerzen(div_gold, DIV_TIMEFRAME)
                    ds = geschlossene_kerzen(div_silber, DIV_TIMEFRAME)
                    if dg is not None and ds is not None:
                        _, grund = divergenz_signal(dg, ds)
                        log.info(f"   Divergenz {div_gold}/{div_silber}: {grund}")
                letzter_herzschlag = time.monotonic()

            geaendert = False

            # --- Strategie 1: Trend + Pullback -------------------------
            for symbol, tf in maerkte.items():
                df = geschlossene_kerzen(symbol, tf)
                if df is None or df.empty:
                    continue

                neueste = str(df.index[-1])
                schluessel = f"TP:{symbol}"
                if letzte_kerze.get(schluessel) == neueste:
                    continue
                erste_pruefung = schluessel not in letzte_kerze
                letzte_kerze[schluessel] = neueste
                geaendert = True
                if erste_pruefung:
                    log.info(f"{symbol}: erste Kerze erfasst ({neueste}) — "
                             f"Signale ab der naechsten.")
                    continue

                sig, grund = signal(df)
                if sig is None:
                    log.info(f"kein Signal: {symbol} ({tf}) @ {neueste} — {grund}")
                    continue

                signale_gesamt += 1
                melde_signal("Trend-Pullback", symbol, tf, neueste, sig, grund)

            # --- Strategie 2: Divergenz Gold/Silber --------------------
            if div_gold and div_silber:
                dg = geschlossene_kerzen(div_gold, DIV_TIMEFRAME)
                ds = geschlossene_kerzen(div_silber, DIV_TIMEFRAME)
                if dg is not None and not dg.empty and ds is not None:
                    neueste = str(dg.index[-1])
                    schluessel = f"DIV:{div_gold}"
                    if letzte_kerze.get(schluessel) != neueste:
                        erste_pruefung = schluessel not in letzte_kerze
                        letzte_kerze[schluessel] = neueste
                        geaendert = True
                        if erste_pruefung:
                            log.info(f"Divergenz: erste Kerze erfasst "
                                     f"({neueste}) — Signale ab der naechsten.")
                        else:
                            sig, grund = divergenz_signal(dg, ds)
                            if sig is None:
                                log.info(f"kein Signal: Divergenz "
                                         f"{div_gold} ({DIV_TIMEFRAME}) "
                                         f"@ {neueste} — {grund}")
                            else:
                                signale_gesamt += 1
                                melde_signal("Divergenz", div_gold,
                                             DIV_TIMEFRAME, neueste, sig,
                                             grund, wert_name="Differenz")

            if geaendert:
                state_speichern({"bars": letzte_kerze})

            time.sleep(POLL_SECONDS)

    except KeyboardInterrupt:
        log.info(f"Beobachter gestoppt. {signale_gesamt} Signal(e) erfasst.")
    except Exception:
        log.exception("UNERWARTETER FEHLER — Beobachter wird beendet.")
    finally:
        state_speichern({"bars": letzte_kerze})
        mt5.shutdown()
        log.info("MT5-Verbindung geschlossen.")


if __name__ == "__main__":
    main()
