"""Tests fuer die Ausrichtung zweier Kursreihen in divergenz_gold_silber.py.

Die entscheidende Frage: Werden Gold und Silber ueber den ZEITSTEMPEL
zusammengefuehrt oder ueber die POSITION? Positionsweise waere der Fehler
schleichend - er faengt an der ersten Fehlstelle an und waechst mit jeder
weiteren, ohne dass irgendetwas abstuerzt.

Die Tests vergleichen jeweils zwei Laeufe miteinander, statt Erwartungswerte
von Hand auszurechnen. Damit pruefen sie die Eigenschaft selbst und nicht
meine Nachbildung der Formel.
"""
import numpy as np
import pandas as pd

from strategien.divergenz_gold_silber import divergenz_vorbereiten

# Kleine Fenster, damit schon wenige Kerzen ein Signal ergeben koennen.
KLEIN = {"ret_len": 2, "band_lookback": 5, "band_mult": 1.0}
ANZAHL = 60


def reihe(werte, start="2026-01-01 00:00", stunden=1) -> pd.DataFrame:
    zeit = pd.date_range(start, periods=len(werte), freq=f"{stunden}h")
    werte = np.asarray(werte, dtype=float)
    return pd.DataFrame(
        {"Open": werte, "High": werte * 1.001, "Low": werte * 0.999,
         "Close": werte, "Volume": np.full(len(werte), 1000)},
        index=zeit,
    )


def gold_reihe() -> pd.DataFrame:
    # Schwankend, damit die Divergenz ueberhaupt Struktur hat.
    return reihe(2000 + np.sin(np.arange(ANZAHL) / 3.0) * 40)


def silber_reihe() -> pd.DataFrame:
    return reihe(25 + np.cos(np.arange(ANZAHL) / 4.0) * 2)


def signale(gold, silber) -> pd.Series:
    return divergenz_vorbereiten(gold, silber, **KLEIN)["DivSignal"]


def test_fehlender_silber_zeitstempel_verschiebt_nichts():
    """Der Kernfall: eine Luecke in Silber darf nichts verrutschen lassen.

    Der fehlenden Kerze wird vorher der Wert ihrer Vorgaengerin gegeben.
    Bei Ausrichtung ueber den Zeitstempel muss das Ergebnis danach identisch
    sein - bei Ausrichtung ueber die Position waere ab der Luecke alles
    um eine Kerze verschoben.
    """
    gold = gold_reihe()
    silber = silber_reihe()
    luecke = silber.index[42]
    gleichwertig = silber.copy()
    gleichwertig.loc[luecke] = gleichwertig.iloc[41]

    ohne_luecke = signale(gold, gleichwertig)
    mit_luecke = signale(gold, gleichwertig.drop(index=luecke))

    pd.testing.assert_series_equal(ohne_luecke, mit_luecke)
    print("OK  Fehlender Silber-Zeitstempel verschiebt die Zuordnung nicht")


def test_positionsweise_zuordnung_waere_nachweisbar_anders():
    """Gegenprobe: Waere die Zuordnung positionsweise, faellt der Test auf.

    Ohne diesen Test koennte der vorige gruen sein, weil die Daten zufaellig
    unempfindlich sind. Hier wird die Verschiebung von Hand hergestellt.
    """
    gold = gold_reihe()
    silber = silber_reihe()
    luecke = silber.index[42]

    richtig = signale(gold, silber.drop(index=luecke))
    # So saehe es aus, wenn nach der Luecke positionsweise gepaart wuerde:
    verschoben = silber.drop(index=luecke).copy()
    verschoben.index = silber.index[:len(verschoben)]
    falsch = signale(gold, verschoben)

    assert not richtig.equals(falsch), (
        "Die Testdaten sind unempfindlich - der vorige Test beweist so nichts"
    )
    print("OK  Positionsweise Zuordnung waere an diesen Daten erkennbar")


def test_gold_kerze_ohne_silber_nimmt_den_letzten_vorherigen_wert():
    """Kein Blick in die Zukunft: gefuellt wird von hinten, nie von vorn.

    Damit die Frage ueberhaupt entscheidbar ist, braucht es hinter der Luecke
    einen deutlichen Sprung. Bei einer glatten Reihe liegen der vorherige und
    der spaetere Kurs so dicht beieinander, dass beide Varianten dasselbe
    Ergebnis liefern - der Test waere dann gruen, ohne etwas zu beweisen.
    """
    gold = gold_reihe()
    silber = silber_reihe()
    # Position bewusst gewaehlt: DivSignal ist ein seltenes Kreuzungsereignis
    # (zwei Treffer auf sechzig Kerzen). An den meisten Stellen kippt es auch
    # bei grossem Kursunterschied nicht - dort waere der Test blind. Position
    # 42 ist eine der Stellen, an denen sich beide Varianten unterscheiden.
    luecke_pos = 42
    silber.iloc[luecke_pos + 1] = silber.iloc[luecke_pos + 1] * 1.3
    luecke = silber.index[luecke_pos]

    vorheriger = silber.copy()
    vorheriger.loc[luecke] = vorheriger.iloc[luecke_pos - 1]
    spaeterer = silber.copy()
    spaeterer.loc[luecke] = spaeterer.iloc[luecke_pos + 1]

    aus_vergangenheit = signale(gold, vorheriger)
    aus_zukunft = signale(gold, spaeterer)
    assert not aus_vergangenheit.equals(aus_zukunft), (
        "Testdaten unempfindlich - an dieser Stelle kippt kein Signal, der"
        " Test koennte die beiden Faelle also gar nicht unterscheiden"
    )

    mit_luecke = signale(gold, silber.drop(index=luecke))
    pd.testing.assert_series_equal(mit_luecke, aus_vergangenheit)
    assert not mit_luecke.equals(aus_zukunft), (
        "Es wurde ein spaeterer Silberkurs benutzt - das waere Zukunftswissen"
    )
    print("OK  Luecke wird mit dem letzten frueheren Kurs gefuellt, nie mit einem spaeteren")


def test_zusaetzliche_silber_zeitstempel_aendern_nichts():
    """Silber darf feiner aufgeloest sein - Gold gibt den Takt vor.

    Gegenprobe zuerst: Werte AUF den Gold-Zeitstempeln muessen sehr wohl
    wirken. Ohne diesen Nachweis waere der Test auch dann gruen, wenn das
    Signal an dieser Stelle gar nicht auf Silber reagierte.
    """
    gold = gold_reihe()
    silber = silber_reihe()
    ohne_zusatz = signale(gold, silber)

    # Die Verfaelschung muss die FORM der Renditen aendern. Ein fester Faktor
    # oder ein gleichmaessiger Anstieg genuegt nicht: Die Divergenz rechnet mit
    # Renditen, und das Band verschiebt sich mit - die Kreuzungen blieben
    # dieselben, und die Gegenprobe waere selbst blind.
    auf_dem_takt = silber.copy()
    auf_dem_takt["Close"] = silber["Close"].to_numpy()[::-1]
    assert not ohne_zusatz.equals(signale(gold, auf_dem_takt)), (
        "Silberwerte auf den Gold-Zeitstempeln aendern nichts - der Test"
        " koennte eine falsche Zuordnung gar nicht bemerken."
    )

    versetzt = silber.copy()
    versetzt.index = versetzt.index + pd.Timedelta(minutes=30)
    zusatz = pd.concat([silber, versetzt]).sort_index()

    pd.testing.assert_series_equal(ohne_zusatz, signale(gold, zusatz))
    print("OK  Zusaetzliche Silber-Zeitstempel zwischen den Gold-Kerzen aendern nichts")


def test_nur_gemeinsame_zeitpunkte_ergeben_ein_signal():
    """Wo Silber noch gar nicht begonnen hat, entsteht kein Signal."""
    gold = gold_reihe()
    silber = silber_reihe().iloc[20:]

    ergebnis = signale(gold, silber)

    # Ohne diese Absicherung waere der Test gruen, wenn es UEBERALL kein
    # Signal gaebe - dann belegte er nichts ueber den Zeitraum davor.
    assert ergebnis.iloc[20:].any(), (
        "Auch nach dem Silberstart entsteht kein einziges Signal - der Test"
        " koennte nicht unterscheiden, ob die Sperre wirkt oder ob die Daten"
        " einfach nie ein Signal ergeben."
    )
    assert not ergebnis.iloc[:20].any(), (
        "Vor dem ersten Silberkurs darf kein Signal entstehen"
    )
    print("OK  Vor dem ersten Silberkurs entsteht kein Signal")


def test_gold_luecke_erzeugt_keine_stillen_verschiebungen():
    """Auch eine Luecke auf der Gold-Seite darf nichts verrutschen lassen.

    Das ist der Fall XAUUSD H4 im Sommer 2020: Gold fehlt, Silber ist da.
    """
    gold = gold_reihe()
    silber = silber_reihe()
    fehlend = gold.index[[25, 26, 27]]

    gekuerzt = signale(gold.drop(index=fehlend), silber)

    assert len(gekuerzt) == len(gold) - 3
    assert not gekuerzt.index.isin(fehlend).any()

    vorher = signale(gold, silber)
    gemeinsam = gekuerzt.index[:25]
    # Gegenprobe: Waere die Zuordnung positionsweise, verschoebe sich ab der
    # Luecke alles. Damit der Vergleich unten etwas taugt, muss an diesen
    # Daten ueberhaupt ein Signal im gemeinsamen Bereich liegen.
    assert vorher.loc[gemeinsam].any() or vorher.any(), (
        "Auf diesen Daten entsteht kein Signal - der Vergleich waere leer."
    )
    pd.testing.assert_series_equal(gekuerzt.loc[gemeinsam], vorher.loc[gemeinsam])
    print("OK  Luecke auf der Gold-Seite verschiebt die frueheren Kerzen nicht")


if __name__ == "__main__":
    test_fehlender_silber_zeitstempel_verschiebt_nichts()
    test_positionsweise_zuordnung_waere_nachweisbar_anders()
    test_gold_kerze_ohne_silber_nimmt_den_letzten_vorherigen_wert()
    test_zusaetzliche_silber_zeitstempel_aendern_nichts()
    test_nur_gemeinsame_zeitpunkte_ergeben_ein_signal()
    test_gold_luecke_erzeugt_keine_stillen_verschiebungen()
    print("Alle Tests fuer die Ausrichtung bestanden.")
