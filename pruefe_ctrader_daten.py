#!/usr/bin/env python3
"""pruefe_ctrader_daten.py - Integritaetsbericht ueber data-ctrader/.

Je Symbol und Zeitrahmen: erste und letzte Kerze, Anzahl, doppelte
Zeitstempel, Luecken laenger als ein Wochenende, Kerzen mit Volumen null,
unplausible Spannen.

Der Bericht benennt Auffaelligkeiten mit Datum. Er mittelt nichts weg: eine
saubere Kennzahl mit einem versteckten Ausreisser darin ist genau die Art
Zahl, die spaeter teuer wird.

Aufruf:

    .venv/bin/python pruefe_ctrader_daten.py            # alles
    .venv/bin/python pruefe_ctrader_daten.py XAUUSD     # nur ein Symbol
"""
from __future__ import annotations

import csv
import re
import sys
from collections import Counter
from pathlib import Path

import pandas as pd

ORDNER = Path(__file__).resolve().parent / "data-ctrader"
VERDAECHTIG_DATEI = ORDNER / "verdaechtige_kerzen.csv"
ENTFERNT_DATEI = ORDNER / "entfernte_kerzen.csv"
# Die ersten sechs Spalten sind die vereinbarte Schnittstelle; danach folgt
# Zusammenhang, damit sich eine Kerze ohne Blick in die Rohdatei einordnen laesst.
VERDAECHTIG_SPALTEN = ("symbol", "zeitrahmen", "zeitstempel", "auffaelligkeit",
                       "kennzahl", "urteil", "open", "high", "low", "close",
                       "volumen", "median_nachbarn")
# Erlaubte Eintraege in der Spalte urteil - von Hand zu setzen.
URTEILE = ("fehltick", "echtes ereignis")
# Paare, deren Zeitstempel nach dem Bereinigen noch zusammenpassen muessen.
PAARE = (("XAUUSD", "XAGUSD"),)
# Ein normales Wochenende dauert gut zwei Tage. Alles darueber wird genannt.
WOCHENENDE = pd.Timedelta(days=3)
# Kerzenlaenge je Dateisuffix, in Minuten.
LAENGE = {"M_1": 1, "M_5": 5, "M_15": 15, "M_30": 30,
          "H_1": 60, "H_4": 240, "D_1": 1440, "W_1": 10080}
# Ab dieser Spanne innerhalb einer Kerze wird nachgefragt.
SPANNE_GRENZE_PROZENT = 10.0
# So oft muss dieselbe Pause wiederkehren, um als Marktstruktur zu gelten.
PAUSE_MINDESTZAHL = 20
# Nachbarkerzen links und rechts, an denen ein Ausreisser gemessen wird.
NACHBARN = 5
# So weit darf ein Docht ueber die Nachbarkerzen hinausragen, bevor er
# als Fehltick gilt statt als Marktbewegung.
DOCHT_GRENZE = 0.90
BEISPIELE = 5


def dateien_finden(filter_symbol: str | None) -> list:
    """Kursdateien - die Protokolldateien gehoeren nicht dazu."""
    if not ORDNER.exists():
        raise SystemExit(f"{ORDNER} fehlt - erst lade_ctrader_voll.py laufen lassen.")
    protokolle = {VERDAECHTIG_DATEI.name, ENTFERNT_DATEI.name}
    dateien = sorted(p for p in ORDNER.glob("*.csv")
                     if not p.name.startswith(".") and p.name not in protokolle)
    if filter_symbol:
        dateien = [p for p in dateien if p.name.upper().startswith(filter_symbol.upper())]
    return dateien


def zerlegen(name: str) -> tuple[str, str]:
    treffer = re.match(r"^(.+)_([MHDW]_\d+)$", name)
    return treffer.groups() if treffer else (name, "?")


def luecken_finden(index: pd.DatetimeIndex, minuten: int) -> tuple[list, list, dict]:
    """Trennt lange Luecken, taegliche Handelspausen und echte Loecher.

    Metalle und Indizes pausieren jeden Abend. Diese Pausen als Loecher zu
    melden waere Laerm - sie wandern aber mit der Sommerzeit durch die
    Stunden, deshalb wird jede Kombination aus Stunde und Dauer gezaehlt und
    ab einer Mindestzahl als Struktur gewertet.
    """
    dauer = pd.Timedelta(minutes=minuten)
    abstaende = index.to_series().diff()
    lang, kandidaten = [], []
    for zeit, abstand in abstaende.items():
        if pd.isna(abstand) or abstand <= dauer:
            continue
        if abstand > WOCHENENDE:
            lang.append((zeit, abstand))
        elif zeit.weekday() not in (0, 6):
            # Montag und Sonntag tragen den Wochenendsprung.
            kandidaten.append((zeit, abstand))

    haeufigkeit = Counter((zeit.hour, abstand) for zeit, abstand in kandidaten)
    pausen = {muster: anzahl for muster, anzahl in haeufigkeit.items()
              if anzahl >= PAUSE_MINDESTZAHL}
    loecher = [(zeit, abstand) for zeit, abstand in kandidaten
               if (zeit.hour, abstand) not in pausen]
    return lang, loecher, pausen


def docht_pruefen(df: pd.DataFrame, zeit) -> str:
    """Stuetzen die Nachbarkerzen den Ausschlag - oder ist es ein Fehltick?"""
    stelle = df.index.get_loc(zeit)
    umfeld = df.iloc[max(0, stelle - NACHBARN):stelle + NACHBARN + 1].drop(index=zeit)
    if umfeld.empty:
        return "kein Umfeld"
    zeile = df.loc[zeit]
    if zeile["Low"] < umfeld["Low"].min() * DOCHT_GRENZE:
        return (f"Fehltick nach unten (Low {zeile['Low']}, Nachbarn tiefstens"
                f" {umfeld['Low'].min()}, Open {zeile['Open']},"
                f" Close {zeile['Close']})")
    if zeile["High"] > umfeld["High"].max() / DOCHT_GRENZE:
        return (f"Fehltick nach oben (High {zeile['High']}, Nachbarn hoechstens"
                f" {umfeld['High'].max()}, Open {zeile['Open']},"
                f" Close {zeile['Close']})")
    return "vom Umfeld gestuetzt - vermutlich echte Bewegung"


def spannen_pruefen(df: pd.DataFrame) -> dict:
    hoch, tief = df["High"], df["Low"]
    verdreht = df[hoch < tief]
    ausserhalb = df[(df["Open"] > hoch) | (df["Open"] < tief)
                    | (df["Close"] > hoch) | (df["Close"] < tief)]
    spanne = (hoch - tief) / tief.abs() * 100
    weit = df[spanne > SPANNE_GRENZE_PROZENT]
    fehltick = [zeit for zeit in weit.index
                if docht_pruefen(df, zeit).startswith("Fehltick")]
    return {"verdreht": verdreht, "ausserhalb": ausserhalb, "weit": weit,
            "spanne": spanne, "fehltick": fehltick}


def bericht(pfad: Path) -> dict:
    symbol, zeitrahmen = zerlegen(pfad.stem)
    df = pd.read_csv(pfad, index_col=0, parse_dates=True)
    if df.index.tz is not None:
        df.index = df.index.tz_localize(None)
    df = df.sort_index()
    minuten = LAENGE.get(zeitrahmen, 60)

    doppelt = df.index[df.index.duplicated()]
    lang, innerhalb, pausen = luecken_finden(df.index, minuten)
    null_volumen = df[df["Volume"] == 0]
    spannen = spannen_pruefen(df)

    befund = {
        "symbol": symbol, "zeitrahmen": zeitrahmen, "anzahl": len(df),
        "von": df.index.min(), "bis": df.index.max(),
        "doppelt": doppelt, "lang": lang, "innerhalb": innerhalb,
        "pausen": pausen, "null_volumen": null_volumen, "df": df, **spannen,
    }
    # Wiederkehrende Handelspausen sind Struktur, kein Befund.
    befund["sauber"] = not (len(doppelt) or lang or innerhalb
                            or len(null_volumen) or len(spannen["verdreht"])
                            or len(spannen["ausserhalb"]) or spannen["fehltick"])
    return befund


def zeile_ausgeben(b: dict) -> None:
    print(f"   {b['symbol']:<9}{b['zeitrahmen']:<6}{b['anzahl']:>8}"
          f"  {b['von']:%Y-%m-%d}  {b['bis']:%Y-%m-%d}"
          f"{len(b['doppelt']):>7}{len(b['lang']):>8}{len(b['innerhalb']):>8}"
          f"{sum(b['pausen'].values()):>8}{len(b['null_volumen']):>8}"
          f"{len(b['weit']):>8}{len(b['fehltick']):>9}")


def auffaelligkeiten(b: dict) -> None:
    kopf = f"{b['symbol']} {b['zeitrahmen']}"
    if len(b["doppelt"]):
        print(f"\n   {kopf}: {len(b['doppelt'])} doppelte Zeitstempel")
        for zeit in b["doppelt"][:BEISPIELE]:
            print(f"      {zeit}")
    if b["lang"]:
        print(f"\n   {kopf}: {len(b['lang'])} Luecken laenger als ein Wochenende")
        for zeit, abstand in sorted(b["lang"], key=lambda x: -x[1])[:BEISPIELE]:
            print(f"      bis {zeit}: {abstand}")
    if b["innerhalb"]:
        print(f"\n   {kopf}: {len(b['innerhalb'])} Loecher mitten in der Woche"
              " (ohne die wiederkehrenden Handelspausen)")
        for zeit, abstand in sorted(b["innerhalb"], key=lambda x: -x[1])[:BEISPIELE]:
            print(f"      bis {zeit}: {abstand}")
    if len(b["null_volumen"]):
        tage = Counter(b["null_volumen"].index.day_name())
        print(f"\n   {kopf}: {len(b['null_volumen'])} Kerzen mit Volumen null"
              f" - Wochentage: {dict(tage)}")
        for zeit in b["null_volumen"].index[:BEISPIELE]:
            print(f"      {zeit}")
    for schluessel, text in (("verdreht", "High kleiner als Low"),
                             ("ausserhalb", "Open/Close ausserhalb High-Low")):
        if len(b[schluessel]):
            print(f"\n   {kopf}: {len(b[schluessel])} Kerzen mit {text}")
            for zeit in b[schluessel].index[:BEISPIELE]:
                print(f"      {zeit}")
    if len(b["weit"]):
        print(f"\n   {kopf}: {len(b['weit'])} Kerzen mit Spanne ueber"
              f" {SPANNE_GRENZE_PROZENT} %, davon {len(b['fehltick'])}"
              " ohne Rueckhalt im Umfeld")
        groesste = b["spanne"].loc[b["weit"].index].sort_values(ascending=False)
        for zeit, wert in groesste[:BEISPIELE].items():
            print(f"      {zeit}: {wert:.2f} %  {docht_pruefen(b['df'], zeit)}")


def kandidaten_sammeln(befunde: list) -> list:
    """Alle auffaelligen Kerzen als Zeilen fuer verdaechtige_kerzen.csv.

    Die Spalte urteil bleibt leer: ob ein Ausschlag ein Fehltick oder ein
    echtes Ereignis war, entscheidet ein Mensch. Das Kriterium "vom Umfeld
    nicht gestuetzt" findet beides - der 15.01.2015 (Aufhebung des
    Franken-Mindestkurses) sieht darin genauso aus wie ein kaputter Tick.
    """
    zeilen = []
    for b in befunde:
        df = b["df"]
        for zeit in b["weit"].index:
            zeilen.append(kandidat_bauen(b, df, zeit, "spanne ueber grenze",
                                         b["spanne"].loc[zeit]))
        for schluessel, art in (("verdreht", "high kleiner low"),
                                ("ausserhalb", "open/close ausserhalb high-low")):
            for zeit in b[schluessel].index:
                zeilen.append(kandidat_bauen(b, df, zeit, art, float("nan")))
    return sorted(zeilen, key=lambda z: (z["symbol"], z["zeitrahmen"],
                                         z["zeitstempel"]))


def kandidat_bauen(b: dict, df: pd.DataFrame, zeit, art: str, spanne) -> dict:
    stelle = df.index.get_loc(zeit)
    umfeld = df.iloc[max(0, stelle - NACHBARN):stelle + NACHBARN + 1].drop(index=zeit)
    zeile = df.loc[zeit]
    if art == "spanne ueber grenze" and zeit in b["fehltick"]:
        art = "spanne ueber grenze, vom umfeld nicht gestuetzt"

    # Kennzahl: Abweichung vom Median der Nachbarkerzen, in Prozent.
    if umfeld.empty:
        median, kennzahl = float("nan"), spanne
    elif zeile["Low"] < umfeld["Low"].median():
        median = umfeld["Low"].median()
        kennzahl = (median - zeile["Low"]) / abs(median) * 100
    else:
        median = umfeld["High"].median()
        kennzahl = (zeile["High"] - median) / abs(median) * 100

    return {"symbol": b["symbol"], "zeitrahmen": b["zeitrahmen"],
            "zeitstempel": f"{zeit:%Y-%m-%d %H:%M:%S}", "auffaelligkeit": art,
            "kennzahl": f"{kennzahl:.2f}", "urteil": "",
            "open": zeile["Open"], "high": zeile["High"], "low": zeile["Low"],
            "close": zeile["Close"], "volumen": int(zeile["Volume"]),
            "median_nachbarn": f"{median:.5f}" if median == median else ""}


def verdaechtige_schreiben(zeilen: list) -> None:
    """Schreibt die Kandidatenliste - bereits gefaellte Urteile bleiben stehen."""
    bisher = {}
    if VERDAECHTIG_DATEI.exists():
        with VERDAECHTIG_DATEI.open(newline="", encoding="utf-8") as datei:
            for satz in csv.DictReader(datei):
                if satz.get("urteil"):
                    schluessel = (satz["symbol"], satz["zeitrahmen"],
                                  satz["zeitstempel"])
                    bisher[schluessel] = satz["urteil"]
    uebernommen = 0
    for zeile in zeilen:
        schluessel = (zeile["symbol"], zeile["zeitrahmen"], zeile["zeitstempel"])
        if schluessel in bisher:
            zeile["urteil"] = bisher[schluessel]
            uebernommen += 1

    ORDNER.mkdir(exist_ok=True)
    with VERDAECHTIG_DATEI.open("w", newline="", encoding="utf-8") as datei:
        schreiber = csv.DictWriter(datei, fieldnames=VERDAECHTIG_SPALTEN)
        schreiber.writeheader()
        schreiber.writerows(zeilen)
    print(f"\n   {len(zeilen)} Kandidaten in {VERDAECHTIG_DATEI.name}"
          f" ({uebernommen} bereits beurteilt).")
    print(f"   Spalte urteil von Hand fuellen: {' oder '.join(URTEILE)}.")


def fehltick_zeitstempel(symbol: str, zeitrahmen: str) -> set:
    """Zeitstempel, die von Hand als fehltick eingestuft wurden.

    Dafuer gedacht, dass der Pruefstand spaeter mit und ohne diese Kerzen
    rechnen kann - haengt ein Ergebnis an einzelnen kaputten Kerzen, muss
    das sichtbar werden.
    """
    if not VERDAECHTIG_DATEI.exists():
        return set()
    with VERDAECHTIG_DATEI.open(newline="", encoding="utf-8") as datei:
        return {pd.Timestamp(satz["zeitstempel"]) for satz in csv.DictReader(datei)
                if satz["symbol"] == symbol and satz["zeitrahmen"] == zeitrahmen
                and satz["urteil"].strip().lower() == "fehltick"}


def entfernte_zusammenfassen() -> None:
    """Haeufungen an einzelnen Tagen sichtbar machen."""
    print("\n" + "=" * 86)
    print("Zentral entfernte Kerzen (Volumen null)")
    print("=" * 86)
    if not ENTFERNT_DATEI.exists():
        print("   Kein Protokoll vorhanden.")
        return
    tabelle = pd.read_csv(ENTFERNT_DATEI, parse_dates=["Zeit"])
    if tabelle.empty:
        print("   Nichts entfernt.")
        return
    print(f"   {len(tabelle)} Kerzen aus {tabelle['Symbol'].nunique()} Symbolen.")
    tage = tabelle.groupby(tabelle["Zeit"].dt.date).size().sort_values(ascending=False)
    wochentage = tabelle["Zeit"].dt.day_name().value_counts()
    print(f"   Wochentage: {dict(wochentage)}")
    print(f"\n   Tage mit den meisten Entfernungen (von {len(tage)} Tagen):")
    print(f"      {'Datum':<14}{'Wochentag':<12}{'Kerzen':>7}")
    for datum, anzahl in tage.head(10).items():
        tag = pd.Timestamp(datum)
        marke = ""
        if (tag.month, tag.day) in ((12, 24), (12, 25), (12, 26), (12, 31), (1, 1)):
            marke = "   <== Feiertag: koennen echte umsatzlose Stunden sein"
        elif tag.weekday() != 6:
            marke = "   <== kein Sonntag: moeglicherweise Handelsunterbrechung"
        print(f"      {str(datum):<14}{tag.day_name():<12}{anzahl:>7}{marke}")

    ausser_sonntag = tabelle[tabelle["Zeit"].dt.weekday != 6]
    if not ausser_sonntag.empty:
        print(f"\n   {len(ausser_sonntag)} Entfernungen ausserhalb des Sonntags"
              " - diese bitte einzeln ansehen:")
        for _, satz in ausser_sonntag.head(BEISPIELE * 2).iterrows():
            print(f"      {satz['Symbol']:<8}{satz['Zeitrahmen']:<6}"
                  f"{satz['Zeit']}  {satz['Zeit'].day_name()}")
        if len(ausser_sonntag) > BEISPIELE * 2:
            print(f"      ... und {len(ausser_sonntag) - BEISPIELE * 2} weitere"
                  f" in {ENTFERNT_DATEI.name}")


def paare_pruefen() -> None:
    """Passen die Zeitstempel der Paare nach dem Bereinigen noch zusammen?"""
    print("\n" + "=" * 86)
    print("Deckungsgleichheit der Paare nach dem Bereinigen")
    print("=" * 86)
    for links, rechts in PAARE:
        for zeitrahmen in ("H_1", "H_4"):
            pfad_a = ORDNER / f"{links}_{zeitrahmen}.csv"
            pfad_b = ORDNER / f"{rechts}_{zeitrahmen}.csv"
            if not (pfad_a.exists() and pfad_b.exists()):
                print(f"   {links}/{rechts} {zeitrahmen}: Datei fehlt")
                continue
            a = pd.read_csv(pfad_a, index_col=0, parse_dates=True).index
            b = pd.read_csv(pfad_b, index_col=0, parse_dates=True).index
            gemeinsam = a.intersection(b)
            nur_a, nur_b = a.difference(b), b.difference(a)
            urteil = ("deckungsgleich" if not len(nur_a) and not len(nur_b)
                      else "ABWEICHUNG")
            print(f"   {links}/{rechts} {zeitrahmen}: {len(gemeinsam)} gemeinsam,"
                  f" nur {links} {len(nur_a)}, nur {rechts} {len(nur_b)}"
                  f"   {urteil}")
            for name, fehlend in ((links, nur_a), (rechts, nur_b)):
                for zeit in fehlend[:BEISPIELE]:
                    print(f"      nur in {name}: {zeit}")


def main() -> int:
    filter_symbol = sys.argv[1] if len(sys.argv) > 1 else None
    dateien = dateien_finden(filter_symbol)
    if not dateien:
        print("Keine Dateien gefunden.")
        return 1

    print("=" * 86)
    print(f"Integritaetsbericht data-ctrader/ ({len(dateien)} Dateien)")
    print("=" * 86)
    print(f"   {'Symbol':<9}{'TF':<6}{'Kerzen':>8}  {'von':<12}{'bis':<12}"
          f"{'dopp.':>7}{'Luecken':>8}{'Loecher':>8}{'Pausen':>8}{'Vol 0':>8}"
          f"{'Spanne':>8}{'Fehltick':>9}")
    print("   " + "-" * 97)

    befunde = [bericht(pfad) for pfad in dateien]
    for b in befunde:
        zeile_ausgeben(b)

    print("\n" + "=" * 86)
    print("Auffaelligkeiten im Einzelnen")
    print("=" * 86)
    auffaellig = [b for b in befunde if not b["sauber"]]
    if not auffaellig:
        print("   Keine.")
    for b in auffaellig:
        auffaelligkeiten(b)

    verdaechtige_schreiben(kandidaten_sammeln(befunde))
    entfernte_zusammenfassen()
    paare_pruefen()

    print(f"\n{len(befunde) - len(auffaellig)} von {len(befunde)} Dateien"
          " ohne Befund.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
