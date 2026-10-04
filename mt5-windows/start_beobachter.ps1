# start_beobachter.ps1 - Dauerbetrieb des Beobachters auf dem VPS.
# Wird beim Anmelden von tradingbot ueber den Autostart-Ordner gestartet.
# Wartet, bis MT5 laeuft, und startet den Beobachter nach jedem Abbruch neu.
# Stoppen: Datei STOP im Bot-Ordner anlegen (oder Prozess beenden).

$bot = Join-Path $env:USERPROFILE "bot"
Set-Location $bot
$env:MT5_PFAD = "C:\Program Files\Pepperstone MetaTrader 5\terminal64.exe"
$env:PYTHONIOENCODING = "utf-8"
$konsole = Join-Path $bot "beobachter_konsole.txt"

# Nur eine Instanz (WMI ist fuer das Bot-Konto gesperrt, daher Mutex)
$neu = $false
$mutex = New-Object System.Threading.Mutex($true, "Local\TradingbotBeobachter", [ref]$neu)
if (-not $neu) { exit }

while (-not (Test-Path (Join-Path $bot "STOP"))) {
    if (-not (Get-Process terminal64 -ErrorAction SilentlyContinue |
              Where-Object { $_.SessionId -eq (Get-Process -Id $PID).SessionId })) {
        Start-Sleep -Seconds 30
        continue
    }
    Start-Sleep -Seconds 60   # MT5 Zeit zum Anmelden geben
    "$(Get-Date -Format s) Starte Beobachter" | Out-File $konsole -Append -Encoding utf8
    & "$bot\.venv\Scripts\python.exe" "$bot\beobachter.py" *>> $konsole
    "$(Get-Date -Format s) Beobachter beendet (Code $LASTEXITCODE), Neustart in 60 s" |
        Out-File $konsole -Append -Encoding utf8
}
