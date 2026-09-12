#!/usr/bin/env python3
"""pruefe_ctrader_mt5.py - Deckt sich cTrader mit MT5?

Vergleicht eine Datei aus data-ctrader/ mit derselben Datei aus data-mt5/
im gemeinsamen Zeitraum: Anzahl, Zeitstempel, Abweichungen in Open, High,
Low und Close.

Der Bericht mittelt Auffaelligkeiten NICHT weg. Ein sauberer Mittelwert bei
einem grossen Ausreisser ist genau die Art Zahl, die spaeter teuer wird.

Aufruf:

    .venv/bin/python pruefe_ctrader_mt5.py XAUUSD H_1
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

WURZEL = Path(__file__).resolve().parent
CTRADER_ORDNER = WURZEL / "data-ctrader"
MT5_ORDNER = WURZEL / "data-mt5"
PREISSPALTEN = ("Open", "High", "Low", "Close")

# Ab welchem Vielfachen der mittleren Abweichung ein Wert als Ausreisser gilt.
AUSREISSER_FAKTOR = 10
# Ab welchem Anteil der mittleren Abweichung ein Versatz als systematisch gilt.
VERSATZ_ANTEIL = 0.5
# Zwei Feeds desselben Marktes duerfen sich um Spread unterscheiden, nicht mehr.
# Darueber beschreiben die Reihen nicht mehr dieselben Kerzen.
PLAUSIBEL_PROZENT = 0.05
# In diesem Bereich wird nach einem Zeitversatz gesucht (volle Stunden).
VERSATZ_SUCHE = range(-12, 13)
# So viel besser muss ein verschobener Vergleich sein, damit der Versatz gilt.
VERSATZ_BESSER_FAKTOR = 5


def lade(ordner: Path, symbol: str, zeitrahmen: str) -> pd.DataFrame:
    pfad = ordner / f"{symbol}_{zeitrahmen}.csv"
    if not pfad.exists():
        vorhanden = sorted(p.stem for p in ordner.glob("*.csv"))
        raise SystemExit(
            f"Datei fehlt: {pfad}\nVorhanden in {ordner.name}: "
            f"{', '.join(vorhanden) or 'nichts'}"
        )
    df = pd.read_csv(pfad, index_col=0, parse_dates=True)
    # Zeitzone abstreifen, damit beide Indizes vergleichbar sind.
    if df.index.tz is not None:
        df.index = df.index.tz_localize(None)
    return df.sort_index()


def zeitstempel_vergleichen(ct: pd.DataFrame, mt5: pd.DataFrame) -> pd.DatetimeIndex:
    print("\n1. Anzahl und Zeitraum")
    print("-" * 70)
    print(f"   cTrader: {len(ct):5d} Kerzen  {ct.index.min()} bis {ct.index.max()}")
    print(f"   MT5:     {len(mt5):5d} Kerzen  {mt5.index.min()} bis {mt5.index.max()}")
    if len(ct) == len(mt5):
        print("   Gleiche Anzahl Kerzen im Zeitraum.")
    else:
        print(f"   ABWEICHUNG: {abs(len(ct) - len(mt5))} Kerzen Unterschied.")

    print("\n2. Zeitstempel")
    print("-" * 70)
    gemeinsam = ct.index.intersection(mt5.index)
    nur_ct = ct.index.difference(mt5.index)
    nur_mt5 = mt5.index.difference(ct.index)
    print(f"   Deckungsgleich: {len(gemeinsam)}")
    if len(nur_ct) == 0 and len(nur_mt5) == 0:
        print("   Die Zeitstempel sind vollstaendig deckungsgleich.")
    for name, fehlend in (("nur in cTrader", nur_ct), ("nur in MT5", nur_mt5)):
        if len(fehlend):
            beispiele = ", ".join(str(z) for z in fehlend[:5])
            print(f"   {len(fehlend):5d} {name}: {beispiele}"
                  f"{' ...' if len(fehlend) > 5 else ''}")
    if len(gemeinsam) == 0:
        stunden_ct = sorted(set(ct.index.hour))[:8]
        stunden_mt5 = sorted(set(mt5.index.hour))[:8]
        print(f"   Kein einziger gemeinsamer Zeitstempel."
              f"\n   Stunden cTrader: {stunden_ct}\n   Stunden MT5:     {stunden_mt5}"
              "\n   Das deutet auf einen Zeitzonenversatz hin, nicht auf Datenfehler.")
    return gemeinsam


def spalte_vergleichen(name: str, a: pd.Series, b: pd.Series) -> dict:
    differenz = a - b
    betrag = differenz.abs()
    relativ = betrag / b.abs() * 100
    schlimmster = betrag.idxmax()
    return {
        "spalte": name,
        "mittel": betrag.mean(),
        "mittel_prozent": relativ.mean(),
        "max": betrag.max(),
        "max_prozent": relativ.max(),
        "max_zeit": schlimmster,
        "ct_wert": a[schlimmster],
        "mt5_wert": b[schlimmster],
        "versatz": differenz.mean(),
        "betraege": betrag,
    }


def abweichungen_zeigen(ct: pd.DataFrame, mt5: pd.DataFrame, gemeinsam) -> list:
    print("\n3. Abweichungen in den gemeinsamen Kerzen")
    print("-" * 70)
    if len(gemeinsam) == 0:
        print("   Nicht moeglich - keine gemeinsamen Zeitstempel.")
        return []

    print(f"   {'Spalte':<7}{'Mittel':>12}{'Mittel %':>11}"
          f"{'Maximum':>12}{'Max %':>10}   schlimmste Kerze")
    ergebnisse = []
    for spalte in PREISSPALTEN:
        ergebnis = spalte_vergleichen(
            spalte, ct.loc[gemeinsam, spalte], mt5.loc[gemeinsam, spalte]
        )
        ergebnisse.append(ergebnis)
        print(f"   {spalte:<7}{ergebnis['mittel']:>12.5f}"
              f"{ergebnis['mittel_prozent']:>10.4f}%"
              f"{ergebnis['max']:>12.5f}{ergebnis['max_prozent']:>9.4f}%"
              f"   {ergebnis['max_zeit']}")
    return ergebnisse


def auffaelligkeiten_benennen(ergebnisse: list) -> None:
    print("\n4. Auffaelligkeiten")
    print("-" * 70)
    etwas_gefunden = False

    for ergebnis in ergebnisse:
        spalte = ergebnis["spalte"]
        betraege = ergebnis["betraege"]
        mittel = ergebnis["mittel"]

        # Systematischer Versatz: alle Werte zeigen in dieselbe Richtung.
        if mittel > 0 and abs(ergebnis["versatz"]) > VERSATZ_ANTEIL * mittel:
            richtung = "hoeher" if ergebnis["versatz"] > 0 else "niedriger"
            print(f"   {spalte}: systematischer Versatz, cTrader liegt im Mittel"
                  f" {abs(ergebnis['versatz']):.5f} {richtung} als MT5."
                  "\n      Typische Ursache: unterschiedliche Notierung"
                  " (Bid gegen Mid) oder abweichender Broker-Feed.")
            etwas_gefunden = True

        # Einzelne Ausreisser, die den Mittelwert nicht verraet.
        grenze = AUSREISSER_FAKTOR * mittel
        ausreisser = betraege[betraege > grenze] if mittel > 0 else betraege[[]]
        if len(ausreisser):
            print(f"   {spalte}: {len(ausreisser)} Kerze(n) weichen mehr als"
                  f" das {AUSREISSER_FAKTOR}-fache des Mittels ab"
                  f" (> {grenze:.5f}):")
            for zeit, wert in ausreisser.sort_values(ascending=False)[:5].items():
                print(f"      {zeit}  Abweichung {wert:.5f}")
            etwas_gefunden = True

    if not etwas_gefunden:
        # Bewusst KEINE Entwarnung: dieser Abschnitt sieht nur die Verteilung,
        # nicht die Groessenordnung. Ob die ueberhaupt stimmt, klaert Punkt 5.
        print("   Keine einzelnen Ausreisser, kein systematischer Versatz."
              "\n   Das sagt nichts ueber die Groesse der Abweichung - siehe Punkt 5.")


def versatz_suchen(ct: pd.DataFrame, mt5: pd.DataFrame) -> list:
    """Probiert stundenweise Verschiebungen durch.

    Passt die Anzahl der Kerzen, aber die Preise weichen weit ab, liegt das
    fast immer an der Zeitzone einer Quelle - nicht an schlechten Daten.
    """
    funde = []
    for stunden in VERSATZ_SUCHE:
        verschoben = ct.copy()
        verschoben.index = verschoben.index + pd.Timedelta(hours=stunden)
        gemeinsam = verschoben.index.intersection(mt5.index)
        if len(gemeinsam) < len(ct) // 2:
            continue
        abweichung = (
            verschoben.loc[gemeinsam, "Close"] - mt5.loc[gemeinsam, "Close"]
        ).abs()
        funde.append({
            "stunden": stunden,
            "treffer": len(gemeinsam),
            "mittel": abweichung.mean(),
        })
    return sorted(funde, key=lambda fund: fund["mittel"])


def plausibilitaet_pruefen(ct, mt5, ergebnisse: list) -> int | None:
    """Ist die Abweichung zu gross fuer denselben Markt? Dann Ursache suchen."""
    print("\n5. Plausibilitaet")
    print("-" * 70)
    schlimmste = max(ergebnis["mittel_prozent"] for ergebnis in ergebnisse)
    if schlimmste <= PLAUSIBEL_PROZENT:
        print(f"   Groesste mittlere Abweichung {schlimmste:.4f} % liegt unter"
              f" {PLAUSIBEL_PROZENT} % - das ist Spread-Groessenordnung.")
        return None

    print(f"   WARNUNG: Groesste mittlere Abweichung {schlimmste:.4f} % liegt"
          f" ueber {PLAUSIBEL_PROZENT} %.")
    print("   Fuer denselben Markt aus zwei Quellen ist das zu viel. Das sind"
          "\n   keine Preisunterschiede, sondern verschiedene Kerzen.")
    print("   Suche nach einem Zeitversatz ...")

    funde = versatz_suchen(ct, mt5)
    if not funde:
        print("   Kein Versatz zwischen -12 h und +12 h bringt genug Treffer.")
        return None

    bester = funde[0]
    ohne_versatz = next((f for f in funde if f["stunden"] == 0), None)
    print(f"   {'Versatz':>8}{'Treffer':>10}{'Abweichung Close':>20}")
    for fund in funde[:3]:
        print(f"   {fund['stunden']:>+7d}h{fund['treffer']:>10d}"
              f"{fund['mittel']:>20.5f}")

    if bester["stunden"] == 0:
        print("   Der beste Wert liegt bei 0 h - der Versatz erklaert es nicht.")
        return None
    if ohne_versatz and bester["mittel"] * VERSATZ_BESSER_FAKTOR > ohne_versatz["mittel"]:
        print("   Kein Versatz ist deutlich besser als 0 h - Ursache offen.")
        return None

    print(f"\n   BEFUND: Die Reihen sind um {bester['stunden']:+d} Stunden"
          " gegeneinander verschoben.")
    print(f"   Mit dieser Verschiebung passen {bester['treffer']} Zeitstempel"
          f" und die Abweichung faellt auf {bester['mittel']:.5f}.")
    print("   cTrader liefert utcTimestampInMinutes, also echtes UTC."
          "\n   Damit traegt die MT5-Datei Serverzeit, ist aber als UTC"
          " beschriftet.")
    return bester["stunden"]


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 1
    symbol, zeitrahmen = sys.argv[1].upper(), sys.argv[2]

    ct = lade(CTRADER_ORDNER, symbol, zeitrahmen)
    mt5_voll = lade(MT5_ORDNER, symbol, zeitrahmen)
    # Grosszuegig beschneiden - ein Zeitversatz braucht Rand zum Vergleichen.
    rand = pd.Timedelta(days=1)
    mt5 = mt5_voll.loc[ct.index.min() - rand:ct.index.max() + rand]

    print("=" * 70)
    print(f"Vergleich cTrader gegen MT5 - {symbol} {zeitrahmen}")
    print("=" * 70)

    im_zeitraum = mt5.loc[ct.index.min():ct.index.max()]
    gemeinsam = zeitstempel_vergleichen(ct, im_zeitraum)
    ergebnisse = abweichungen_zeigen(ct, im_zeitraum, gemeinsam)
    if not ergebnisse:
        return 1
    auffaelligkeiten_benennen(ergebnisse)

    versatz = plausibilitaet_pruefen(ct, mt5, ergebnisse)
    if versatz is None:
        return 0

    print("\n" + "=" * 70)
    print(f"Gleicher Vergleich, cTrader um {versatz:+d} Stunden verschoben")
    print("=" * 70)
    berichtigt = ct.copy()
    berichtigt.index = berichtigt.index + pd.Timedelta(hours=versatz)
    gemeinsam = zeitstempel_vergleichen(berichtigt, mt5.loc[
        berichtigt.index.min():berichtigt.index.max()])
    ergebnisse = abweichungen_zeigen(berichtigt, mt5, gemeinsam)
    if ergebnisse:
        auffaelligkeiten_benennen(ergebnisse)
    return 0


if __name__ == "__main__":
    sys.exit(main())
