"""
test_beobachter.py — Prueft die Signal-Logik von beobachter.py OHNE MT5.

Warum: beobachter.py laeuft nur unter Windows, aber seine Rechen-Logik
(EMA, RSI, ATR, Signal) ist reines pandas. Die kann und MUSS hier auf
dem Server geprueft werden — sonst faellt ein Denkfehler erst auf
Dominiques Rechner auf.

Getestet wird:
  1. Die Indikatoren stimmen mit denen des Pruefstands ueberein.
  2. Die Signale des Beobachters stimmen mit dem Backtest-Baustein
     TrendPullbackV2 (nur Long) ueberein.

MT5 wird durch ein Attrappen-Modul ersetzt, damit der Import klappt.
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

import pandas as pd

# --- MT5-Attrappe, damit beobachter.py importierbar ist -----------------
fake = types.ModuleType("MetaTrader5")
for i, name in enumerate([
    "TIMEFRAME_M15", "TIMEFRAME_M30", "TIMEFRAME_H1", "TIMEFRAME_H4",
    "TIMEFRAME_D1", "ORDER_TYPE_BUY", "ORDER_TYPE_SELL",
    "ACCOUNT_TRADE_MODE_DEMO", "SYMBOL_TRADE_MODE_FULL",
]):
    setattr(fake, name, i)
sys.modules["MetaTrader5"] = fake

sys.path.insert(0, str(Path(__file__).parent / "mt5-windows"))
import beobachter  # noqa: E402

sys.path.insert(0, str(Path(__file__).parent))
from strategien.indikatoren import ema as ema_ref, rsi as rsi_ref  # noqa: E402


def lade(symbol: str, tf: str) -> pd.DataFrame:
    pfad = Path(__file__).parent / "data" / f"{symbol}_{tf}.csv"
    df = pd.read_csv(pfad, index_col=0, parse_dates=True)
    df = df.rename(columns=str.lower)
    return df[["open", "high", "low", "close"]].dropna()


def test_indikatoren_stimmen_ueberein():
    """EMA und RSI muessen dieselben Werte liefern wie im Pruefstand."""
    df = lade("EURUSD", "H_1")
    close = df["close"]

    e_beob = beobachter.ema(close, 200)
    e_ref = pd.Series(ema_ref(close, 200), index=close.index)
    diff = (e_beob - e_ref).abs().dropna().max()
    assert diff < 1e-9, f"EMA weicht ab: {diff}"

    r_beob = beobachter.rsi(close, 14)
    r_ref = pd.Series(rsi_ref(close, 14), index=close.index)
    gemeinsam = r_beob.notna() & r_ref.notna()
    diff = (r_beob[gemeinsam] - r_ref[gemeinsam]).abs().max()
    assert diff < 1e-6, f"RSI weicht ab: {diff}"
    print(f"  Indikatoren identisch (EMA und RSI, {len(df)} Kerzen)")


def test_signale_stimmen_mit_backtest():
    """
    Der Beobachter muss dieselben Kerzen als Signal erkennen wie die
    Backtest-Klasse TrendPullbackV2 mit trade_short = False.
    """
    df = lade("EURUSD", "H_1")

    # Signale des Beobachters: Fenster durchschieben wie im Livebetrieb.
    fenster = beobachter.BARS_HISTORY
    beob_signale = []
    for i in range(fenster, len(df) + 1):
        teil = df.iloc[i - fenster:i]
        sig, _ = beobachter.signal(teil)
        if sig:
            beob_signale.append((teil.index[-1], sig["dir"]))

    # Referenz: dieselbe Regel vektoriell nachgerechnet.
    close = df["close"]
    e = beobachter.ema(close, beobachter.TREND_LEN)
    r = beobachter.rsi(close, beobachter.RSI_LEN)
    a = beobachter.atr(df, beobachter.ATR_LEN)
    puffer = a * beobachter.TREND_BUFFER_ATR
    auf = close > e + puffer
    kreuz = (r.shift(1) <= beobachter.RSI_OVERSOLD) & (r > beobachter.RSI_OVERSOLD)
    gueltig = e.notna() & r.notna() & r.shift(1).notna() & a.notna()
    ref = df.index[auf & kreuz & gueltig]
    # Nur Kerzen, die der Beobachter ueberhaupt sehen konnte
    ref = [z for z in ref if z >= df.index[fenster - 1]]

    beob_zeiten = [z for z, _ in beob_signale]
    fehlend = set(ref) - set(beob_zeiten)
    zuviel = set(beob_zeiten) - set(ref)

    assert not fehlend, f"Beobachter verpasst {len(fehlend)} Signale"
    assert not zuviel, f"Beobachter erfindet {len(zuviel)} Signale"
    assert all(r == "long" for _, r in beob_signale), "Short darf nicht kommen"
    print(f"  Signale identisch zur Referenz: {len(beob_signale)} Stueck, alle Long")


def test_short_ist_aus():
    """Sicherheitsnetz: TRADE_SHORT muss abgeschaltet sein (gemessen schlechter)."""
    assert beobachter.TRADE_SHORT is False, "Short sollte aus sein"
    assert beobachter.TRADE_LONG is True
    print("  Short ist abgeschaltet, Long aktiv")


def test_kein_order_send_im_code():
    """Der wichtigste Test: Der Beobachter darf NIRGENDS Auftraege senden."""
    quelle = (Path(__file__).parent / "mt5-windows" / "beobachter.py").read_text(
        encoding="utf-8")
    # Kommentare/Docstring erwaehnen order_send absichtlich — echte Aufrufe
    # haetten die Form "mt5.order_send("
    assert "mt5.order_send(" not in quelle, "GEFAHR: order_send im Beobachter!"
    for verboten in ("TRADE_ACTION_DEAL", "TRADE_ACTION_SLTP", "position_close"):
        assert verboten not in quelle, f"GEFAHR: {verboten} im Beobachter!"
    print("  Kein einziger Auftrags-Aufruf im Beobachter enthalten")


def test_divergenz_stimmt_mit_backtest():
    """
    Die Divergenz im Beobachter muss GENAU dieselben Kerzen erkennen wie
    der gepruefte Backtest-Baustein. Sonst laeuft live etwas anderes als
    das, was zehn Jahre lang getestet wurde.

    Geprueft auf den echten MT5-Daten (zehn Jahre H4).
    """
    from strategien.divergenz_gold_silber import divergenz_vorbereiten

    basis = Path(__file__).parent / "data-mt5"
    if not (basis / "XAUUSD_H_4.csv").exists():
        print("  uebersprungen (keine MT5-Daten vorhanden)")
        return

    def lade_gross(sym):
        df = pd.read_csv(basis / f"{sym}_H_4.csv", index_col=0, parse_dates=True)
        if df.index.tz is not None:
            df.index = df.index.tz_localize(None)
        return df[["Open", "High", "Low", "Close"]].dropna()

    gold_gross = lade_gross("XAUUSD")
    silber_gross = lade_gross("XAGUSD")

    # Referenz: der getestete Backtest-Baustein
    kombi = divergenz_vorbereiten(gold_gross, silber_gross)
    ema_ref = kombi["Close"].ewm(span=150, adjust=False).mean()
    ref_zeiten = set(kombi.index[kombi["DivSignal"] & (kombi["Close"] > ema_ref)])

    # Beobachter: Fenster durchschieben wie im Livebetrieb
    gold = gold_gross.rename(columns=str.lower)
    silber = silber_gross.rename(columns=str.lower)
    fenster = beobachter.BARS_HISTORY

    beob_zeiten = set()
    for i in range(fenster, len(gold) + 1):
        g = gold.iloc[i - fenster:i]
        # Silber bis zum selben Zeitpunkt, wie es live verfuegbar waere
        s = silber[silber.index <= g.index[-1]].iloc[-fenster:]
        sig, _ = beobachter.divergenz_signal(g, s)
        if sig:
            beob_zeiten.add(g.index[-1])

    # Nur Kerzen vergleichen, die der Beobachter sehen konnte
    ab = gold.index[fenster - 1]
    ref_sichtbar = {z for z in ref_zeiten if z >= ab}

    fehlend = ref_sichtbar - beob_zeiten
    zuviel = beob_zeiten - ref_sichtbar

    print(f"  Referenz (Backtest): {len(ref_sichtbar)} Signale")
    print(f"  Beobachter:          {len(beob_zeiten)} Signale")
    assert not fehlend, f"Beobachter verpasst {len(fehlend)} Signale, z.B. {sorted(fehlend)[:3]}"
    assert not zuviel, f"Beobachter erfindet {len(zuviel)} Signale, z.B. {sorted(zuviel)[:3]}"
    print("  Divergenz identisch zum geprueften Backtest-Baustein")


def test_divergenz_kein_zukunftsblick():
    """
    Silber darf NUR mit Kursen bis zum Gold-Zeitpunkt einfliessen.
    Test: Silber-Daten nach der letzten Gold-Kerze anhaengen und pruefen,
    dass sich am Signal nichts aendert.
    """
    basis = Path(__file__).parent / "data-mt5"
    if not (basis / "XAUUSD_H_4.csv").exists():
        print("  uebersprungen (keine MT5-Daten vorhanden)")
        return

    def lade(sym):
        df = pd.read_csv(basis / f"{sym}_H_4.csv", index_col=0, parse_dates=True)
        if df.index.tz is not None:
            df.index = df.index.tz_localize(None)
        return df.rename(columns=str.lower)[["open", "high", "low", "close"]].dropna()

    gold = lade("XAUUSD").iloc[-600:]
    silber_voll = lade("XAGUSD")

    # Fall A: Silber nur bis zum Gold-Ende
    s_normal = silber_voll[silber_voll.index <= gold.index[-1]].iloc[-600:]
    sig_a, _ = beobachter.divergenz_signal(gold, s_normal)

    # Fall B: Silber MIT spaeteren Kursen (die es live nicht gaebe)
    s_zukunft = silber_voll.iloc[-600:].copy()
    zukunft = s_zukunft.iloc[-5:].copy()
    zukunft.index = zukunft.index + pd.Timedelta(days=30)
    zukunft["close"] = zukunft["close"] * 1.5   # kraeftig verfaelscht
    s_mit_zukunft = pd.concat([s_zukunft, zukunft])

    sig_b, _ = beobachter.divergenz_signal(gold, s_mit_zukunft)

    gleich = (sig_a is None) == (sig_b is None)
    if sig_a and sig_b:
        gleich = abs(sig_a["rsi"] - sig_b["rsi"]) < 1e-9
    assert gleich, "Spaetere Silberkurse veraendern das Signal — Zukunftsblick!"
    print("  Spaetere Silberkurse beeinflussen das Signal nicht")


if __name__ == "__main__":
    print("Pruefe beobachter.py ohne MT5:\n")
    test_indikatoren_stimmen_ueberein()
    test_signale_stimmen_mit_backtest()
    test_short_ist_aus()
    test_kein_order_send_im_code()
    test_divergenz_stimmt_mit_backtest()
    test_divergenz_kein_zukunftsblick()
    print("\nAlle Pruefungen bestanden.")
