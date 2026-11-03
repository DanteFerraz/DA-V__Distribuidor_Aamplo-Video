#!/usr/bin/env bash
# ==============================================================================
# DA-V (Distribuidor Amplo de Vídeo) — Gerador Oficial de AppImage Linux
# Autor: Dante Ferraz (MonoTech)
# ==============================================================================
set -euo pipefail

APP_NAME="DA-V"
ARCH="x86_64"
APP_DIR="AppDir"
OUTPUT_DIR="../../dist_installer"

echo "=== [DA-V] Construindo Pacote Portátil AppImage para Linux ($ARCH) ==="

mkdir -p "$OUTPUT_DIR"
rm -rf "$APP_DIR"
mkdir -p "$APP_DIR/usr/bin"
mkdir -p "$APP_DIR/usr/lib"
mkdir -p "$APP_DIR/usr/share/applications"
mkdir -p "$APP_DIR/usr/share/icons/hicolor/256x256/apps"

# 1. Copia o lançador desktop e ícone
cp dav.desktop "$APP_DIR/usr/share/applications/dav.desktop"
cp dav.desktop "$APP_DIR/dav.desktop"

# Cria ícone SVG padrão se não houver PNG
cat << 'EOF' > "$APP_DIR/dav.png"
<?xml version="1.0" encoding="UTF-8"?>
<svg width="256" height="256" version="1.1" xmlns="http://www.w3.org/2000/svg">
  <rect width="256" height="256" rx="32" fill="#0c121d"/>
  <circle cx="128" cy="128" r="96" fill="#00d26a"/>
  <polygon points="104,80 180,128 104,176" fill="#070a0f"/>
</svg>
EOF
cp "$APP_DIR/dav.png" "$APP_DIR/usr/share/icons/hicolor/256x256/apps/dav.png"

# 2. Cria o AppRun
cat << 'EOF' > "$APP_DIR/AppRun"
#!/usr/bin/env bash
HERE="$(dirname "$(readlink -f "${0}")")"
export PATH="${HERE}/usr/bin:${PATH}"
export LD_LIBRARY_PATH="${HERE}/usr/lib:${LD_LIBRARY_PATH:-}"
export PYTHONPATH="${HERE}/opt/dav:${PYTHONPATH:-}"

# Detecção automática X11 / Wayland para Qt/PySide6
if [ "${XDG_SESSION_TYPE:-}" = "wayland" ]; then
    export QT_QPA_PLATFORM="${QT_QPA_PLATFORM:-wayland;xcb}"
else
    export QT_QPA_PLATFORM="${QT_QPA_PLATFORM:-xcb}"
fi

# Executa o DA-V
exec python3 "${HERE}/opt/dav/scripts/gui_app.py" "$@"
EOF
chmod +x "$APP_DIR/AppRun"

# 3. Copia a base de código do DA-V
mkdir -p "$APP_DIR/opt/dav"
cp -r ../../*.py "$APP_DIR/opt/dav/" 2>/dev/null || true
cp -r ../../src "$APP_DIR/opt/dav/"
cp -r ../../scripts "$APP_DIR/opt/dav/"
cp -r ../../include "$APP_DIR/opt/dav/" 2>/dev/null || true

# 4. Baixa e empacota com appimagetool se disponivel
if command -v appimagetool &> /dev/null; then
    echo "Gerando ${OUTPUT_DIR}/${APP_NAME}-${ARCH}.AppImage ..."
    ARCH=x86_64 appimagetool "$APP_DIR" "${OUTPUT_DIR}/${APP_NAME}-${ARCH}.AppImage"
    echo "✓ AppImage gerado com sucesso!"
else
    echo "AVISO: 'appimagetool' não encontrado no PATH. Estrutura ${APP_DIR} preparada com sucesso."
    echo "Para gerar o arquivo final, execute: appimagetool AppDir DA-V-x86_64.AppImage"
fi

