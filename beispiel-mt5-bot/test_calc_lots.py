"""
Mock-Tests für calc_lots() (Sizing-Logik) im Haupt-Bot, OHNE echtes
MT5-Terminal. Mockt das MetaTrader5-Modul komplett (Projekt-Konvention,
s. CLAUDE.md "Technische Hinweise": "Tests der Signal-Logik ohne MT5:
Modul mocken").

Test 1 (Gold-Fall):    order_calc_profit liefert ein plausibles
                       Risiko/Lot, calc_lots() muss korrekt abrunden und
                       das Ist-Risiko unter dem 1,5x-Ziel zurückgeben.
Test 2 (Forex-Fall):   dieselbe Logik auf einem Forex-Markt (CHFJPY) mit
                       anderer Preis-/Risiko-Größenordnung — bestätigt,
                       dass calc_lots() nicht Gold-spezifisch ist.
Test 3 (Ablehnungsfall): order_calc_profit liefert ein Risiko/Lot, bei
                       dem selbst das Mindest-Lot > 1,5x Zielrisiko
                       kostet -> calc_lots() muss None zurückgeben.

Start: python test_calc_lots.py
"""
from __future__ import annotations

import sys
import types


def make_mock_mt5(risk_per_lot: float, volume_min: float = 0.01,
                  volume_max: float = 100.0, volume_step: float = 0.01,
                  equity: float = 50_000.0, margin_free: float = 1_000_000.0):
    """Baut ein Fake-'MetaTrader5'-Modul mit kontrolliertem order_calc_profit."""
    mt5 = types.SimpleNamespace()

    mt5.ORDER_TYPE_BUY = 0
    mt5.ORDER_TYPE_SELL = 1
    mt5.TIMEFRAME_H1 = 16385
    mt5.TIMEFRAME_H4 = 16388
    mt5.TRADE_ACTION_DEAL = 1
    mt5.TRADE_ACTION_SLTP = 6
    mt5.ORDER_TIME_GTC = 0
    mt5.ORDER_FILLING_IOC = 1
    mt5.ORDER_FILLING_FOK = 2
    mt5.TRADE_RETCODE_DONE = 10009
    mt5.TRADE_RETCODE_INVALID_FILL = 10030
    mt5.TRADE_RETCODE_UNSUPPORTED_FILL_MODE = 10018
    mt5.SYMBOL_TRADE_MODE_FULL = 4
    mt5.ACCOUNT_TRADE_MODE_DEMO = 0
    mt5.DEAL_ENTRY_OUT = 1
    mt5.DEAL_REASON_SL = 3
    mt5.DEAL_REASON_TP = 4

    def account_info():
        return types.SimpleNamespace(equity=equity, balance=equity,
                                     currency="EUR", margin_free=margin_free,
                                     login=12345, server="MockServer",
                                     trade_mode=mt5.ACCOUNT_TRADE_MODE_DEMO)

    def symbol_info(symbol):
        return types.SimpleNamespace(
            volume_min=volume_min, volume_max=volume_max, volume_step=volume_step,
            digits=2, point=0.01, trade_tick_size=0.01, trade_tick_value=1.0,
            trade_stops_level=0, trade_mode=mt5.SYMBOL_TRADE_MODE_FULL,
        )

    def order_calc_profit(order_type, symbol, volume, entry, sl):
        # Risiko skaliert linear mit dem Volumen (vereinfachtes, aber
        # realistisches Modell für den Test) -- Vorzeichen negativ (Verlust)
        return -(risk_per_lot * volume)

    def order_calc_margin(order_type, symbol, volume, entry):
        return 10.0 * volume

    mt5.account_info = account_info
    mt5.symbol_info = symbol_info
    mt5.order_calc_profit = order_calc_profit
    mt5.order_calc_margin = order_calc_margin
    mt5.last_error = lambda: "MOCK: kein Fehler"
    mt5.symbol_info_tick = lambda symbol: types.SimpleNamespace(ask=2000.0, bid=1999.5)
    mt5.positions_get = lambda *a, **k: []
    mt5.order_send = lambda req: None
    mt5.initialize = lambda **k: True
    mt5.shutdown = lambda: None
    mt5.copy_rates_from_pos = lambda *a, **k: None
    mt5.symbol_select = lambda *a, **k: True
    mt5.history_deals_get = lambda **k: None
    mt5.history_select = lambda *a, **k: True

    return mt5


def load_bot_with_mock(mock_mt5):
    """Importiert bot.py frisch mit dem gegebenen Mock-MT5-Modul."""
    sys.modules["MetaTrader5"] = mock_mt5
    for mod in ("bot", "config", "strategy"):
        sys.modules.pop(mod, None)
    import bot  # noqa: F401  (Import nach dem Mock-Setzen)
    return bot


def test_gold_sizing_korrekt() -> None:
    """Gold @ 2000, Stop-Abstand 2000*0,0025*2,5 (grob) -- Risiko/Lot vom
    Mock auf einen realistischen Wert gesetzt: 1% von 50.000 = 500 EUR
    Zielrisiko, Risiko/Lot = 550 EUR (etwas höher als 1 Lot exakt passen
    würde) -> erwartet: abgerundetes Lot < 1.0, Ist-Risiko <= 1,5x Ziel."""
    mock = make_mock_mt5(risk_per_lot=550.0)  # 550 EUR Verlust pro 1,0 Lot
    bot = load_bot_with_mock(mock)

    entry = 2000.0
    sl = 2000.0 - (2000.0 * 0.0025 * 2.5)  # ATR-Stop-Abstand grob simuliert
    result = bot.calc_lots("XAUUSD", entry, sl)

    assert result is not None, "calc_lots sollte hier einen Trade zulassen"
    lots, actual_risk = result
    zielrisiko = 50_000.0 * 0.01  # 500 EUR

    # Erwartete Lots: floor(500/550 / 0.01) * 0.01 = floor(0.909.. / 0.01)*0.01 = 0.90
    expected_lots = 0.90
    assert abs(lots - expected_lots) < 1e-9, f"Erwartet {expected_lots} Lots, bekam {lots}"
    assert actual_risk <= 1.5 * zielrisiko, "Ist-Risiko darf 1,5x Zielrisiko nicht übersteigen"
    assert actual_risk < zielrisiko, "Durch Abrunden muss das Ist-Risiko UNTER dem Ziel liegen"
    print(f"Test 1 (Gold-Fall) OK: Lots={lots} (erwartet {expected_lots}), "
          f"Ist-Risiko={actual_risk:.2f} EUR (Ziel={zielrisiko:.2f} EUR)")


def test_forex_sizing_korrekt() -> None:
    """CHFJPY @ 165, Stop-Abstand deutlich kleiner (Forex-typische
    Preis-/Punktgröße) -- anderes Risiko/Lot als beim Gold-Fall, bestätigt
    dass calc_lots() nicht Gold-spezifisch rechnet, sondern in jedem Fall
    ausschließlich über order_calc_profit geht."""
    mock = make_mock_mt5(risk_per_lot=83.0)  # 83 EUR Verlust pro 1,0 Lot
    bot = load_bot_with_mock(mock)

    entry = 165.0
    sl = 165.0 - (165.0 * 0.0015 * 2.0)  # engerer ATR-Stop-Abstand, Forex-typisch
    result = bot.calc_lots("CHFJPY", entry, sl)

    assert result is not None, "calc_lots sollte hier einen Trade zulassen"
    lots, actual_risk = result
    zielrisiko = 50_000.0 * 0.01  # 500 EUR

    # Erwartete Lots: floor(500/83 / 0.01) * 0.01 = floor(6.024.. / 0.01)*0.01 = 6.02
    expected_lots = 6.02
    assert abs(lots - expected_lots) < 1e-9, f"Erwartet {expected_lots} Lots, bekam {lots}"
    assert actual_risk <= 1.5 * zielrisiko, "Ist-Risiko darf 1,5x Zielrisiko nicht übersteigen"
    assert actual_risk < zielrisiko, "Durch Abrunden muss das Ist-Risiko UNTER dem Ziel liegen"
    print(f"Test 2 (Forex-Fall, CHFJPY) OK: Lots={lots} (erwartet {expected_lots}), "
          f"Ist-Risiko={actual_risk:.2f} EUR (Ziel={zielrisiko:.2f} EUR)")


def test_ablehnung_bei_zu_hohem_mindestrisiko() -> None:
    """Risiko/Lot so hoch angesetzt, dass selbst das Mindest-Lot (0,01)
    weit über dem 1,5x-Zielrisiko liegt -> calc_lots() muss None liefern,
    NICHT einen zu großen Trade eröffnen."""
    # 500 EUR Ziel, Mindest-Lot 0.01 -> Mindest-Risiko darf hier riesig sein:
    # risk_per_lot so hoch, dass 0.01 * risk_per_lot > 1.5 * 500 = 750
    mock = make_mock_mt5(risk_per_lot=100_000.0, volume_min=0.01)
    bot = load_bot_with_mock(mock)

    entry = 2000.0
    sl = 1990.0
    result = bot.calc_lots("XAUUSD", entry, sl)

    assert result is None, "calc_lots sollte bei überhöhtem Mindest-Lot-Risiko ablehnen (None)"
    print("Test 3 (Ablehnungsfall) OK: calc_lots() lehnt korrekt ab (None), "
          "kein überdimensionierter Trade.")


if __name__ == "__main__":
    test_gold_sizing_korrekt()
    test_forex_sizing_korrekt()
    test_ablehnung_bei_zu_hohem_mindestrisiko()
    print("\nAlle Mock-Tests bestanden.")
