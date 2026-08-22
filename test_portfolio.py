"""
test_portfolio.py — Traut man dem Portfolio-Rahmen? Erst pruefen.

Der gefaehrlichste Fehler in einem Portfolio-Backtest ist der stille Blick in
die Zukunft. Er faellt nicht auf, er macht die Ergebnisse nur wunderschoen.
Diese Tests weisen nach, dass der Rahmen sauber rechnet.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from portfolio import (
    gewichte,
    kaufen_und_halten,
    kennzahlen,
    permutationstest,
    rendite_reihe,
    signale,
)


def _kurse(n=800, m=5, seed=3, drift=0.0):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2020-01-01", periods=n, freq="B")
    daten = {}
    for j in range(m):
        r = rng.normal(drift, 0.01, n)
        daten[f"SYM{j}"] = 100 * np.exp(np.cumsum(r))
    return pd.DataFrame(daten, index=idx)


def test_kein_blick_in_die_zukunft():
    """Ein Signal, das die Zukunft KENNT, darf nach dem Versatz nichts bringen.

    Konstruktion: Signal = Vorzeichen der Rendite von HEUTE. Wer heute schon
    weiss, wie der Tag endet, muesste ohne Versatz sagenhaft verdienen.
    Nach korrektem Versatz (Signal von heute wirkt morgen) darf davon
    NICHTS uebrig bleiben.
    """
    kurse = _kurse()
    heute = kurse.pct_change(fill_method=None)
    hellsicht = pd.DataFrame(
        np.sign(heute.to_numpy()), index=kurse.index, columns=kurse.columns
    ).fillna(0.0)

    # Mit korrektem Versatz (so rechnet unser Modul)
    mit_versatz = kennzahlen(rendite_reihe(kurse, hellsicht, kosten=0.0))
    # Ohne Versatz, also FALSCH gerechnet, nur zum Vergleich
    tagesr = kurse.pct_change(fill_method=None).fillna(0.0)
    ohne = kennzahlen(((hellsicht * tagesr).sum(axis=1)) / len(kurse.columns))

    print(f"    Hellsicht OHNE Versatz (falsch): Sharpe {ohne['Sharpe']:8.2f}")
    print(f"    Hellsicht MIT  Versatz (richtig): Sharpe {mit_versatz['Sharpe']:8.2f}")
    assert ohne["Sharpe"] > 10, "Ohne Versatz muesste Hellsicht absurd gut sein"
    assert abs(mit_versatz["Sharpe"]) < 1.0, (
        f"MIT Versatz darf Hellsicht nichts bringen, war {mit_versatz['Sharpe']}. "
        "Wenn das fehlschlaegt, blickt der Backtest in die Zukunft!"
    )
    print("OK  kein Blick in die Zukunft: der Versatz wirkt korrekt")


def test_echtes_momentum_wird_erkannt():
    """Gegenprobe: bei kuenstlich trendenden Daten MUSS Momentum verdienen."""
    rng = np.random.default_rng(5)
    n = 1200
    idx = pd.date_range("2020-01-01", periods=n, freq="B")
    daten = {}
    for j in range(6):
        # Trendphasen von je 120 Tagen mit wechselnder Richtung
        r = []
        for block in range(n // 120 + 1):
            richtung = 1 if (block + j) % 2 == 0 else -1
            r.extend(rng.normal(richtung * 0.004, 0.006, 120))
        daten[f"T{j}"] = 100 * np.exp(np.cumsum(np.array(r[:n])))
    kurse = pd.DataFrame(daten, index=idx)

    sig = signale(kurse, rueckblick=60, halten=21)
    gew = gewichte(kurse, sig)
    k = kennzahlen(rendite_reihe(kurse, gew))
    print(f"    Trendmaerkte: Sharpe {k['Sharpe']:.2f}  pro Jahr {k['pro Jahr %']:.1f} %")
    assert k["Sharpe"] > 0.5, (
        f"Bei echten Trends muss Momentum verdienen, Sharpe war {k['Sharpe']}. "
        "Sonst ist der Rahmen kaputt und wuerde eine echte Kante uebersehen."
    )
    print("OK  echtes Momentum wird erkannt: der Rahmen findet eine Kante")


def test_reines_rauschen_bringt_nichts():
    """Bei reinem Rauschen darf keine Kante entstehen."""
    kurse = _kurse(n=1500, m=8, seed=11)
    sig = signale(kurse, rueckblick=60, halten=21)
    gew = gewichte(kurse, sig)
    k = kennzahlen(rendite_reihe(kurse, gew))
    print(f"    Rauschen: Sharpe {k['Sharpe']:.2f}  pro Jahr {k['pro Jahr %']:.1f} %")
    assert abs(k["Sharpe"]) < 1.0, "Bei Rauschen darf keine starke Kante erscheinen"
    print("OK  Rauschen bringt nichts: keine Scheinkante")


def test_kosten_wirken():
    """Mehr Kosten muessen das Ergebnis verschlechtern, sonst greifen sie nicht."""
    kurse = _kurse(n=1000, m=5, seed=7)
    sig = signale(kurse, rueckblick=60, halten=5)   # haeufig handeln
    gew = gewichte(kurse, sig)
    guenstig = kennzahlen(rendite_reihe(kurse, gew, kosten=0.0))["Gesamt %"]
    teuer = kennzahlen(rendite_reihe(kurse, gew, kosten=0.005))["Gesamt %"]
    print(f"    ohne Kosten {guenstig:7.1f} %   mit hohen Kosten {teuer:7.1f} %")
    assert teuer < guenstig, "Hoehere Kosten muessen das Ergebnis senken"
    print("OK  Kosten wirken")


def test_permutation_erkennt_zufall():
    """Bei Rauschen muss der Zufallstest hohe Werte liefern.

    Zusaetzlich wird der Umschlag geprueft: echte und Zufallsvariante
    muessen aehnlich oft handeln, sonst vergleicht man Kosten statt Signale.
    """
    kurse = _kurse(n=1500, m=8, seed=13)
    sig = signale(kurse, rueckblick=60, halten=21)
    gew = gewichte(kurse, sig)
    p = permutationstest(kurse, sig, gew, runden=60, halten=21)
    verhaeltnis = p["Umschlag Zufall"] / max(p["Umschlag echt"], 1e-9)
    print(f"    Rauschen: Zufall besser {p['Zufall besser %']:.1f} %")
    print(f"    Umschlag echt {p['Umschlag echt']:.1f} vs Zufall "
          f"{p['Umschlag Zufall']:.1f}  (Verhaeltnis {verhaeltnis:.2f})")
    assert 0.5 < verhaeltnis < 2.0, (
        f"Umschlag muss vergleichbar sein, Verhaeltnis war {verhaeltnis:.2f}. "
        "Sonst misst der Test Handelskosten statt Signalguete."
    )
    assert p["Zufall besser %"] > 10, (
        "Bei Rauschen muss Zufall oft mithalten, sonst ist der Test zu lasch"
    )
    print("OK  Permutationstest erkennt Zufall, bei gleichem Umschlag")


if __name__ == "__main__":
    print("=" * 74)
    print("SELBSTTEST DES PORTFOLIO-RAHMENS")
    print("=" * 74)
    test_kein_blick_in_die_zukunft()
    test_kosten_wirken()
    test_reines_rauschen_bringt_nichts()
    test_permutation_erkennt_zufall()
    test_echtes_momentum_wird_erkannt()
    print("=" * 74)
    print("Alle Tests bestanden. Der Rahmen rechnet ohne Zukunftsblick,")
    print("erkennt echte Trends und faellt bei Rauschen nicht darauf herein.")
    print("=" * 74)
