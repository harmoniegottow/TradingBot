"""
Konfiguration des Gold/Silber-Divergenz-Bots — Demo-Test-Instanz für den
Fund "Intermarket-Divergenz Gold gegen Silber".

Gut geprüfter Fund aus der Forschungsarbeit an diesem Projekt:
Out-of-Sample-Verhältnis 2,43-2,65 (3 verschiedene Split-Methoden),
142 Trades auf H4 über 10 Jahre, Gewinn-Konzentration sehr niedrig
(Top-5-Trades nur 10,7% des Bruttogewinns — niedriger als bei der
Baseline-Strategie selbst, die zum Vergleich diente). Gewinnt klar in
3 von 5 Testfenstern, verliert nie katastrophal. Auf Tagesbasis (D1)
bestätigt sich dieselbe Richtung.

IDEE (einfach erklärt): Gold und Silber bewegen sich normalerweise
sehr ähnlich. Bleibt Gold gegenüber Silber kurzzeitig deutlich zurück
und holt dann wieder auf, ist das ein Kaufsignal für Gold — die
Erwartung ist, dass sich das "Nachhinken" wieder ausgleicht.

TECHNISCHE BESONDERHEIT: dieser Bot braucht ZWEI Kurse (XAUUSD UND
XAGUSD), um die Divergenz zu berechnen — wie beim BTC-Season-Bot.
Gehandelt wird NUR XAUUSD, XAGUSD dient ausschließlich als Referenz.

WICHTIG: Dieser Bot ist für DEMO-KONTEN gebaut. Der Schutzschalter
ALLOW_REAL_ACCOUNT steht auf False und der Bot verweigert den Start
auf einem Echtgeldkonto.
"""

# --- Sicherheit ---
ALLOW_REAL_ACCOUNT = False   # NIEMALS leichtfertig auf True setzen
MAGIC_NUMBER = 100003        # eigene Nummer, kollidiert mit keinem anderen Bot.
                             # Frei wählbar — nur wichtig: nicht dieselbe Zahl
                             # wie bei einem anderen Bot verwenden, der
                             # gleichzeitig auf demselben Konto läuft.
LOG_PREFIX = "[DIVERGENZ]"

# --- Login (leer lassen, wenn MT5-Terminal schon eingeloggt ist) ---
MT5_LOGIN = None
MT5_PASSWORD = None
MT5_SERVER = None

# --- Markt: gehandelt wird NUR Gold, Silber wird zusaetzlich als
#     Referenz-Kurs benoetigt (s. strategy.py) ---
MARKETS = {
    "XAUUSD": "H4",
}
REFERENCE_SYMBOL = "XAGUSD"   # nur zur Signal-Berechnung, wird NICHT gehandelt

# --- Strategie-Parameter ---
TREND_LEN = 150
ATR_LEN = 14
ATR_STOP_MULT = 2.0
RR_RATIO = 2.0
RET_LEN = 20            # Kerzen fuer die Renditeberechnung (Momentum-Differenz)
BAND_LOOKBACK = 100      # Kerzen fuer Mittelwert/Standardabweichung der Differenz
BAND_MULT = 1.5          # -1,5-Standardabweichungs-Band

# --- Risikomanagement ---
RISK_PERCENT = 1.0
MAX_OPEN_POSITIONS = 1

# --- Technik ---
BARS_HISTORY = 400
POLL_SECONDS = 30
LOG_FILE = "bot.log"

# --- Anzeige / "Herzschlag" ---
HEARTBEAT_MINUTES = 15
SHOW_MARKET_STATUS = True
SHOW_STARTUP_SNAPSHOT = True
