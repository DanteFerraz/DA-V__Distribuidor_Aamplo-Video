param(
    [switch]$NonInteractive,
    [int]$Duration = 30
)

# DA-V Live Benchmark Launcher (PowerShell)
try { $host.UI.RawUI.WindowTitle = 'DA-V Live Benchmark Launcher' } catch {}
Write-Host '========================================================' -ForegroundColor Cyan
Write-Host '  DA-V - Teste de Performance em Ambiente Grafico Real' -ForegroundColor Cyan
Write-Host '========================================================' -ForegroundColor Cyan
Write-Host ''
Write-Host 'Metodologia: Janelas fisicas + Coleta de estagio ao vivo' -ForegroundColor Gray
Write-Host ''

# ── Pre-flight: encerrar instâncias anteriores para liberar portas UDP 9000/9002 ──
Write-Host '[Pre-flight] Encerrando processos Python anteriores (portas 9000/9002)...' -ForegroundColor DarkYellow
try {
    Get-Process -Name "python", "py" -ErrorAction SilentlyContinue | ForEach-Object {
        Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue
    }
    Start-Sleep -Milliseconds 800
    Write-Host '[Pre-flight] Limpeza concluida.' -ForegroundColor DarkGreen
} catch {
    Write-Host "[Pre-flight] Aviso: $($_.Exception.Message)" -ForegroundColor DarkYellow
}

# ── Variáveis dos processos filhos para limpeza no finally ──
$procRecv = $null
$procSend = $null

try {
    Write-Host '1. Abrindo Receptor (porta UDP 9002)...' -ForegroundColor Yellow
    $procRecv = Start-Process -FilePath 'py' -ArgumentList '-3', 'scripts/gui_app.py', '--port', '9002', '--target-port', '9000', '--pin', '777-888', '--auto-recv' -PassThru

    Start-Sleep -Seconds 3

    Write-Host '2. Abrindo Transmissor (porta UDP 9000, Monitor 1, NVENC RTX 4070)...' -ForegroundColor Yellow
    $procSend = Start-Process -FilePath 'py' -ArgumentList '-3', 'scripts/gui_app.py', '--port', '9000', '--target-port', '9002', '--pin', '777-888', '--auto-send', '--monitor', '1' -PassThru

    Start-Sleep -Seconds 5

    Write-Host ''
    Write-Host "3. Iniciando coleta de metricas por estagio ($Duration segundos)..." -ForegroundColor Green
    Write-Host '   Observe o HUD no Receptor e a aba Diagnostico TUPA para ver' -ForegroundColor Gray
    Write-Host '   as barras de latencia por estagio atualizando em tempo real.' -ForegroundColor Gray
    Write-Host ''

    & py -3 scripts/dav_live_benchmark.py --duration $Duration --no-gui

    Write-Host ''
    Write-Host '========================================================' -ForegroundColor Cyan
    Write-Host '  Relatorio gerado na pasta: logs/' -ForegroundColor Green
    Write-Host '  Use: py -3 scripts/dav_stage_probe.py --report' -ForegroundColor Yellow
    Write-Host '  para ver o relatorio de latencia por estagio.' -ForegroundColor Yellow
    Write-Host '========================================================' -ForegroundColor Cyan

} finally {
    # ── Cleanup: encerrar janelas abertas de forma limpa (Ctrl+C ou fim normal) ──
    Write-Host '' 
    Write-Host '[Cleanup] Encerrando janelas de teste...' -ForegroundColor DarkYellow
    if ($procRecv -and -not $procRecv.HasExited) {
        Stop-Process -Id $procRecv.Id -Force -ErrorAction SilentlyContinue
    }
    if ($procSend -and -not $procSend.HasExited) {
        Stop-Process -Id $procSend.Id -Force -ErrorAction SilentlyContinue
    }
    # Limpar qualquer filho restante (subprocessos Python do sender_worker)
    Start-Sleep -Milliseconds 500
    Get-Process -Name "python", "py" -ErrorAction SilentlyContinue | ForEach-Object {
        Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue
    }
    Write-Host '[Cleanup] Concluido.' -ForegroundColor DarkGreen
}

if (-not $NonInteractive) {
    Read-Host 'Pressione ENTER para fechar...'
}
