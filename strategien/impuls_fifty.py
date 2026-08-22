"""
strategien/impuls_fifty.py — Baustein 5: Rücksetzer auf die Mitte einer
Impulsbewegung, mit Bestaetigungskerze.

Herkunft:
  TikTok-Video von cem_trades (18.08.2026, tiktok.com/@cem_trades/video/
  7675309392526396694). Regeln aus dem Tonspur-Transkript abgeleitet, die
  Definition der "starken Bewegung" (acht bis zehn positive Folgekerzen) von
  Dominique aus dem Bild ergaenzt.

  WICHTIG: Das Video liefert KEINEN Beleg. Kein Backtest, kein Zeitraum, kein
  Markt, keine Zahlen genannt. Der Urheber verweist am Ende auf seine
  kostenpflichtige Academy - das Video ist Werbung, nicht Nachweis. Diese
  Umsetzung dient dazu, die Regeln SELBST nachzurechnen, statt sie zu glauben.
  Details siehe Vault-Ressource "Impuls-Fifty".

Signal-Logik (Long-only):
  1. IMPULS erkennen: mindestens IMPULS_KERZEN aufeinanderfolgende positive
     Kerzen (Schluss ueber Eroeffnung). Endet die Serie, ist der Impuls fertig.
     Hoch = hoechstes Hoch der Serie, Tief = tiefstes Tief der Serie.
  2. MITTE berechnen: 50-Prozent-Niveau genau zwischen Hoch und Tief. Das ist
     das einzige verwendete Niveau.
  3. ABWARTEN, bis der Kurs in dieses Niveau zurueckfaellt (Tief der Kerze
     erreicht das Niveau oder faellt darunter).
  4. ERSTE PRUEFUNG: Haben die Verkaeufer im Ruecksetzer MAX_GEGENKERZEN
     Folgekerzen in dieselbe Richtung geschafft? Wenn ja, Aufbau verwerfen
     (die Gegenseite ist zu stark). Wenn nein, weiter.
  5. BESTAETIGUNG abwarten: eine Kerze, die UEBER dem Hoch der Vorkerze
     schliesst. Das ist das Einstiegssignal.
  6. STOP: so weit unter dem Einstieg, wie der Ruecksetzer lang ist
     (Einstieg minus tiefstes Tief seit Beginn des Ruecksetzers).
  7. ZIEL: festes Chance-Risiko-Verhaeltnis von RR_RATIO zu eins.

  Verworfen wird der Aufbau ausserdem, wenn der Kurs unter das Impulstief
  faellt (dann ist die Bewegung gebrochen) oder wenn zu viele Kerzen ohne
  Bestaetigung verstreichen.

Datenbedarf:
  Funktioniert auf jedem Zeitrahmen mit OHLC-Kerzen. Der Zeitrahmen, auf dem
  die Strategie gemeint war, wird im Video NICHT genannt - das muss pro Markt
  und Zeitrahmen selbst geprueft werden.
"""
from __future__ import annotations

from backtesting import Strategy


class ImpulsFifty(Strategy):
    impuls_kerzen = 8        # Mindestzahl positiver Folgekerzen fuer den Impuls
    max_gegenkerzen = 3      # so viele Gegenkerzen im Ruecksetzer -> verwerfen
    rr_ratio = 2.0           # Chance-Risiko-Verhaeltnis
    max_wartekerzen = 30     # nach so vielen Kerzen ohne Einstieg verwerfen

    def init(self):
        # Impulszaehler
        self._pos_serie = 0
        # Fertiger Impuls, auf den wir warten
        self._imp_hoch = None
        self._imp_tief = None
        self._mitte = None
        # Ruecksetzer-Zustand
        self._mitte_beruehrt = False
        self._gegen_serie = 0
        self._rueck_tief = None
        self._warte = 0

    def _aufbau_verwerfen(self):
        self._imp_hoch = None
        self._imp_tief = None
        self._mitte = None
        self._mitte_beruehrt = False
        self._gegen_serie = 0
        self._rueck_tief = None
        self._warte = 0

    def next(self):
        o = self.data.Open[-1]
        h = self.data.High[-1]
        t = self.data.Low[-1]
        c = self.data.Close[-1]

        positiv = c > o
        negativ = c < o

        # --- Schritt 1: Impuls zaehlen -------------------------------------
        if self._mitte is None:
            if positiv:
                self._pos_serie += 1
            else:
                # Serie endet. War sie lang genug, ist der Impuls fertig.
                if self._pos_serie >= self.impuls_kerzen:
                    n = self._pos_serie
                    # Hoch/Tief der Impulsserie (die n Kerzen vor dieser)
                    hochs = [self.data.High[-1 - i] for i in range(1, n + 1)]
                    tiefs = [self.data.Low[-1 - i] for i in range(1, n + 1)]
                    self._imp_hoch = max(hochs)
                    self._imp_tief = min(tiefs)
                    if self._imp_hoch > self._imp_tief:
                        self._mitte = (self._imp_hoch + self._imp_tief) / 2.0
                        self._mitte_beruehrt = False
                        self._gegen_serie = 0
                        self._rueck_tief = None
                        self._warte = 0
                self._pos_serie = 0
            return

        # --- Ab hier liegt ein fertiger Impuls vor -------------------------
        if self.position:
            return

        self._warte += 1
        if self._warte > self.max_wartekerzen:
            self._aufbau_verwerfen()
            return

        # Impuls gebrochen -> Aufbau ungueltig
        if c < self._imp_tief:
            self._aufbau_verwerfen()
            return

        # Tiefsten Punkt des Ruecksetzers mitfuehren
        self._rueck_tief = t if self._rueck_tief is None else min(self._rueck_tief, t)

        # --- Schritt 3: Ruecksetzer erreicht die Mitte? --------------------
        if not self._mitte_beruehrt:
            if t <= self._mitte:
                self._mitte_beruehrt = True
            else:
                return

        # --- Schritt 4: Gegenkerzen zaehlen (Verkaeufer zu stark?) --------
        if negativ:
            self._gegen_serie += 1
            if self._gegen_serie >= self.max_gegenkerzen:
                self._aufbau_verwerfen()
                return
        else:
            self._gegen_serie = 0

        # --- Schritt 5: Bestaetigung = Schluss ueber dem Hoch der Vorkerze -
        vor_hoch = self.data.High[-2]
        if c <= vor_hoch:
            return

        # --- Schritt 6/7: Stop = Laenge des Ruecksetzers, Ziel = RR --------
        stop_dist = c - self._rueck_tief
        if not (stop_dist > 0):
            return

        self.buy(size=0.1, sl=c - stop_dist, tp=c + stop_dist * self.rr_ratio)
        self._aufbau_verwerfen()
