"""Sichert die Grenze der reinen Module ab: kein Netzwerk, auch nicht ueber Umwege.

Geprueft werden risiko.py und ausfuehrung.py.

Warum als eigene Datei und in einem eigenen Prozess: In diesem Testlauf ist
handel.py meist schon geladen, und damit stuenden ctrader_open_api und
twisted ohnehin in sys.modules. Die Frage lautet aber, was ein FRISCHER
Interpreter beim Import von risiko.py mitzieht - also wird genau das
gemessen, in einem eigenen Prozess.

Der Test prueft ein AUSBLEIBEN ("risiko zieht nichts nach"). Damit das eine
Aussage ist, weist er vorher nach, dass er eine Netzwerkabhaengigkeit
ueberhaupt fiende - gemessen an handel.py, das sie hat.
"""
import subprocess
import sys
from pathlib import Path

WURZEL = Path(__file__).resolve().parent
VERBOTEN = ("ctrader_open_api", "twisted")
# Module, die ohne Netzwerk auskommen muessen.
REINE_MODULE = ("risiko", "ausfuehrung")

PROGRAMM = """
import sys
sys.path.insert(0, {wurzel!r})
import {modul}
treffer = sorted({{m.split('.')[0] for m in sys.modules
                  if m.split('.')[0] in {verboten!r}}})
print(','.join(treffer))
"""


def mitgezogene_module(modul: str) -> set:
    """Welche verbotenen Pakete zieht `import <modul>` nach sich?"""
    ergebnis = subprocess.run(
        [sys.executable, "-c", PROGRAMM.format(
            wurzel=str(WURZEL), modul=modul, verboten=VERBOTEN)],
        capture_output=True, text=True, timeout=120,
    )
    if ergebnis.returncode != 0:
        raise AssertionError(
            f"Import von {modul} scheiterte:\n{ergebnis.stderr.strip()}")
    ausgabe = ergebnis.stdout.strip()
    return set(ausgabe.split(",")) if ausgabe else set()


def test_die_messung_findet_netzwerkabhaengigkeiten():
    """Positivkontrolle: An handel.py MUSS die Messung anschlagen.

    Ohne diesen Nachweis waere ein leeres Ergebnis bei risiko.py wertlos -
    es koennte auch heissen, dass die Messung gar nichts findet.
    """
    gefunden = mitgezogene_module("handel")
    assert gefunden == set(VERBOTEN), (
        f"Die Messung findet an handel.py nur {gefunden or 'nichts'}, erwartet"
        f" waren {set(VERBOTEN)}. Sie koennte eine zurueckgewanderte"
        " Abhaengigkeit in risiko.py nicht bemerken."
    )
    print(f"OK  Positivkontrolle: an handel.py gefunden {sorted(gefunden)}")


def test_reine_module_ziehen_kein_netzwerkmodul_nach():
    for modul in REINE_MODULE:
        gefunden = mitgezogene_module(modul)
        assert not gefunden, (
            f"{modul}.py zieht {sorted(gefunden)} nach - direkt oder ueber ein"
            " Modul, das es importiert. Damit waere die Rechnung nicht mehr"
            " ohne Broker pruefbar. Den neuen Import wieder herausnehmen."
        )
        print(f"OK  {modul}.py zieht weder ctrader_open_api noch twisted nach")


def test_ausfuehrung_darf_risiko_importieren_aber_nicht_umgekehrt():
    """Die Richtung muss stimmen, sonst entsteht ein Kreis.

    Gegenprobe: Der erwartete Import MUSS vorhanden sein - sonst pruefte der
    Test unten nur, dass zwei Dateien nichts voneinander wissen.
    """
    def importzeilen(datei: str) -> list:
        # Nur echte Importe zaehlen. Eine Erwaehnung im Docstring ist ein
        # Verweis fuer Lesende, kein Kreis - der erste Anlauf dieses Tests
        # ist genau daran gescheitert.
        return [z.strip() for z in (WURZEL / datei).read_text(
            encoding="utf-8").splitlines()
            if z.strip().startswith(("import ", "from "))]

    aus = importzeilen("ausfuehrung.py")
    ris = importzeilen("risiko.py")
    assert any(z.startswith("from risiko import") for z in aus), (
        "ausfuehrung.py importiert gar nicht aus risiko - die Richtung laesst"
        " sich dann nicht pruefen."
    )
    assert not any("ausfuehrung" in z for z in ris), (
        f"risiko.py importiert ausfuehrung - das waere ein Kreis: {ris}"
    )
    print("OK  ausfuehrung.py baut auf risiko.py auf, nicht umgekehrt")


def test_reine_module_importieren_kein_projektmodul_mit_netzwerk():
    """Auch der Umweg ueber eigene Module ist gesperrt.

    Gegenprobe: Die Liste der eigenen Module darf nicht leer sein, sonst
    prueft die Schleife unten nichts.
    """
    mit_netzwerk = ("handel", "verbindung", "lade_ctrader", "lade_ctrader_voll")
    assert mit_netzwerk, "Ohne Vergleichsliste prueft dieser Test nichts"

    for rein in REINE_MODULE:
        quelle = (WURZEL / f"{rein}.py").read_text(encoding="utf-8")
        for modul in mit_netzwerk:
            for zeile in quelle.splitlines():
                nackt = zeile.strip()
                if nackt.startswith(("import ", "from ")):
                    assert f" {modul}" not in f" {nackt} ", (
                        f"{rein}.py importiert {modul}: {nackt}"
                    )
        print(f"OK  {rein}.py importiert kein Projektmodul mit Netzwerkzugriff")


if __name__ == "__main__":
    test_die_messung_findet_netzwerkabhaengigkeiten()
    test_reine_module_ziehen_kein_netzwerkmodul_nach()
    test_ausfuehrung_darf_risiko_importieren_aber_nicht_umgekehrt()
    test_reine_module_importieren_kein_projektmodul_mit_netzwerk()
    print("\nDie Grenze von risiko.py haelt.")
