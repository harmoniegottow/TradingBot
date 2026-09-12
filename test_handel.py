"""Tests fuer handel.py - Sendesperren und Orderbau, ohne Netzwerk.

Die reine Rechnung liegt in risiko.py und wird in test_risiko.py geprueft.
Hier bleibt, was Protobuf oder die Betriebsart betrifft.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import handel
from handel import (
    MODUS_SENDEN,
    MODUS_TROCKENLAUF,
    order_bauen,
    senden_erlaubt,
    vorschlag_bauen,
)
from risiko import (
    Bestand,
    Kapitalstand,
    Kursstand,
    Symbolgrenzen,
    Tagesergebnis,
)

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


def test_trockenlauf_sendet_nicht():
    """Gegenprobe zuerst: Auf demselben Konto MUSS 'senden' erlaubt sein."""
    darf_mit_senden, _ = senden_erlaubt(MODUS_SENDEN, False, False)
    assert darf_mit_senden, (
        "Selbst mit Modus 'senden' auf einem Demokonto wird gesperrt - dann"
        " prueft der Test unten nicht den Modus, sondern eine andere Sperre."
    )

    darf, grund = senden_erlaubt(MODUS_TROCKENLAUF, False, False)
    assert not darf
    assert MODUS_SENDEN in grund
    print("OK  Trockenlauf sendet nicht, obwohl Senden hier moeglich waere")


def test_livekonto_bleibt_ohne_zweite_bestaetigung_gesperrt():
    """Gegenprobe: Dieselben Einstellungen auf dem Demokonto erlauben Senden."""
    auf_demo, _ = senden_erlaubt(MODUS_SENDEN, False, False)
    assert auf_demo, (
        "Auf dem Demokonto wird schon gesperrt - der Test unten koennte die"
        " Live-Sperre gar nicht nachweisen."
    )

    darf, grund = senden_erlaubt(MODUS_SENDEN, True, False)
    assert not darf
    assert "ECHTGELD_AUSDRUECKLICH_ERLAUBT" in grund
    print("OK  Livekonto bleibt trotz Modus 'senden' ohne zweite Bestaetigung gesperrt")


def test_livekonto_mit_zweiter_bestaetigung_waere_erlaubt():
    darf, grund = senden_erlaubt(MODUS_SENDEN, True, True)
    assert darf
    assert "ACHTUNG" in grund and "echtem Geld" in grund
    print("OK  Livekonto mit zweiter Bestaetigung erlaubt - und sagt es laut")


def test_modus_allein_genuegt_auf_live_nicht():
    """Der Schalter fuer Echtgeld allein darf ebenfalls nicht genuegen."""
    darf, _ = senden_erlaubt(MODUS_TROCKENLAUF, True, True)
    assert not darf, "Echtgeld-Schalter ohne Modus 'senden' darf nicht reichen"
    print("OK  Beide Schalter noetig - einer allein genuegt nicht")


def _grenze(kapital: Decimal) -> Decimal:
    return kapital * handel.TAGESVERLUST_GRENZE_PROZENT / Decimal(100)


def test_order_enthaelt_alle_werte():
    vorschlag = vorschlag_bauen(
        GOLD, "BUY", Decimal("4000"), Decimal("3960"), Decimal("4080"),
        "Testanlass", umrechnung=EINS, kapital=Decimal("50000"))
    assert vorschlag.entscheid.angenommen

    order = order_bauen(4711, vorschlag)
    assert order.ctidTraderAccountId == 4711
    assert order.symbolId == GOLD.symbol_id
    assert order.volume == vorschlag.volumen
    assert order.label == vorschlag.label
    assert abs(order.stopLoss - 3960.0) < 1e-9
    assert abs(order.takeProfit - 4080.0) < 1e-9
    assert len(order.SerializeToString()) > 0
    print("OK  Die fertige Order traegt alle Werte")


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


def kurs(alter: timedelta, symbol="EURUSD", wert="1.0842") -> Kursstand:
    jetzt = datetime(2026, 9, 12, 12, 0, tzinfo=timezone.utc)
    return Kursstand(symbol, Decimal(wert), jetzt - alter, alter)


def test_vorgabe_ist_trockenlauf():
    assert handel.MODUS == MODUS_TROCKENLAUF
    assert handel.ECHTGELD_AUSDRUECKLICH_ERLAUBT is False
    print("OK  Vorgabe ist Trockenlauf, Echtgeld ist nicht erlaubt")

# ------------------------------------------- Versand ohne Netzwerk

import tempfile  # noqa: E402
from contextlib import contextmanager  # noqa: E402

import ausfuehrung  # noqa: E402
from ctrader_open_api.messages.OpenApiCommonMessages_pb2 import (  # noqa: E402
    ProtoMessage,
)
from ctrader_open_api.messages.OpenApiMessages_pb2 import (  # noqa: E402
    ProtoOANewOrderReq,
    ProtoOAReconcileReq,
    ProtoOAReconcileRes,
)
from ausfuehrung import AUSFUEHRUNG_TIMEOUT, LAGE_OHNE_ANTWORT  # noqa: E402
from twisted.internet import defer  # noqa: E402
from twisted.internet.task import Clock  # noqa: E402

GOLD_T = Symbolgrenzen(41, "XAUUSD", 100, 500_000, 100, 10_000, 2)


class FalscherClient:
    """Client-Attrappe: zaehlt Versendungen, antwortet nur auf Reconcile."""

    def __init__(self, positionen=()):
        self.gesendet = []
        # Genau wie beim echten Client: Der Empfaenger liegt unter
        # _messageReceivedCallback. Die Ausfuehrungswache liest dieses
        # Attribut aus, um die Kette weiterzureichen - eine Attrappe mit
        # anderem Namen wuerde eine heile Kette als kaputt melden.
        self._messageReceivedCallback = None
        self._positionen = positionen

    def setMessageReceivedCallback(self, rueckruf):
        self._messageReceivedCallback = rueckruf

    def send(self, nachricht, responseTimeoutInSeconds=None, **_):
        self.gesendet.append(nachricht)
        if isinstance(nachricht, ProtoOAReconcileReq):
            antwort = ProtoOAReconcileRes(ctidTraderAccountId=1)
            for position in self._positionen:
                antwort.position.append(position)
            return defer.succeed(ProtoMessage(
                payloadType=antwort.payloadType,
                payload=antwort.SerializeToString()))
        # Auf eine Order kommt hier absichtlich nie eine Antwort.
        return defer.Deferred()

    def zahl(self, art) -> int:
        return sum(1 for n in self.gesendet if isinstance(n, art))


def testvorschlag():
    vorschlag = vorschlag_bauen(
        GOLD_T, "BUY", Decimal("4000"), Decimal("3960"), Decimal("4080"),
        "Test", umrechnung=Decimal(1), kapital=Decimal("50000"))
    return handel.replace(vorschlag, label="hermes-XAUUSD-20260912-testkennung")


@contextmanager
def protokoll_umgelenkt(ziel: Path):
    """Lenkt das Orderprotokoll um und stellt es danach zurueck.

    Die Umlenkung muss die GANZE Wartezeit ueberdauern - der
    Nachschau-Eintrag entsteht erst nach dem Zeitablauf, also ausserhalb des
    Aufrufs von order_senden. Genau daran ist ein frueherer Anlauf
    gescheitert: Drei Eintraege landeten im echten Protokoll.
    """
    original = ausfuehrung.PROTOKOLL_DATEI
    ausfuehrung.PROTOKOLL_DATEI = ziel
    try:
        yield
    finally:
        ausfuehrung.PROTOKOLL_DATEI = original


def versand_starten(client, uhr):
    """Startet order_senden und liefert die Sammelliste fuer das Ergebnis."""
    ergebnis = []

    def bei_fehler(fehler):
        raise AssertionError(f"order_senden scheiterte: {fehler.getTraceback()}")

    handel.order_senden(client, 1, testvorschlag(), uhr=uhr).addCallbacks(
        ergebnis.append, bei_fehler)
    return ergebnis


def test_zeitablauf_loest_keine_zweite_order_aus():
    """Die wichtigste Regel: bei Unklarheit nachsehen, nicht nachsenden.

    Gegenprobe unten: Der Zaehler MUSS eine zweite Order bemerken - sonst
    belegte "genau eine" nur, dass die Messung nicht zaehlt.
    """
    with tempfile.TemporaryDirectory() as ordner, \
            protokoll_umgelenkt(Path(ordner) / "protokoll.jsonl"):
        client, uhr = FalscherClient(), Clock()
        ergebnis = versand_starten(client, uhr)

        assert client.zahl(ProtoOANewOrderReq) == 1, "Es muss gesendet werden"
        assert not ergebnis, "Vor dem Zeitablauf darf nichts entschieden sein"

        uhr.advance(AUSFUEHRUNG_TIMEOUT + 1)

        assert ergebnis, "Nach dem Zeitablauf muss entschieden sein"
        assert client.zahl(ProtoOANewOrderReq) == 1, (
            f"Es wurden {client.zahl(ProtoOANewOrderReq)} Orders gesendet -"
            " nach einem Zeitablauf darf keine zweite folgen."
        )

        # Gegenprobe: Der Zaehler wuerde eine zweite Order sehr wohl sehen.
        client.send(ProtoOANewOrderReq())
        assert client.zahl(ProtoOANewOrderReq) == 2, (
            "Der Zaehler bemerkt nicht einmal eine von Hand gesendete Order -"
            " die Zusicherung oben waere wertlos."
        )
    print("OK  Zeitablauf loest keine zweite Order aus")


def test_nach_zeitablauf_wird_der_bestand_abgefragt():
    """Gegenprobe: Vor dem Zeitablauf darf noch nichts abgefragt sein."""
    with tempfile.TemporaryDirectory() as ordner, \
            protokoll_umgelenkt(Path(ordner) / "protokoll.jsonl"):
        client, uhr = FalscherClient(), Clock()
        versand_starten(client, uhr)

        assert client.zahl(ProtoOAReconcileReq) == 0, (
            "Der Bestand wird schon vor dem Zeitablauf abgefragt - dann"
            " belegte der Test unten nicht den Zusammenhang."
        )

        uhr.advance(AUSFUEHRUNG_TIMEOUT + 1)

        assert client.zahl(ProtoOAReconcileReq) == 1, (
            "Nach dem Zeitablauf muss der Bestand abgefragt werden."
        )
    print("OK  Nach Zeitablauf wird die Bestandsaufnahme abgefragt")


def test_zeitablauf_mit_vorhandener_position_meldet_erfolg():
    """Findet die Nachschau die Position, gilt die Order als angekommen."""
    from ctrader_open_api.messages.OpenApiModelMessages_pb2 import (
        ProtoOAPosition, ProtoOAPositionStatus, ProtoOATradeData,
    )
    kennung = "hermes-XAUUSD-20260912-testkennung"
    # positionStatus und swap sind im Protobuf Pflicht - ohne sie laesst sich
    # die Antwort nicht serialisieren.
    position = ProtoOAPosition(
        positionId=1, swap=0,
        positionStatus=ProtoOAPositionStatus.Value("POSITION_STATUS_OPEN"),
        tradeData=ProtoOATradeData(symbolId=41, volume=700,
                                   tradeSide=1, label=kennung))

    with tempfile.TemporaryDirectory() as ordner, \
            protokoll_umgelenkt(Path(ordner) / "a.jsonl"):
        ohne, uhr_ohne = FalscherClient(), Clock()
        leer = versand_starten(ohne, uhr_ohne)
        uhr_ohne.advance(AUSFUEHRUNG_TIMEOUT + 1)
        assert leer[0][0].lage == LAGE_OHNE_ANTWORT, (
            "Ohne Position wird kein Fehlen gemeldet - der Vergleich unten"
            " sagte dann nichts."
        )

        mit, uhr_mit = FalscherClient(positionen=[position]), Clock()
        gefunden = versand_starten(mit, uhr_mit)
        uhr_mit.advance(AUSFUEHRUNG_TIMEOUT + 1)

        befund = gefunden[0][0]
        assert befund.erfolgreich, befund.text
        assert "NICHT wiederholen" in befund.text
        assert mit.zahl(ProtoOANewOrderReq) == 1
    print("OK  Gefundene Position nach Zeitablauf gilt als angekommen")


def test_kein_testlauf_schreibt_ins_echte_protokoll():
    """Gegenprobe: Ohne Umlenkung WUERDE ins echte Protokoll geschrieben."""
    echt = ausfuehrung.PROTOKOLL_DATEI
    assert echt.name.endswith(".jsonl"), echt

    with tempfile.TemporaryDirectory() as ordner:
        ziel = Path(ordner) / "um.jsonl"
        with protokoll_umgelenkt(ziel):
            assert ausfuehrung.PROTOKOLL_DATEI == ziel, "Umlenkung greift nicht"
            ausfuehrung.protokoll_schreiben(ausfuehrung.protokoll_eintrag("test", {}))
            assert ziel.exists(), "Der Eintrag landete nicht im Ersatzziel"
        assert ausfuehrung.PROTOKOLL_DATEI == echt, "Nicht zurueckgestellt"
    assert not echt.exists(), (
        f"{echt.name} wurde von einem Testlauf angelegt - Tests duerfen nicht"
        " ins echte Orderprotokoll schreiben."
    )
    print("OK  Kein Testlauf schreibt ins echte Orderprotokoll")


def test_client_ohne_empfaenger_bricht_ab():
    """Kein stilles None: Fehlt das Attribut, wird nichts gesendet.

    Gegenprobe zuerst: Mit dem Attribut MUSS es durchgehen - sonst belegte
    der Abbruch unten nur, dass die Pruefung immer ausloest.
    """
    class MitEmpfaenger:
        _messageReceivedCallback = None

    assert handel.empfaenger_holen(MitEmpfaenger()) is None, (
        "Schon ein Client MIT dem Attribut wird abgelehnt - der Test unten"
        " pruefte dann nicht das Fehlen."
    )

    class OhneEmpfaenger:
        """Wie ein Client, dessen Bibliothek das Attribut umbenannt hat."""

    try:
        handel.empfaenger_holen(OhneEmpfaenger())
        assert False, "haette Handelsfehler werfen muessen"
    except handel.Handelsfehler as fehler:
        text = str(fehler)
        assert "_messageReceivedCallback" in text, text
        assert "nichts" in text and "gesendet" in text, text
        # BEIDE Ursachen muessen dastehen. Nur die Bibliothek zu nennen
        # schickt die Suche an die falsche Stelle, wenn in Wahrheit die
        # Reihenfolge im eigenen Ablauf nicht stimmt.
        assert "umbenannt" in text, f"Ursache 1 fehlt:\n{text}"
        assert "BEVOR ein Empfaenger gesetzt war" in text, (
            f"Ursache 2 fehlt:\n{text}")
        assert "mit_verbindung_ausfuehren" in text, (
            f"Der Hinweis auf die zu pruefende Stelle fehlt:\n{text}")
    print("OK  Client ohne Nachrichtenempfaenger bricht ab und nennt beide Ursachen")


def test_wache_haengt_sich_nicht_blind_ein():
    """Auch die Wache selbst darf sich nicht an einen tauben Client haengen."""
    class OhneEmpfaenger:
        def setMessageReceivedCallback(self, rueckruf):
            raise AssertionError(
                "Die Wache hat sich eingehaengt, obwohl der Empfaenger fehlt")

    try:
        handel.Ausfuehrungswache(OhneEmpfaenger(), "egal", uhr=Clock())
        assert False, "haette Handelsfehler werfen muessen"
    except handel.Handelsfehler:
        pass
    print("OK  Die Wache haengt sich nicht an einen Client ohne Empfaenger")


def test_zaehler_bemerkt_eine_unterbrochene_kette():
    """Die Generalprobe muss einen Bruch der Kette erkennen koennen.

    Gegenprobe zuerst: Bei heiler Kette MUSS die Auswertung zustimmen -
    sonst belegte ein Fehlschlag unten nur, dass sie immer meckert.
    """
    class HeileWache:
        gesehen = 5

    class TauberZaehler:
        anzahl = 5

    assert handel.generalprobe_auswerten(HeileWache(), TauberZaehler()), (
        "Die Auswertung lehnt schon eine heile Kette ab."
    )

    class LoechrigerZaehler:
        anzahl = 2

    assert not handel.generalprobe_auswerten(HeileWache(), LoechrigerZaehler())

    class StummeWache:
        gesehen = 0

    assert not handel.generalprobe_auswerten(StummeWache(), TauberZaehler()), (
        "Eine Wache, die nichts gesehen hat, darf nicht als Erfolg gelten."
    )
    print("OK  Die Generalprobe erkennt eine unterbrochene Kette")


def test_wache_reicht_jede_nachricht_weiter():
    """Auch Nachrichten, die keine Ausfuehrungsereignisse sind."""
    # ProtoOAReconcileRes gewaehlt, weil es ohne verschachtelte Pflichtfelder
    # serialisierbar ist - ProtoOATraderRes verlangt ein vollstaendiges
    # trader-Feld und waere hier nur Beiwerk.
    client = FalscherClient()
    innen = handel.Nachrichtenzaehler()
    client.setMessageReceivedCallback(innen)
    wache = handel.Ausfuehrungswache(client, "egal", uhr=Clock(), timeout=3600)

    fremd = ProtoOAReconcileRes(ctidTraderAccountId=1)
    nachricht = ProtoMessage(payloadType=fremd.payloadType,
                             payload=fremd.SerializeToString())
    for _ in range(3):
        client._messageReceivedCallback(client, nachricht)

    assert wache.gesehen == 3, wache.gesehen
    assert innen.anzahl == 3, (
        f"Nur {innen.anzahl} von 3 Nachrichten kamen durch - die Wache"
        " verschluckt Nachrichten."
    )
    wache.beenden()
    print("OK  Die Wache reicht jede Nachricht weiter, nicht nur Orderereignisse")


def test_requirements_nagelt_ctrader_fest():
    """Die Fassung, an der das private Attribut haengt, muss festgenagelt sein.

    Gegenprobe: Die Datei muss ueberhaupt lesbare Pins enthalten - sonst
    belegte der Fund unten nur, dass irgendwo eine Zeichenkette steht.
    """
    datei = Path(__file__).resolve().parent / "requirements.txt"
    assert datei.exists(), "requirements.txt fehlt"
    zeilen = [z.strip() for z in datei.read_text(encoding="utf-8").splitlines()
              if z.strip() and not z.strip().startswith("#")]
    assert len(zeilen) >= 10, f"Nur {len(zeilen)} Pins - das sieht unvollstaendig aus"
    assert all("==" in z for z in zeilen), (
        f"Nicht jede Zeile ist festgenagelt: {[z for z in zeilen if '==' not in z]}"
    )

    import importlib.metadata as meta
    pins = dict(z.split("==") for z in zeilen)
    assert "ctrader-open-api" in pins, pins.keys()
    assert pins["ctrader-open-api"] == meta.version("ctrader-open-api"), (
        "Der Pin weicht von der laufenden Fassung ab - genau das soll die"
        " Datei verhindern."
    )
    print(f"OK  ctrader-open-api ist auf {pins['ctrader-open-api']} festgenagelt")


def test_requirements_erklaert_den_pyopenssl_konflikt():
    """Der bewusste Konflikt muss dokumentiert sein, sonst wird er repariert."""
    datei = Path(__file__).resolve().parent / "requirements.txt"
    text = datei.read_text(encoding="utf-8")
    for begriff in ("pyOpenSSL", "24.1.0", "BEWUSSTER KONFLIKT", "pip check"):
        assert begriff in text, f"'{begriff}' fehlt in requirements.txt"
    print("OK  Der pyOpenSSL-Konflikt ist in requirements.txt erklaert")


if __name__ == "__main__":
    for _name, _funktion in sorted(list(globals().items())):
        if _name.startswith("test_") and callable(_funktion):
            _funktion()
    print("\nAlle Tests fuer handel.py bestanden.")
