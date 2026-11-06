# DA-V — Script de Configuração e Liberação de Firewall do Windows
# Autor: Dante Ferraz (MonoTech)
# Libera as faixas UDP 9000-9020, 19000-19010 (Streaming P2P/LAN) e UDP 9005 (LAN Beacon)

if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host "[*] Solicitando privilégios de Administrador para configurar o Windows Firewall..." -ForegroundColor Cyan
    Start-Process powershell.exe -Verb RunAs -ArgumentList ("-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`"")
    exit
}

Write-Host "================================================================" -ForegroundColor Cyan
Write-Host "       DA-V: CONFIGURADOR DE FIREWALL DO WINDOWS (v2.0)         " -ForegroundColor Cyan
Write-Host "================================================================" -ForegroundColor Cyan

netsh advfirewall firewall delete rule name="DA-V Video Streaming" 2>$null | Out-Null
netsh advfirewall firewall delete rule name="DA-V LAN Discovery" 2>$null | Out-Null

Write-Host "[+] Liberando portas UDP 9000-9020 e 19000-19010 (Streaming P2P & LAN)..." -ForegroundColor Yellow
netsh advfirewall firewall add rule name="DA-V Video Streaming" dir=in action=allow protocol=UDP localport=9000-9020,19000-19010 profile=any description="Permite transmissão e recepção P2P/LAN de vídeo em tempo real no DA-V"

Write-Host "[+] Liberando porta UDP 9005 (Descoberta Automática LAN Beacon)..." -ForegroundColor Yellow
netsh advfirewall firewall add rule name="DA-V LAN Discovery" dir=in action=allow protocol=UDP localport=9005 profile=any description="Permite anúncio e descoberta automática de dispositivos locais no DA-V"

Write-Host ""
Write-Host "[SUCESSO] Regras de entrada UDP aplicadas com êxito no Windows Firewall!" -ForegroundColor Green
Start-Sleep -Seconds 2
