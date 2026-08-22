#!/usr/bin/env bash
# Laedt die Instrumente der Quellbehauptung (Metalle + JPY-Paare) auf H1 und H4.
# Teiler 100000 ist per Kreuzkurs-Konsistenz geprueft und gilt hier einheitlich.
set -u
cd /opt/data/tradingbot
for SYM in XAUUSD XAGUSD CHFJPY USDJPY EURUSD; do
  for TF in H_1 H_4; do
    if [ -f "data/${SYM}_${TF}.csv" ]; then
      echo ">>> ${SYM} ${TF} bereits vorhanden, uebersprungen"
      continue
    fi
    echo ">>> ${SYM} ${TF}"
    python3 daten_mcp.py "$SYM" "$TF" 730 100000 2>&1 | tail -3
  done
done
echo "=== FERTIG ==="
wc -l data/*.csv
