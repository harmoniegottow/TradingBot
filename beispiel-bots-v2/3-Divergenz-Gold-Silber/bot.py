"""
Gold/Silber-Divergenz-Bot — Demo-Test-Instanz für den Fund "Intermarket-
Divergenz Gold gegen Silber".

Gut geprüfter Fund aus der Forschungsarbeit an diesem Projekt
(s. config.py für die Kennzahlen im Detail).

Ablauf:
  1. Verbindet sich mit dem laufenden MT5-Terminal
  2. SICHERHEITSCHECK: verweigert Start auf Echtgeldkonten
  3. Prüft bei jeder neu geschlossenen H4-Kerze (Gold UND Silber) das Signal
  4. Bei Signal: berechnet Lot-Größe broker-seitig (order_calc_profit)
     aus 1%-Risiko und Stop-Abstand, platziert Market-Order MIT
     Stop-Loss und Take-Profit
  5. Max. eine Position, max. MAX_OPEN_POSITIONS gesamt
  6. Loggt alles in Konsole + bot.log, Trades in trades.csv

Start:  python bot.py
Stopp:  Strg + C  (offene Positionen bleiben bestehen — SL/TP liegen beim Broker!)
"""

from __future__ import annotations

import csv
import json
import logging
import math
import os
import sys
import time
from datetime import datetime, timedelta, timezone

import pandas as pd

import config
import strategy

try:
    import MetaTrader5 as mt5
except ImportError:
    print("FEHLER: MetaTrader5-Paket fehlt. Installieren mit:")
    print("  pip install MetaTrader5")
    sys.exit(1)


# ----------------------------------------------------------------------
# Logging
# ----------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(config.LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("bot")

TIMEFRAMES = {"H1": mt5.TIMEFRAME_H1, "H4": mt5.TIMEFRAME_H4}

JOURNAL_FILE = "trades.csv"   # eigene Datei im eigenen Ordner (goldsilber-divergenz-bot/)
JOURNAL_COLS = ["zeit", "ereignis", "symbol", "timeframe", "session", "lots",
                "entry", "sl", "tp", "exit", "risiko_eur", "risk_reward",
                "rsi", "gebuehren", "gewinn", "grund", "equity"]

STATE_FILE = "bot_state.json"   # Kerzenzeiten je Symbol, überlebt Neustarts


def state_load() -> dict:
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def state_save(last_bar_time: dict) -> None:
    """Speichert Kerzenzeiten atomar (kein halb geschriebenes File bei Absturz)."""
    try:
        tmp = STATE_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({s: t.isoformat() for s, t in last_bar_time.items()}, f)
        os.replace(tmp, STATE_FILE)
    except OSError as exc:
        log.warning(f"Zustand konnte nicht gespeichert werden: {exc}")


def trading_session() -> str:
    """Grobe Handels-Session nach UTC-Stunde (für spätere Analyse nach Tageszeit)."""
    h = datetime.now(timezone.utc).hour
    if 0 <= h < 7:
        return "Asien"
    if 7 <= h < 12:
        return "London"
    if 12 <= h < 16:
        return "London+NY"
    if 16 <= h < 21:
        return "NewYork"
    return "Spaet"


def journal_write(row: dict) -> None:
    """Hängt eine Zeile ans Trade-Journal an (CSV, Excel-kompatibel mit Semikolon).
    Nutzt das csv-Modul: Sonderzeichen in einem Feld verschieben keine Spalten.
    Schreibfehler beenden den Bot nicht — Handeln hat Vorrang vor Protokollieren."""
    try:
        new_file = not os.path.exists(JOURNAL_FILE)
        with open(JOURNAL_FILE, "a", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=JOURNAL_COLS, delimiter=";",
                                    extrasaction="ignore", restval="")
            if new_file:
                writer.writeheader()
            writer.writerow(row)
    except OSError as exc:
        log.error(f"Journal konnte nicht geschrieben werden: {exc}")


def journal_trade_open(symbol: str, tf: str, lots: float, entry: float,
                       sl: float, tp: float, risk_amount: float, rr: float,
                       rsi: float, reason: str, equity: float) -> None:
    """risk_amount ist das TATSÄCHLICHE, broker-berechnete Risiko (aus
    calc_lots), NICHT der Soll-Prozentwert — Community-Audit-Punkt:
    das Journal soll zeigen, was wirklich riskiert wurde."""
    journal_write({
        "zeit": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "ereignis": "OPEN", "symbol": symbol, "timeframe": tf,
        "session": trading_session(),
        "lots": lots, "entry": entry, "sl": sl, "tp": tp,
        "risiko_eur": f"{risk_amount:.2f}", "risk_reward": rr,
        "rsi": f"{rsi:.5f}", "grund": reason, "equity": f"{equity:.2f}",
    })


def journal_trade_close(ticket: int, symbol: str) -> bool:
    """Holt die Abschluss-Daten einer verschwundenen Position aus der Historie.
    Rückgabe True, wenn protokolliert werden konnte (sonst später erneut
    versuchen — die Broker-Historie ist manchmal erst nach ein paar
    Sekunden befüllt)."""
    now = datetime.now(timezone.utc)
    if hasattr(mt5, "history_select"):  # nur in manchen mt5-Paketversionen vorhanden
        mt5.history_select(now - timedelta(days=30), now + timedelta(days=1))

    deals = mt5.history_deals_get(position=ticket)
    if not deals:
        return False

    entry_out = getattr(mt5, "DEAL_ENTRY_OUT", 1)
    exit_deals = [d for d in deals if d.entry == entry_out]
    if not exit_deals:
        return False

    d = exit_deals[-1]
    profit = sum(x.profit for x in deals)
    fees = sum(x.commission + x.fee + x.swap for x in deals)
    net = profit + fees

    reason_map = {
        getattr(mt5, "DEAL_REASON_SL", 3): "Stop-Loss getroffen",
        getattr(mt5, "DEAL_REASON_TP", 4): "Take-Profit getroffen",
    }
    reason = reason_map.get(getattr(d, "reason", -1), "geschlossen (manuell/sonstig)")

    acc = mt5.account_info()
    journal_write({
        "zeit": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "ereignis": "CLOSE", "symbol": symbol,
        "session": trading_session(),
        "exit": d.price, "gebuehren": f"{fees:.2f}",
        "gewinn": f"{net:.2f}", "grund": reason,
        "equity": f"{acc.equity:.2f}" if acc else "",
    })
    emoji = "🟢" if net >= 0 else "🔴"
    log.info(f"{emoji} TRADE GESCHLOSSEN: {symbol} @ {d.price} | "
             f"{'Gewinn' if net >= 0 else 'Verlust'} {net:+.2f} "
             f"(brutto {profit:+.2f}, Kosten {fees:+.2f}) | {reason}")
    return True


# ----------------------------------------------------------------------
# Verbindung & Sicherheit
# ----------------------------------------------------------------------
def connect() -> None:
    kwargs = {}
    if config.MT5_LOGIN:
        kwargs = dict(login=config.MT5_LOGIN, password=config.MT5_PASSWORD,
                      server=config.MT5_SERVER)
    if not mt5.initialize(**kwargs):
        log.error(f"MT5-Initialisierung fehlgeschlagen: {mt5.last_error()}")
        log.error("Ist das MT5-Terminal gestartet und eingeloggt?")
        sys.exit(1)

    acc = mt5.account_info()
    if acc is None:
        log.error("Kein Konto gefunden — im MT5-Terminal einloggen.")
        mt5.shutdown()
        sys.exit(1)

    is_demo = acc.trade_mode == mt5.ACCOUNT_TRADE_MODE_DEMO
    log.info(f"{config.LOG_PREFIX} Verbunden: Konto {acc.login} ({acc.server}), "
             f"{'DEMO' if is_demo else 'ECHTGELD'}, "
             f"Balance {acc.balance:.2f} {acc.currency}")

    if not is_demo and not config.ALLOW_REAL_ACCOUNT:
        log.error("SICHERHEITSSTOPP: Dies ist ein ECHTGELDKONTO.")
        log.error("Der Bot ist für Demo-Betrieb konfiguriert (ALLOW_REAL_ACCOUNT=False).")
        mt5.shutdown()
        sys.exit(1)


def ensure_symbols() -> list[str]:
    """Prüft, welche konfigurierten Symbole der Broker anbietet, aktiviert sie."""
    available = []
    for symbol in config.MARKETS:
        info = mt5.symbol_info(symbol)
        if info is None:
            log.warning(f"{symbol}: beim Broker nicht gefunden — wird übersprungen. "
                        f"(Symbolname prüfen: manche Broker nutzen z.B. 'GOLD' statt 'XAUUSD')")
            continue
        if not info.visible and not mt5.symbol_select(symbol, True):
            log.warning(f"{symbol}: konnte nicht aktiviert werden "
                        f"({mt5.last_error()}) — wird übersprungen.")
            continue
        if info.trade_tick_size <= 0 or info.trade_tick_value <= 0:
            log.warning(f"{symbol}: keine gültigen Tick-Daten — wird übersprungen.")
            continue
        available.append(symbol)
        log.info(f"{symbol}: aktiv ({config.MARKETS[symbol]})")
    if not available:
        log.error("Keines der konfigurierten Symbole verfügbar — Abbruch.")
        mt5.shutdown()
        sys.exit(1)

    # Referenz-Symbol (wird NICHT gehandelt, nur fuer die Divergenz-
    # Berechnung benoetigt) -- ohne dieses Symbol kann kein Signal berechnet werden.
    ref = config.REFERENCE_SYMBOL
    ref_info = mt5.symbol_info(ref)
    if ref_info is None or (not ref_info.visible and not mt5.symbol_select(ref, True)):
        log.error(f"Referenz-Symbol {ref} beim Broker nicht verfügbar — "
                  f"ohne dieses Symbol kann kein Signal berechnet werden. Abbruch.")
        mt5.shutdown()
        sys.exit(1)
    log.info(f"{ref}: aktiv (nur Referenzkurs, wird nicht gehandelt)")
    return available


# ----------------------------------------------------------------------
# Daten & Positionen
# ----------------------------------------------------------------------
def get_closed_bars(symbol: str, tf_str: str) -> pd.DataFrame | None:
    """Holt die letzten Kerzen OHNE die aktuell laufende (nur geschlossene)."""
    tf = TIMEFRAMES.get(tf_str)
    if tf is None:
        log.error(f"{symbol}: unbekannter Timeframe '{tf_str}'.")
        return None
    try:
        rates = mt5.copy_rates_from_pos(symbol, tf, 0, config.BARS_HISTORY)
    except Exception as exc:
        log.warning(f"{symbol}: Kursabruf fehlgeschlagen: {exc}")
        return None
    if rates is None or len(rates) < 2:
        return None
    df = pd.DataFrame(rates)
    if not {"time", "open", "high", "low", "close"}.issubset(df.columns):
        log.warning(f"{symbol}: unerwartetes Datenformat vom Broker.")
        return None
    df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
    df = df.set_index("time")[["open", "high", "low", "close"]]
    df = df.iloc[:-1]
    return df if not df.empty else None


def bot_positions(symbol: str | None = None):
    """Offene Positionen, die DIESER Bot eröffnet hat (per Magic Number)."""
    positions = mt5.positions_get(symbol=symbol) if symbol else mt5.positions_get()
    if positions is None:
        return []
    return [p for p in positions if p.magic == config.MAGIC_NUMBER]


def calc_lots(symbol: str, entry: float, sl: float) -> tuple[float, float] | None:
    """
    Lot-Größe über die Broker-eigene Berechnung (order_calc_profit), NICHT
    über eine manuelle Tick-Formel.

    Grund (s. CLAUDE.md "Bekannte Bugs"): die frühere Formel
    (stop_dist / tick_size) * tick_value hat bei Metallen auf dem
    VPS-Broker das Risiko um Faktor 9 unterschätzt (David-Bot V2, Gold:
    0,1 Lot statt der geplanten ~0,01 Lot). order_calc_profit() fragt
    den Broker direkt, was das gewählte Volumen zwischen Einstieg und
    SL kostet, und berücksichtigt damit automatisch Kontraktgröße,
    Tick-Wert und Währungsumrechnung so, wie der Broker sie tatsächlich
    anwendet. Übernommen aus "DAVID BOT NEU"/bot.py (dort bereits gegen
    den realen Bug gehärtet).

    Rückgabe: (Lot-Größe, tatsächliches Risiko in Kontowährung) oder None.
    """
    acc = mt5.account_info()
    info = mt5.symbol_info(symbol)
    if acc is None or info is None:
        return None

    risk_amount = acc.equity * (config.RISK_PERCENT / 100)
    if risk_amount <= 0:
        log.warning(f"{symbol}: Kapital {acc.equity:.2f} — kein Risikobudget.")
        return None

    order_type = mt5.ORDER_TYPE_BUY  # Long only

    def loss_for(volume: float) -> float | None:
        result = mt5.order_calc_profit(order_type, symbol, volume, entry, sl)
        if result is None:
            return None
        return abs(result)

    risk_per_lot = loss_for(1.0)
    if risk_per_lot is None:
        log.warning(f"{symbol}: order_calc_profit fehlgeschlagen "
                    f"({mt5.last_error()}) — Trade übersprungen.")
        return None
    if risk_per_lot <= 0:
        log.warning(f"{symbol}: order_calc_profit lieferte 0 Risiko pro Lot — "
                    f"Trade übersprungen.")
        return None

    raw_lots = risk_amount / risk_per_lot

    # ABRUNDEN auf die Broker-Schrittweite, NICHT kaufmännisch runden:
    # round() würde z.B. bei 0.106 auf 0.11 aufrunden und damit MEHR
    # riskieren als erlaubt. Lieber minimal unter dem Ziel bleiben.
    step = info.volume_step or 0.01
    lots = math.floor(raw_lots / step) * step
    lots = round(lots, 8)  # Float-Artefakte glätten (0.30000000000000004 -> 0.3)

    if lots > info.volume_max:
        lots = info.volume_max
        log.info(f"{symbol}: Lot-Größe auf Broker-Maximum {lots} begrenzt.")

    if lots < info.volume_min:
        min_risk = loss_for(info.volume_min)
        if min_risk is None:
            log.warning(f"{symbol}: Mindest-Lot-Risiko nicht berechenbar "
                        f"({mt5.last_error()}) — Trade übersprungen.")
            return None
        if min_risk > 2 * risk_amount:
            log.warning(f"{symbol}: Mindest-Lot {info.volume_min} riskiert "
                        f"{min_risk:.2f} (> 2x Zielrisiko {risk_amount:.2f}) — "
                        f"Trade übersprungen.")
            return None
        lots = info.volume_min
        log.info(f"{symbol}: Lot-Größe auf Broker-Minimum {lots} angehoben "
                 f"(Risiko {min_risk:.2f} statt {risk_amount:.2f}).")

    margin = mt5.order_calc_margin(order_type, symbol, lots, entry)
    if margin is not None and margin > acc.margin_free:
        log.warning(f"{symbol}: benötigte Margin {margin:.2f} > freie Margin "
                    f"{acc.margin_free:.2f} — Trade übersprungen.")
        return None

    # Letzte Sicherung vor dem Senden: tatsächliches Risiko der GEWÄHLTEN
    # Lot-Größe noch einmal broker-seitig gegenrechnen (1,5x-Wächter).
    actual_risk = loss_for(lots)
    if actual_risk is None:
        log.warning(f"{symbol}: finale Risikoprüfung fehlgeschlagen "
                    f"({mt5.last_error()}) — Trade übersprungen.")
        return None
    if actual_risk > 1.5 * risk_amount:
        log.warning(f"{symbol}: finale Risikoprüfung {actual_risk:.2f} > "
                    f"1,5x Zielrisiko {risk_amount:.2f} (Lots {lots}) — "
                    f"Trade abgebrochen.")
        return None

    return lots, actual_risk


def close_position(pos, comment: str) -> bool:
    """Schließt eine einzelne Position zum Marktpreis. True bei Erfolg."""
    tick = mt5.symbol_info_tick(pos.symbol)
    if tick is None:
        log.error(f"{pos.symbol}: kein Kurs zum Schließen von {pos.ticket} verfügbar.")
        return False
    order_type, price = mt5.ORDER_TYPE_SELL, tick.bid  # Long-Bot: immer Verkauf zum Schließen
    req = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": pos.symbol,
        "volume": pos.volume,
        "type": order_type,
        "position": pos.ticket,
        "price": price,
        "deviation": 50,
        "magic": config.MAGIC_NUMBER,
        "comment": comment[:31],
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }
    res = mt5.order_send(req)
    if res is None or res.retcode != mt5.TRADE_RETCODE_DONE:
        req["type_filling"] = mt5.ORDER_FILLING_FOK
        res = mt5.order_send(req)
    if res and res.retcode == mt5.TRADE_RETCODE_DONE:
        log.info(f"Position {pos.ticket} ({pos.symbol}) geschlossen.")
        return True
    log.critical(f"✖✖ {pos.symbol}: Position {pos.ticket} konnte NICHT geschlossen "
                 f"werden (Retcode {res.retcode if res else '?'}). "
                 f"BITTE MANUELL IM TERMINAL PRÜFEN!")
    return False


def enforce_protection(ticket: int, sl: float, tp: float) -> None:
    """
    SL/TP-WÄCHTER: Prüft nach einer Order, ob GENAU DIESE Position
    geschützt ist. Fehlt SL oder TP -> nachrüsten. Scheitert auch das
    -> Position schließen. Eine ungeschützte Position darf unter
    keinen Umständen bestehen bleiben (CLAUDE.md, nicht verhandelbare
    Regel 2). Arbeitet mit dem Ticket, nicht dem Symbol, damit ältere
    Positionen desselben Symbols nicht versehentlich überschrieben werden.
    """
    time.sleep(1)
    pos = None
    for _ in range(3):
        found = mt5.positions_get(ticket=ticket)
        if found:
            pos = found[0]
            break
        time.sleep(1)

    if pos is None:
        log.warning(f"Position {ticket} nicht auffindbar — evtl. sofort "
                    f"geschlossen. Bitte im Terminal prüfen.")
        return

    if pos.sl > 0 and pos.tp > 0:
        log.info(f"✔ SCHUTZ BESTÄTIGT: {pos.symbol} hat SL {pos.sl} und TP {pos.tp}.")
        return

    log.warning(f"⚠ {pos.symbol}: Position {ticket} OHNE vollständigen Schutz "
                f"(SL={pos.sl}, TP={pos.tp}) — rüste nach...")
    fix = {
        "action": mt5.TRADE_ACTION_SLTP,
        "symbol": pos.symbol,
        "position": ticket,
        "sl": sl,
        "tp": tp,
        "magic": config.MAGIC_NUMBER,
    }
    res = mt5.order_send(fix)
    if res and res.retcode == mt5.TRADE_RETCODE_DONE:
        log.info(f"✔ SCHUTZ NACHGERÜSTET: {pos.symbol} SL {sl} / TP {tp}.")
        return

    log.error(f"✖ {pos.symbol}: Schutz konnte NICHT gesetzt werden "
              f"(Retcode {res.retcode if res else '?'}) — Position wird "
              f"SOFORT GESCHLOSSEN. Ungeschützt wird nicht gehandelt.")
    close_position(pos, "NoSL-Close")


RETRY_FILLING_CODES = {
    getattr(mt5, "TRADE_RETCODE_INVALID_FILL", 10030),
    getattr(mt5, "TRADE_RETCODE_UNSUPPORTED_FILL_MODE", 10018),
}


def place_long(symbol: str, stop_dist: float, sig: dict) -> None:
    info = mt5.symbol_info(symbol)
    if info is None:
        log.warning(f"{symbol}: keine Symbol-Daten — Trade übersprungen.")
        return

    if info.trade_mode != mt5.SYMBOL_TRADE_MODE_FULL:
        log.info(f"{symbol}: Handel derzeit nicht möglich "
                 f"(trade_mode={info.trade_mode}) — Trade übersprungen.")
        return

    tick = mt5.symbol_info_tick(symbol)
    if tick is None or tick.ask <= 0 or tick.bid <= 0:
        log.warning(f"{symbol}: kein gültiger Kurs — Trade übersprungen.")
        return

    digits = info.digits
    point = info.point
    price = tick.ask

    # Spread-Schutz: liegt der Spread über 15% des geplanten Stop-Abstands,
    # frisst er zu viel vom Erwartungswert (typisch bei News/Rollover).
    spread = tick.ask - tick.bid
    if spread > stop_dist * 0.15:
        log.info(f"{symbol}: Spread {spread / point:.0f} Punkte zu hoch "
                 f"(> 15% des Stop-Abstands) — Trade übersprungen.")
        return

    stops_level = getattr(info, "trade_stops_level", 0) or 0
    min_stop_dist = max(stops_level * point, spread * 2)
    eff_stop = max(stop_dist, min_stop_dist * 1.1)
    if eff_stop > stop_dist:
        log.info(f"{symbol}: Stop-Abstand auf Broker-Minimum angehoben "
                 f"({stop_dist:.{digits}f} -> {eff_stop:.{digits}f}).")

    def stops_fuer(p: float) -> tuple[float, float]:
        return round(p - eff_stop, digits), round(p + eff_stop * config.RR_RATIO, digits)

    sl, tp = stops_fuer(price)

    # Lots (und Ist-Risiko) IMMER aus dem tatsächlich verwendeten SL berechnen.
    calc = calc_lots(symbol, price, sl)
    if calc is None:
        return
    lots, actual_risk = calc

    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": lots,
        "type": mt5.ORDER_TYPE_BUY,
        "price": price,
        "sl": sl,
        "tp": tp,
        "deviation": 20,
        "magic": config.MAGIC_NUMBER,
        "comment": "Divergenz-XAUUSD",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }
    result = mt5.order_send(request)
    if result is None:
        log.error(f"{symbol}: order_send fehlgeschlagen: {mt5.last_error()} — "
                  f"kein zweiter Versuch (Order könnte trotzdem angekommen sein).")
        return

    if result.retcode != mt5.TRADE_RETCODE_DONE and result.retcode in RETRY_FILLING_CODES:
        log.info(f"{symbol}: Filling-Modus IOC abgelehnt — versuche FOK.")
        fresh = mt5.symbol_info_tick(symbol)
        if fresh and fresh.ask > 0:
            sl, tp = stops_fuer(fresh.ask)
            request["price"] = fresh.ask
            request["sl"] = sl
            request["tp"] = tp
        request["type_filling"] = mt5.ORDER_FILLING_FOK
        result = mt5.order_send(request)

    if result and result.retcode == mt5.TRADE_RETCODE_DONE:
        acc = mt5.account_info()
        equity = acc.equity if acc else 0.0
        log.info(f"ORDER AUSGEFÜHRT: LONG {symbol} {lots} Lots @ {result.price} "
                 f"| SL {sl} | TP {tp} | Gold/Silber-Differenz {sig['rsi']:.5f}")
        ticket = getattr(result, "order", 0) or getattr(result, "deal", 0)
        enforce_protection(ticket, sl, tp)
        journal_trade_open(
            symbol=symbol, tf=config.MARKETS[symbol], lots=lots,
            entry=result.price, sl=sl, tp=tp,
            risk_amount=actual_risk,  # Ist-Risiko, nicht Soll-Prozentwert
            rr=config.RR_RATIO, rsi=sig["rsi"],
            reason=f"Trend über EMA{config.TREND_LEN}, Gold/Silber-Differenz "
                    f"kreuzt zurueck ueber ihr {config.BAND_LOOKBACK}er-Band",
            equity=equity,
        )
    else:
        log.error(f"{symbol}: Order abgelehnt, Retcode "
                  f"{result.retcode if result else '?'} — siehe MT5-Journal. "
                  f"Es wird KEIN ungeschützter Ersatz-Trade platziert.")


def print_market_status(symbols: list[str]) -> None:
    for symbol in symbols:
        tf = config.MARKETS[symbol]
        df = get_closed_bars(symbol, tf)
        df_ref = get_closed_bars(config.REFERENCE_SYMBOL, tf)
        if df is None or df.empty or df_ref is None or df_ref.empty:
            log.info(f"   {symbol:<7} ({tf}): keine Daten (Markt geschlossen? "
                     f"Referenzsymbol {config.REFERENCE_SYMBOL} verfuegbar?)")
            continue
        st = strategy.market_status(df, df_ref)
        if st is None:
            log.info(f"   {symbol:<7} ({tf}): warte auf genug Kerzen")
            continue
        trend = "Aufwärts ↑" if st["up_trend"] else "Abwärts ↓ (kein Kauf)"
        if not st["up_trend"]:
            hint = "Trend falsch"
        elif st["unter_band"]:
            hint = ">> Gold gegenueber Silber abgehaengt, wartet auf Aufhol-Kreuzung <<"
        else:
            hint = "Differenz ueber dem Band (kein Abhaenge-Zustand gerade)"
        log.info(f"   {symbol:<7} ({tf}): {trend} | Differenz {st['d']:.5f} "
                 f"(Band {st['band']:.5f}) | {hint}")


# ----------------------------------------------------------------------
# Hauptschleife
# ----------------------------------------------------------------------
def main() -> None:
    log.info("=" * 70)
    log.info(f"{config.LOG_PREFIX} GOLD/SILBER-DIVERGENZ-BOT startet (Long only, Demo-Modus)")
    log.info(f"{config.LOG_PREFIX} HINWEIS: gut geprüfter Fund (Out-of-Sample-"
             f"Verhaeltnis 2,43-2,65 ueber 3 Split-Methoden, 142 Trades/10 Jahre) "
             f"— s. ANLEITUNG.md")
    log.info(f"{config.LOG_PREFIX} Magic-Nummer: {config.MAGIC_NUMBER}")
    log.info(f"{config.LOG_PREFIX} Markt: {', '.join(f'{s} ({tf})' for s, tf in config.MARKETS.items())} "
             f"| Referenz (nicht gehandelt): {config.REFERENCE_SYMBOL}")
    log.info(f"{config.LOG_PREFIX} Parameter: EMA{config.TREND_LEN}, {config.RET_LEN}-Kerzen-"
             f"Renditedifferenz, {config.BAND_LOOKBACK}er-Band x{config.BAND_MULT}, "
             f"ATR{config.ATR_LEN}x{config.ATR_STOP_MULT}, RR {config.RR_RATIO}, "
             f"Risiko {config.RISK_PERCENT}%/Trade")
    log.info(f"{config.LOG_PREFIX} ALLOW_REAL_ACCOUNT = {config.ALLOW_REAL_ACCOUNT} "
             f"({'DEMO-SICHERUNG AKTIV' if not config.ALLOW_REAL_ACCOUNT else 'ACHTUNG: ECHTGELD ERLAUBT'})")
    log.info("=" * 70)

    connect()
    symbols = ensure_symbols()

    state = state_load()
    last_bar_time: dict[str, datetime] = {}
    for s, iso in state.items():
        try:
            last_bar_time[s] = datetime.fromisoformat(iso)
        except (ValueError, TypeError):
            pass

    if config.SHOW_STARTUP_SNAPSHOT:
        log.info("-" * 70)
        log.info("Marktzustand beim Start:")
        print_market_status(symbols)
        log.info("-" * 70)

    log.info(f"{config.LOG_PREFIX} Warte auf neue Kerzen... "
             f"(Stopp: Strg+C — SL/TP bleiben beim Broker aktiv)")
    last_heartbeat = time.monotonic()
    known_tickets: dict[int, str] = {p.ticket: p.symbol for p in bot_positions()}
    pending_closes: dict[int, str] = {}

    try:
        while True:
            current = {p.ticket: p.symbol for p in bot_positions()}
            for ticket, sym in list(known_tickets.items()):
                if ticket not in current:
                    pending_closes[ticket] = sym
            known_tickets = current

            for ticket, sym in list(pending_closes.items()):
                if journal_trade_close(ticket, sym):
                    del pending_closes[ticket]

            if time.monotonic() - last_heartbeat >= config.HEARTBEAT_MINUTES * 60:
                now = datetime.now().strftime("%H:%M")
                acc = mt5.account_info()
                eq = f", Kapital {acc.equity:.2f} {acc.currency}" if acc else ""
                log.info(f"{config.LOG_PREFIX} ♥ {now} — Bot läuft, {len(symbols)} Märkte überwacht, "
                         f"{len(current)} Position(en) offen{eq}.")
                if config.SHOW_MARKET_STATUS:
                    print_market_status(symbols)
                last_heartbeat = time.monotonic()

            for symbol in symbols:
                tf = config.MARKETS[symbol]
                df = get_closed_bars(symbol, tf)
                df_ref = get_closed_bars(config.REFERENCE_SYMBOL, tf)
                if df is None or df.empty or df_ref is None or df_ref.empty:
                    continue

                newest = df.index[-1]
                if last_bar_time.get(symbol) == newest:
                    continue
                first_check = symbol not in last_bar_time
                last_bar_time[symbol] = newest
                state_save(last_bar_time)
                if first_check:
                    continue  # beim Start keine Alt-Signale nachhandeln

                sig = strategy.check_signal(df, df_ref)
                if sig is None:
                    continue

                log.info(f"SIGNAL: {symbol} ({tf}) @ Kerze {newest} "
                         f"| Gold/Silber-Differenz {sig['rsi']:.5f} | Stop-Abstand {sig['stop_dist']:.5f}")

                if bot_positions(symbol):
                    log.info(f"{symbol}: bereits Position offen — übersprungen.")
                    continue
                if len(bot_positions()) >= config.MAX_OPEN_POSITIONS:
                    log.info(f"{symbol}: Max. offene Positionen "
                             f"({config.MAX_OPEN_POSITIONS}) erreicht — übersprungen.")
                    continue

                place_long(symbol, sig["stop_dist"], sig)

            time.sleep(config.POLL_SECONDS)
    except KeyboardInterrupt:
        log.info(f"{config.LOG_PREFIX} Bot gestoppt. Offene Positionen sind durch SL/TP beim Broker gesichert.")
    finally:
        mt5.shutdown()


if __name__ == "__main__":
    main()
