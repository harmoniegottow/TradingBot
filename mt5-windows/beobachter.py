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
MAERKTE = {
    "EURUSD": "H1",
    "GBPUSD": "H1",
    "USDJPY": "H1",
    "XAUUSD": "H4",
}

ALTERNATIVEN = {
    "XAUUSD": ["GOLD", "GOLDUSD"],
    "XAGUSD": ["SILVER", "SILVERUSD"],
}

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
    "zeit", "kerze", "symbol", "timeframe", "richtung", "kurs",
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
# Verbindung und Symbole
# ----------------------------------------------------------------------
def verbinden() -> None:
    if not mt5.initialize():
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


def finde_symbole() -> dict[str, str]:
    """Sucht die echten Broker-Namen (mit eventuellem Kuerzel wie '.a')."""
    alle = mt5.symbols_get()
    namen = [s.name for s in alle] if alle else []
    ergebnis: dict[str, str] = {}

    for basis, tf in MAERKTE.items():
        kandidaten = [basis] + ALTERNATIVEN.get(basis, [])
        treffer = []
        for k in kandidaten:
            treffer += [n for n in namen
                        if n == k or (n.startswith(k) and len(n) <= len(k) + 5)]
        treffer = sorted(set(treffer), key=len)
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
def main() -> None:
    log.info("=" * 64)
    log.info("BEOBACHTUNGSMODUS — dieser Bot sendet KEINE Auftraege.")
    log.info(f"Parameter: EMA{TREND_LEN} (Puffer {TREND_BUFFER_ATR} ATR), "
             f"RSI{RSI_LEN} @ {RSI_OVERSOLD}, ATR{ATR_LEN}x{ATR_STOP_MULT}, "
             f"RR {RR_RATIO}")
    log.info(f"Richtung: {'Long' if TRADE_LONG else ''}"
             f"{' + Short' if TRADE_SHORT else '  (Short bewusst aus)'}")
    log.info("=" * 64)

    verbinden()
    maerkte = finde_symbole()

    gespeichert = state_laden()
    letzte_kerze: dict[str, str] = gespeichert.get("bars", {})
    if letzte_kerze:
        log.info(f"Zustand geladen: {len(letzte_kerze)} Markt/Maerkte aus "
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
                letzter_herzschlag = time.monotonic()

            geaendert = False
            for symbol, tf in maerkte.items():
                df = geschlossene_kerzen(symbol, tf)
                if df is None or df.empty:
                    continue

                neueste = str(df.index[-1])
                if letzte_kerze.get(symbol) == neueste:
                    continue
                erste_pruefung = symbol not in letzte_kerze
                letzte_kerze[symbol] = neueste
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
                plan = wuerde_handeln(symbol, sig)

                log.info("-" * 64)
                log.info(f"SIGNAL {sig['dir'].upper()}: {symbol} ({tf}) "
                         f"@ Kerze {neueste}")
                log.info(f"   RSI {sig['rsi']:.1f}, ATR {sig['atr']:.5f}")
                if plan.get("moeglich"):
                    log.info(f"   WUERDE handeln: {plan['lots']} Lots @ "
                             f"{plan['kurs']}")
                    log.info(f"   SL {plan['sl']}  TP {plan['tp']}")
                    log.info(f"   Risiko laut Broker: {plan['risiko']:.2f} "
                             f"(Ziel {plan['risiko_ziel']:.2f})")
                    log.info(f"   Spread: {plan.get('spread_punkte', 0):.0f} Punkte "
                             f"= {plan.get('spread_anteil_stop', 0) * 100:.1f} % "
                             f"des Stop-Abstands")
                else:
                    log.info(f"   WUERDE NICHT handeln: {plan.get('grund', '?')}")
                log.info("   (Es wurde nichts gesendet — Beobachtungsmodus.)")
                log.info("-" * 64)

                journal({
                    "zeit": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "kerze": neueste, "symbol": symbol, "timeframe": tf,
                    "richtung": sig["dir"].upper(),
                    "kurs": plan.get("kurs", ""),
                    "sl": plan.get("sl", ""), "tp": plan.get("tp", ""),
                    "lots_berechnet": plan.get("lots", ""),
                    "risiko_waehrung": (f"{plan['risiko']:.2f}"
                                        if plan.get("risiko") is not None
                                        and plan.get("moeglich") else ""),
                    "spread_punkte": f"{plan.get('spread_punkte', 0):.1f}",
                    "spread_anteil_stop": f"{plan.get('spread_anteil_stop', 0):.3f}",
                    "rsi": f"{sig['rsi']:.1f}", "atr": f"{sig['atr']:.5f}",
                    "grund": plan.get("grund", "") or grund,
                    "kapital": (f"{plan['kapital']:.2f}"
                                if plan.get("kapital") else ""),
                    "haette_gehandelt": "ja" if plan.get("moeglich") else "nein",
                })

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
