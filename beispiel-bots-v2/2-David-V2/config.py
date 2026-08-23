"""
Konfiguration des MT5 Trend+Pullback Bots.

Alle einstellbaren Parameter an einem Ort — bot.py und strategy.py
lesen ausschließlich aus dieser Datei.
"""

# ----------------------------------------------------------------------
# MT5-Zugang
# ----------------------------------------------------------------------
# Bleibt MT5_LOGIN auf 0, verbindet sich der Bot mit dem BEREITS
# LAUFENDEN, eingeloggten MT5-Terminal (empfohlener Weg).
# Alternativ Zugangsdaten eintragen, dann loggt sich der Bot selbst ein.
MT5_LOGIN = 0            # z. B. 12345678  (0 = laufendes Terminal verwenden)
MT5_PASSWORD = ""
MT5_SERVER = ""          # z. B. "MetaQuotes-Demo"

# Sicherheitsschalter: Solange False, verweigert der Bot den Start auf
# einem Echtgeldkonto (siehe connect() in bot.py).
ALLOW_REAL_ACCOUNT = False

# ----------------------------------------------------------------------
# Märkte:  Symbol -> Timeframe ("H1" oder "H4")
# ----------------------------------------------------------------------
# Achtung: Symbolnamen sind brokerabhängig (z. B. "GOLD" statt "XAUUSD",
# "EURUSD.a", "EURUSD.m" ...). Nicht gefundene Symbole überspringt der
# Bot beim Start mit einer Warnung — Namen ggf. im MT5-Marktfenster
# nachschlagen und hier anpassen.
MARKETS = {
    "EURUSD": "H1",
    "GBPUSD": "H1",
    "USDJPY": "H1",
    "XAUUSD": "H4",
}

# ----------------------------------------------------------------------
# Strategie-Parameter (Trend + Pullback, Long only)
# ----------------------------------------------------------------------
# --- Handelsrichtung ---
# Long UND Short. Der Trendfilter blockiert Long-only in Abwärtsphasen
# komplett — im Live-Log waren 2 von 4 Märkten 23 Stunden lang tot.
TRADE_LONG = True
TRADE_SHORT = True   # Davids Original-Setup — bewusst als Live-Experiment

TREND_LEN = 200       # EMA-Länge Trendfilter
RSI_LEN = 14          # RSI-Periode
RSI_OVERSOLD = 35     # Pullback-Schwelle LONG: Signal, wenn der RSI von
                      # unten darüber zurückkreuzt. 30 = klassisch
                      # (seltener), 40 = mehr Signale in starken Trends.
                      # Die SHORT-Schwelle ergibt sich automatisch als
                      # Spiegelung: 100 - RSI_OVERSOLD (bei 35 also 65).

# Neutralzone um die Trend-EMA, gemessen in ATR. Liegt der Kurs näher an
# der EMA als dieser Puffer, wird NICHT gehandelt — dort entscheidet
# Rauschen über die Richtung, nicht der Trend. 0 = kein Puffer (wie V1).
TREND_BUFFER_ATR = 0.25
ATR_LEN = 14          # ATR-Periode für den Stop-Abstand
ATR_STOP_MULT = 1.5   # Stop-Loss-Abstand = ATR * dieser Faktor
RR_RATIO = 2.0        # Take-Profit = Stop-Abstand * RR_RATIO (Chance/Risiko 2:1)

# ----------------------------------------------------------------------
# Gewinn-Absicherung — Stop nachziehen, sobald Gewinn erreicht ist
# ----------------------------------------------------------------------
# Steht ein Trade weit genug im Plus, wird der Stop-Loss so nachgezogen,
# dass ein Rest-Gewinn abgesichert ist. Der Trade kann ab da nicht mehr
# im Minus schließen.
#
# Beide Werte sind PROZENT DES KONTOKAPITALS, nicht feste Beträge —
# damit die Regel bei wachsendem Konto gleich streng bleibt.
#   Bei 10.000 € Kapital:  0.8% =  80 €  ->  0.1% =  10 € gesichert
#   Bei 20.000 € Kapital:  0.8% = 160 €  ->  0.1% =  20 € gesichert
#
# ACHTUNG — das ist kein kostenloser Schutz:
# Der Stop rückt nah an den Markt. Trades, die nur kurz zurücklaufen und
# danach ihr Ziel erreicht hätten, werden vorher ausgestoppt. Die Winrate
# steigt, der Durchschnittsgewinn sinkt. Ob der Erwartungswert steigt,
# musst du im Backtest messen — nicht annehmen.
#
# Hinweis zum Abstand: Zwischen Auslöseschwelle und gesichertem Gewinn
# liegen hier 0.7% des Kapitals, die du wieder hergibst, wenn der Trade
# dreht. Nach Spread und Kommission bleibt vom gesicherten Rest real
# weniger übrig — der Bot loggt den echten Nettobetrag.
SECURE_PROFIT_ENABLED = True        # aktiv — im Backtest gegenprüfen!
SECURE_PROFIT_TRIGGER_PCT = 0.8     # ab wie viel % Buchgewinn der Stop wandert
SECURE_PROFIT_LOCK_PCT = 0.1        # wie viel % Gewinn danach abgesichert sind

# ----------------------------------------------------------------------
# Risiko & Limits
# ----------------------------------------------------------------------
# 0.5 statt 1.0: Bei einem 100.000-EUR-Demokonto sind 1% = 1.000 EUR pro
# Trade. Ein späteres Echtgeldkonto ist deutlich kleiner — mit 0.5% bleiben
# die Demo-Ergebnisse besser übertragbar.
RISK_PERCENT = 0.5        # Risiko pro Trade in % des Kontokapitals (Equity)

# --- Tageslimits ---------------------------------------------------
# Erreicht der Tagesverlust bzw. -gewinn diese Marke, eröffnet der Bot
# für den Rest des Tages KEINE neuen Trades mehr. Bereits offene
# Positionen laufen normal weiter bis SL oder TP.
#
# Hinweis zum Verlustlimit: Bei RISK_PERCENT = 1.0 beendet bereits EIN
# Verlusttrade den Handelstag. Das ist sehr streng — üblich sind 3 bis 5
# Prozent, damit zwei bis drei Fehlschläge verkraftbar bleiben. Prüfe im
# Backtest, wie oft die Sperre greift (Spalte "TageGestoppt...").
DAILY_LOSS_LIMIT_PCT = 1.0    # Tagesverlust in % -> keine neuen Trades
DAILY_PROFIT_LIMIT_PCT = 5.0  # Tagesgewinn in % -> keine neuen Trades
# Stunde (UTC), zu der ein neuer Handelstag beginnt. 0 = Mitternacht UTC.
# Bei Broker-Serverzeit abweichend ggf. anpassen.
DAILY_RESET_HOUR_UTC = 0
MAX_OPEN_POSITIONS = 3    # max. gleichzeitig offene Bot-Positionen (gesamt)
MAGIC_NUMBER = 100002     # Kennung, damit der Bot nur SEINE Positionen verwaltet.
                          # Frei wählbar — nur wichtig: nicht dieselbe Zahl wie
                          # bei einem anderen Bot verwenden, der gleichzeitig
                          # auf demselben Konto läuft.

# ----------------------------------------------------------------------
# Daten & Laufverhalten
# ----------------------------------------------------------------------
# Geladene Kerzen je Prüfung. Muss mindestens das 2-Fache von TREND_LEN
# betragen (plus Puffer): eine EMA200 ist nach genau 200 Kerzen noch vom
# Startkurs verzerrt und liefert einen falschen Trendfilter.
BARS_HISTORY = 600
POLL_SECONDS = 15         # Pause zwischen zwei Prüfdurchläufen (Sekunden)
HEARTBEAT_MINUTES = 30    # Lebenszeichen im Log alle X Minuten
SHOW_STARTUP_SNAPSHOT = True   # Marktübersicht direkt beim Start anzeigen
SHOW_MARKET_STATUS = True      # Marktübersicht auch bei jedem Heartbeat anzeigen

# ----------------------------------------------------------------------
# Logging
# ----------------------------------------------------------------------
LOG_FILE = "bot.log"

# ----------------------------------------------------------------------
# Plausibilitätsprüfung (läuft einmal beim Import, schützt vor Tippfehlern)
# ----------------------------------------------------------------------
ALLOWED_TIMEFRAMES = ("M5", "M15", "M30", "H1", "H4", "D1")

# Die Trend-EMA braucht rund das Doppelte ihrer Spanne, um eingeschwungen
# zu sein. Wird hier zu wenig geladen, zeigt der Trendfilter Unsinn.
if BARS_HISTORY < TREND_LEN * 2 + 20:
    raise ValueError(
        f"BARS_HISTORY ({BARS_HISTORY}) ist zu klein für TREND_LEN "
        f"({TREND_LEN}). Nötig sind mindestens {TREND_LEN * 2 + 20} Kerzen, "
        f"damit die EMA eingeschwungen ist."
    )

if not MARKETS:
    raise ValueError("MARKETS ist leer — mindestens ein Symbol eintragen.")

_bad_tf = {s: tf for s, tf in MARKETS.items() if tf not in ALLOWED_TIMEFRAMES}
if _bad_tf:
    raise ValueError(
        f"Ungültige Timeframes in MARKETS "
        f"(erlaubt: {', '.join(ALLOWED_TIMEFRAMES)}): {_bad_tf}"
    )

if not 0 < RISK_PERCENT <= 10:
    raise ValueError(
        f"RISK_PERCENT ({RISK_PERCENT}) unplausibel — üblich sind 0.5 bis 2."
    )

if not 0 < RSI_OVERSOLD < 100:
    raise ValueError(f"RSI_OVERSOLD ({RSI_OVERSOLD}) muss zwischen 0 und 100 liegen.")

if RSI_LEN < 2 or ATR_LEN < 2 or TREND_LEN < 2:
    raise ValueError("RSI_LEN, ATR_LEN und TREND_LEN müssen mindestens 2 sein.")

if ATR_STOP_MULT <= 0:
    raise ValueError(f"ATR_STOP_MULT ({ATR_STOP_MULT}) muss größer als 0 sein.")

if RR_RATIO <= 0:
    raise ValueError(f"RR_RATIO ({RR_RATIO}) muss größer als 0 sein.")

if MAX_OPEN_POSITIONS < 1:
    raise ValueError(f"MAX_OPEN_POSITIONS ({MAX_OPEN_POSITIONS}) muss mindestens 1 sein.")

if POLL_SECONDS < 1:
    raise ValueError(f"POLL_SECONDS ({POLL_SECONDS}) muss mindestens 1 sein.")

if not (TRADE_LONG or TRADE_SHORT):
    raise ValueError("TRADE_LONG und TRADE_SHORT sind beide False — "
                     "der Bot könnte gar nicht handeln.")

if TREND_BUFFER_ATR < 0:
    raise ValueError(f"TREND_BUFFER_ATR ({TREND_BUFFER_ATR}) darf nicht "
                     f"negativ sein.")
if TREND_BUFFER_ATR > 2:
    raise ValueError(f"TREND_BUFFER_ATR ({TREND_BUFFER_ATR}) ist sehr groß — "
                     f"bei über 2 ATR läge fast jeder Kurs in der Neutralzone "
                     f"und der Bot würde praktisch nie handeln.")

if TRADE_SHORT and RSI_OVERSOLD >= 50:
    raise ValueError(
        f"RSI_OVERSOLD ({RSI_OVERSOLD}) muss unter 50 liegen, wenn Short "
        f"aktiv ist — sonst überlappen die Long-Schwelle ({RSI_OVERSOLD}) "
        f"und die gespiegelte Short-Schwelle ({100 - RSI_OVERSOLD})."
    )

if DAILY_LOSS_LIMIT_PCT <= 0 or DAILY_PROFIT_LIMIT_PCT <= 0:
    raise ValueError("DAILY_LOSS_LIMIT_PCT und DAILY_PROFIT_LIMIT_PCT "
                     "müssen größer als 0 sein.")
if not 0 <= DAILY_RESET_HOUR_UTC <= 23:
    raise ValueError(f"DAILY_RESET_HOUR_UTC ({DAILY_RESET_HOUR_UTC}) "
                     f"muss zwischen 0 und 23 liegen.")

if SECURE_PROFIT_ENABLED:
    if SECURE_PROFIT_TRIGGER_PCT <= 0:
        raise ValueError(
            f"SECURE_PROFIT_TRIGGER_PCT ({SECURE_PROFIT_TRIGGER_PCT}) "
            f"muss größer als 0 sein."
        )
    if not 0 < SECURE_PROFIT_LOCK_PCT < SECURE_PROFIT_TRIGGER_PCT:
        raise ValueError(
            f"SECURE_PROFIT_LOCK_PCT ({SECURE_PROFIT_LOCK_PCT}) muss größer "
            f"als 0 und kleiner als SECURE_PROFIT_TRIGGER_PCT "
            f"({SECURE_PROFIT_TRIGGER_PCT}) sein — sonst würde der Stop "
            f"über den aktuellen Kurs gesetzt."
        )
    if SECURE_PROFIT_TRIGGER_PCT > RISK_PERCENT * RR_RATIO:
        raise ValueError(
            f"SECURE_PROFIT_TRIGGER_PCT ({SECURE_PROFIT_TRIGGER_PCT}%) liegt "
            f"über dem maximal möglichen Gewinn eines Trades "
            f"({RISK_PERCENT * RR_RATIO}% = RISK_PERCENT × RR_RATIO). "
            f"Die Regel würde nie auslösen."
        )
