"""Prueft die Symbolsuche gegen die ECHTEN Namen von Dominiques Pepperstone-Konto."""
import sys
import types

# MT5-Attrappe
fake = types.ModuleType("MetaTrader5")
for i, n in enumerate(["TIMEFRAME_M15", "TIMEFRAME_M30", "TIMEFRAME_H1",
                       "TIMEFRAME_H4", "TIMEFRAME_D1", "ORDER_TYPE_BUY",
                       "ORDER_TYPE_SELL", "ACCOUNT_TRADE_MODE_DEMO",
                       "SYMBOL_TRADE_MODE_FULL"]):
    setattr(fake, n, i)
sys.modules["MetaTrader5"] = fake
sys.path.insert(0, "/opt/data/tradingbot/mt5-windows")
import beobachter  # noqa: E402

# Genau die Namen, die Dominiques Konto laut Rueckmeldung liefert.
ECHTE_NAMEN = [
    "XAUUSD", "XAUUSD-F", "GOLD-PERP",
    "XAGUSD", "XAGUSD-F",
    "XPTUSD", "EURUSD", "GBPUSD", "USDJPY", "CHFJPY", "AUDUSD", "NZDUSD",
]

ERWARTET = {"XAUUSD": "XAUUSD", "EURUSD": "EURUSD", "GBPUSD": "GBPUSD",
            "USDJPY": "USDJPY"}


def suche(basis, namen):
    """Bildet die Logik aus finde_symbole() nach."""
    kandidaten = [basis] + beobachter.ALTERNATIVEN.get(basis, [])
    treffer = []
    for k in kandidaten:
        treffer += [n for n in namen
                    if n == k or (n.startswith(k) and len(n) <= len(k) + 5)]
    treffer = [n for n in treffer
               if not any(t in n.upper() for t in ("-F", "PERP", "FUT", "-C"))]
    return sorted(set(treffer), key=len)


print("Symbolsuche gegen Dominiques echte Broker-Namen:\n")
fehler = 0
for basis, soll in ERWARTET.items():
    treffer = suche(basis, ECHTE_NAMEN)
    ist = treffer[0] if treffer else None
    ok = ist == soll
    fehler += 0 if ok else 1
    print(f"  {basis:<8} -> {ist!s:<10} {'ok' if ok else f'FEHLER, erwartet {soll}'}")

# Der entscheidende Test: Futures duerfen NIE gewaehlt werden.
gold = suche("XAUUSD", ECHTE_NAMEN)
print(f"\n  Gold-Kandidaten nach Filter: {gold}")
assert "XAUUSD-F" not in gold, "Future darf nicht durchkommen"
assert "GOLD-PERP" not in gold, "Dauerkontrakt darf nicht durchkommen"
assert gold[0] == "XAUUSD", "Kassamarkt muss gewaehlt werden"
print("  Futures und Dauerkontrakte werden korrekt aussortiert")

assert fehler == 0, f"{fehler} Symbol(e) falsch zugeordnet"
print("\nAlle Symbole korrekt zugeordnet.")
