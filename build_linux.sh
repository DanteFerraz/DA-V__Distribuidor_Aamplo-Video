#!/usr/bin/env bash
# ==============================================================================
# DA-V: Distribuidor Amplo de Vídeo — Script de Build Nativo para Linux
# Compila o Core C-ABI (libdav_core.so) e o Daemon C++ (dav_daemon) via CMake.
# ==============================================================================
set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

echo "===================================================================="
echo "   DA-V: Compilação Nativa C++23 para Linux (libdav_core.so)"
echo "===================================================================="

# 1. Verifica compilador C++23
CXX_COMPILER=""
if command -v g++-13 &> /dev/null; then
    CXX_COMPILER="g++-13"
elif command -v g++ &> /dev/null; then
    CXX_COMPILER="g++"
elif command -v clang++-17 &> /dev/null; then
    CXX_COMPILER="clang++-17"
elif command -v clang++ &> /dev/null; then
    CXX_COMPILER="clang++"
else
    echo "[!] Erro: Compilador C++ com suporte a C++23 não encontrado."
    echo "    Instale no Ubuntu/Debian: sudo apt update && sudo apt install -y build-essential cmake libx11-dev libxext-dev ninja-build"
    exit 1
fi

echo "[*] Compilador C++: $CXX_COMPILER"

# 2. Verifica CMake
if ! command -v cmake &> /dev/null; then
    echo "[!] Erro: cmake não encontrado. Instale com: sudo apt install -y cmake"
    exit 1
fi

# 3. Gerador (Ninja ou Makefiles)
BUILD_GEN="Unix Makefiles"
if command -v ninja &> /dev/null; then
    BUILD_GEN="Ninja"
fi
echo "[*] Gerador de Build: $BUILD_GEN"

# 4. Configuração do CMake
BUILD_DIR="$DIR/build"
mkdir -p "$BUILD_DIR"

echo "[*] Configurando projeto CMake em modo Release..."
cmake -B "$BUILD_DIR" \
    -G "$BUILD_GEN" \
    -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_CXX_COMPILER="$CXX_COMPILER"

# 5. Compilação
echo "[*] Compilando libdav_core.so e dav_daemon..."
CORES=$(nproc 2>/dev/null || echo 4)
cmake --build "$BUILD_DIR" --config Release -j "$CORES"

# 6. Validação dos Artefatos
SO_TARGET="$BUILD_DIR/libdav_core.so"
DAEMON_TARGET="$BUILD_DIR/dav_daemon"

if [ -f "$SO_TARGET" ]; then
    echo "[OK] Biblioteca compartilhada C-ABI gerada: $SO_TARGET"
else
    echo "[!] Aviso: libdav_core.so não encontrado no diretório raiz de build."
fi

if [ -f "$DAEMON_TARGET" ]; then
    echo "[OK] Daemon de serviço gerado: $DAEMON_TARGET"
fi

echo "===================================================================="
echo "   COMPILAÇÃO NATIVA DO DA-V CONCLUÍDA COM SUCESSO!"
echo "===================================================================="
