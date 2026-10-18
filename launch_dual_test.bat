@echo off
cd /d "%~dp0"
title DA-V Live Benchmark Launcher
echo ========================================================
echo   DA-V - Teste de Performance em Ambiente Grafico Real
echo ========================================================
echo.
echo Metodologia: Janelas fisicas + Coleta de estagio ao vivo
echo.
echo 1. Abrindo Receptor (porta UDP 9002)...
start "DA-V [Receptor 9002]" py -3 scripts\gui_app.py --port 9002 --target-port 9000 --pin 777-888 --auto-recv

timeout /t 3 /nobreak > nul

echo 2. Abrindo Transmissor (porta UDP 9000, Monitor 2, NVENC RTX 4070)...
start "DA-V [Transmissor 9000]" py -3 scripts\gui_app.py --port 9000 --target-port 9002 --pin 777-888 --auto-send --monitor 1

timeout /t 5 /nobreak > nul

echo.
echo 3. Iniciando coleta de metricas por estagio (30 segundos)...
echo    Observe o HUD no Receptor e a aba "Diagnostico TUPA" para ver
echo    as barras de latencia por estagio atualizando em tempo real.
echo.
py -3 scripts\dav_live_benchmark.py --duration 30 --no-gui

echo.
echo ========================================================
echo   Relatorio gerado em logs\
echo   Use: py -3 scripts\dav_stage_probe.py --report
echo   para ver o relatorio de latencia por estagio.
echo ========================================================
pause
