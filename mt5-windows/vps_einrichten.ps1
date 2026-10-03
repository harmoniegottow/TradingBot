# vps_einrichten.ps1 - Teil A, als Administrator auf dem IONOS-VPS ausfuehren.
# Legt das Konto "tradingbot" an, aktiviert OpenSSH nur mit Schluessel und
# oeffnet Port 22 nur fuer den Hermes-Server.

$ErrorActionPreference = "Stop"
$BotUser  = "tradingbot"
$HermesIP = "152.239.113.4"
$PubKey   = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIDroiySjn65w1RqJ/h/HWXlee+bu9yeMggM0Edh+Jp+O hermes-tradingbot"

# 1. Konto ohne Adminrechte, darf sich per RDP anmelden
$pw = Read-Host "Passwort fuer $BotUser (mind. 16 Zeichen)" -AsSecureString
New-LocalUser -Name $BotUser -Password $pw -FullName "MT5 Bot" `
    -Description "Laufzeitkonto Tradingbot" -PasswordNeverExpires
Add-LocalGroupMember -Group "Remote Desktop Users" -Member $BotUser

# 2. OpenSSH-Server (bei Server 2025 meist vorinstalliert)
$cap = Get-WindowsCapability -Online -Name "OpenSSH.Server*"
if ($cap.State -ne "Installed") { Add-WindowsCapability -Online -Name $cap.Name }
Set-Service sshd -StartupType Automatic
Start-Service sshd   # erzeugt beim ersten Start C:\ProgramData\ssh\sshd_config

# 3. Schluessel zentral ablegen (unabhaengig vom Benutzerprofil)
$keyFile = "C:\ProgramData\ssh\tradingbot_authorized_keys"
Set-Content -Path $keyFile -Value $PubKey -Encoding ascii
icacls $keyFile /inheritance:r /grant "SYSTEM:F" /grant "Administrators:F" /grant "${BotUser}:R" | Out-Null

# 4. sshd: nur Schluessel, nur dieses Konto
$cfg = "C:\ProgramData\ssh\sshd_config"
Copy-Item $cfg "$cfg.bak" -Force
$extra = @"

PasswordAuthentication no
PubkeyAuthentication yes
AllowUsers $BotUser
Match User $BotUser
    AuthorizedKeysFile __PROGRAMDATA__/ssh/tradingbot_authorized_keys
"@
Add-Content -Path $cfg -Value $extra -Encoding ascii
New-ItemProperty -Path "HKLM:\SOFTWARE\OpenSSH" -Name DefaultShell `
    -Value "C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe" -PropertyType String -Force | Out-Null
Restart-Service sshd

# 5. Windows-Firewall: Port 22 nur fuer Hermes
Get-NetFirewallRule -Name "OpenSSH-Server-In-TCP" -ErrorAction SilentlyContinue | Remove-NetFirewallRule
New-NetFirewallRule -Name "SSH-Hermes" -DisplayName "SSH nur Hermes" -Direction Inbound `
    -Protocol TCP -LocalPort 22 -RemoteAddress $HermesIP -Action Allow | Out-Null

Write-Host "Fertig. sshd laeuft:" (Get-Service sshd).Status
