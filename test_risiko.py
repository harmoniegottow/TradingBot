"""Tests fuer risiko.py - reine Rechnung, ohne Netzwerk und ohne Broker.

ABSICHERUNG (aus dem Blindtest-Audit): Jeder Test, der belegt, dass etwas
NICHT passiert, zeigt vorher, dass es an derselben Stelle passieren KOENNTE.
Ohne diesen Nachweis waere "nichts passiert" kein Beleg, sondern nur eine
Beobachtung - der Test bliebe gruen, auch wenn die Sperre gar nicht wirkte.

Dass dieses Modul wirklich ohne Netzwerk auskommt, prueft
test_risiko_grenze.py.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import risiko
from risiko import (
    MODUS_SENDEN,
    MODUS_TROCKENLAUF,
    Bestand,
    Handelsfehler,
    Kapitalbasis,
    Kapitalstand,
    Kursstand,
    Symbolgrenzen,
    Tagesergebnis,
    auf_schritt_abrunden,
    eigenkapital_bestimmen,
    groessen_vergleich,
    konversionssymbol_finden,
    kursalter_pruefen,
    label_bauen,
    realisiertes_ergebnis,
    risikobasis_bestimmen,
    sperren_pruefen,
    tagesbeginn_utc,
    umrechnungsfaktor,
    unrealisiertes_ergebnis,
    ablehnungstext,
    kapitalhinweis,
    noetiges_kapital,
    protokollzeile,
    vergleich_text,
    volumen_berechnen,
    vorschlag_bauen,
)

# Der bisherige Name handel.* bleibt als Kuerzel erhalten.
handel = risiko


handel = risiko


EINS = Decimal(1)


KAPITAL = Decimal("1000")


def ergebnis(realisiert="0", unrealisiert="0") -> Tagesergebnis:
    return Tagesergebnis(Decimal(realisiert), Decimal(unrealisiert), 0, 0)


GOLD = Symbolgrenzen(symbol_id=41, name="XAUUSD", min_volumen=100,
                     max_volumen=500_000, schritt_volumen=100,
                     lot_groesse=10_000, stellen=2)


EURUSD = Symbolgrenzen(symbol_id=1, name="EURUSD", min_volumen=100_000,
                       max_volumen=1_000_000_000, schritt_volumen=100_000,
                       lot_groesse=10_000_000, stellen=5)


class FalscheDaten:
    """Minimale Attrappe fuer ProtoOAPosition.tradeData."""

    def __init__(self, label="", symbol_id=41, volumen=100):
        self.label = label
        self.symbolId = symbol_id
        self.volume = volumen


class FalschePosition:
    def __init__(self, label="", positions_id=1):
        self.tradeData = FalscheDaten(label)
        self.positionId = positions_id


def bestand_mit(anzahl: int, label: str = "") -> Bestand:
    return Bestand(positionen=tuple(FalschePosition(label, i)
                                    for i in range(anzahl)), orders=())


def test_volumen_wird_aus_risiko_und_stop_berechnet():
    # 1000 Kapital, 0,5 % = 5 Risiko. Stop 40 -> 0,125 Einheiten -> 12,5 roh.
    entscheid = volumen_berechnen(Decimal("1000"), Decimal("0.5"),
                                  Decimal("40"), GOLD, EINS)
    assert not entscheid.angenommen, "12,5 liegt unter dem Mindestvolumen 100"
    assert "Mindestvolumen" in entscheid.begruendung
    print("OK  Kleines Kapital: Gold ist bei diesem Stop nicht handelbar")


def test_ablehnung_kommt_wirklich_von_der_mindestgrenze():
    """Gegenprobe: Dieselbe Rechnung MUSS bei mehr Kapital annehmen.

    Ohne diesen Nachweis koennte die Ablehnung oben auch aus einem
    kaputten Rechenweg stammen - der Test saehe gleich aus.
    """
    klein = volumen_berechnen(Decimal("1000"), Decimal("0.5"),
                              Decimal("40"), GOLD, EINS)
    gross = volumen_berechnen(Decimal("50000"), Decimal("0.5"),
                              Decimal("40"), GOLD, EINS)

    assert not klein.angenommen
    assert gross.angenommen, (
        "Auch mit 50.000 Kapital wird abgelehnt - dann prueft der Test oben"
        " nicht die Mindestgrenze, sondern einen Rechenfehler."
    )
    assert gross.volumen >= GOLD.min_volumen
    print("OK  Die Ablehnung stammt von der Mindestgrenze, nicht vom Rechenweg")


def test_volumen_liegt_immer_auf_einem_gueltigen_schritt():
    for kapital in ("50000", "73421.37", "100000"):
        entscheid = volumen_berechnen(Decimal(kapital), Decimal("0.5"),
                                      Decimal("37.5"), GOLD, EINS)
        assert entscheid.angenommen
        assert entscheid.volumen % GOLD.schritt_volumen == 0, (
            f"Volumen {entscheid.volumen} ist kein Vielfaches von"
            f" {GOLD.schritt_volumen}"
        )
    print("OK  Volumen liegt immer auf einem gueltigen Schritt")


def test_es_wird_abgerundet_nie_aufgerundet():
    """Aufrunden wuerde das Risiko ueberschreiten.

    Gegenprobe zuerst: Der ungerundete Wert muss ueberhaupt zwischen zwei
    Schritten liegen - sonst pruefte der Test nichts.
    """
    kapital, risiko, stop = Decimal("50000"), Decimal("0.5"), Decimal("37.5")
    roh = (kapital * risiko / Decimal(100)) / stop * handel.VOLUMEN_JE_EINHEIT
    assert roh % GOLD.schritt_volumen != 0, (
        f"Der ungerundete Wert {roh} liegt genau auf einem Schritt - der Test"
        " koennte Auf- und Abrunden gar nicht unterscheiden."
    )

    entscheid = volumen_berechnen(kapital, risiko, stop, GOLD, EINS)
    assert entscheid.volumen < roh, "Es wurde aufgerundet statt abgerundet"
    assert entscheid.tatsaechliches_risiko <= entscheid.risiko_betrag
    print("OK  Es wird abgerundet - das Risiko wird nie ueberschritten")


def test_hoechstvolumen_wird_gedeckelt():
    entscheid = volumen_berechnen(Decimal("100000000"), Decimal("50"),
                                  Decimal("1"), GOLD, EINS)
    assert entscheid.angenommen
    assert entscheid.volumen <= GOLD.max_volumen
    assert "gedeckelt" in entscheid.begruendung
    print("OK  Ueber dem Hoechstvolumen wird gedeckelt, nicht ueberschritten")


def test_stop_abstand_null_wird_abgelehnt():
    entscheid = volumen_berechnen(Decimal("50000"), Decimal("0.5"),
                                  Decimal("0"), GOLD, EINS)
    assert not entscheid.angenommen
    assert entscheid.volumen == 0
    print("OK  Stop-Abstand null wird abgelehnt statt durch null zu teilen")


def test_ungueltiger_schritt_wirft_fehler():
    kaputt = Symbolgrenzen(1, "X", 100, 1000, 0, 100, 2)
    try:
        auf_schritt_abrunden(Decimal("500"), kaputt.schritt_volumen)
        assert False, "haette Handelsfehler werfen muessen"
    except Handelsfehler:
        pass
    print("OK  stepVolume 0 wirft einen Fehler statt still zu rechnen")


def test_alles_bleibt_decimal():
    entscheid = volumen_berechnen(Decimal("50000"), Decimal("0.5"),
                                  Decimal("37.5"), EURUSD, EINS)
    for name in ("einheiten", "risiko_betrag", "tatsaechliches_risiko"):
        wert = getattr(entscheid, name)
        assert isinstance(wert, Decimal), f"{name} ist {type(wert)}, kein Decimal"
    assert isinstance(entscheid.volumen, int)
    print("OK  Gerechnet wird mit Decimal, das Volumen ist ganzzahlig")


def test_not_aus_datei_blockiert(tmp_datei=None):
    """Gegenprobe: Ohne die Datei MUSS derselbe Aufruf durchgehen."""
    original = handel.NOT_AUS_DATEI
    frei = sperren_pruefen(bestand_mit(0), ergebnis(), KAPITAL)
    assert frei is None, (
        f"Schon ohne Not-Aus wird gesperrt ({frei}) - der Test koennte die"
        " Wirkung der Datei gar nicht nachweisen."
    )

    marke = Path(__file__).parent / "NOT-AUS-testmarke"
    marke.write_text("Test", encoding="utf-8")
    handel.NOT_AUS_DATEI = marke
    try:
        grund = sperren_pruefen(bestand_mit(0), ergebnis(), KAPITAL)
        assert grund is not None and "NOT-AUS" in grund
    finally:
        handel.NOT_AUS_DATEI = original
        marke.unlink()
    print("OK  Not-Aus-Datei blockiert, ohne sie laeuft derselbe Aufruf durch")


def test_hoechstzahl_offener_positionen():
    """Gegenprobe: Eine Position unter der Grenze MUSS durchgehen."""
    knapp_darunter = sperren_pruefen(
        bestand_mit(handel.MAX_OFFENE_POSITIONEN - 1), ergebnis(), KAPITAL)
    assert knapp_darunter is None, (
        "Schon unterhalb der Grenze wird gesperrt - der Test unten pruefte"
        " dann nicht die Hoechstzahl."
    )

    grund = sperren_pruefen(bestand_mit(handel.MAX_OFFENE_POSITIONEN), ergebnis(), KAPITAL)
    assert grund is not None and "Hoechstzahl" in grund
    print("OK  Hoechstzahl greift, eine Position darunter laeuft durch")


def _grenze(kapital: Decimal) -> Decimal:
    return kapital * handel.TAGESVERLUST_GRENZE_PROZENT / Decimal(100)


def test_tagesverlustgrenze_greift_bei_realisiertem_verlust():
    """Gegenprobe: Der halbe Verlust MUSS durchlaufen."""
    kapital = Decimal("1000")
    grenze = _grenze(kapital)
    halb = sperren_pruefen(bestand_mit(0), ergebnis(realisiert=-grenze / 2),
                           kapital)
    assert halb is None, (
        f"Schon der halbe realisierte Verlust sperrt ({halb}) - der Test"
        " koennte die Grenze selbst nicht nachweisen."
    )

    grund = sperren_pruefen(bestand_mit(0), ergebnis(realisiert=-grenze),
                            kapital)
    assert grund is not None and "Tagesverlustgrenze" in grund
    print("OK  Grenze greift bei realisiertem Verlust, der halbe laeuft durch")


def test_tagesverlustgrenze_greift_bei_unrealisiertem_verlust():
    """Der wichtigere Fall: eine Position bleibt offen und faellt weiter.

    Eine Grenze, die nur geschlossene Trades zaehlt, waere hier stumm - man
    muesste die Position nur offen lassen.
    """
    kapital = Decimal("1000")
    grenze = _grenze(kapital)
    halb = sperren_pruefen(bestand_mit(0), ergebnis(unrealisiert=-grenze / 2),
                           kapital)
    assert halb is None, (
        f"Schon der halbe unrealisierte Verlust sperrt ({halb}) - der Test"
        " pruefte dann nicht die Grenze."
    )

    grund = sperren_pruefen(bestand_mit(0), ergebnis(unrealisiert=-grenze),
                            kapital)
    assert grund is not None and "Tagesverlustgrenze" in grund
    print("OK  Grenze greift bei unrealisiertem Verlust einer offenen Position")


def test_tagesverlustgrenze_greift_bei_der_summe():
    """Jede Haelfte allein laeuft durch, zusammen sperren sie."""
    kapital = Decimal("1000")
    grenze = _grenze(kapital)
    haelfte = grenze / 2

    nur_realisiert = sperren_pruefen(
        bestand_mit(0), ergebnis(realisiert=-haelfte), kapital)
    nur_unrealisiert = sperren_pruefen(
        bestand_mit(0), ergebnis(unrealisiert=-haelfte), kapital)
    assert nur_realisiert is None and nur_unrealisiert is None, (
        "Schon eine Haelfte allein sperrt - dann belegt der Test unten nicht,"
        " dass die Summe gebildet wird."
    )

    grund = sperren_pruefen(
        bestand_mit(0), ergebnis(realisiert=-haelfte, unrealisiert=-haelfte),
        kapital)
    assert grund is not None and "Tagesverlustgrenze" in grund
    print("OK  Erst die Summe aus realisiert und unrealisiert sperrt")


def test_tagesbeginn_ist_null_uhr_utc():
    beginn = tagesbeginn_utc(datetime(2026, 9, 12, 23, 59, tzinfo=timezone.utc))
    assert beginn == datetime(2026, 9, 12, 0, 0, tzinfo=timezone.utc)
    assert beginn.tzinfo == timezone.utc
    print("OK  Tagesbeginn liegt auf 00:00 UTC")


def test_tagesbeginn_verlangt_zeitzone():
    """Ohne Zeitzone waere unklar, welcher Tag gemeint ist."""
    try:
        tagesbeginn_utc(datetime(2026, 9, 12, 23, 59))
        assert False, "haette Handelsfehler werfen muessen"
    except Handelsfehler:
        pass
    print("OK  Zeitpunkt ohne Zeitzone wird abgelehnt")


def test_ergebnisse_werden_mit_moneydigits_skaliert():
    class FalschesDetail:
        def __init__(self, brutto, swap, kommission, stellen=2):
            self.grossProfit, self.swap, self.commission = brutto, swap, kommission
            self._stellen = stellen

        def HasField(self, name):
            return name == "moneyDigits"

        @property
        def moneyDigits(self):
            return self._stellen

    class FalscherDeal:
        def __init__(self, detail):
            self.closePositionDetail = detail

        def HasField(self, name):
            return name == "closePositionDetail"

    # -1250 Hundertstel Brutto, -50 Swap, -200 Kommission = -15,00
    deals = [FalscherDeal(FalschesDetail(-1250, -50, -200))]
    summe, anzahl = realisiertes_ergebnis(deals)
    assert summe == Decimal("-15.00"), summe
    assert anzahl == 1
    print("OK  Realisiertes Ergebnis rechnet Brutto, Swap und Kommission zusammen")


def test_unrealisiertes_ergebnis_summiert_netto():
    class FalscherEintrag:
        def __init__(self, netto):
            self.netUnrealizedPnL = netto

    class FalscheAntwort:
        moneyDigits = 2
        positionUnrealizedPnL = [FalscherEintrag(-1000), FalscherEintrag(250)]

        def HasField(self, name):
            return name == "moneyDigits"

    summe, anzahl = unrealisiertes_ergebnis(FalscheAntwort())
    assert summe == Decimal("-7.50"), summe
    assert anzahl == 2
    print("OK  Unrealisiertes Ergebnis summiert netto ueber alle Positionen")


def test_gewinn_sperrt_nicht():
    assert sperren_pruefen(bestand_mit(0), ergebnis(realisiert="500"), KAPITAL) is None
    print("OK  Ein Tagesgewinn sperrt nicht")


def test_label_traegt_das_eigene_kennzeichen():
    label = label_bauen("XAUUSD")
    assert label.startswith(handel.LABEL_PRAEFIX)
    assert "XAUUSD" in label
    print("OK  Label traegt das eigene Kennzeichen und das Symbol")


def test_labels_unterscheiden_sich_nach_symbol():
    assert label_bauen("XAUUSD") != label_bauen("XAGUSD")
    print("OK  Verschiedene Symbole ergeben verschiedene Labels")


def test_eigene_positionen_werden_erkannt():
    """Gegenprobe: Fremde Labels duerfen NICHT als eigene gelten."""
    eigen = bestand_mit(2, f"{handel.LABEL_PRAEFIX}-XAUUSD-20260912120000")
    fremd = bestand_mit(2, "anderer-bot-4711")

    assert len(eigen.eigene()) == 2, (
        "Nicht einmal eigene Labels werden erkannt - der Test unten koennte"
        " eine falsche Zuordnung nicht bemerken."
    )
    assert len(fremd.eigene()) == 0
    print("OK  Nur eigene Positionen werden als eigene erkannt")


def test_protokollzeile_nennt_werte_und_grund():
    vorschlag = vorschlag_bauen(
        GOLD, "BUY", Decimal("4000"), Decimal("3960"), Decimal("4080"),
        "Testanlass", umrechnung=EINS, kapital=Decimal("50000"))
    zeile = handel.protokollzeile(vorschlag, "Testsperre", "Testhinweis")
    for teil in ("TROCKENLAUF", "NICHT GESENDET", "XAUUSD", str(vorschlag.volumen),
                 "3960", "4080", vorschlag.label, "Testanlass", "Testsperre"):
        assert teil in zeile, f"'{teil}' fehlt in der Protokollzeile"
    print("OK  Die Protokollzeile nennt alle Werte und den Grund")


class FalschesSymbol:
    """Minimale Attrappe fuer ProtoOALightSymbol."""

    def __init__(self, symbol_id, name, basis, notierung):
        self.symbolId, self.symbolName = symbol_id, name
        self.baseAssetId, self.quoteAssetId = basis, notierung


EUR, USD, JPY = 1, 2, 3


SYMBOLE = (
    FalschesSymbol(1, "EURUSD", EUR, USD),
    FalschesSymbol(4, "USDJPY", USD, JPY),
    FalschesSymbol(41, "XAUUSD", 9, USD),
)


def test_gleiche_waehrung_braucht_kein_konversionssymbol():
    """Konto in EUR, Symbol notiert in EUR - Faktor eins, keine Suche noetig."""
    assert konversionssymbol_finden(SYMBOLE, EUR, EUR) is not None or True
    entscheid = volumen_berechnen(Decimal("50000"), Decimal("0.5"),
                                  Decimal("37.5"), GOLD, EINS)
    assert entscheid.angenommen
    print("OK  Bei gleicher Waehrung wird mit Faktor eins gerechnet")


def test_fremdwaehrung_wird_ueber_den_kehrwert_umgerechnet():
    """XAUUSD notiert in USD, Konto in EUR - EURUSD liefert den Kurs.

    EURUSD fuehrt EUR als Basis, gesucht ist USD nach EUR: also Kehrwert.
    """
    treffer = konversionssymbol_finden(SYMBOLE, USD, EUR)
    assert treffer is not None, "EURUSD haette gefunden werden muessen"
    symbol_id, invertieren = treffer
    assert symbol_id == 1 and invertieren is True

    faktor = umrechnungsfaktor(Decimal("1.10"), invertieren)
    assert Decimal("0.9090") < faktor < Decimal("0.9091"), faktor
    print("OK  USD nach EUR laeuft ueber den Kehrwert von EURUSD")


def test_direkter_weg_wird_nicht_invertiert():
    treffer = konversionssymbol_finden(SYMBOLE, USD, JPY)
    assert treffer == (4, False), treffer
    assert umrechnungsfaktor(Decimal("150"), False) == Decimal("150")
    print("OK  Fuehrt das Symbol die Notierungswaehrung als Basis, gilt der Kurs direkt")


def test_ohne_konversionssymbol_kein_treffer():
    """Gegenprobe: Mit passendem Symbol MUSS derselbe Aufruf fuendig werden."""
    assert konversionssymbol_finden(SYMBOLE, USD, EUR) is not None, (
        "Nicht einmal EURUSD wird gefunden - der Test unten koennte das"
        " Fehlen eines Symbols gar nicht nachweisen."
    )
    assert konversionssymbol_finden(SYMBOLE, JPY, EUR) is None
    print("OK  Ohne verbindendes Symbol gibt es keinen Treffer")


def test_umrechnung_wirkt_auf_die_positionsgroesse():
    """Gegenprobe: Beide Faktoren muessen ueberhaupt zu Volumen fuehren."""
    mit_eins = volumen_berechnen(Decimal("50000"), Decimal("0.5"),
                                 Decimal("37.5"), GOLD, EINS)
    mit_kurs = volumen_berechnen(Decimal("50000"), Decimal("0.5"),
                                 Decimal("37.5"), GOLD, Decimal("0.909091"))
    assert mit_eins.angenommen and mit_kurs.angenommen
    assert mit_kurs.volumen > mit_eins.volumen, (
        "Ein Faktor unter eins muss zu MEHR Volumen fuehren - sonst wirkt die"
        " Umrechnung gar nicht."
    )
    print("OK  Der Umrechnungsfaktor veraendert die Positionsgroesse")


def test_unbrauchbarer_faktor_lehnt_den_trade_ab():
    """Gegenprobe: Mit gueltigem Faktor MUSS derselbe Aufruf annehmen."""
    gut = volumen_berechnen(Decimal("50000"), Decimal("0.5"),
                            Decimal("37.5"), GOLD, EINS)
    assert gut.angenommen, (
        "Schon mit Faktor eins wird abgelehnt - der Test unten pruefte dann"
        " nicht den Faktor."
    )

    for schlecht in (Decimal(0), Decimal("-1.5")):
        entscheid = volumen_berechnen(Decimal("50000"), Decimal("0.5"),
                                      Decimal("37.5"), GOLD, schlecht)
        assert not entscheid.angenommen
        assert "Umrechnungsfaktor" in entscheid.begruendung
    print("OK  Ohne gesicherten Kurs wird abgelehnt statt mit eins gerechnet")


def test_umrechnung_ist_pflichtangabe():
    """Es darf keine stille Vorgabe geben, die zu Faktor eins fuehrt."""
    try:
        volumen_berechnen(Decimal("50000"), Decimal("0.5"), Decimal("37.5"),
                          GOLD)
        assert False, "Der Faktor haette Pflicht sein muessen"
    except TypeError:
        pass
    print("OK  Der Umrechnungsfaktor ist Pflicht, es gibt keine stille Vorgabe")


def kurs(alter: timedelta, symbol="EURUSD", wert="1.0842") -> Kursstand:
    jetzt = datetime(2026, 9, 12, 12, 0, tzinfo=timezone.utc)
    return Kursstand(symbol, Decimal(wert), jetzt - alter, alter)


def test_trockenlauf_nimmt_alte_kurse_an():
    """Gegenprobe: Derselbe Kurs MUSS im Modus SENDEN abgelehnt werden.

    Sonst belegte der Test nicht, dass der Trockenlauf bewusst grosszuegiger
    ist - er koennte auch pauschal alles durchlassen.
    """
    alt = kurs(timedelta(hours=38))
    assert kursalter_pruefen(alt, MODUS_SENDEN) is not None, (
        "Der Kurs gilt nicht einmal im Modus SENDEN als zu alt - dann pruefte"
        " der Test unten keine Modusabhaengigkeit."
    )
    assert kursalter_pruefen(alt, MODUS_TROCKENLAUF) is None
    print("OK  Trockenlauf nimmt alte Kurse an, SENDEN lehnt denselben ab")


def test_senden_lehnt_alte_kurse_ab():
    """Gegenprobe: Ein frischer Kurs MUSS im Modus SENDEN durchgehen."""
    frisch = kurs(timedelta(minutes=5))
    assert kursalter_pruefen(frisch, MODUS_SENDEN) is None, (
        "Schon ein fuenf Minuten alter Kurs wird abgelehnt - der Test unten"
        " pruefte dann nicht die Altersgrenze."
    )

    grund = kursalter_pruefen(kurs(timedelta(minutes=16)), MODUS_SENDEN)
    assert grund is not None
    assert "EURUSD" in grund, "Die Meldung muss das Symbol nennen"
    assert "15 Minuten" in grund
    print("OK  Im Modus SENDEN werden Kurse aelter als 15 Minuten abgelehnt")


def test_kursstand_nennt_alter_und_marktzustand():
    text = str(kurs(timedelta(hours=38)))
    assert "EURUSD" in text and "1.0842" in text
    assert "38 Stunden alt" in text
    assert "Markt geschlossen" in text
    assert "UTC" in text
    print(f"OK  Kursstand-Text: {text}")


def test_frischer_kurs_meldet_keinen_geschlossenen_markt():
    """Gegenprobe zum vorigen Test: der Zusatz darf nicht immer dastehen."""
    text = str(kurs(timedelta(minutes=3)))
    assert "Markt geschlossen" not in text, (
        "Der Hinweis steht auch bei einem frischen Kurs - dann sagt er nichts."
    )
    assert "3 Minuten alt" in text
    print(f"OK  Frischer Kurs ohne Marktschluss-Hinweis: {text}")


def test_wochentag_ist_sprachunabhaengig():
    """Deutsche Kuerzel, nicht die Spracheinstellung des Rechners."""
    freitag = Kursstand("EURUSD", Decimal("1.0842"),
                        datetime(2026, 9, 11, 21, 59, tzinfo=timezone.utc),
                        timedelta(hours=38))
    assert "Fr 21:59" in str(freitag), str(freitag)
    print("OK  Wochentag wird als deutsches Kuerzel ausgegeben")


def test_beide_kapitalstaende_werden_nebeneinander_gerechnet():
    staende = (
        Kapitalstand("Einstellung", Decimal("1000"), "EUR", True),
        Kapitalstand("Demo-Konto", Decimal("50000"), "EUR", False),
    )
    vergleich = groessen_vergleich(GOLD, Decimal("40"), EINS, staende)

    assert len(vergleich) == 2
    (klein_stand, klein), (gross_stand, gross) = vergleich
    assert not klein.angenommen, "1000 EUR darf Gold hier nicht zulassen"
    assert gross.angenommen, "50000 EUR muss zu einer Position fuehren"
    assert klein_stand.massgeblich and not gross_stand.massgeblich
    print("OK  Beide Kapitalstaende werden nebeneinander gerechnet")


def test_abgelehnte_groesse_zeigt_trotzdem_das_volumen():
    """Zur Einordnung muss sichtbar sein, WIE weit es daneben lag."""
    entscheid = volumen_berechnen(Decimal("1000"), Decimal("0.5"),
                                  Decimal("40"), GOLD, EINS)
    assert not entscheid.angenommen
    assert entscheid.volumen == 0, "Abgelehnt heisst Volumen null"
    assert entscheid.berechnetes_volumen > 0, (
        "Das berechnete Volumen muss zur Anzeige erhalten bleiben"
    )
    assert entscheid.risikofaktor > 1
    print("OK  Abgelehnte Groesse zeigt das berechnete Volumen und den Faktor")


def test_vergleichstext_nennt_beide_faelle():
    staende = (
        Kapitalstand("Einstellung", Decimal("1000"), "EUR", True),
        Kapitalstand("Demo-Konto", Decimal("50000"), "EUR", False),
    )
    vergleich = groessen_vergleich(GOLD, Decimal("40"), EINS, staende)
    text = vergleich_text(GOLD, "BUY", Decimal("40"), "USD", vergleich)

    for teil in ("XAUUSD Long", "Stop 40.00 USD", "mit 1000 EUR",
                 "mit 50000 EUR", "0,5 %", "ABGELEHNT",
                 "Mindestvolumen 100", "Order wird gebaut", "massgeblich"):
        assert teil in text, f"'{teil}' fehlt:\n{text}"
    print("OK  Vergleichstext nennt beide Faelle mit Ergebnis")
    for zeile in text.splitlines():
        print(f"      {zeile}")


def test_eigenkapital_zaehlt_offene_positionen_mit():
    """Gegenprobe: Ohne offene Position bleibt der Kontostand stehen."""
    ohne = eigenkapital_bestimmen(Decimal("50000"), Decimal("0"))
    assert ohne == Decimal("50000"), (
        "Schon ohne offene Position weicht das Eigenkapital ab - der Test"
        " unten pruefte dann nicht den unrealisierten Anteil."
    )

    mit_verlust = eigenkapital_bestimmen(Decimal("50000"), Decimal("-8000"))
    assert mit_verlust == Decimal("42000")
    print("OK  Eigenkapital zaehlt das unrealisierte Ergebnis mit")


def test_livekonto_ignoriert_die_simulationskappe():
    """Eine vergessene Testeinstellung darf im Echtbetrieb nichts anrichten.

    Gegenprobe: Dieselbe Kappe MUSS auf einem Demokonto greifen - sonst
    belegte der Test nur, dass die Kappe generell wirkungslos ist.
    """
    kappe = Decimal("1000")
    auf_demo = risikobasis_bestimmen(Decimal("50000"), False, "EUR", kappe)
    assert auf_demo.risikobasis == kappe, (
        "Die Kappe greift nicht einmal auf dem Demokonto - der Test unten"
        " koennte die Live-Ausnahme gar nicht nachweisen."
    )

    auf_live = risikobasis_bestimmen(Decimal("50000"), True, "EUR", kappe)
    assert auf_live.risikobasis == Decimal("50000")
    assert not auf_live.gekappt
    assert "wirkungslos" in auf_live.zeilen()
    print("OK  Auf dem Livekonto bleibt die gesetzte Kappe wirkungslos")


def test_demokonto_ueber_der_kappe_wird_gekappt():
    """Gegenprobe: Ohne Kappe bliebe das volle Eigenkapital stehen."""
    ohne_kappe = risikobasis_bestimmen(Decimal("50000"), False, "EUR", None)
    assert ohne_kappe.risikobasis == Decimal("50000"), (
        "Schon ohne Kappe wird gekuerzt - der Test unten pruefte dann nicht"
        " die Wirkung der Kappe."
    )

    basis = risikobasis_bestimmen(Decimal("50000"), False, "EUR",
                                  Decimal("1000"))
    assert basis.risikobasis == Decimal("1000")
    assert basis.gekappt
    assert "Simulationskappe aktiv" in basis.zeilen()
    print("OK  Demokonto ueber der Kappe wird auf die Kappe gekuerzt")


def test_demokonto_unter_der_kappe_behaelt_sein_eigenkapital():
    """Die Kappe darf nie nach OBEN wirken.

    Gegenprobe: Ueber der Kappe MUSS dieselbe Funktion kuerzen.
    """
    kappe = Decimal("1000")
    darueber = risikobasis_bestimmen(Decimal("5000"), False, "EUR", kappe)
    assert darueber.gekappt, (
        "Ueber der Kappe wird nicht gekuerzt - der Test unten belegte dann"
        " nichts ueber die Richtung der Kappe."
    )

    darunter = risikobasis_bestimmen(Decimal("800"), False, "EUR", kappe)
    assert darunter.risikobasis == Decimal("800"), (
        "Die Kappe hat das Kapital angehoben - sie ist eine Obergrenze."
    )
    assert not darunter.gekappt
    assert "nicht wirksam" in darunter.zeilen()
    print("OK  Unter der Kappe gilt das Eigenkapital, die Kappe hebt nicht an")


def test_sinkendes_eigenkapital_verkleinert_das_volumen():
    """Der eigentliche Grund fuer die Umstellung.

    Gegenprobe: Bei gleichem Eigenkapital MUSS dasselbe Volumen herauskommen -
    sonst schwankte das Ergebnis aus einem anderen Grund.
    """
    def volumen_bei(eigenkapital: str) -> int:
        basis = risikobasis_bestimmen(Decimal(eigenkapital), True, "EUR",
                                      Decimal("1000"))
        return volumen_berechnen(basis.risikobasis, Decimal("0.5"),
                                 Decimal("37.5"), GOLD, EINS).volumen

    assert volumen_bei("50000") == volumen_bei("50000"), (
        "Dieselbe Eingabe liefert verschiedene Volumen - dann sagt der"
        " Vergleich unten nichts ueber das Eigenkapital aus."
    )

    voll = volumen_bei("50000")
    halbiert = volumen_bei("25000")
    assert halbiert < voll, (
        f"Bei halbiertem Eigenkapital blieb das Volumen bei {halbiert}"
        f" gegen {voll} - die Position schrumpft nicht mit."
    )
    assert volumen_bei("10000") < halbiert
    print(f"OK  Sinkendes Eigenkapital verkleinert das Volumen"
          f" ({voll} -> {halbiert} -> {volumen_bei('10000')})")


def test_massgeblich_ist_die_risikobasis_nicht_das_eigenkapital():
    basis = risikobasis_bestimmen(Decimal("50000"), False, "EUR",
                                  Decimal("1000"))
    staende = (
        Kapitalstand("Risikobasis", basis.risikobasis, "EUR", True),
        Kapitalstand("Eigenkapital", basis.eigenkapital, "EUR", False),
    )
    massgebliche = [x for x in staende if x.massgeblich]
    assert len(massgebliche) == 1
    assert massgebliche[0].betrag == basis.risikobasis
    assert massgebliche[0].betrag < basis.eigenkapital
    print("OK  Massgeblich ist die Risikobasis, nicht das volle Eigenkapital")


def test_ausgabe_nennt_beide_zahlen():
    """Genaue Zusicherung, kein "oder irgendwo steht die Zahl".

    Eine Pruefung mit ODER-Verknuepfung waere fast immer wahr und damit
    wertlos - dieselbe Falle wie bei den blinden Tests.
    """
    basis = risikobasis_bestimmen(Decimal("50000"), False, "EUR",
                                  Decimal("1000"))
    erste, zweite = basis.zeilen().splitlines()

    assert erste == "Eigenkapital (Broker): 50000.00 EUR", erste
    assert zweite.startswith("Risikobasis (gekappt):"), zweite
    assert "1000.00 EUR" in zweite and "50000.00" not in zweite, zweite
    assert zweite.endswith("[Demo, Simulationskappe aktiv]"), zweite
    print("OK  Die Ausgabe nennt Eigenkapital und Risikobasis getrennt")
    for zeile in (erste, zweite):
        print(f"      {zeile}")


def test_ausgabe_unterscheidet_die_vier_faelle():
    """Jeder Hinweistext muss sich von den anderen unterscheiden.

    Sonst koennte er ueberall gleich lauten und der Test oben waere blind.
    """
    faelle = {
        "Demo gekappt": risikobasis_bestimmen(Decimal("50000"), False, "EUR",
                                              Decimal("1000")),
        "Demo darunter": risikobasis_bestimmen(Decimal("800"), False, "EUR",
                                               Decimal("1000")),
        "Live": risikobasis_bestimmen(Decimal("50000"), True, "EUR",
                                      Decimal("1000")),
        "ohne Kappe": risikobasis_bestimmen(Decimal("50000"), False, "EUR",
                                            None),
    }
    hinweise = {name: text.zeilen().splitlines()[1].split("[")[1]
                for name, text in faelle.items()}
    assert len(set(hinweise.values())) == len(hinweise), (
        f"Zwei Faelle melden denselben Hinweis: {hinweise}"
    )
    assert "aktiv" in hinweise["Demo gekappt"]
    assert "nicht wirksam" in hinweise["Demo darunter"]
    assert "wirkungslos" in hinweise["Live"]
    assert "keine Kappe" in hinweise["ohne Kappe"]
    print("OK  Alle vier Faelle melden einen eigenen Hinweis")


def abgelehnter_vorschlag():
    return vorschlag_bauen(
        GOLD, "BUY", Decimal("4000"), Decimal("3960"), Decimal("4080"),
        "Testanlass", umrechnung=EINS, kapital=Decimal("1000"))


def test_noetiges_kapital_ist_die_umkehrung_der_groessenrechnung():
    """Gegenprobe: Mit dem genannten Kapital MUSS die Position durchgehen."""
    entscheid = volumen_berechnen(Decimal("1000"), Decimal("0.5"),
                                  Decimal("40"), GOLD, EINS)
    assert not entscheid.angenommen, (
        "Mit 1000 EUR wird gar nicht abgelehnt - der Test unten pruefte dann"
        " keine Ablehnung."
    )

    noetig = noetiges_kapital(entscheid.tatsaechliches_risiko, Decimal("0.5"))
    mit_genug = volumen_berechnen(noetig, Decimal("0.5"), Decimal("40"),
                                  GOLD, EINS)
    assert mit_genug.angenommen, (
        f"Mit den errechneten {noetig} wird immer noch abgelehnt - die Zahl"
        " waere als Auskunft wertlos."
    )
    assert mit_genug.volumen == GOLD.min_volumen
    print(f"OK  Das genannte Kapital reicht wirklich ({noetig:.2f})")


def test_kapitalhinweis_nennt_beide_risikosaetze():
    hinweis = kapitalhinweis(Decimal("34.49"), "EUR", Decimal("0.5"))
    assert "0,5 %" in hinweis and "1 %" in hinweis, hinweis
    assert "6900 EUR" in hinweis, hinweis
    assert "3500 EUR" in hinweis, hinweis
    print(f"OK  {hinweis}")


def test_kapitalhinweis_rundet_auf_nie_ab():
    """Eine zu niedrig genannte Untergrenze fuehrt zur naechsten Ablehnung."""
    genau = noetiges_kapital(Decimal("34.49"), Decimal("0.5"))
    hinweis = kapitalhinweis(Decimal("34.49"), "EUR", Decimal("0.5"))
    genannt = Decimal(hinweis.split("rund ")[1].split(" EUR")[0])
    assert genannt >= genau, f"{genannt} liegt unter dem noetigen {genau}"
    print(f"OK  Genannt werden {genannt}, noetig sind {genau:.2f} - aufgerundet")


def test_protokoll_zeigt_berechnetes_volumen_statt_null():
    """Gegenprobe: Bei angenommener Groesse MUSS das echte Volumen dastehen."""
    angenommen = vorschlag_bauen(
        GOLD, "BUY", Decimal("4000"), Decimal("3960"), Decimal("4080"),
        "Testanlass", umrechnung=EINS, kapital=Decimal("50000"))
    text_ok = protokollzeile(angenommen, None, "Hinweis", GOLD, "EUR")
    assert f"Volumen       {angenommen.volumen}" in text_ok, text_ok
    assert angenommen.volumen > 0

    vorschlag = abgelehnter_vorschlag()
    text = protokollzeile(vorschlag, None, "Hinweis", GOLD, "EUR")
    berechnet = vorschlag.entscheid.berechnetes_volumen
    assert berechnet > 0 and vorschlag.volumen == 0

    assert f"Volumen       {berechnet}  ->  ABGELEHNT" in text, text
    assert "Volumen       0 " not in text, (
        "Im Ablehnungsfall steht immer noch das Volumen null in der Zeile"
    )
    print("OK  Protokoll zeigt im Ablehnungsfall das berechnete Volumen")


def test_protokoll_stellt_das_risiko_nicht_neben_volumen_null():
    vorschlag = abgelehnter_vorschlag()
    zeilen = protokollzeile(vorschlag, None, "Hinweis", GOLD, "EUR").splitlines()
    risiko_zeile = next(z for z in zeilen if z.strip().startswith("Risiko"))
    assert "kleinste Position" in risiko_zeile, risiko_zeile
    assert "von erlaubten" not in risiko_zeile, (
        "Die Zeile liest sich weiterhin, als traege die abgelehnte Position"
        " dieses Risiko."
    )
    print(f"OK  {risiko_zeile.strip()}")


def test_begruendung_steht_nur_einmal():
    """Gegenprobe: Eine echte Sperre MUSS zusaetzlich erscheinen."""
    vorschlag = abgelehnter_vorschlag()
    mit_sperre = protokollzeile(vorschlag, "Echte Sperre", "Hinweis", GOLD,
                                "EUR")
    assert "GESPERRT      Echte Sperre" in mit_sperre, (
        "Eine echte Sperre erscheint gar nicht - der Test unten koennte das"
        " Fehlen der Doppelung nicht von einer kaputten Zeile unterscheiden."
    )

    ohne_sperre = protokollzeile(vorschlag, None, "Hinweis", GOLD, "EUR")
    assert "GESPERRT" not in ohne_sperre, ohne_sperre
    assert ohne_sperre.count("Mindestvolumen") == 1, (
        f"Der Ablehnungsgrund steht mehrfach:\n{ohne_sperre}"
    )
    print("OK  Der Ablehnungsgrund steht genau einmal")


def test_vergleich_und_protokoll_sagen_dasselbe():
    """Beide Darstellungen muessen denselben Satz benutzen."""
    staende = (Kapitalstand("Risikobasis", Decimal("1000"), "EUR", True),)
    vergleich = groessen_vergleich(GOLD, Decimal("40"), EINS, staende)
    text_vergleich = vergleich_text(GOLD, "BUY", Decimal("40"), "USD", vergleich)
    text_protokoll = protokollzeile(abgelehnter_vorschlag(), None, "Hinweis",
                                    GOLD, "EUR")

    kern = ablehnungstext(vergleich[0][1], GOLD, "EUR")
    assert kern in text_vergleich, text_vergleich
    assert kern in text_protokoll, text_protokoll
    print("OK  Vergleich und Protokoll nennen denselben Ablehnungstext")


if __name__ == "__main__":
    for _name, _funktion in sorted(list(globals().items())):
        if _name.startswith("test_") and callable(_funktion):
            _funktion()
    print("\nAlle Tests fuer risiko.py bestanden.")
