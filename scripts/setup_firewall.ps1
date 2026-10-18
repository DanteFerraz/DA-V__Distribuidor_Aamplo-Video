# DA-V — Script de Configuracao e Liberacao de Firewall do Windows
# Executa a liberacao das portas UDP 9000 (Video Streaming) e UDP 9005 (LAN Discovery Beacon)

# Garante execucao como Administrador
if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host "[*] Solicitando privilegios de Administrador para configurar o Firewall..." -ForegroundColor Cyan
    Start-Process powershell.exe -Verb RunAs -ArgumentList ("-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`"")
    exit
}

Write-Host "================================================================" -ForegroundColor Cyan
Write-Host "       DA-V: CONFIGURADOR DE FIREWALL DO WINDOWS               " -ForegroundColor Cyan
Write-Host "================================================================" -ForegroundColor Cyan

# 1. Remover regras antigas se existirem
netsh advfirewall firewall delete rule name="DA-V Video Streaming" 2>$null
netsh advfirewall firewall delete rule name="DA-V LAN Discovery" 2>$null

# 2. Adicionar regra para UDP 9000 (Video Streaming Inbound)
Write-Host "[+] Adicionando regra para Porta UDP 9000 (Video Streaming)..." -ForegroundColor Yellow
netsh advfirewall firewall add rule name="DA-V Video Streaming" dir=in action=allow protocol=UDP localport=9000 profile=any description="Permite transmissao e recepcao de video de ultra-baixa latencia do DA-V"

# 3. Adicionar regra para UDP 9005 (LAN Discovery Beacon Inbound)
Write-Host "[+] Adicionando regra para Porta UDP 9005 (LAN Beacon Discovery)..." -ForegroundColor Yellow
netsh advfirewall firewall add rule name="DA-V LAN Discovery" dir=in action=allow protocol=UDP localport=9005 profile=any description="Permite anuncio e deteccao de dispositivos locais no DA-V"

# 4. Validar status
Write-Host ""
Write-Host "================= STATUS DAS REGRAS ATIVAS =====================" -ForegroundColor Green
netsh advfirewall firewall show rule name="DA-V Video Streaming"
Write-Host "----------------------------------------------------------------"
netsh advfirewall firewall show rule name="DA-V LAN Discovery"
Write-Host "================================================================" -ForegroundColor Green
Write-Host "[SUCESSO] Portas UDP 9000 e 9005 liberadas com sucesso no Windows Firewall!" -ForegroundColor Green
Write-Host "Pressione qualquer tecla para fechar..."
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
