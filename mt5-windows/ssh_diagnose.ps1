# ssh_diagnose.ps1 - als Administrator ausfuehren. Aendert nichts, liest nur.
# Zeigt, warum sshd den Schluessel des Kontos tradingbot ablehnt.

$u = "tradingbot"
Write-Host "=== 1. Ist $u Administrator? (dann gilt administrators_authorized_keys) ==="
Get-LocalGroupMember -Group (Get-LocalGroup -SID "S-1-5-32-544") |
    Where-Object { $_.Name -like "*\$u" } | ForEach-Object { "JA: " + $_.Name }

Write-Host "=== 2. Schluesseldatei ==="
$k = "C:\ProgramData\ssh\tradingbot_authorized_keys"
if (Test-Path $k) { Get-Content $k; icacls $k } else { "FEHLT: $k" }

Write-Host "=== 3. Wirksame sshd-Einstellungen fuer $u ==="
& "C:\Windows\System32\OpenSSH\sshd.exe" -T -C "user=$u,host=x,addr=152.239.113.4" |
    Select-String -Pattern "^(authorizedkeysfile|passwordauthentication|pubkeyauthentication|allowusers|strictmodes)"

Write-Host "=== 4. Letzte sshd-Meldungen ==="
Get-WinEvent -LogName "OpenSSH/Operational" -MaxEvents 15 -ErrorAction SilentlyContinue |
    Select-Object TimeCreated, Message | Format-List
