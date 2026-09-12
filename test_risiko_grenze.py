"""Sichert die Grenze von risiko.py ab: kein Netzwerk, auch nicht ueber Umwege.

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


def test_risiko_zieht_kein_netzwerkmodul_nach():
    gefunden = mitgezogene_module("risiko")
    assert not gefunden, (
        f"risiko.py zieht {sorted(gefunden)} nach - direkt oder ueber ein"
        " Modul, das es importiert. Damit waere die Rechnung nicht mehr ohne"
        " Broker pruefbar. Den neuen Import wieder herausnehmen."
    )
    print("OK  risiko.py zieht weder ctrader_open_api noch twisted nach")


def test_risiko_importiert_kein_projektmodul_mit_netzwerk():
    """Auch der Umweg ueber eigene Module ist gesperrt.

    Gegenprobe: Die Liste der eigenen Module darf nicht leer sein, sonst
    prueft die Schleife unten nichts.
    """
    mit_netzwerk = ("handel", "verbindung", "lade_ctrader", "lade_ctrader_voll")
    assert mit_netzwerk, "Ohne Vergleichsliste prueft dieser Test nichts"

    quelle = (WURZEL / "risiko.py").read_text(encoding="utf-8")
    for modul in mit_netzwerk:
        for zeile in quelle.splitlines():
            nackt = zeile.strip()
            if nackt.startswith(("import ", "from ")):
                assert f" {modul}" not in f" {nackt} ", (
                    f"risiko.py importiert {modul}: {nackt}"
                )
    print("OK  risiko.py importiert kein Projektmodul mit Netzwerkzugriff")


if __name__ == "__main__":
    test_die_messung_findet_netzwerkabhaengigkeiten()
    test_risiko_zieht_kein_netzwerkmodul_nach()
    test_risiko_importiert_kein_projektmodul_mit_netzwerk()
    print("\nDie Grenze von risiko.py haelt.")
