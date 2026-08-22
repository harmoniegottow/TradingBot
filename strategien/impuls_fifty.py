"""
strategien/impuls_fifty.py — Baustein 5: Ruecksetzer auf die Mitte einer
Impulsbewegung, mit Bestaetigungskerze.

Herkunft:
  TikTok-Video von cem_trades (18.08.2026, tiktok.com/@cem_trades/video/
  7675309392526396694). Regeln aus dem Tonspur-Transkript abgeleitet.

  WICHTIG: Das Video liefert KEINEN Beleg. Kein Backtest, kein Zeitraum, kein
  Markt, keine Zahlen. Der Urheber verweist am Ende auf seine kostenpflichtige
  Academy - das Video ist Werbung, nicht Nachweis. Diese Umsetzung dient dazu,
  die Regeln SELBST nachzurechnen. Details siehe Vault-Ressource "Impuls-Fifty".

Zur Definition des Impulses (wichtige Praezisierung vom 22.08.2026):
  Erste Fassung zaehlte stur acht aufeinanderfolgende positive Kerzen. Das war
  zu woertlich. Dominique hat klargestellt: Im Video ging es um die DARSTELLUNG
  eines klaren Aufwaertstrends OHNE Ruecklauf, nicht um eine exakte Kerzenzahl.

  Deshalb wird der Impuls jetzt ueber seine Geradlinigkeit gemessen:
  Eine Bewegung von einem Tief zu einem Hoch gilt als Impuls, wenn der
  GROESSTE Rueckschlag INNERHALB der Bewegung klein bleibt (Anteil
  max_rueck an der Gesamthoehe). Genau das ist "ohne Ruecklauf" - objektiv
  messbar und unabhaengig davon, ob jede einzelne Kerze positiv schliesst.

Signal-Logik (Long-only):
  1. IMPULS suchen: im Rueckblickfenster das tiefste Tief und danach das
     hoechste Hoch. Bedingungen:
       - Hoehe mindestens min_atr mal ATR (Bewegung muss bedeutsam sein)
       - mindestens min_kerzen Kerzen Dauer
       - groesster Rueckschlag innerhalb der Bewegung hoechstens
         max_rueck der Gesamthoehe  ->  "ohne Ruecklauf"
       - die Bewegung ist beendet (Kurs steht unter dem Hoch)
  2. MITTE: 50-Prozent-Niveau zwischen Impulstief und -hoch. Einziges Niveau.
  3. ABWARTEN, bis der Kurs in dieses Niveau zurueckfaellt.
  4. ERSTE PRUEFUNG: Schaffen die Verkaeufer max_gegenkerzen Folgekerzen im
     Ruecksetzer, wird der Aufbau verworfen (Gegenseite zu stark).
  5. BESTAETIGUNG: eine Kerze, die UEBER dem Hoch der Vorkerze schliesst.
     Das ist das Einstiegssignal.
  6. STOP: so weit unter dem Einstieg, wie der Ruecksetzer lang ist.
  7. ZIEL: festes Chance-Risiko-Verhaeltnis von rr_ratio zu eins.

  Verworfen wird ausserdem, wenn der Kurs unter das Impulstief faellt
  (Bewegung gebrochen) oder zu viele Kerzen ohne Bestaetigung verstreichen.
"""
from __future__ import annotations

import numpy as np
from backtesting import Strategy

from strategien.indikatoren import atr


class ImpulsFifty(Strategy):
    # --- Impulserkennung ---
    rueckblick = 40          # wie viele Kerzen rueckwaerts nach dem Impuls suchen
    min_kerzen = 4           # Mindestdauer der Bewegung in Kerzen
    min_atr = 3.0            # Mindesthoehe der Bewegung in ATR-Einheiten
    max_rueck = 0.30         # max. Rueckschlag INNERHALB der Bewegung (30 %)
    atr_len = 14

    # --- Ruecksetzer und Einstieg ---
    max_gegenkerzen = 3      # so viele Gegenkerzen im Ruecksetzer -> verwerfen
    rr_ratio = 2.0
    max_wartekerzen = 30     # nach so vielen Kerzen ohne Einstieg verwerfen

    def init(self):
        self.atr_wert = self.I(
            atr, self.data.High, self.data.Low, self.data.Close, self.atr_len
        )
        self._imp_hoch = None
        self._imp_tief = None
        self._mitte = None
        self._mitte_beruehrt = False
        self._gegen_serie = 0
        self._rueck_tief = None
        self._warte = 0

    def _verwerfen(self):
        self._imp_hoch = None
        self._imp_tief = None
        self._mitte = None
        self._mitte_beruehrt = False
        self._gegen_serie = 0
        self._rueck_tief = None
        self._warte = 0

    def _impuls_suchen(self):
        """
        Sucht im Rueckblickfenster eine geradlinige Aufwaertsbewegung.
        Gibt (tief, hoch) zurueck oder None.
        """
        n = min(self.rueckblick, len(self.data.Close) - 1)
        if n < self.min_kerzen + 2:
            return None

        hoch_arr = np.asarray(self.data.High[-n:], dtype=float)
        tief_arr = np.asarray(self.data.Low[-n:], dtype=float)

        atr_akt = float(self.atr_wert[-1])
        if not np.isfinite(atr_akt) or atr_akt <= 0:
            return None

        # Startpunkt: tiefstes Tief im Fenster
        i_start = int(np.argmin(tief_arr))
        # Endpunkt: hoechstes Hoch NACH dem Startpunkt
        if i_start >= len(hoch_arr) - self.min_kerzen:
            return None
        i_ende = i_start + int(np.argmax(hoch_arr[i_start:]))
        if i_ende - i_start < self.min_kerzen:
            return None

        tief = float(tief_arr[i_start])
        hoch = float(hoch_arr[i_ende])
        hoehe = hoch - tief
        if hoehe < self.min_atr * atr_akt:
            return None

        # --- Kernpruefung: groesster Rueckschlag INNERHALB der Bewegung ---
        # Laufendes Hoch mitfuehren, groessten Abstand nach unten messen.
        lauf_hoch = tief
        max_rueckschlag = 0.0
        for k in range(i_start, i_ende + 1):
            lauf_hoch = max(lauf_hoch, hoch_arr[k])
            rueckschlag = lauf_hoch - tief_arr[k]
            max_rueckschlag = max(max_rueckschlag, rueckschlag)
        if max_rueckschlag > self.max_rueck * hoehe:
            return None   # zu zappelig, kein klarer Anstieg "ohne Ruecklauf"

        # Die Bewegung muss beendet sein: Kurs steht unter dem Hoch
        if float(self.data.Close[-1]) >= hoch:
            return None

        return tief, hoch

    def next(self):
        o = float(self.data.Open[-1])
        h = float(self.data.High[-1])
        t = float(self.data.Low[-1])
        c = float(self.data.Close[-1])
        negativ = c < o

        # --- Phase 1: Impuls suchen, solange keiner vorliegt --------------
        if self._mitte is None:
            gefunden = self._impuls_suchen()
            if gefunden is None:
                return
            self._imp_tief, self._imp_hoch = gefunden
            self._mitte = (self._imp_hoch + self._imp_tief) / 2.0
            self._mitte_beruehrt = False
            self._gegen_serie = 0
            self._rueck_tief = None
            self._warte = 0
            return

        if self.position:
            return

        self._warte += 1
        if self._warte > self.max_wartekerzen:
            self._verwerfen()
            return

        # Bewegung gebrochen -> Aufbau ungueltig
        if c < self._imp_tief:
            self._verwerfen()
            return

        self._rueck_tief = t if self._rueck_tief is None else min(self._rueck_tief, t)

        # --- Phase 2: Ruecksetzer erreicht die Mitte? ---------------------
        if not self._mitte_beruehrt:
            if t <= self._mitte:
                self._mitte_beruehrt = True
            else:
                return

        # --- Phase 3: Gegenkerzen zaehlen (Verkaeufer zu stark?) ---------
        if negativ:
            self._gegen_serie += 1
            if self._gegen_serie >= self.max_gegenkerzen:
                self._verwerfen()
                return
        else:
            self._gegen_serie = 0

        # --- Phase 4: Bestaetigung = Schluss ueber dem Hoch der Vorkerze --
        if c <= float(self.data.High[-2]):
            return

        stop_dist = c - self._rueck_tief
        if not (stop_dist > 0):
            return

        self.buy(size=0.1, sl=c - stop_dist, tp=c + stop_dist * self.rr_ratio)
        self._verwerfen()
