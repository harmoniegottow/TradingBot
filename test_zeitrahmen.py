"""Tests fuer die Zeitrahmen-Pruefung der Strategie-Bausteine.

Ohne Netzwerk. Die Daten werden hier gebaut, nicht geladen - so laesst sich
auch der Fall pruefen, den es in data-ctrader/ gar nicht geben soll: eine
Datei mit falschem Namen.

ABSICHERUNG: Jeder Test, der einen Abbruch belegt, zeigt vorher, dass
derselbe Aufruf mit passenden Daten durchlaeuft.
"""
import tempfile
from datetime import timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from strategien.divergenz_gold_silber import ZEITRAHMEN, divergenz_vorbereiten
from strategien.zeitrahmen import (
    MINUTEN,
    VERMERK_FEHLT,
    VERMERK_UNGEPRUEFT,
    angabe_von,
    spaltenwert,
    vermerk,
    referenz_pruefen,
    ZeitrahmenFehler,
    Zeitrahmenangabe,
    abstand_messen,
    kuerzel_zu,
    ungeprueft,
    zeitrahmen_pruefen,
)

ANZAHL = 400


def reihe(minuten: int, anzahl: int = ANZAHL, start="2026-01-01") -> pd.DataFrame:
    zeit = pd.date_range(start, periods=anzahl, freq=f"{minuten}min")
    werte = 2000 + np.sin(np.arange(anzahl) / 7.0) * 40
    return pd.DataFrame(
        {"Open": werte, "High": werte * 1.001, "Low": werte * 0.999,
         "Close": werte, "Volume": np.full(anzahl, 1000)}, index=zeit)


def test_abstand_wird_aus_den_daten_gemessen():
    for kuerzel, minuten in (("H_1", 60), ("H_4", 240), ("D_1", 1440),
                             ("M_15", 15)):
        gemessen = abstand_messen(reihe(minuten).index)
        assert gemessen == timedelta(minutes=minuten), (kuerzel, gemessen)
        assert kuerzel_zu(gemessen) == kuerzel
    print("OK  Der Kerzenabstand wird aus den Daten gemessen")


def test_wochenendluecken_verziehen_die_messung_nicht():
    """Gegenprobe: Ohne Luecken MUSS dasselbe herauskommen."""
    ohne = reihe(240)
    assert abstand_messen(ohne.index) == timedelta(hours=4)

    # Jede zwanzigste Kerze entfernen - wie ein Wochenende.
    mit_luecken = ohne.drop(ohne.index[::20])
    assert len(mit_luecken) < len(ohne), "Es wurde gar nichts entfernt"
    assert abstand_messen(mit_luecken.index) == timedelta(hours=4), (
        "Die Luecken haben die Messung verzogen"
    )
    print("OK  Luecken verziehen die Messung nicht (haeufigster Abstand)")


def test_passende_daten_laufen_durch():
    gold, silber = reihe(240), reihe(240)
    kombi = divergenz_vorbereiten(gold, silber)
    assert "DivSignal" in kombi.columns
    assert len(kombi) == len(gold)
    print("OK  H4-Daten laufen durch den H4-Baustein")


def test_h1_daten_am_h4_baustein_brechen_ab():
    """Gegenprobe: Mit H4 MUSS derselbe Aufruf durchlaufen."""
    assert ZEITRAHMEN.kuerzel == "H_4", ZEITRAHMEN
    divergenz_vorbereiten(reihe(240), reihe(240))  # muss gehen

    try:
        divergenz_vorbereiten(reihe(60), reihe(60))
        assert False, "haette ZeitrahmenFehler werfen muessen"
    except ZeitrahmenFehler as fehler:
        text = str(fehler)
        assert "H_1" in text and "H_4" in text, text
        assert "Abbruch" in text, text
        assert "Divergenz Gold" in text, text
    print("OK  H1-Daten am H4-Baustein brechen ab")


def test_feinere_referenz_ist_zulaessig():
    """Silber darf feiner sein - es wird ohnehin auf den Gold-Index gelegt.

    Gegenprobe: Die GROEBERE Reihe unten MUSS abbrechen, sonst prueft diese
    Unterscheidung nichts.
    """
    assert referenz_pruefen(reihe(60).index, ZEITRAHMEN, "Test") is not None
    kombi = divergenz_vorbereiten(reihe(240), reihe(60, anzahl=ANZAHL * 4))
    assert "DivSignal" in kombi.columns
    print("OK  Feinere Referenzreihe ist zulaessig")


def test_groebere_referenz_bricht_ab():
    """Ein Tageskurs ueber sechs H4-Kerzen fortzuschreiben ist ein Fehler."""
    try:
        divergenz_vorbereiten(reihe(240), reihe(1440))
        assert False, "haette ZeitrahmenFehler werfen muessen"
    except ZeitrahmenFehler as fehler:
        text = str(fehler)
        assert "Divergenz Silber" in text, text
        assert "GROEBER" in text, text
        assert "Feiner waere" in text, text
    print("OK  Groebere Referenzreihe bricht ab")


def test_falsch_benannte_datei_wird_am_inhalt_erkannt():
    """Der Kern: Der Name luegt, der Inhalt nicht.

    Gegenprobe: Dieselbe Datei mit richtigem Inhalt MUSS durchlaufen -
    sonst belegte der Abbruch nur, dass CSV-Lesen scheitert.
    """
    with tempfile.TemporaryDirectory() as ordner:
        echt = Path(ordner) / "XAUUSD_H_4.csv"
        reihe(240).to_csv(echt, index_label="Zeit")
        geladen = pd.read_csv(echt, index_col=0, parse_dates=True)
        divergenz_vorbereiten(geladen, geladen)  # muss gehen

        # Derselbe Dateiname, aber H1-Inhalt.
        gelogen = Path(ordner) / "XAUUSD_H_4.csv"
        reihe(60).to_csv(gelogen, index_label="Zeit")
        falsch = pd.read_csv(gelogen, index_col=0, parse_dates=True)

        try:
            divergenz_vorbereiten(falsch, falsch)
            assert False, "Die falsch benannte Datei ist durchgerutscht"
        except ZeitrahmenFehler as fehler:
            assert "gemessen" in str(fehler).lower(), str(fehler)
    print("OK  Falsch benannte Datei wird am Inhalt erkannt, nicht am Namen")


def test_ungeprueft_bricht_nicht_ab():
    """Ohne Beleg wird nichts geprueft - eine geratene Angabe waere schlimmer."""
    angabe = ungeprueft("kein Beleg vorhanden")
    assert not angabe.belegt
    assert zeitrahmen_pruefen(reihe(60).index, angabe, "Test") is None
    assert zeitrahmen_pruefen(reihe(240).index, angabe, "Test") is None
    print("OK  Ungeprueft: es wird nichts geprueft und nichts behauptet")


def test_zu_wenige_kerzen_werden_gemeldet():
    """Gegenprobe: Mit genug Kerzen MUSS es gehen."""
    angabe = Zeitrahmenangabe("H_4", "Test")
    zeitrahmen_pruefen(reihe(240, anzahl=50).index, angabe)

    try:
        zeitrahmen_pruefen(reihe(240, anzahl=5).index, angabe)
        assert False, "haette ZeitrahmenFehler werfen muessen"
    except ZeitrahmenFehler as fehler:
        assert "reicht nicht" in str(fehler), str(fehler)
    print("OK  Zu wenige Kerzen werden gemeldet statt stillschweigend gemessen")


def test_jeder_baustein_hat_eine_angabe():
    """Kein Baustein darf die Angabe vergessen."""
    import importlib
    import pkgutil

    import strategien

    ohne = []
    geprueft = {}
    for modul in pkgutil.iter_modules(strategien.__path__):
        if modul.name in ("indikatoren", "zeitrahmen"):
            continue
        geladen = importlib.import_module(f"strategien.{modul.name}")
        angabe = getattr(geladen, "ZEITRAHMEN", None)
        if angabe is None:
            ohne.append(modul.name)
        else:
            geprueft[modul.name] = angabe

    assert not ohne, f"Ohne Zeitrahmenangabe: {ohne}"
    assert len(geprueft) >= 7, f"Nur {len(geprueft)} Bausteine gefunden"
    belegt = [n for n, a in geprueft.items() if a.belegt]
    assert belegt == ["divergenz_gold_silber"], (
        f"Belegt sind {belegt} - erwartet war nur die Divergenz."
    )
    print(f"OK  Alle {len(geprueft)} Bausteine haben eine Angabe,"
          f" belegt: {belegt}")


def test_ergebniszeile_kennzeichnet_ungeprueften_zeitrahmen():
    """Der Vermerk gehoert in die Zeile, in der die Zahl steht.

    Gegenprobe: Der BELEGTE Baustein darf dort keinen Vermerk tragen -
    sonst sagte die Kennzeichnung nichts aus.
    """
    from pruefstand import bewerte
    from strategien.ma_kreuzung import MaKreuzung

    gold, silber = reihe(240, anzahl=1200), reihe(240, anzahl=1200)
    kombi = divergenz_vorbereiten(gold, silber)

    from strategien.divergenz_gold_silber import DivergenzGoldSilber
    belegt = bewerte(kombi, DivergenzGoldSilber, mit_permutation=False)
    assert belegt["Zeitrahmen"] == "H_4", belegt["Zeitrahmen"]

    ohne = bewerte(kombi, MaKreuzung, mit_permutation=False)
    assert ohne["Zeitrahmen"] == "ungeprueft", ohne["Zeitrahmen"]
    print("OK  Jede Ergebniszeile nennt den Zeitrahmen oder 'ungeprueft'")


def test_vermerk_unterscheidet_die_drei_faelle():
    """belegt, ungeprueft, Angabe fehlt ganz - drei verschiedene Ausgaben."""
    from strategien.divergenz_gold_silber import DivergenzGoldSilber
    from strategien.ma_kreuzung import MaKreuzung

    class OhneAngabe:
        __module__ = "einmodulohnezeitrahmen"

    faelle = {
        "belegt": vermerk(angabe_von(DivergenzGoldSilber)),
        "ungeprueft": vermerk(angabe_von(MaKreuzung)),
        "fehlt": vermerk(angabe_von(OhneAngabe)),
    }
    assert faelle["belegt"] == "", faelle
    assert faelle["ungeprueft"] == VERMERK_UNGEPRUEFT, faelle
    assert faelle["fehlt"] == VERMERK_FEHLT, faelle
    assert len(set(faelle.values())) == 3, f"Faelle nicht unterscheidbar: {faelle}"
    assert spaltenwert(angabe_von(DivergenzGoldSilber)) == "H_4"
    assert spaltenwert(angabe_von(MaKreuzung)) == "ungeprueft"
    assert spaltenwert(angabe_von(OhneAngabe)) == "fehlt"
    print("OK  Vermerk unterscheidet belegt, ungeprueft und fehlende Angabe")


def test_vergleich_fuehrt_die_ungeprueften_auf():
    """Die Zusammenfassung unter der Tabelle nennt sie beim Namen."""
    import vergleich
    from strategien import REGISTRY

    assert "Zeitrahmen" in vergleich.SPALTEN, vergleich.SPALTEN
    ungeprueft = [n for n, k in REGISTRY.items() if vermerk(angabe_von(k))]
    assert ungeprueft, (
        "Kein einziger Baustein in der REGISTRY ist ungeprueft - dann prueft"
        " dieser Test die Auflistung gar nicht."
    )
    assert len(ungeprueft) == len(REGISTRY), (
        f"Belegt waere in der REGISTRY: {set(REGISTRY) - set(ungeprueft)}"
    )
    print(f"OK  vergleich.py fuehrt {len(ungeprueft)} ungepruefte Bausteine auf")


if __name__ == "__main__":
    for _name, _funktion in sorted(list(globals().items())):
        if _name.startswith("test_") and callable(_funktion):
            _funktion()
    print("\nAlle Tests fuer die Zeitrahmen-Pruefung bestanden.")
