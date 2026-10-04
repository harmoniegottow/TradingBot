"""mt5_verbindungstest.py - prueft, ob Python das laufende MT5 steuern kann.
Liest nur: Konto, Modus, Handelsfreigabe, drei Kerzen. Sendet KEINE Orders."""
import MetaTrader5 as mt5

PFAD = r"C:\Program Files\Pepperstone MetaTrader 5\terminal64.exe"
ok = mt5.initialize(path=PFAD, timeout=20000)
print("initialize:", ok, mt5.last_error())
if ok:
    a = mt5.account_info()
    t = mt5.terminal_info()
    modus = {0: "DEMO", 1: "WETTBEWERB", 2: "ECHTGELD"}.get(a.trade_mode, a.trade_mode)
    print("Konto:", a.login, a.server, "Modus:", modus, a.balance, a.currency)
    print("Terminal verbunden:", t.connected, "| Algo-Handel erlaubt:", t.trade_allowed)
    r = mt5.copy_rates_from_pos("EURUSD", mt5.TIMEFRAME_H1, 0, 3)
    print("EURUSD H1 Kerzen:", None if r is None else len(r), mt5.last_error())
    mt5.shutdown()
