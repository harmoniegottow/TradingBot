# vps_einrichten.ps1 - als Administrator auf dem IONOS-VPS ausfuehren.
# Legt das Konto "tradingbot" an, aktiviert OpenSSH nur mit Schluessel und
# oeffnet Port 22 nur fuer den Hermes-Server. Mehrfach ausfuehrbar.

$ErrorActionPreference = "Stop"
Write-Host "vps_einrichten.ps1 Fassung 3 (Gruppen per SID, deutsches Windows)"
$BotUser  = "tradingbot"
$HermesIP = "152.239.113.4"
$PubKey   = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIDroiySjn65w1RqJ/h/HWXlee+bu9yeMggM0Edh+Jp+O hermes-tradingbot"

# 1. Konto ohne Adminrechte, darf sich per RDP anmelden
if (-not (Get-LocalUser -Name $BotUser -ErrorAction SilentlyContinue)) {
    $pw = Read-Host "Passwort fuer $BotUser (mind. 16 Zeichen)" -AsSecureString
    New-LocalUser -Name $BotUser -Password $pw -FullName "MT5 Bot" `
        -Description "Laufzeitkonto Tradingbot" -PasswordNeverExpires | Out-Null
    Write-Host "Konto $BotUser angelegt."
} else { Write-Host "Konto $BotUser existiert bereits." }
# Gruppe per SID, weil sie auf deutschem Windows "Remotedesktopbenutzer" heisst
$rdpGruppe = Get-LocalGroup -SID "S-1-5-32-555"
if (-not (Get-LocalGroupMember -Group $rdpGruppe -ErrorAction SilentlyContinue |
          Where-Object { $_.Name -like "*\$BotUser" })) {
    Add-LocalGroupMember -Group $rdpGruppe -Member $BotUser
    Write-Host "$BotUser zur Gruppe $($rdpGruppe.Name) hinzugefuegt."
} else { Write-Host "$BotUser ist bereits in $($rdpGruppe.Name)." }

# Server 2025: sshd_config enthaelt ab Werk "AllowGroups administrators openssh users".
# Ohne Mitgliedschaft in "OpenSSH Users" (SID S-1-5-32-585) lehnt sshd das Konto ab.
$sshGruppe = Get-LocalGroup -SID "S-1-5-32-585" -ErrorAction SilentlyContinue
if ($sshGruppe -and -not (Get-LocalGroupMember -Group $sshGruppe -ErrorAction SilentlyContinue |
          Where-Object { $_.Name -like "*\$BotUser" })) {
    Add-LocalGroupMember -Group $sshGruppe -Member $BotUser
    Write-Host "$BotUser zur Gruppe $($sshGruppe.Name) hinzugefuegt."
}

# 2. OpenSSH-Server
$cap = Get-WindowsCapability -Online -Name "OpenSSH.Server*"
if ($cap.State -ne "Installed") { Add-WindowsCapability -Online -Name $cap.Name | Out-Null }
Set-Service sshd -StartupType Automatic
Start-Service sshd   # erzeugt beim ersten Start C:\ProgramData\ssh\sshd_config

# 3. Schluessel zentral ablegen
$keyFile = "C:\ProgramData\ssh\tradingbot_authorized_keys"
Set-Content -Path $keyFile -Value $PubKey -Encoding ascii
icacls $keyFile /inheritance:r /grant "*S-1-5-18:F" /grant "*S-1-5-32-544:F" /grant "${BotUser}:R" | Out-Null

# 4. sshd_config: eigene Regeln OBEN einfuegen (vor jedem Match-Block,
#    sonst gelten sie nur innerhalb des Match-Blocks der Standarddatei)
$cfg = "C:\ProgramData\ssh\sshd_config"
if (-not (Test-Path "$cfg.original")) {
    # Die erste Skriptfassung hat das Original als .bak gesichert
    if (Test-Path "$cfg.bak") { Copy-Item "$cfg.bak" "$cfg.original" }
    else { Copy-Item $cfg "$cfg.original" }
}
$alt = Get-Content "$cfg.original"
$neu = @(
    "# --- Tradingbot ---",
    "PasswordAuthentication no",
    "PubkeyAuthentication yes",
    "AllowUsers $BotUser",
    "# --- Ende Tradingbot ---"
) + $alt + @(
    "",
    "Match User $BotUser",
    "    AuthorizedKeysFile __PROGRAMDATA__/ssh/tradingbot_authorized_keys"
)
Set-Content -Path $cfg -Value $neu -Encoding ascii
& "C:\Windows\System32\OpenSSH\sshd.exe" -t
if ($LASTEXITCODE -ne 0) { throw "sshd_config fehlerhaft, Original liegt in $cfg.original" }
New-ItemProperty -Path "HKLM:\SOFTWARE\OpenSSH" -Name DefaultShell `
    -Value "C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe" -PropertyType String -Force | Out-Null
Restart-Service sshd

# 5. Windows-Firewall: Port 22 nur fuer Hermes
Get-NetFirewallRule -Name "OpenSSH-Server-In-TCP" -ErrorAction SilentlyContinue | Remove-NetFirewallRule
Get-NetFirewallRule -Name "SSH-Hermes" -ErrorAction SilentlyContinue | Remove-NetFirewallRule
New-NetFirewallRule -Name "SSH-Hermes" -DisplayName "SSH nur Hermes" -Direction Inbound `
    -Protocol TCP -LocalPort 22 -RemoteAddress $HermesIP -Action Allow | Out-Null

Write-Host "Fertig. sshd laeuft:" (Get-Service sshd).Status
