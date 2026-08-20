"""
strategien/orb.py — Baustein 4: Opening Range Breakout (Ausbruch aus der
Eroeffnungsspanne).

Herkunft und Beleg:
  Idee von Toby Crabel (1990). Moderner, veroeffentlichter Backtest:
  Zarattini & Aziz, "Can Day Trading Really Be Profitable?", 2023, SSRN
  4416622 (US-Aktien, 2016-2023). Details siehe Vault-Ressource ORB.

WICHTIG - Anpassung fuer Forex:
  Der Originalbeleg stammt vom US-AKTIENmarkt mit klarer Eroeffnung um
  9:30 ET. Forex laeuft 24/5 OHNE echte Eroeffnung. Deshalb ankern wir an
  den Beginn einer grossen Handelssitzung (Standard: London 07:00 UTC).
  Die Eroeffnungsspanne ist das Hoch/Tief der ersten OPENING_MINUTES nach
  diesem Anker. Der beste Anker und die beste Spannenlaenge unterscheiden
  sich je Markt und MUESSEN pro Instrument neu getestet werden.

WICHTIG - Datenbedarf:
  ORB braucht INTRADAY-Daten (z.B. 5- oder 15-Minuten-Kerzen) MIT Uhrzeit.
  Mit reinen Tagesdaten ist die Strategie NICHT testbar. Trifft dieser
  Baustein auf Daten ohne Intraday-Zeitstempel, loest er BEWUSST keine
  Trades aus (kein stiller Unsinn) - erkennbar an null Trades im Vergleich.

WICHTIG - Kosten:
  ORB handelt oft und ist sehr kostenempfindlich. Eine unabhaengige
  Replikation fand den Break-even schon bei geringer Slippage. Immer mit
  realistischen, eher zu hohen Kosten testen.

Signal-Logik (Long-only, passend zum backtesting.py-Rahmen):
  1. Taeglich ab dem Sitzungsanker die ersten OPENING_MINUTES beobachten,
     Hoch und Tief dieser Spanne festhalten.
  2. Nach Ablauf des Fensters: erster Schlusskurs ueber dem Spannenhoch
     -> Long. (Short-Seite hier bewusst weggelassen; der Rahmen testet
     zunaechst Long, wie die anderen Bausteine.)
  3. Stop = Spannentief (Gegenseite der Spanne). Ziel = Einstieg plus
     RR_RATIO mal Spannenbreite.
  4. Nur EIN Einstieg pro Tag. Position wird zum Sitzungsende glattgestellt.
"""
from __future__ import annotations

import datetime as dt

from backtesting import Strategy


class OpeningRangeBreakout(Strategy):
    # Sitzungsanker in UTC. 7 = London-Open (Sommerzeit grob), 13 = NY grob.
    session_start_hour = 7
    session_start_minute = 0
    opening_minutes = 30      # Laenge der Eroeffnungsspanne in Minuten
    session_length_hours = 8  # nach so vielen Stunden glattstellen
    rr_ratio = 2.0

    def init(self):
        # Zustand pro Handelstag
        self._akt_tag = None
        self._range_hoch = None
        self._range_tief = None
        self._range_fertig = False
        self._heute_gehandelt = False
        self._einstieg_zeit = None

    def _ist_intraday(self, zeit) -> bool:
        # Nur echte Intraday-Daten haben eine sinnvolle Uhrzeit.
        return isinstance(zeit, (dt.datetime,)) and not (
            zeit.hour == 0 and zeit.minute == 0 and zeit.second == 0
        )

    def next(self):
        zeit = self.data.index[-1]
        # Auf Tagesdaten (Zeit 00:00:00) macht ORB keinen Sinn -> nichts tun.
        if not self._ist_intraday(zeit):
            return

        tag = zeit.date()
        anker = dt.time(self.session_start_hour, self.session_start_minute)
        fenster_ende_minute = self.session_start_minute + self.opening_minutes
        fenster_ende_stunde = self.session_start_hour + fenster_ende_minute // 60
        fenster_ende = dt.time(fenster_ende_stunde % 24, fenster_ende_minute % 60)

        # Neuer Tag -> Zustand zuruecksetzen
        if tag != self._akt_tag:
            self._akt_tag = tag
            self._range_hoch = None
            self._range_tief = None
            self._range_fertig = False
            self._heute_gehandelt = False
            self._einstieg_zeit = None

        akt_zeit = zeit.time()
        hoch = self.data.High[-1]
        tief = self.data.Low[-1]
        kurs = self.data.Close[-1]

        # Zeit-Ausstieg: offene Position am Sitzungsende schliessen
        if self.position and self._einstieg_zeit is not None:
            offen_stunden = (zeit - self._einstieg_zeit).total_seconds() / 3600
            if offen_stunden >= self.session_length_hours:
                self.position.close()
            return

        # Phase 1: Eroeffnungsspanne aufbauen (Anker bis Fensterende)
        if anker <= akt_zeit < fenster_ende:
            self._range_hoch = hoch if self._range_hoch is None else max(self._range_hoch, hoch)
            self._range_tief = tief if self._range_tief is None else min(self._range_tief, tief)
            return

        # Fenster abgeschlossen?
        if akt_zeit >= fenster_ende and self._range_hoch is not None:
            self._range_fertig = True

        # Phase 2: auf den ersten Ausbruch ueber das Spannenhoch warten
        if (self._range_fertig and not self._heute_gehandelt
                and not self.position):
            spannen_breite = self._range_hoch - self._range_tief
            if spannen_breite <= 0:
                return
            if kurs > self._range_hoch:
                sl = self._range_tief
                tp = kurs + spannen_breite * self.rr_ratio
                self.buy(size=0.1, sl=sl, tp=tp)
                self._heute_gehandelt = True
                self._einstieg_zeit = zeit
