#!/usr/bin/env bash
# ==============================================================================
# DA-V: Distribuidor Amplo de Video — Compilacao e Empacotamento Linux (.tar.gz)
# Autor: Dante Ferraz (MonoTech)
#
# Compila o Core C++23 (libdav_core.so e dav_daemon), empacota o executavel ELF
# DA-V + instalador grafico DA-V_Instalador_Linux_x86_64 com PyInstaller e gera
# o pacote final release_assets/DA-V_v<VERSION>_Linux_x86_64.tar.gz.
# ==============================================================================
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

RUN_TESTS=1
for arg in "$@"; do
    case "$arg" in
        --skip-tests) RUN_TESTS=0 ;;
    esac
done

VERSION="$(tr -d '[:space:]' < "$ROOT_DIR/VERSION")"
ARCH="$(uname -m)"
VENV_DIR="$ROOT_DIR/.venv-build"

echo "============================================================"
echo "INICIANDO COMPILACAO DA-V v${VERSION} (Linux ${ARCH})"
echo "============================================================"

if [ ! -f "$ROOT_DIR/build_linux.sh" ]; then
    echo "[ERRO] Execute este script dentro do diretorio raiz do DA-V."
    exit 1
fi

chmod +x "$ROOT_DIR/build_linux.sh" "$ROOT_DIR/launch_dav.sh"

# 1. Compilar backend C++23 nativo (libdav_core.so e dav_daemon)
echo "[1/5] Compilando Core C++23 (libdav_core.so e dav_daemon)..."
"$ROOT_DIR/build_linux.sh" --clean

if [ ! -f "$ROOT_DIR/build/libdav_core.so" ] || [ ! -f "$ROOT_DIR/build/dav_daemon" ]; then
    echo "[ERRO] Falha ao gerar build/libdav_core.so ou build/dav_daemon."
    exit 1
fi

# 2. Preparar virtualenv isolada de build (evita erro PEP 668 no Ubuntu 24.04+)
echo "[2/5] Configurando ambiente Python isolado em .venv-build..."
if ! command -v python3 >/dev/null 2>&1; then
    echo "[ERRO] python3 nao encontrado. Instale python3, python3-venv e python3-dev."
    exit 1
fi

if [ ! -d "$VENV_DIR" ]; then
    python3 -m venv "$VENV_DIR"
fi
# shellcheck source=/dev/null
source "$VENV_DIR/bin/activate"

python -m pip install --upgrade pip
python -m pip install -r "$ROOT_DIR/requirements.txt" aiohttp Pillow opencv-python-headless pyinstaller

# 3. Executar validacao de testes antes do empacotamento (opcional)
if [ "$RUN_TESTS" -eq 1 ]; then
    echo "[3/5] Executando suite pytest..."
    QT_QPA_PLATFORM=offscreen python -m pytest tests/ -v
else
    echo "[3/5] Testes ignorados (--skip-tests)."
fi

# 4. Empacotar aplicacao ELF (onedir) e validar --self-check
echo "[4/5] Compilando aplicacao DA-V e instalador Linux via PyInstaller..."
QT_QPA_PLATFORM="${QT_QPA_PLATFORM:-offscreen}" pyinstaller --noconfirm --clean --onedir --windowed \
    --name DA-V \
    --paths "$ROOT_DIR" \
    --add-data "$ROOT_DIR/installer/dav_icon.png:." \
    --add-data "$ROOT_DIR/installer/dav_icon.ico:." \
    --add-data "$ROOT_DIR/VERSION:." \
    --collect-all av \
    --collect-all src.dav \
    --collect-all src.ui \
    --hidden-import scripts.dav_sender_worker \
    --hidden-import scripts.dav_client \
    --hidden-import src.signaling.server.dav_rendezvous \
    --hidden-import src.capture.linux_wayland_portal \
    --hidden-import mss \
    --hidden-import aiohttp \
    --hidden-import src.dav.modules.updater.update_checker \
    --hidden-import src.dav.modules.updater.auto_installer \
    --hidden-import src.dav.modules.updater.service \
    --hidden-import src.dav.modules.updater.manifest \
    --hidden-import src.dav.modules.audio.manifest \
    --hidden-import cryptography \
    --exclude-module PyQt5 \
    --exclude-module PyQt6 \
    --exclude-module tkinter \
    --exclude-module pytest \
    "$ROOT_DIR/scripts/gui_app.py"

cp "$ROOT_DIR/installer/dav_icon.png" "$ROOT_DIR/dist/DA-V/"
cp "$ROOT_DIR/build/libdav_core.so" "$ROOT_DIR/dist/DA-V/"
chmod +x "$ROOT_DIR/dist/DA-V/DA-V"

echo "Validando binario compilado (--self-check)..."
QT_QPA_PLATFORM="${QT_QPA_PLATFORM:-offscreen}" "$ROOT_DIR/dist/DA-V/DA-V" --self-check

mkdir -p "$ROOT_DIR/build_payload"
tar -czf "$ROOT_DIR/build_payload/dav_app_payload_linux.tar.gz" -C "$ROOT_DIR/dist/DA-V" .

QT_QPA_PLATFORM="${QT_QPA_PLATFORM:-offscreen}" pyinstaller --noconfirm --clean --onefile --windowed \
    --name DA-V_Instalador_Linux_x86_64 \
    --paths "$ROOT_DIR" \
    --add-data "$ROOT_DIR/build_payload/dav_app_payload_linux.tar.gz:." \
    --exclude-module PyQt5 \
    --exclude-module PyQt6 \
    --exclude-module tkinter \
    "$ROOT_DIR/scripts/dav_installer_linux.py"

# 5. Montar tarball final em release_assets/
echo "[5/5] Empacotando tarball final em release_assets/..."
STAGE_PARENT="$ROOT_DIR/stage_linux"
STAGE_NAME="DA-V-v${VERSION}-Linux-${ARCH}"
STAGE="$STAGE_PARENT/$STAGE_NAME"

rm -rf "$STAGE_PARENT"
mkdir -p "$STAGE/build" "$ROOT_DIR/release_assets"

cp -r "$ROOT_DIR/dist/DA-V/"* "$STAGE/"
cp -r "$ROOT_DIR/src" "$ROOT_DIR/scripts" "$ROOT_DIR/include" "$ROOT_DIR/cmake" "$ROOT_DIR/third_party" "$ROOT_DIR/deploy" "$ROOT_DIR/installer" "$STAGE/"
cp "$ROOT_DIR/CMakeLists.txt" "$ROOT_DIR/README.md" "$ROOT_DIR/LEIA-ME_LINUX.md" "$ROOT_DIR/CHANGELOG.md" "$ROOT_DIR/VERSION" "$ROOT_DIR/requirements.txt" "$STAGE/"
if [ -f "$ROOT_DIR/GUIA_RAPIDO_LINUX.md" ]; then
    cp "$ROOT_DIR/GUIA_RAPIDO_LINUX.md" "$STAGE/"
fi
cp "$ROOT_DIR/launch_dav.sh" "$ROOT_DIR/build_linux.sh" "$STAGE/"
cp "$ROOT_DIR/build/libdav_core.so" "$ROOT_DIR/build/dav_daemon" "$STAGE/build/"
cp "$ROOT_DIR/dist/DA-V_Instalador_Linux_x86_64" "$STAGE/"

find "$STAGE" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
find "$STAGE" -type f \( -name "*.pyc" -o -name "*.pyo" \) -delete 2>/dev/null || true

chmod +x "$STAGE/DA-V" "$STAGE/launch_dav.sh" "$STAGE/build_linux.sh" "$STAGE/scripts/build_linux_bundle.sh" "$STAGE/DA-V_Instalador_Linux_x86_64" "$STAGE/build/dav_daemon"

OUT_TAR="$ROOT_DIR/release_assets/DA-V_v${VERSION}_Linux_${ARCH}.tar.gz"
tar -czf "$OUT_TAR" -C "$STAGE_PARENT" "$STAGE_NAME"
cp "$ROOT_DIR/dist/DA-V_Instalador_Linux_x86_64" "$ROOT_DIR/release_assets/"

rm -rf "$STAGE_PARENT"

echo "============================================================"
echo "BUILD LINUX CONCLUIDA COM SUCESSO!"
echo "Pacote Final : $OUT_TAR"
echo "Instalador   : $ROOT_DIR/release_assets/DA-V_Instalador_Linux_x86_64"
echo "Binario      : $ROOT_DIR/dist/DA-V/DA-V"
echo "============================================================"
