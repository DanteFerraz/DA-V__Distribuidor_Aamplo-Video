@echo off
title DA-V - Assistente de Instalacao Windows
cd /d "%~dp0"
echo ========================================================
echo   DA-V - DISTRIBUIDOR AMPLO DE VIDEO (SETUP WINDOWS)
echo ========================================================
echo.
echo Iniciando o assistente grafico de instalacao...
py scripts\dav_installer_win.py
if %ERRORLEVEL% NEQ 0 (
    python scripts\dav_installer_win.py
)

