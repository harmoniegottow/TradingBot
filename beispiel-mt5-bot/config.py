"""
Konfiguration des MT5-Trading-Bots.

WICHTIG: Dieser Bot ist für DEMO-KONTEN gebaut. Der Schutzschalter
ALLOW_REAL_ACCOUNT steht auf False und der Bot verweigert den Start
auf einem Echtgeldkonto. Ändere das erst, wenn das System über Wochen
im Demo-Betrieb bewiesen hat, dass es sich wie erwartet verhält —
und auch dann nur mit Geld, dessen Verlust du verkraften kannst.
"""

# --- Sicherheit ---
ALLOW_REAL_ACCOUNT = False   # NIEMALS leichtfertig auf True setzen
MAGIC_NUMBER = 20260709      # Kennung: so erkennt der Bot seine eigenen Orders

# --- Login (leer lassen, wenn MT5-Terminal schon eingeloggt ist) ---
MT5_LOGIN = None             # z.B. 12345678 (Demo-Kontonummer)
MT5_PASSWORD = None          # Demo-Passwort
MT5_SERVER = None            # z.B. "MetaQuotes-Demo"

# --- Validierte Märkte und Zeitrahmen (aus der Backtest-Pipeline) ---
# Format: Symbol -> Timeframe-String ("H1" oder "H4")
MARKETS = {
    "XAUUSD": "H1",   # Gold    - PF 1.92 im 1h-Fixed-Test
    "XAGUSD": "H1",   # Silber  - PF 1.30
    "XPTUSD": "H1",   # Platin  - PF 1.52
    "CHFJPY": "H4",   # 4h-Kern - mehrfach validiert
    "USDJPY": "H4",   # 4h-Kern
}

# --- Strategie-Parameter (die NEUTRALEN Werte aus dem Robustheitstest,
#     NICHT die pro Markt überoptimierten!) ---
TREND_LEN = 150
RSI_LEN = 14
RSI_OVERSOLD = 35
ATR_LEN = 14
ATR_STOP_MULT = 2.0
RR_RATIO = 2.0

# --- Risikomanagement ---
RISK_PERCENT = 1.0           # % des Kontostands pro Trade riskiert
MAX_OPEN_POSITIONS = 3       # nie mehr als N Positionen gleichzeitig
                             # (Metalle sind korreliert - 3 offene Metall-Trades
                             #  wären faktisch 3x dasselbe Risiko)

# --- Technik ---
BARS_HISTORY = 400           # wie viele Kerzen für die Indikator-Berechnung laden
POLL_SECONDS = 30            # wie oft nach neuen Kerzen geschaut wird
LOG_FILE = "bot.log"

# --- Anzeige / "Herzschlag" (fürs Zuschauen und fürs Video) ---
HEARTBEAT_MINUTES = 15       # alle N Minuten eine Status-Zeile "ich lebe und prüfe"
SHOW_MARKET_STATUS = True    # bei jedem Herzschlag pro Markt: Trend + RSI + Abstand zum Signal
SHOW_STARTUP_SNAPSHOT = True # direkt beim Start einmal den Marktzustand ausgeben
