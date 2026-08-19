# Changelog — MT5 Trend+Pullback Bot (Community-Release v2)

> ⚠️ Auch dieser Changelog gilt nur für den **Demo-Betrieb**. Nichts hier
> ist eine Gewinngarantie oder Anlageberatung — s. `ANLEITUNG.md`.

## Was ist neu gegenüber der alten Discord-Version?

Die alte Version berechnete die Positionsgröße ("wie viele Lots kaufe
ich") mit einer selbst gebauten Formel aus Tick-Größe und Tick-Wert. Ein
aufmerksames Community-Mitglied (**danke an Steff**, der die alte
Gratis-Version über ChatGPT hat auditieren lassen) hat mehrere Punkte
daran zurecht bemängelt — dieselben Schwachstellen wurden hier
systematisch behoben:

### 🛠️ Behoben

1. **Positionsgröße kommt jetzt direkt vom Broker (`order_calc_profit`),
   nicht mehr aus einer selbst gebauten Formel.**
   Die alte Formel (`Stop-Abstand ÷ Tick-Größe × Tick-Wert`) hat bei
   Metallen (Gold/Silber/Platin) das tatsächliche Risiko teils massiv
   unterschätzt, weil sie Kontraktgröße und Währungsumrechnung nicht
   korrekt berücksichtigte. Der Bot fragt jetzt den Broker direkt: "Was
   würde dieses Volumen zwischen Einstieg und Stop-Loss kosten?" — das
   ist die Zahl, die der Broker beim echten Handel auch tatsächlich
   anwendet.

2. **Konsequentes Abrunden statt kaufmännischem Runden.**
   Die alte Version rundete die Lot-Größe normal (0,106 → 0,11), was im
   Zweifel MEHR Risiko bedeutet als geplant. Jetzt wird immer nach unten
   abgerundet — im Zweifel wird lieber etwas weniger riskiert als das
   Ziel, nie mehr.

3. **Doppelter Sicherheits-Wächter statt nur einem 2x-Check.**
   Zusätzlich zur bestehenden Prüfung (Mindest-Lot darf nicht mehr als
   das 2-fache Zielrisiko kosten) gibt es jetzt eine ZWEITE, finale
   Prüfung direkt vor dem Absenden der Order: das tatsächliche,
   broker-berechnete Risiko der endgültig gewählten Lot-Größe darf das
   1,5-fache des Ziels nicht übersteigen — sonst wird der Trade
   abgebrochen statt mit falscher Größe gesendet.

4. **Positionsgröße wird jetzt korrekt aus dem TATSÄCHLICH verwendeten
   Stop-Loss berechnet.** Hebt der Broker-Mindestabstand den Stop
   nachträglich an (kommt z. B. bei manchen Brokern/Marktphasen vor),
   floss vorher trotzdem der ursprüngliche, engere Stop-Abstand in die
   Risikoberechnung ein — das Ist-Risiko passte dann nicht mehr zur
   tatsächlichen Lot-Größe. Jetzt wird die Positionsgröße immer aus dem
   Stop-Loss berechnet, der wirklich in der Order steht.

5. **Echtes Ist-Risiko im Trade-Journal statt dem geplanten 1 %-Sollwert.**
   `trades.csv` zeigt jetzt, was für JEDEN einzelnen Trade tatsächlich
   berechnet und riskiert wurde — nicht mehr pauschal den Zielwert.

6. **Kein Absturz mehr beim ersten Trade-Abschluss (`history_select`-
   Absicherung).** Der Aufruf, der die Trade-Historie beim Broker lädt,
   existiert nicht in jeder Version des Python-Pakets. Der Bot prüft das
   jetzt vorher ab, statt beim ersten geschlossenen Trade mit einem
   Fehler abzubrechen.

7. **Schließungsgrund im Log/Journal jetzt korrekt.** Die alte Version
   nutzte feste Zahlen (3/4) für "durch Stop-Loss" bzw. "durch
   Take-Profit" geschlossen — auf manchen Brokern stimmen diese Zahlen
   aber nicht mit den echten MT5-Konstanten überein. Jetzt werden die
   echten Konstanten verwendet, mit Rückfalloption auf 3/4 falls sie
   fehlen sollten.

### ✅ Unverändert geblieben (bewusst!)

- Die eigentliche Handelsstrategie (EMA150-Trendfilter, RSI(14)-Pullback
  über 35, ATR(14)×2,0-Stop, Chance-Risiko-Verhältnis 2,0, ausschließlich
  Long) ist **exakt dieselbe wie im Backtest validiert** — daran wurde
  nichts geändert.
- Die Standard-Märkte (Gold, Silber, Platin auf Stundenkerzen; CHFJPY,
  USDJPY auf 4-Stunden-Kerzen) sind unverändert.
- Der Demo-Sicherheitsschalter (`ALLOW_REAL_ACCOUNT = False`) und der
  Schutz-Wächter, der nach jeder Order Stop-Loss/Take-Profit überprüft,
  waren schon vorher vorhanden und wurden nicht angetastet.

### 🔴 Noch offen (Ehrlichkeit vor Schönfärberei)

- Es gibt aktuell noch **keine Ausführungskontrolle nach einer
  Not-Schließung** — der Bot schickt den Schließungs-Befehl, prüft aber
  nicht aktiv nach, ob er auch wirklich angekommen ist. Das ist ein
  bekannter, noch offener Punkt aus demselben Community-Audit.
- Dieser Bot handelt bewusst NUR long (auf steigende Kurse). Das ist kein
  Fehler, sondern die validierte, getestete Konfiguration — eine
  Short-Variante wurde in ausführlichen Backtests separat geprüft und
  NICHT übernommen, weil sie die Prüfung nicht bestanden hat.

---

*Fragen, Bugs gefunden, oder etwas stimmt nicht? Meldet euch im Discord —
jeder ernsthafte Hinweis wird geprüft, genau wie beim letzten Mal.*
