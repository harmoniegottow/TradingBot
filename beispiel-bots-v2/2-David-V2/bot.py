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

TIMEFRAMES = {
    "M5": mt5.TIMEFRAME_M5,
    "M15": mt5.TIMEFRAME_M15,
    "M30": mt5.TIMEFRAME_M30,
    "H1": mt5.TIMEFRAME_H1,
    "H4": mt5.TIMEFRAME_H4,
    "D1": mt5.TIMEFRAME_D1,
}

JOURNAL_FILE = "trades.csv"
JOURNAL_COLS = ["zeit", "ereignis", "symbol", "richtung", "timeframe", "session",
                "lots", "entry", "sl", "tp", "exit", "risiko_eur", "risk_reward",
                "rsi", "gebuehren", "gewinn", "grund", "equity"]

# Datei, die den Zeitstempel der zuletzt geprüften Kerze je Symbol speichert.
# Damit erkennt der Bot nach einem Neustart, wo er stehen geblieben ist, und
# handelt weder alte Signale nach noch verpasst er die erste neue Kerze.
STATE_FILE = "bot_state.json"


def state_load() -> dict:
    """
    Lädt den gespeicherten Zustand: Kerzenzeiten je Symbol und den
    Tagesstand für die Limits.

    Ältere Dateien enthalten nur die Kerzenzeiten auf oberster Ebene —
    die werden erkannt und übernommen, damit ein Update den Bot nicht
    seine Historie vergessen lässt.
    """
    leer = {"bars": {}, "tag": {}}
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return leer

    if not isinstance(data, dict):
        return leer
    if "bars" in data or "tag" in data:
        return {"bars": data.get("bars", {}) or {},
                "tag": data.get("tag", {}) or {}}
    # Altes Format: flaches Symbol -> Zeitstempel
    return {"bars": data, "tag": {}}


def state_save(last_bar_time: dict, tages_state: dict | None = None) -> None:
    """Speichert Kerzenzeiten und Tagesstand atomar."""
    try:
        tmp = STATE_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({
                "bars": {s: t.isoformat() for s, t in last_bar_time.items()},
                "tag": tages_state or {},
            }, f)
        os.replace(tmp, STATE_FILE)  # atomar: nie halbe Datei bei Absturz
    except OSError as exc:
        log.warning(f"Zustand konnte nicht gespeichert werden: {exc}")


def handelstag_utc(jetzt: datetime | None = None) -> str:
    """
    Kennung des aktuellen Handelstags (YYYY-MM-DD) nach UTC.

    Liegt DAILY_RESET_HOUR_UTC über 0, beginnt der Handelstag später —
    Stunden davor zählen noch zum Vortag.
    """
    jetzt = jetzt or datetime.now(timezone.utc)
    if jetzt.hour < config.DAILY_RESET_HOUR_UTC:
        jetzt = jetzt - timedelta(days=1)
    return jetzt.strftime("%Y-%m-%d")


def tageslimit_pruefen(state: dict, equity: float) -> tuple[bool, str]:
    """
    Prüft, ob heute noch neue Trades erlaubt sind.

    `state` hält das Startkapital des Handelstags und überlebt Neustarts
    über bot_state.json — sonst könnte ein Neustart die Sperre umgehen.

    Rückgabe: (gesperrt, Begründung)
    """
    heute = handelstag_utc()

    if state.get("tag") != heute:
        state["tag"] = heute
        state["start_equity"] = equity
        state["gemeldet"] = False
        log.info(f"Neuer Handelstag {heute} — Startkapital {equity:.2f}, "
                 f"Limits: -{config.DAILY_LOSS_LIMIT_PCT}% / "
                 f"+{config.DAILY_PROFIT_LIMIT_PCT}%")
        return False, ""

    start = state.get("start_equity", 0.0)
    if start <= 0:
        return False, ""

    pct = (equity - start) / start * 100
    if pct <= -config.DAILY_LOSS_LIMIT_PCT:
        return True, (f"Tagesverlust {pct:.2f}% erreicht "
                      f"(Limit -{config.DAILY_LOSS_LIMIT_PCT}%)")
    if pct >= config.DAILY_PROFIT_LIMIT_PCT:
        return True, (f"Tagesgewinn {pct:+.2f}% erreicht "
                      f"(Limit +{config.DAILY_PROFIT_LIMIT_PCT}%)")
    return False, ""


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
    """
    Hängt eine Zeile ans Trade-Journal an (CSV, Excel-kompatibel mit Semikolon).

    Nutzt das csv-Modul: Semikolons oder Zeilenumbrüche in einem Feld
    (z. B. im Grund-Text) werden sauber maskiert, statt die Spalten zu
    verschieben. Schreibfehler beenden den Bot nicht — Handeln hat
    Vorrang vor Protokollieren.
    """
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
                       rsi: float, reason: str, equity: float,
                       richtung: str = "long") -> None:
    journal_write({
        "zeit": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "ereignis": "OPEN", "symbol": symbol, "richtung": richtung.upper(),
        "timeframe": tf,
        "session": trading_session(),
        "lots": lots, "entry": entry, "sl": sl, "tp": tp,
        "risiko_eur": f"{risk_amount:.2f}", "risk_reward": rr,
        "rsi": f"{rsi:.1f}", "grund": reason, "equity": f"{equity:.2f}",
    })


def journal_trade_close(ticket: int, symbol: str) -> bool:
    """
    Holt die Abschluss-Daten einer verschwundenen Position aus der Historie.

    Rückgabe True, wenn die Schließung protokolliert werden konnte.
    Bei False sollte der Aufrufer es später erneut versuchen: die
    Broker-Historie ist manchmal ein paar Sekunden nach dem Schließen
    noch nicht befüllt, und ein zu früher Abruf liefert nichts.
    """
    # history_deals_get(position=...) braucht bei vielen Brokern ein
    # geladenes Zeitfenster. Ohne history_select() kommt oft None zurück.
    now = datetime.now(timezone.utc)
    # history_select gibt es nur in MQL5, nicht im Python-Paket.
    # Absicherung: nur aufrufen, falls eine zukünftige Version es anbietet.
    if hasattr(mt5, "history_select"):
        mt5.history_select(now - timedelta(days=30), now + timedelta(days=1))

    deals = mt5.history_deals_get(position=ticket)
    if not deals:
        return False

    entry_out = getattr(mt5, "DEAL_ENTRY_OUT", 1)
    exit_deals = [d for d in deals if d.entry == entry_out]
    if not exit_deals:
        return False

    d = exit_deals[-1]
    # Gewinn und Kosten immer über ALLE Deals der Position summieren,
    # sonst fehlen Teilschließungen und die Einstiegs-Kommission.
    profit = sum(x.profit for x in deals)
    fees = sum(x.commission + x.fee + x.swap for x in deals)
    net = profit + fees  # Kommission/Swap sind negativ

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

        # Aktivierung kann fehlschlagen (z. B. Symbol nicht im Kontotyp
        # enthalten). Ohne Prüfung landet es trotzdem in der Liste und
        # jeder Kursabruf liefert später None.
        if not info.visible and not mt5.symbol_select(symbol, True):
            log.warning(f"{symbol}: konnte nicht aktiviert werden "
                        f"({mt5.last_error()}) — wird übersprungen.")
            continue

        # Tick-Daten sind Voraussetzung für jede Lot-Berechnung. Fehlen
        # sie, scheitert später JEDER Trade — besser gleich melden.
        if info.trade_tick_size <= 0 or info.trade_tick_value <= 0:
            log.warning(f"{symbol}: keine gültigen Tick-Daten "
                        f"(tick_size={info.trade_tick_size}, "
                        f"tick_value={info.trade_tick_value}) — wird übersprungen.")
            continue

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
    tf = TIMEFRAMES.get(tf_str)
    if tf is None:
        log.error(f"{symbol}: unbekannter Timeframe '{tf_str}'.")
        return None

    try:
        rates = mt5.copy_rates_from_pos(symbol, tf, 0, config.BARS_HISTORY)
    except Exception as exc:  # MT5-Anbindung kann sporadisch werfen
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
    df = df.iloc[:-1]  # letzte Zeile = laufende Kerze -> weg
    return df if not df.empty else None


def bot_positions(symbol: str | None = None):
    """Offene Positionen, die DIESER Bot eröffnet hat (per Magic Number)."""
    positions = mt5.positions_get(symbol=symbol) if symbol else mt5.positions_get()
    if positions is None:
        return []
    return [p for p in positions if p.magic == config.MAGIC_NUMBER]


def calc_lots(symbol: str, is_long: bool, entry: float,
             sl: float) -> tuple[float, float] | None:
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

    order_type = mt5.ORDER_TYPE_BUY if is_long else mt5.ORDER_TYPE_SELL

    def loss_for(volume: float) -> float | None:
        """Verlust laut Broker für `volume` Lots zwischen entry und sl (immer positiv)."""
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

    # Reicht die freie Margin? Sonst lehnt der Broker die Order ohnehin ab.
    margin = mt5.order_calc_margin(order_type, symbol, lots, entry)
    if margin is not None and margin > acc.margin_free:
        log.warning(f"{symbol}: benötigte Margin {margin:.2f} > freie Margin "
                    f"{acc.margin_free:.2f} — Trade übersprungen.")
        return None

    # Letzte Sicherung vor dem Senden (Wächter): tatsächliches Risiko der
    # GEWÄHLTEN Lot-Größe noch einmal broker-seitig gegenrechnen. Weicht es
    # deutlich vom Ziel ab — z. B. weil sich zwischen den obigen Schritten
    # etwas Unerwartetes ergeben hat — wird NICHT gehandelt statt mit
    # falscher Größe zu senden.
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


def secure_profit() -> None:
    """
    Zieht den Stop nach, sobald ein Trade genug Buchgewinn hat.

    Auslöser und gesicherter Rest sind Prozent des Kontokapitals
    (SECURE_PROFIT_TRIGGER_PCT / SECURE_PROFIT_LOCK_PCT), damit die
    Regel bei wachsendem Konto gleich streng bleibt.

    Rechnet in Kontowährung, nicht in Preisabständen: aus dem gesuchten
    Geldbetrag wird über tick_value und Lot-Größe der nötige Kursabstand
    zurückgerechnet.

    Wurde der Stop bereits nachgezogen (er sichert schon Gewinn), passiert
    nichts weiter — das hier ist kein Trailing Stop.
    """
    if not config.SECURE_PROFIT_ENABLED:
        return

    acc = mt5.account_info()
    if acc is None or acc.equity <= 0:
        return

    trigger_geld = acc.equity * (config.SECURE_PROFIT_TRIGGER_PCT / 100)
    lock_geld = acc.equity * (config.SECURE_PROFIT_LOCK_PCT / 100)

    for pos in bot_positions():
        info = mt5.symbol_info(pos.symbol)
        tick = mt5.symbol_info_tick(pos.symbol)
        if info is None or tick is None or pos.sl <= 0 or pos.volume <= 0:
            continue

        digits = info.digits
        point = info.point
        tick_size = info.trade_tick_size or point
        tick_value = info.trade_tick_value or 0.0
        if tick_size <= 0 or tick_value <= 0:
            continue

        # Wie viel Kursbewegung entspricht dem gesuchten Geldbetrag?
        geld_je_preiseinheit = (tick_value / tick_size) * pos.volume
        if geld_je_preiseinheit <= 0:
            continue
        lock_abstand = lock_geld / geld_je_preiseinheit

        # Buchgewinn zum aktuellen Marktpreis (nicht pos.profit — das
        # enthält je nach Broker bereits Swap und Kommission)
        if pos.type == mt5.POSITION_TYPE_BUY:
            if pos.sl >= pos.price_open:
                continue  # Stop sichert bereits Gewinn
            gewinn_geld = (tick.bid - pos.price_open) * geld_je_preiseinheit
            neuer_sl = round(pos.price_open + lock_abstand, digits)
            min_abstand = max(getattr(info, "trade_stops_level", 0) * point,
                              (tick.ask - tick.bid) * 2)
            if neuer_sl >= tick.bid - min_abstand:
                continue  # zu nah am Markt, Broker würde ablehnen
        else:
            if pos.sl <= pos.price_open:
                continue
            gewinn_geld = (pos.price_open - tick.ask) * geld_je_preiseinheit
            neuer_sl = round(pos.price_open - lock_abstand, digits)
            min_abstand = max(getattr(info, "trade_stops_level", 0) * point,
                              (tick.ask - tick.bid) * 2)
            if neuer_sl <= tick.ask + min_abstand:
                continue

        if gewinn_geld < trigger_geld:
            continue  # noch nicht genug im Plus

        res = mt5.order_send({
            "action": mt5.TRADE_ACTION_SLTP,
            "symbol": pos.symbol,
            "position": pos.ticket,
            "sl": neuer_sl,
            "tp": pos.tp,
            "magic": config.MAGIC_NUMBER,
        })
        if res and res.retcode == mt5.TRADE_RETCODE_DONE:
            # Realistisch: vom gesicherten Betrag geht noch die Kommission ab
            netto_hinweis = ""
            if lock_geld < 20:
                netto_hinweis = (" — nach Kommission bleibt davon real "
                                 "deutlich weniger übrig")
            log.info(f"⇧ GEWINN GESICHERT: {pos.symbol} #{pos.ticket} steht "
                     f"{gewinn_geld:.2f} {acc.currency} im Plus (Schwelle "
                     f"{trigger_geld:.2f}). Stop von {pos.sl} auf {neuer_sl} "
                     f"gezogen, sichert {lock_geld:.2f} {acc.currency}"
                     f"{netto_hinweis}.")
            journal_write({
                "zeit": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "ereignis": "STOP_NACHGEZOGEN", "symbol": pos.symbol,
                "session": trading_session(), "entry": pos.price_open,
                "sl": neuer_sl, "tp": pos.tp,
                "grund": (f"Gewinn {gewinn_geld:.2f} über Schwelle "
                          f"{trigger_geld:.2f}, {lock_geld:.2f} gesichert"),
                "equity": f"{acc.equity:.2f}",
            })
        else:
            log.warning(f"{pos.symbol}: Stop konnte nicht nachgezogen werden "
                        f"(Retcode {res.retcode if res else '?'}). "
                        f"Der ursprüngliche Stop bleibt aktiv.")


def close_position(pos, comment: str) -> bool:
    """Schließt eine einzelne Position zum Marktpreis. True bei Erfolg."""
    tick = mt5.symbol_info_tick(pos.symbol)
    if tick is None:
        log.error(f"{pos.symbol}: kein Kurs zum Schließen von {pos.ticket} verfügbar.")
        return False

    # Gegenrichtung zur Position, und immer die passende Seite des Spreads
    if pos.type == mt5.POSITION_TYPE_BUY:
        order_type, price = mt5.ORDER_TYPE_SELL, tick.bid
    else:
        order_type, price = mt5.ORDER_TYPE_BUY, tick.ask

    req = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": pos.symbol,
        "volume": pos.volume,
        "type": order_type,
        "position": pos.ticket,
        "price": price,
        "deviation": 50,
        "magic": config.MAGIC_NUMBER,
        "comment": comment[:31],  # MT5 begrenzt Kommentare auf 31 Zeichen
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }
    res = mt5.order_send(req)
    if res is None or res.retcode != mt5.TRADE_RETCODE_DONE:
        # Zweiter Versuch mit anderem Filling-Modus (brokerabhängig)
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
    -> Position schließen. Eine ungeschützte Position darf nicht
    bestehen bleiben.

    Arbeitet bewusst mit dem Ticket der neuen Position, nicht mit dem
    Symbol: sonst würden ältere Positionen desselben Symbols mit den
    SL/TP-Werten des neuen Trades überschrieben.
    """
    time.sleep(1)  # Broker kurz Zeit geben, die Position zu registrieren

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


# Retcodes, nach denen ein zweiter Versuch mit anderem Filling-Modus
# sinnvoll ist. Bei allen anderen Ablehnungen wird NICHT erneut gesendet:
# ein blinder Retry kann sonst eine zweite Position eröffnen, wenn die
# erste Order in Wahrheit doch durchging.
RETRY_FILLING_CODES = {
    getattr(mt5, "TRADE_RETCODE_INVALID_FILL", 10030),
    getattr(mt5, "TRADE_RETCODE_UNSUPPORTED_FILL_MODE", 10018),
}


def place_order(symbol: str, sig: dict) -> bool:
    """
    Eröffnet eine Position in Signalrichtung (long oder short).

    Long:  Einstieg zum Ask, Stop darunter, Ziel darüber.
    Short: Einstieg zum Bid, Stop darüber, Ziel darunter.

    Rückgabe True, wenn die Order ausgeführt UND geschützt wurde.
    """
    richtung = sig["dir"]
    is_long = richtung == "long"
    stop_dist = sig["stop_dist"]

    info = mt5.symbol_info(symbol)
    if info is None:
        log.warning(f"{symbol}: keine Symbol-Daten — Trade übersprungen.")
        return False

    # Handelt der Broker das Symbol gerade überhaupt? (Wochenende,
    # Feiertag, Nur-Schließen-Modus) — sonst läuft die Order ins Leere.
    if info.trade_mode != mt5.SYMBOL_TRADE_MODE_FULL:
        log.info(f"{symbol}: Handel derzeit nicht möglich "
                 f"(trade_mode={info.trade_mode}) — Trade übersprungen.")
        return False

    tick = mt5.symbol_info_tick(symbol)
    if tick is None or tick.ask <= 0 or tick.bid <= 0:
        log.warning(f"{symbol}: kein gültiger Kurs — Trade übersprungen.")
        return False

    digits = info.digits
    point = info.point
    # Long kauft zum Ask, Short verkauft zum Bid
    price = tick.ask if is_long else tick.bid

    # Spread-Schutz: liegt der Spread über 15 % des geplanten Stop-Abstands,
    # frisst er zu viel vom Erwartungswert (typisch bei News oder Rollover).
    spread = tick.ask - tick.bid
    if spread > stop_dist * 0.15:
        log.info(f"{symbol}: Spread {spread / point:.0f} Punkte zu hoch "
                 f"(> 15 % des Stop-Abstands) — Trade übersprungen.")
        return False

    # Broker-Mindestabstand für Stops beachten (sonst "Invalid stops"-Ablehnung).
    # trade_stops_level kann 0 sein — dann greift ein Sicherheitspuffer
    # aus dem aktuellen Spread.
    stops_level = getattr(info, "trade_stops_level", 0) or 0
    min_stop_dist = max(stops_level * point, spread * 2)
    eff_stop = max(stop_dist, min_stop_dist * 1.1)
    if eff_stop > stop_dist:
        log.info(f"{symbol}: Stop-Abstand auf Broker-Minimum angehoben "
                 f"({stop_dist:.{digits}f} -> {eff_stop:.{digits}f}).")

    def stops_fuer(p: float) -> tuple[float, float]:
        """SL/TP für einen Einstiegspreis — gespiegelt je nach Richtung."""
        if is_long:
            return (round(p - eff_stop, digits),
                    round(p + eff_stop * config.RR_RATIO, digits))
        return (round(p + eff_stop, digits),
                round(p - eff_stop * config.RR_RATIO, digits))

    sl, tp = stops_fuer(price)
    order_type = mt5.ORDER_TYPE_BUY if is_long else mt5.ORDER_TYPE_SELL

    # Lots (und tatsächliches Risiko) IMMER aus dem tatsächlich verwendeten
    # SL berechnen, sonst stimmt das Risiko nicht mehr, wenn eff_stop
    # angehoben wurde.
    calc = calc_lots(symbol, is_long, price, sl)
    if calc is None:
        return False
    lots, actual_risk = calc

    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": lots,
        "type": order_type,
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
        log.error(f"{symbol}: order_send fehlgeschlagen: {mt5.last_error()} — "
                  f"kein zweiter Versuch (Order könnte trotzdem angekommen sein).")
        return False

    # Nur bei einem echten Filling-Problem erneut senden, und dann mit
    # frischem Kurs — der alte Preis wäre inzwischen abgelaufen.
    if (result.retcode != mt5.TRADE_RETCODE_DONE
            and result.retcode in RETRY_FILLING_CODES):
        log.info(f"{symbol}: Filling-Modus IOC abgelehnt — versuche FOK.")
        fresh = mt5.symbol_info_tick(symbol)
        if fresh and fresh.ask > 0 and fresh.bid > 0:
            neuer_preis = fresh.ask if is_long else fresh.bid
            sl, tp = stops_fuer(neuer_preis)
            request["price"] = neuer_preis
            request["sl"] = sl
            request["tp"] = tp
        request["type_filling"] = mt5.ORDER_FILLING_FOK
        result = mt5.order_send(request)

    if result and result.retcode == mt5.TRADE_RETCODE_DONE:
        acc = mt5.account_info()
        equity = acc.equity if acc else 0.0
        pfeil = "▲ LONG" if is_long else "▼ SHORT"
        log.info(f"ORDER AUSGEFÜHRT: {pfeil} {symbol} {lots} Lots @ "
                 f"{result.price} | SL {sl} | TP {tp} | RSI {sig['rsi']:.1f}")
        # Ticket der neuen Position — order_send liefert die Order-ID,
        # die bei Market-Orders der Positions-ID entspricht.
        ticket = getattr(result, "order", 0) or getattr(result, "deal", 0)
        enforce_protection(ticket, sl, tp)
        schwelle = (config.RSI_OVERSOLD if is_long
                    else strategy.rsi_overbought())
        journal_trade_open(
            symbol=symbol, tf=config.MARKETS[symbol], lots=lots,
            entry=result.price, sl=sl, tp=tp,
            richtung=richtung,
            # Echtes, broker-berechnetes Risiko (aus calc_lots), nicht der
            # Soll-Prozentwert — das Journal soll zeigen, was tatsächlich
            # riskiert wurde, nicht was geplant war.
            risk_amount=actual_risk,
            rr=config.RR_RATIO, rsi=sig["rsi"],
            reason=(f"Trend {'über' if is_long else 'unter'} "
                    f"EMA{config.TREND_LEN}, RSI-Kreuz "
                    f"{'über' if is_long else 'unter'} {schwelle:.0f}"),
            equity=equity,
        )
        return True

    log.error(f"{symbol}: Order abgelehnt, Retcode "
              f"{result.retcode if result else '?'} — siehe MT5-Journal. "
              f"Es wird KEIN ungeschützter Ersatz-Trade platziert.")
    return False


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

        trend_txt = {"up": "Aufwärts ↑", "down": "Abwärts ↓",
                     "neutral": "Seitwärts ~"}[st["trend"]]

        if st["richtung"] == "keine":
            if st["trend"] == "neutral":
                hint = "Kurs zu nah an der EMA — kein klarer Trend"
            else:
                hint = (f"{'Short' if st['trend'] == 'down' else 'Long'} "
                        f"ist deaktiviert")
        elif st["ready"]:
            hint = (f">> BEREIT für {st['richtung'].upper()}: Rücksetzer "
                    f"läuft, Signal jederzeit möglich <<")
        else:
            bewegung = "fallen" if st["richtung"] == "long" else "steigen"
            hint = (f"{st['richtung'].upper()}-Setup | RSI muss noch "
                    f"{st['to_signal']:.0f} Punkte {bewegung}")
        log.info(f"   {symbol:<7} ({tf}): {trend_txt} | RSI {st['rsi']:.0f} | {hint}")


# ----------------------------------------------------------------------
# Hauptschleife
# ----------------------------------------------------------------------
def main() -> None:
    log.info("=" * 60)
    seiten = []
    if config.TRADE_LONG:
        seiten.append("Long")
    if config.TRADE_SHORT:
        seiten.append("Short")
    log.info(f"MT5 Trend+Pullback Bot startet ({' + '.join(seiten)})")
    log.info(f"Parameter: EMA{config.TREND_LEN} (Puffer {config.TREND_BUFFER_ATR} ATR), "
             f"RSI{config.RSI_LEN} @ {config.RSI_OVERSOLD}/"
             f"{strategy.rsi_overbought():.0f}, "
             f"ATR{config.ATR_LEN}x{config.ATR_STOP_MULT}, RR {config.RR_RATIO}, "
             f"Risiko {config.RISK_PERCENT}%/Trade")
    if config.SECURE_PROFIT_ENABLED:
        log.info(f"Gewinn-Absicherung aktiv: ab +{config.SECURE_PROFIT_TRIGGER_PCT}% "
                 f"wandert der Stop auf +{config.SECURE_PROFIT_LOCK_PCT}%")
    log.info(f"Tageslimits: -{config.DAILY_LOSS_LIMIT_PCT}% / "
             f"+{config.DAILY_PROFIT_LIMIT_PCT}%")
    connect()
    symbols = ensure_symbols()

    # Zuletzt geprüfte Kerze je Symbol aus der letzten Sitzung laden.
    # Ohne das würde der Bot nach jedem Neustart die erste erkannte
    # Kerze als "schon gesehen" verwerfen und ein gültiges Signal verpassen.
    saved = state_load()
    last_bar_time: dict[str, pd.Timestamp] = {}
    for sym, iso in saved["bars"].items():
        try:
            last_bar_time[sym] = pd.Timestamp(iso)
        except ValueError:
            continue
    if last_bar_time:
        log.info(f"Zustand geladen: {len(last_bar_time)} Symbol(e) aus "
                 f"vorheriger Sitzung — keine Alt-Signale werden nachgehandelt.")

    # Tagesstand für die Limits — überlebt Neustarts, sonst könnte ein
    # Neustart die Tagessperre einfach umgehen.
    tages_state: dict = saved["tag"] if isinstance(saved.get("tag"), dict) else {}
    if tages_state.get("tag") == handelstag_utc():
        log.info(f"Handelstag {tages_state['tag']} fortgesetzt, "
                 f"Startkapital {tages_state.get('start_equity', 0):.2f}")

    if config.SHOW_STARTUP_SNAPSHOT:
        log.info("-" * 60)
        log.info("Marktzustand beim Start:")
        print_market_status(symbols)
        log.info("-" * 60)

    log.info("Warte auf neue Kerzen... (Stopp: Strg+C — SL/TP bleiben beim Broker aktiv)")
    last_heartbeat = time.monotonic()
    known_tickets: dict[int, str] = {p.ticket: p.symbol for p in bot_positions()}
    pending_close: dict[int, str] = {}  # Schließungen, deren Historie noch fehlt

    try:
        while True:
            # --- Verbindung prüfen: ohne Terminal ist jede Abfrage sinnlos ---
            if mt5.account_info() is None:
                log.error("Verbindung zu MT5 verloren — versuche neu zu verbinden...")
                mt5.shutdown()
                time.sleep(10)
                try:
                    connect()
                    log.info("Verbindung wiederhergestellt.")
                except SystemExit:
                    log.error("Neuverbindung fehlgeschlagen — nächster Versuch in 60 s.")
                    time.sleep(60)
                    continue

            # --- Schließungen erkennen: verschwundene Positionen ins Journal ---
            current = {p.ticket: p.symbol for p in bot_positions()}
            for ticket, sym in list(known_tickets.items()):
                if ticket not in current:
                    pending_close[ticket] = sym
            known_tickets = current

            # --- Gewinn absichern: Stop nachziehen, wenn genug im Plus ---
            # Läuft bei JEDEM Durchlauf (alle POLL_SECONDS), nicht nur bei
            # neuen Kerzen — sonst würde der Schutz erst Stunden später greifen.
            secure_profit()

            # Broker-Historie hinkt manchmal hinterher: erneut versuchen,
            # bis die Abschlussdaten wirklich da sind.
            for ticket, sym in list(pending_close.items()):
                if journal_trade_close(ticket, sym):
                    del pending_close[ticket]

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

            # --- Tageslimits: sperren neue Einstiege, offene laufen weiter ---
            acc_now = mt5.account_info()
            tag_gesperrt = False
            if acc_now is not None:
                vorher = tages_state.get("tag")
                tag_gesperrt, tag_grund = tageslimit_pruefen(
                    tages_state, acc_now.equity)
                if tages_state.get("tag") != vorher:
                    state_save(last_bar_time, tages_state)  # Tageswechsel sichern
                if tag_gesperrt and not tages_state.get("gemeldet"):
                    log.warning(f"⏸ TAGESLIMIT: {tag_grund}. Bis morgen werden "
                                f"KEINE neuen Trades eröffnet. Offene Positionen "
                                f"laufen normal bis SL oder TP weiter.")
                    tages_state["gemeldet"] = True
                    state_save(last_bar_time, tages_state)

            # Offene Positionen EINMAL je Durchlauf holen statt zweimal
            # pro Symbol — bei 4 Märkten spart das 7 von 8 API-Aufrufen.
            offene = list(current.values())
            anzahl_offen = len(offene)

            state_dirty = False
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
                state_dirty = True
                if first_check:
                    log.info(f"{symbol}: erste Kerze dieser Sitzung erfasst "
                             f"({newest}) — Signal wird ab der nächsten geprüft.")
                    continue  # beim Start keine Alt-Signale nachhandeln

                sig = strategy.check_signal(df)
                if sig is None:
                    # Warum kein Einstieg? Ohne diese Zeile lässt sich später
                    # nicht auswerten, woran Signale scheitern.
                    st = strategy.market_status(df)
                    if st is None:
                        grund = "zu wenige Kerzen"
                    elif st["trend"] == "neutral":
                        grund = "Kurs zu nah an der EMA (Neutralzone)"
                    elif st["richtung"] == "keine":
                        grund = f"Trend {st['trend']}, aber Richtung deaktiviert"
                    elif st["ready"]:
                        grund = (f"{st['richtung'].upper()}: RSI "
                                 f"{st['rsi']:.0f} in der Zone, kein Kreuz")
                    else:
                        grund = (f"{st['richtung'].upper()}: RSI "
                                 f"{st['rsi']:.0f} — noch {st['to_signal']:.0f} "
                                 f"Punkte bis zur Zone")
                    log.info(f"KEIN EINSTIEG: {symbol} ({tf}) @ {newest} — {grund}")
                    continue

                log.info(f"SIGNAL {sig['dir'].upper()}: {symbol} ({tf}) @ Kerze "
                         f"{newest} | RSI {sig['rsi']:.1f} | "
                         f"Stop-Abstand {sig['stop_dist']:.5f}")

                if tag_gesperrt:
                    log.info(f"{symbol}: Signal erkannt, aber Tageslimit aktiv "
                             f"— kein Einstieg.")
                    continue
                if symbol in offene:
                    log.info(f"{symbol}: bereits Position offen — übersprungen.")
                    continue
                if anzahl_offen >= config.MAX_OPEN_POSITIONS:
                    log.info(f"{symbol}: Max. offene Positionen "
                             f"({config.MAX_OPEN_POSITIONS}) erreicht — übersprungen.")
                    continue

                # Zähler sofort mitführen: eröffnet der Bot in DIESEM
                # Durchlauf zwei Trades, muss der zweite das Limit kennen.
                if place_order(symbol, sig):
                    offene.append(symbol)
                    anzahl_offen += 1

            if state_dirty:
                state_save(last_bar_time, tages_state)

            time.sleep(config.POLL_SECONDS)

    except KeyboardInterrupt:
        log.info("Bot gestoppt. Offene Positionen sind durch SL/TP beim Broker gesichert.")
    except Exception:
        # Unerwarteter Fehler: mit vollem Traceback protokollieren, damit
        # er nachvollziehbar ist — und trotzdem sauber herunterfahren.
        log.exception("UNERWARTETER FEHLER — Bot wird beendet. "
                      "Offene Positionen bleiben durch SL/TP beim Broker geschützt.")
    finally:
        state_save(last_bar_time, tages_state)
        mt5.shutdown()
        log.info("MT5-Verbindung geschlossen.")


if __name__ == "__main__":
    main()
