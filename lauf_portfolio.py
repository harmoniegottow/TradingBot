"""
lauf_portfolio.py — Der ehrliche Test: Momentum ueber viele Maerkte.

Vorgehen bewusst in dieser Reihenfolge, damit die Auswahl-Illusion nicht
zuschlaegt (siehe denkfehler_test.py: aus 50 Zufallsstrategien die beste
auszusuchen liefert Profitfaktor 2,3 aus reinem Rauschen):

  1. Die Aufteilung in Trainings- und Pruefzeitraum steht VORHER fest.
     Erste 60 % Training, letzte 40 % Pruefung. Einmal, nicht verschiebbar.
  2. Im Trainingszeitraum wird EIN Parametersatz gewaehlt. Wie viele
     Kandidaten getestet wurden, wird mitgeschrieben und ausgegeben.
  3. Erst danach laeuft dieser eine Satz auf dem Pruefzeitraum. Genau
     einmal. Dieses Ergebnis zaehlt, alles andere ist Suche.
  4. Der Zufallstest laeuft auf dem PRUEFzeitraum.

Aufruf: .venv/bin/python lauf_portfolio.py
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from portfolio import (
    KOSTEN_JE_WECHSEL,
    gewichte,
    kaufen_und_halten,
    kennzahlen,
    lade_kurse,
    permutationstest,
    rendite_reihe,
    signale,
)

TRAINING_ANTEIL = 0.60

# Kandidaten: bewusst klein gehalten. Jeder zusaetzliche Kandidat hebt die
# Huerde, die das Endergebnis schlagen muss.
KANDIDATEN = [
    (60, 21),    # 3 Monate Rueckblick, monatlich neu
    (120, 21),   # 6 Monate Rueckblick, monatlich neu
    (250, 21),   # 12 Monate Rueckblick, monatlich neu (naeher am Original)
    (120, 63),   # 6 Monate Rueckblick, quartalsweise
]


def bewerte(kurse, rueckblick, halten, kosten=KOSTEN_JE_WECHSEL):
    sig = signale(kurse, rueckblick, halten)
    gew = gewichte(kurse, sig)
    return kennzahlen(rendite_reihe(kurse, gew, kosten)), sig, gew


def main():
    kurse = lade_kurse()
    grenze = int(len(kurse) * TRAINING_ANTEIL)
    training = kurse.iloc[:grenze]
    pruefung = kurse.iloc[grenze:]

    print("=" * 86)
    print("PORTFOLIO-MOMENTUM  —  ein Mechanismus, viele Maerkte")
    print("=" * 86)
    print(f"Instrumente : {kurse.shape[1]}")
    print(f"Gesamt      : {kurse.index.min().date()} bis {kurse.index.max().date()}"
          f"  ({len(kurse)} Handelstage)")
    print(f"Training    : {training.index.min().date()} bis {training.index.max().date()}"
          f"  ({len(training)} Tage)")
    print(f"Pruefung    : {pruefung.index.min().date()} bis {pruefung.index.max().date()}"
          f"  ({len(pruefung)} Tage)  <- unangetastet")
    print(f"Kosten      : {KOSTEN_JE_WECHSEL*10000:.0f} Basispunkte je Positionswechsel")
    print("=" * 86)

    # ---- Schritt 1: Auswahl NUR im Training
    print("\nSCHRITT 1  Parameterwahl, ausschliesslich im Trainingszeitraum")
    print(f"  {'Rueckblick':>11s} {'Halten':>7s} {'Sharpe':>8s} {'pro Jahr %':>11s} {'Ruecklauf %':>12s}")
    ergebnisse = []
    for rb, hl in KANDIDATEN:
        k, _, _ = bewerte(training, rb, hl)
        if not k:
            continue
        print(f"  {rb:11d} {hl:7d} {k['Sharpe']:8.2f} {k['pro Jahr %']:11.2f} {k['Ruecklauf %']:12.1f}")
        ergebnisse.append((k["Sharpe"], rb, hl, k))
    if not ergebnisse:
        raise SystemExit("Keine Auswertung moeglich.")

    ergebnisse.sort(key=lambda x: -x[0])
    _, best_rb, best_hl, best_k = ergebnisse[0]
    print(f"\n  Gewaehlt: Rueckblick {best_rb} Tage, Neuausrichtung alle {best_hl} Tage")
    print(f"  Getestete Kandidaten: {len(ergebnisse)}")
    print(f"  ACHTUNG: dieses Trainingsergebnis (Sharpe {best_k['Sharpe']:.2f}) ist")
    print("  KEIN Beleg. Es ist das Ergebnis einer Suche und deshalb geschoent.")

    # ---- Schritt 2: genau ein Lauf auf unangetasteten Daten
    print("\n" + "-" * 86)
    print("SCHRITT 2  Der eine Lauf auf dem Pruefzeitraum (nie fuer Auswahl benutzt)")
    print("-" * 86)
    k_pruef, sig_p, gew_p = bewerte(pruefung, best_rb, best_hl)
    bnh = kaufen_und_halten(pruefung)

    zeilen = {
        "Momentum (gewaehlt)": k_pruef,
        "Kaufen und Halten": bnh,
    }
    tab = pd.DataFrame(zeilen).T
    with pd.option_context("display.width", 200, "display.max_columns", None):
        print(tab.to_string())

    # ---- Schritt 3: Zufallstest auf dem Pruefzeitraum
    print("\n" + "-" * 86)
    print("SCHRITT 3  Zufallstest auf dem Pruefzeitraum (300 Runden)")
    print("-" * 86)
    p = permutationstest(pruefung, sig_p, gew_p, runden=300, halten=best_hl)
    for schluessel, wert in p.items():
        print(f"  {schluessel:26s} {wert}")

    # ---- Schritt 3b: Verhalten in Krisen vs Aufwaertsphasen
    print("\n" + "-" * 86)
    print("SCHRITT 3b  Wann verdient der Mechanismus? (ganzer Zeitraum)")
    print("-" * 86)
    print("Momentum soll klassisch in Krisen verdienen, wenn Halten verliert.")
    print("Genau das ist mit nur 5 Jahren Historie nicht pruefbar gewesen.\n")

    sig_all = signale(kurse, best_rb, best_hl)
    gew_all = gewichte(kurse, sig_all)
    r_mom = rendite_reihe(kurse, gew_all)
    r_bnh = kurse.pct_change(fill_method=None).fillna(0.0).mean(axis=1)

    print(f"  {'Jahr':6s} {'Momentum %':>11s} {'Halten %':>10s} {'Differenz':>10s}")
    for jahr, gruppe in r_mom.groupby(r_mom.index.year):
        m = float((1 + gruppe).prod() - 1) * 100
        b = float((1 + r_bnh.loc[gruppe.index]).prod() - 1) * 100
        marke = "  <- Halten verliert" if b < 0 else ""
        print(f"  {jahr:6d} {m:11.1f} {b:10.1f} {m - b:10.1f}{marke}")

    krise = r_bnh.groupby(r_bnh.index.year).apply(lambda g: (1 + g).prod() - 1) < 0
    krisenjahre = [int(j) for j, ist in krise.items() if ist]
    if krisenjahre:
        maske = r_mom.index.year.isin(krisenjahre)
        km = float((1 + r_mom[maske]).prod() - 1) * 100
        kb = float((1 + r_bnh[maske]).prod() - 1) * 100
        print(f"\n  Nur Jahre, in denen Halten verlor ({', '.join(map(str, krisenjahre))}):")
        print(f"    Momentum {km:+.1f} %   Halten {kb:+.1f} %")
        if km > kb:
            print("    -> Der Mechanismus federt genau dort ab, wo Halten wehtut.")
        else:
            print("    -> Auch in Krisenjahren kein Vorteil. Das ist ein Ausschlusskriterium.")

    # ---- Urteil
    print("\n" + "=" * 86)
    print("URTEIL")
    print("=" * 86)
    zufall = p.get("Zufall besser %", float("nan"))
    sharpe = k_pruef.get("Sharpe", float("nan"))
    umschlag_ok = (
        0.5 < p.get("Umschlag Zufall", 0) / max(p.get("Umschlag echt", 1e-9), 1e-9) < 2.0
    )

    befunde = []
    befunde.append(("Sharpe im Pruefzeitraum positiv", sharpe > 0))
    befunde.append((f"schlaegt Zufall (unter 20 %): {zufall} %", zufall < 20))
    befunde.append((
        f"besser als Kaufen und Halten ({bnh.get('pro Jahr %')} % pro Jahr)",
        k_pruef.get("pro Jahr %", -99) > bnh.get("pro Jahr %", 99),
    ))
    befunde.append(("Umschlag im Zufallstest vergleichbar", umschlag_ok))

    for text, ok in befunde:
        print(f"  [{'JA ' if ok else 'NEIN'}]  {text}")

    if all(ok for _, ok in befunde):
        print("\n  Alle Pruefungen bestanden. Das ist noch KEIN Freifahrtschein,")
        print("  aber der erste Ansatz, der es bis hierhin geschafft hat.")
        print("  Naechster Schritt waere eine lange Demo-Phase, kein Echtgeld.")
    else:
        print("\n  Nicht bestanden. Kein Echtgeld, und jetzt NICHT die Parameter")
        print("  drehen, bis der Pruefzeitraum passt - damit wird er verbrannt")
        print("  und ist als unabhaengiger Test fuer immer wertlos.")
    print("=" * 86)


if __name__ == "__main__":
    main()
