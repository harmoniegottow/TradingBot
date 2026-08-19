# Forex-Tradingbot

Eigener, regelbasierter Handelsassistent fuer Devisen (Forex).
Broker: Pepperstone mit cTrader Open API. Erst Demokonto, spaeter kleines
Echtgeld. Ausfuehrlicher Plan im Obsidian-Vault unter
"02 Projekte/Tradingbot/Tradingbot.md".

## Stand

- Etappe 1 (Fundament): erledigt. Projekt, venv, Zugangsdaten in .env.
- Live-Zugang: blockiert, bis die WebID-Pruefung bei Pepperstone durch ist
  (dann OAuth-Token holen).
- Etappe 3/4 (Strategie + Backtest): in Arbeit, laeuft ohne Konto.

## Dateien

- `daten_laden.py`  — laedt historische Forex-Tagesdaten (Yahoo Finance) nach `data/`.
- `backtest.py`     — testet die Strategie "zwei gleitende Durchschnitte" mit Kosten.
- `.env`           — Zugangsdaten (NICHT im Repo, per .gitignore ausgeschlossen).

## Einrichtung

    uv venv .venv
    VIRTUAL_ENV=.venv uv pip install ctrader-open-api python-dotenv pandas yfinance backtesting

## Nutzung

    .venv/bin/python daten_laden.py     # Daten holen
    .venv/bin/python backtest.py        # Strategie testen

## Wichtige Regeln

- Zugangsdaten (client_id, client_secret, Token) NUR in .env, nie ins Repo.
- Immer erst Demo, dann Echtgeld. Jede Aenderung diesen Weg gehen lassen.
- Backtest-Ergebnisse kritisch pruefen: ein zu schoenes Ergebnis ist meist
  ein Fehler in der Rechnung oder Ueberanpassung an die Vergangenheit.
