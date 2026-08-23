"""
MT5 Trading Bot — Trend + Pullback (Long only) auf validierten Märkten.

Ablauf:
  1. Verbindet sich mit dem laufenden MT5-Terminal
  2. SICHERHEITSCHECK: verweigert Start auf Echtgeldkonten
  3. Prüft bei jeder neu geschlossenen Kerze (H1/H4 je nach Markt) das Signal
  4. Bei Signal: berechnet Lot-Größe aus 1%-Risiko und Stop-Abstand,
     platziert Market-Order MIT Stop-Loss und Take-Profit
  5. Max. eine Position pro Symbol, max. MAX_OPEN_POSITIONS gesamt
  6. Loggt alles in Konsole + bot.log

Start:  python bot.py
Stopp:  Strg + C  (offene Positionen bleiben bestehen — SL/TP liegen beim Broker!)
"""

from __future__ import annotations

import logging
import math
import sys
import time
from datetime import datetime, timedelta

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

JOURNAL_FILE = "trades.csv"
JOURNAL_COLS = ["zeit", "ereignis", "symbol", "timeframe", "session", "lots",
                "entry", "sl", "tp", "exit", "risiko_eur", "risk_reward",
                "rsi", "gebuehren", "gewinn", "grund", "equity"]
JOURNAL_HEADER = ";".join(JOURNAL_COLS) + "\n"


def trading_session() -> str:
    """Grobe Handels-Session nach UTC-Stunde (für spätere Analyse nach Tageszeit)."""
    h = datetime.utcnow().hour
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
    """Hängt eine Zeile ans Trade-Journal an (CSV, Excel-kompatibel mit Semikolon)."""
    import os
    new_file = not os.path.exists(JOURNAL_FILE)
    with open(JOURNAL_FILE, "a", encoding="utf-8") as f:
        if new_file:
            f.write(JOURNAL_HEADER)
        f.write(";".join(str(row.get(k, "")) for k in JOURNAL_COLS) + "\n")


def journal_trade_open(symbol: str, tf: str, lots: float, entry: float,
                       sl: float, tp: float, risk_amount: float, rr: float,
                       rsi: float, reason: str, equity: float) -> None:
    journal_write({
        "zeit": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "ereignis": "OPEN", "symbol": symbol, "timeframe": tf,
        "session": trading_session(),
        "lots": lots, "entry": entry, "sl": sl, "tp": tp,
        "risiko_eur": f"{risk_amount:.2f}", "risk_reward": rr,
        "rsi": f"{rsi:.1f}", "grund": reason, "equity": f"{equity:.2f}",
    })


def journal_trade_close(ticket: int, symbol: str) -> None:
    """Holt die Abschluss-Daten einer verschwundenen Position aus der Historie."""
    # history_deals_get(position=...) braucht bei vielen Brokern ein
    # geladenes Zeitfenster. history_select() gibt es nur in MQL5, nicht
    # in jeder Version des Python-Pakets — daher per hasattr absichern,
    # statt beim ersten Trade-Abschluss abzustürzen.
    now = datetime.utcnow()
    if hasattr(mt5, "history_select"):
        mt5.history_select(now - timedelta(days=30), now + timedelta(days=1))

    deals = mt5.history_deals_get(position=ticket)
    if not deals:
        return
    exit_deals = [d for d in deals if d.entry == 1]  # DEAL_ENTRY_OUT
    if not exit_deals:
        return
    d = exit_deals[-1]
    profit = sum(x.profit for x in exit_deals)
    fees = sum(x.commission + x.fee + x.swap for x in deals)
    # Grund der Schließung ermitteln — über die echten MT5-Konstanten,
    # nicht über die Zahlen 3/4 (die auf manchen Brokern nicht stimmen).
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
        "gewinn": f"{profit:.2f}", "grund": reason,
        "equity": f"{acc.equity:.2f}" if acc else "",
    })
    emoji = "🟢" if profit >= 0 else "🔴"
    log.info(f"{emoji} TRADE GESCHLOSSEN: {symbol} @ {d.price} | "
             f"{'Gewinn' if profit >= 0 else 'Verlust'} {profit:+.2f} | {reason}")


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
    log.info(f"Verbunden: Konto {acc.login} ({acc.server}), "
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
        if not info.visible:
            mt5.symbol_select(symbol, True)
        available.append(symbol)
        log.info(f"{symbol}: aktiv ({config.MARKETS[symbol]})")
    if not available:
        log.error("Keines der konfigurierten Symbole verfügbar — Abbruch.")
        mt5.shutdown()
        sys.exit(1)
    return available


# ----------------------------------------------------------------------
# Daten & Positionen
# ----------------------------------------------------------------------
def get_closed_bars(symbol: str, tf_str: str) -> pd.DataFrame | None:
    """Holt die letzten Kerzen OHNE die aktuell laufende (nur geschlossene)."""
    rates = mt5.copy_rates_from_pos(symbol, TIMEFRAMES[tf_str], 0,
                                    config.BARS_HISTORY)
    if rates is None or len(rates) < 10:
        return None
    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
    df = df.set_index("time")[["open", "high", "low", "close"]]
    return df.iloc[:-1]  # letzte Zeile = laufende Kerze -> weg


def bot_positions(symbol: str | None = None):
    """Offene Positionen, die DIESER Bot eröffnet hat (per Magic Number)."""
    positions = mt5.positions_get(symbol=symbol) if symbol else mt5.positions_get()
    if positions is None:
        return []
    return [p for p in positions if p.magic == config.MAGIC_NUMBER]


def calc_lots(symbol: str, entry: float, sl: float) -> tuple[float, float] | None:
    """
    Lot-Größe über die Broker-eigene Berechnung (order_calc_profit), nicht
    über eine manuelle Tick-Formel.

    Grund: die frühere Formel (stop_dist / tick_size) * tick_value hat bei
    Metallen auf diesem Broker das Risiko um Faktor 9 unterschätzt (0,1
    Lot statt der geplanten ~0,01 Lot). order_calc_profit() fragt den
    Broker direkt, was das gewählte Volumen zwischen Einstieg und SL
    kostet, und berücksichtigt damit automatisch Kontraktgröße, Tick-Wert
    und Währungsumrechnung so, wie der Broker sie tatsächlich anwendet.

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

    def loss_for(volume: float) -> float | None:
        """Verlust laut Broker für `volume` Lots zwischen entry und sl (immer positiv)."""
        result = mt5.order_calc_profit(mt5.ORDER_TYPE_BUY, symbol, volume, entry, sl)
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

    # ABRUNDEN auf die Broker-Schrittweite, nicht kaufmännisch runden:
    # round() würde bei z. B. 0.106 auf 0.11 aufrunden und damit MEHR
    # riskieren als erlaubt. Lieber minimal unter dem Ziel bleiben.
    step = info.volume_step or 0.01
    lots = math.floor(raw_lots / step) * step
    # Float-Artefakte glätten (0.30000000000000004 -> 0.3)
    lots = round(lots, 8)

    if lots > info.volume_max:
        lots = info.volume_max
        log.info(f"{symbol}: Lot-Größe auf Broker-Maximum {lots} begrenzt.")

    # Liegt das Ergebnis unter dem Mindestvolumen, wäre der einzige
    # handelbare Trade das Minimum — nur zulassen, wenn dessen (ebenfalls
    # broker-berechnetes) Risiko das Zielrisiko nicht deutlich übersteigt.
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

    # Letzte Sicherung vor dem Senden (Wächter): tatsächliches Risiko der
    # GEWÄHLTEN Lot-Größe noch einmal broker-seitig gegenrechnen. Weicht es
    # deutlich vom Ziel ab, wird NICHT gehandelt statt mit falscher Größe
    # zu senden.
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


def enforce_protection(symbol: str, sl: float, tp: float) -> None:
    """
    SL/TP-WÄCHTER: Prüft nach einer Order, ob die Position wirklich
    geschützt ist. Fehlt SL oder TP -> sofort nachrüsten. Scheitert
    auch das -> Position schließen. Eine ungeschützte Position darf
    unter keinen Umständen bestehen bleiben.
    """
    time.sleep(1)  # Broker kurz Zeit geben, die Position zu registrieren
    for pos in bot_positions(symbol):
        if pos.sl > 0 and pos.tp > 0:
            log.info(f"✔ SCHUTZ BESTÄTIGT: {symbol} hat SL {pos.sl} und TP {pos.tp} beim Broker.")
            continue

        log.warning(f"⚠ {symbol}: Position {pos.ticket} OHNE vollständigen Schutz "
                    f"(SL={pos.sl}, TP={pos.tp}) — rüste nach...")
        fix = {
            "action": mt5.TRADE_ACTION_SLTP,
            "symbol": symbol,
            "position": pos.ticket,
            "sl": sl,
            "tp": tp,
            "magic": config.MAGIC_NUMBER,
        }
        res = mt5.order_send(fix)
        if res and res.retcode == mt5.TRADE_RETCODE_DONE:
            log.info(f"✔ SCHUTZ NACHGERÜSTET: {symbol} SL {sl} / TP {tp}.")
            continue

        log.error(f"✖ {symbol}: Schutz konnte NICHT gesetzt werden "
                  f"(Retcode {res.retcode if res else '?'}) — Position wird "
                  f"SOFORT GESCHLOSSEN. Ungeschützt wird nicht gehandelt.")
        tick = mt5.symbol_info_tick(symbol)
        close_req = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": pos.volume,
            "type": mt5.ORDER_TYPE_SELL,
            "position": pos.ticket,
            "price": tick.bid if tick else 0.0,
            "deviation": 50,
            "magic": config.MAGIC_NUMBER,
            "comment": "NotClose-NoSL",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        mt5.order_send(close_req)


def place_long(symbol: str, stop_dist: float, sig: dict) -> None:
    info = mt5.symbol_info(symbol)
    tick = mt5.symbol_info_tick(symbol)
    if info is None or tick is None:
        return

    price = tick.ask
    digits = info.digits

    # Broker-Mindestabstand für Stops beachten (sonst "Invalid stops"-Ablehnung)
    min_stop_dist = (info.trade_stops_level or 0) * info.point
    eff_stop = max(stop_dist, min_stop_dist * 1.1)
    if eff_stop > stop_dist:
        log.info(f"{symbol}: Stop-Abstand auf Broker-Minimum angehoben "
                 f"({stop_dist:.5f} -> {eff_stop:.5f}).")

    sl = round(price - eff_stop, digits)
    tp = round(price + eff_stop * config.RR_RATIO, digits)

    # Lots (und tatsächliches Risiko) aus dem TATSÄCHLICH verwendeten SL
    # berechnen — order_calc_profit braucht Entry und SL, nicht nur den
    # Abstand, und berücksichtigt damit auch die Broker-Mindestabstand-
    # Anhebung von eff_stop oben.
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
        "comment": "TrendPullback",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }
    result = mt5.order_send(request)
    if result is None:
        log.error(f"{symbol}: order_send fehlgeschlagen: {mt5.last_error()}")
        return
    if result.retcode != mt5.TRADE_RETCODE_DONE:
        # Manche Broker brauchen FOK statt IOC — einmal anders probieren
        request["type_filling"] = mt5.ORDER_FILLING_FOK
        result = mt5.order_send(request)
    if result and result.retcode == mt5.TRADE_RETCODE_DONE:
        acc = mt5.account_info()
        log.info(f"ORDER AUSGEFÜHRT: LONG {symbol} {lots} Lots @ {result.price} "
                 f"| SL {sl} | TP {tp} | RSI {sig['rsi']:.1f}")
        enforce_protection(symbol, sl, tp)
        journal_trade_open(
            symbol=symbol, tf=config.MARKETS[symbol], lots=lots,
            entry=result.price, sl=sl, tp=tp,
            # Echtes, broker-berechnetes Risiko (aus calc_lots), nicht der
            # Soll-Prozentwert — das Journal soll zeigen, was tatsächlich
            # riskiert wurde, nicht was geplant war.
            risk_amount=actual_risk,
            rr=config.RR_RATIO, rsi=sig["rsi"],
            reason=f"Trend über EMA{config.TREND_LEN}, RSI-Kreuz über {config.RSI_OVERSOLD}",
            equity=acc.equity if acc else 0.0,
        )
    else:
        log.error(f"{symbol}: Order abgelehnt, Retcode "
                  f"{result.retcode if result else '?'} — siehe MT5-Journal. "
                  f"Es wird KEIN ungeschützter Ersatz-Trade platziert.")


def print_market_status(symbols: list[str]) -> None:
    """Zeigt pro Markt den aktuellen Zustand: Trend, RSI, Abstand zum Signal."""
    for symbol in symbols:
        tf = config.MARKETS[symbol]
        df = get_closed_bars(symbol, tf)
        if df is None or df.empty:
            log.info(f"   {symbol:<7} ({tf}): keine Daten (Markt geschlossen?)")
            continue
        st = strategy.market_status(df)
        if st is None:
            log.info(f"   {symbol:<7} ({tf}): warte auf genug Kerzen")
            continue

        trend = "Aufwärts ↑" if st["up_trend"] else "Abwärts ↓ (kein Kauf)"
        if not st["up_trend"]:
            hint = "Trend falsch"
        elif st["ready"]:
            hint = ">> BEREIT: Rücksetzer läuft, Signal jederzeit möglich <<"
        else:
            hint = f"RSI muss noch {st['to_signal']:.0f} Punkte fallen"
        log.info(f"   {symbol:<7} ({tf}): {trend} | RSI {st['rsi']:.0f} | {hint}")


# ----------------------------------------------------------------------
# Hauptschleife
# ----------------------------------------------------------------------
def main() -> None:
    log.info("=" * 60)
    log.info("MT5 Trend+Pullback Bot startet (Long only, Demo-Modus)")
    log.info(f"Parameter: EMA{config.TREND_LEN}, RSI{config.RSI_LEN}@{config.RSI_OVERSOLD}, "
             f"ATR{config.ATR_LEN}x{config.ATR_STOP_MULT}, RR {config.RR_RATIO}, "
             f"Risiko {config.RISK_PERCENT}%/Trade")
    connect()
    symbols = ensure_symbols()

    last_bar_time: dict[str, datetime] = {}

    if config.SHOW_STARTUP_SNAPSHOT:
        log.info("-" * 60)
        log.info("Marktzustand beim Start:")
        print_market_status(symbols)
        log.info("-" * 60)

    log.info("Warte auf neue Kerzen... (Stopp: Strg+C — SL/TP bleiben beim Broker aktiv)")
    last_heartbeat = time.monotonic()
    known_tickets: dict[int, str] = {p.ticket: p.symbol for p in bot_positions()}
    try:
        while True:
            # --- Schließungen erkennen: verschwundene Positionen ins Journal ---
            current = {p.ticket: p.symbol for p in bot_positions()}
            for ticket, sym in list(known_tickets.items()):
                if ticket not in current:
                    journal_trade_close(ticket, sym)
            known_tickets = current

            # --- Herzschlag: regelmäßig zeigen, dass der Bot lebt und prüft ---
            if time.monotonic() - last_heartbeat >= config.HEARTBEAT_MINUTES * 60:
                now = datetime.now().strftime("%H:%M")
                acc = mt5.account_info()
                eq = f", Kapital {acc.equity:.2f} {acc.currency}" if acc else ""
                log.info(f"♥ {now} — Bot läuft, {len(symbols)} Märkte überwacht, "
                         f"{len(current)} Position(en) offen{eq}.")
                if config.SHOW_MARKET_STATUS:
                    print_market_status(symbols)
                last_heartbeat = time.monotonic()

            for symbol in symbols:
                tf = config.MARKETS[symbol]
                df = get_closed_bars(symbol, tf)
                if df is None or df.empty:
                    continue

                newest = df.index[-1]
                if last_bar_time.get(symbol) == newest:
                    continue  # noch keine neue geschlossene Kerze
                first_check = symbol not in last_bar_time
                last_bar_time[symbol] = newest
                if first_check:
                    continue  # beim Start keine Alt-Signale nachhandeln

                sig = strategy.check_signal(df)
                if sig is None:
                    continue

                log.info(f"SIGNAL: {symbol} ({tf}) @ Kerze {newest} "
                         f"| RSI {sig['rsi']:.1f} | Stop-Abstand {sig['stop_dist']:.5f}")

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
        log.info("Bot gestoppt. Offene Positionen sind durch SL/TP beim Broker gesichert.")
    finally:
        mt5.shutdown()


if __name__ == "__main__":
    main()
