#!/usr/bin/env bash
# ==============================================================================
# DA-V: Distribuidor Aamplo - Vídeo
# Script de Inicialização Rápida no Linux (Ubuntu, Debian, Fedora, Arch)
# Suporte: X11 / Wayland / Headless Daemon
# ==============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "======================================================================"
echo "    DA-V: DISTRIBUIDOR AAMPLO - VÍDEO (Linux Runtime Launcher)"
echo "    Arquitetura: 60 FPS Ultra-Low Latency Video Streaming Engine"
echo "======================================================================"

# 1. Verificar Python 3
if ! command -v python3 &>/dev/null; then
    echo "[ERRO] Python 3 não encontrado! Instale via: sudo apt install python3 python3-venv"
    exit 1
fi

PYTHON_VER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
echo "[INFO] Python detectado: $PYTHON_VER"

# 2. Configurar Virtualenv se não existir
if [ ! -d ".venv" ]; then
    echo "[INFO] Criando ambiente virtual Python (.venv)..."
    python3 -m venv .venv
    echo "[INFO] Atualizando pip e instalando dependências do requirements.txt..."
    .venv/bin/pip install --upgrade pip
    .venv/bin/pip install -r requirements.txt
else
    echo "[INFO] Ambiente virtual .venv encontrado."
fi

# Ativar venv
source .venv/bin/activate

# 3. Detectar Servidor Gráfico (X11 / Wayland)
if [ -n "$WAYLAND_DISPLAY" ]; then
    echo "[INFO] Sessão gráfica: Wayland ($WAYLAND_DISPLAY)"
    export QT_QPA_PLATFORM=wayland
elif [ -n "$DISPLAY" ]; then
    echo "[INFO] Sessão gráfica: X11 ($DISPLAY)"
    export QT_QPA_PLATFORM=xcb
else
    echo "[AVISO] Nenhuma variável DISPLAY ou WAYLAND_DISPLAY detectada."
    echo "[AVISO] Rodando em modo Headless / Daemon."
    export QT_QPA_PLATFORM=offscreen
fi

# 4. Processar Argumentos Especiais
if [ "$1" == "--test" ]; then
    echo "[INFO] Executando suíte completa de testes no Linux..."
    pytest tests/ -v
    python3 tests/test_full_pipeline_e2e.py
    python3 tests/test_kcp_transport.py
    python3 tests/test_screen_capture.py
    python3 tests/test_signaling_session.py
    echo "[SUCESSO] Todos os testes passaram com êxito!"
    exit 0
elif [ "$1" == "--bench" ]; then
    echo "[INFO] Executando benchmark de performance no Linux..."
    python3 scripts/dav_perf_benchmark.py
    exit 0
elif [ "$1" == "--daemon" ]; then
    echo "[INFO] Iniciando DA-V em modo Daemon (Headless Sender)..."
    python3 scripts/dav_sender_worker.py "${@:2}"
    exit 0
fi

# 5. Inicializar Interface Gráfica PySide6
echo "[INFO] Iniciando DA-V Desktop GUI..."
python3 scripts/gui_app.py "$@"
