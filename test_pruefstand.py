"""
test_pruefstand.py — Traut man dem Massstab? Erst pruefen, dann glauben.

Ein Pruefstand, der bei allem "verliert" sagt, ist genauso wertlos wie einer,
der alles durchwinkt. Diese Tests weisen nach, dass die Mechanik in BEIDE
Richtungen funktioniert.

Aufruf:  .venv/bin/python test_pruefstand.py
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from backtesting import Strategy

from pruefstand import bewerte, kaufen_und_halten, urteil


def _kurse(werte) -> pd.DataFrame:
    """Baut einen minimalen OHLC-Rahmen aus einer Schlusskursreihe."""
    s = pd.Series(werte, dtype=float)
    idx = pd.date_range("2024-01-01", periods=len(s), freq="h")
    return pd.DataFrame(
        {
            "Open": s.shift(1).fillna(s.iloc[0]).values,
            "High": (s * 1.001).values,
            "Low": (s * 0.999).values,
            "Close": s.values,
        },
        index=idx,
    )


def test_kaufen_und_halten_rechnet_richtig():
    df = _kurse([100.0, 110.0, 120.0, 150.0])
    erg = kaufen_und_halten(df)
    assert abs(erg - 50.0) < 1e-9, f"erwartet +50 %, bekommen {erg}"
    print("OK  kaufen_und_halten: 100 -> 150 ergibt +50,0 %")


def test_hellsehende_strategie_besteht():
    """Gegenprobe: eine Strategie, die die Zukunft kennt, MUSS bestehen.

    Ohne diesen Test koennte der Pruefstand pauschal alles ablehnen und
    wir wuerden es nie merken.
    """
    rng = np.random.default_rng(7)
    # Seitwaerts mit Rauschen, damit Kaufen-und-Halten keine Huerde ist
    werte = 100 + np.cumsum(rng.normal(0, 0.3, 4000))
    df = _kurse(werte)
    zukunft = df["Close"].shift(-12) > df["Close"] * 1.004

    class Hellseher(Strategy):
        def init(self):
            self.signal = self.I(lambda: zukunft.values.astype(float), name="s")

        def next(self):
            if self.position:
                return
            if self.signal[-1] > 0.5:
                kurs = self.data.Close[-1]
                self.buy(size=0.1, sl=kurs * 0.99, tp=kurs * 1.006)

    zeile = bewerte(df, Hellseher, runden=40)
    print(
        f"    Hellseher: PF {zeile['PF']}  Trades {zeile['Trades']}  "
        f"Zufall besser {zeile.get('Zufall besser %')} %  -> {zeile['Urteil']}"
    )
    assert zeile["PF"] > 1.0, "Hellseher muss Gewinn machen"
    assert zeile["Urteil"] == "PRUEFEN", (
        f"Hellseher muss bestehen, Urteil war '{zeile['Urteil']}'. "
        "Wenn das fehlschlaegt, ist der Pruefstand zu streng und "
        "wuerde eine echte Kante uebersehen."
    )
    print("OK  Hellseher besteht: Pruefstand erkennt eine echte Kante")


def test_zufallsstrategie_faellt_durch():
    """Eine reine Muenzwurf-Strategie darf NIEMALS bestehen."""
    rng = np.random.default_rng(11)
    werte = 100 + np.cumsum(rng.normal(0, 0.3, 4000))
    df = _kurse(werte)
    wuerfel = rng.random(len(df) + 10)

    class Muenzwurf(Strategy):
        def init(self):
            pass

        def next(self):
            i = len(self.data.Close) - 1
            if self.position or i < 20:
                return
            if wuerfel[i] < 0.02:
                kurs = self.data.Close[-1]
                self.buy(size=0.1, sl=kurs * 0.99, tp=kurs * 1.02)

    zeile = bewerte(df, Muenzwurf, runden=40)
    print(
        f"    Muenzwurf: PF {zeile['PF']}  Trades {zeile['Trades']}  "
        f"Zufall besser {zeile.get('Zufall besser %')} %  -> {zeile['Urteil']}"
    )
    assert zeile["Urteil"] != "PRUEFEN", (
        f"Muenzwurf darf nicht bestehen, Urteil war '{zeile['Urteil']}'"
    )
    print("OK  Muenzwurf faellt durch: Pruefstand laesst Zufall nicht durch")


def test_urteil_logik():
    """Die Ampel muss die Faelle in der richtigen Rangfolge abfangen."""
    faelle = [
        ({"PF": 0.8, "Trades": 100, "vs K+H": 5, "Zufall besser %": 1.0}, "verliert"),
        ({"PF": 1.5, "Trades": 100, "vs K+H fair": 5, "Zufall besser %": 40.0}, "= Zufall"),
        ({"PF": 1.5, "Trades": 100, "vs K+H fair": -20, "Zufall besser %": 1.0}, "< Halten"),
        ({"PF": 1.5, "Trades": 9, "vs K+H fair": 5, "Zufall besser %": 1.0}, "zu wenig Trades"),
        ({"PF": 1.5, "Trades": 100, "vs K+H fair": 5, "Zufall besser %": 1.0}, "PRUEFEN"),
    ]
    for zeile, erwartet in faelle:
        ist = urteil(zeile)
        assert ist == erwartet, f"{zeile} -> erwartet '{erwartet}', war '{ist}'"
    print(f"OK  Urteilslogik: alle {len(faelle)} Faelle korrekt einsortiert")


if __name__ == "__main__":
    print("=" * 70)
    print("SELBSTTEST DES PRUEFSTANDS")
    print("=" * 70)
    test_kaufen_und_halten_rechnet_richtig()
    test_urteil_logik()
    test_zufallsstrategie_faellt_durch()
    test_hellsehende_strategie_besteht()
    print("=" * 70)
    print("Alle Tests bestanden. Der Massstab unterscheidet echte Kanten")
    print("von Zufall - er lehnt nicht blind alles ab.")
    print("=" * 70)
