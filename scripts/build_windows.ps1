# scripts/build_windows.ps1
# Script de Compilação Local de Build e Instalador — DA-V v4.0.0
# Autor: Dante Ferraz (MonoTech)

$ErrorActionPreference = "Stop"
$Root = (Get-Location).Path
$Ver = (Get-Content "$Root\VERSION" -Raw).Trim()

Write-Host "============================================================"
Write-Host "INICIANDO COMPILACAO DA-V v$Ver (Windows x64)"
Write-Host "============================================================"

# 1. Compilação da Aplicação Desacoplada (onedir)
Write-Host "[1/4] Compilando aplicacao principal DA-V com PyInstaller..."
py -3.13 -m PyInstaller --noconfirm --clean --onedir --windowed `
  --name DA-V `
  --icon "$Root\installer\dav_icon.ico" `
  --paths "$Root" `
  --add-data "$Root\installer\dav_icon.ico;." `
  --add-data "$Root\installer\dav_icon.png;." `
  --add-data "$Root\VERSION;." `
  --collect-all av `
  --collect-all src.dav `
  --collect-all src.ui `
  --hidden-import scripts.dav_sender_worker `
  --hidden-import scripts.dav_client `
  --hidden-import src.signaling.server.dav_rendezvous `
  --hidden-import src.capture.linux_wayland_portal `
  --hidden-import mss `
  --hidden-import aiohttp `
  --hidden-import src.dav.modules.updater.update_checker `
  --hidden-import src.dav.modules.updater.auto_installer `
  --hidden-import src.dav.modules.updater.service `
  --hidden-import src.dav.modules.updater.manifest `
  --exclude-module PyQt5 `
  --exclude-module PyQt6 `
  --exclude-module tkinter `
  --exclude-module pytest `
  "$Root\scripts\gui_app.py"

if (-not (Test-Path "$Root\dist\DA-V\DA-V.exe")) {
    Write-Error "FALHA: Executavel dist\DA-V\DA-V.exe nao foi gerado!"
    exit 1
}

Copy-Item "$Root\installer\dav_icon.ico" "$Root\dist\DA-V\" -Force

# 2. Teste de Sanidade do Executável Gerado
Write-Host "[2/4] Executando auto-teste do executavel compilado (--self-check)..."
$testOutput = & "$Root\dist\DA-V\DA-V.exe" --self-check
if ($LASTEXITCODE -ne 0) {
    Write-Error "FALHA: Auto-teste do executavel retornou codigo $LASTEXITCODE"
    exit 1
}
Write-Host "Auto-teste do binario: SUCESSO ($testOutput)"

# 3. Compactação do Payload para o Instalador Autossuficiente
Write-Host "[3/4] Empacotando payload da aplicacao em build_payload/dav_app_payload.zip..."
New-Item -ItemType Directory -Force -Path "$Root\build_payload" | Out-Null
py -3.13 -c "import pathlib, zipfile; src=pathlib.Path('dist/DA-V'); z=zipfile.ZipFile('build_payload/dav_app_payload.zip','w',zipfile.ZIP_DEFLATED,compresslevel=6); [z.write(p, p.relative_to(src).as_posix()) for p in src.rglob('*') if p.is_file()]; z.close()"

# 4. Compilação do Instalador Autossuficiente
Write-Host "[4/4] Compilando instalador autossuficiente DA-V_Instalador_Windows_x64.exe..."
py -3.13 -m PyInstaller --noconfirm --clean --onefile --windowed `
  --name DA-V_Instalador_Windows_x64 `
  --icon "$Root\installer\dav_icon.ico" `
  --add-data "$Root\build_payload\dav_app_payload.zip;." `
  --exclude-module PyQt5 `
  --exclude-module PyQt6 `
  --exclude-module tkinter `
  "$Root\scripts\dav_installer_win.py"

if (-not (Test-Path "$Root\dist\DA-V_Instalador_Windows_x64.exe")) {
    Write-Error "FALHA: Instalador dist\DA-V_Instalador_Windows_x64.exe nao foi gerado!"
    exit 1
}

# 5. Organização dos Release Assets
Write-Host "Organizando pacotes de release em release_assets/..."
New-Item -ItemType Directory -Force -Path "$Root\release_assets" | Out-Null
Copy-Item "$Root\dist\DA-V_Instalador_Windows_x64.exe" "$Root\release_assets\" -Force

# Gerar arquivo .zip standalone para quem prefere rodar portátil sem instalador
$ZipDest = "$Root\release_assets\DA-V_v${Ver}_Windows_x64_Portable.zip"
if (Test-Path $ZipDest) { Remove-Item $ZipDest -Force }
Compress-Archive -Path "$Root\dist\DA-V\*" -DestinationPath $ZipDest -Force

Write-Host "============================================================"
Write-Host "BUILD CONCLUIDA COM SUCESSO!"
Write-Host "Binario Portatil : $Root\dist\DA-V\DA-V.exe"
Write-Host "Instalador Final : $Root\dist\DA-V_Instalador_Windows_x64.exe"
Write-Host "Release Assets   : $Root\release_assets\"
Write-Host "============================================================"

