#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Dante Ferraz Oliveira Paiva (MonoTech)
# Additional Terms (Section 7): see NOTICE and LICENSE in the repository root.
# ==============================================================================
# DA-V v5.0.0 — Desempacotador e Inicializador do Instalador Gráfico (Linux)
# Autor: Dante Ferraz (MonoTech)
#
# Fluxo automatizado:
#   1. Localiza um pacote .tar.gz local (argumento $1, pasta atual, release_assets
#      ou ~/Downloads), usa o diretório já extraído ou baixa a release oficial;
#   2. Verifica dependências gráficas essenciais da distribuição (xcb-cursor,
#      PipeWire/GStreamer em Wayland, python3-venv no modo fonte);
#   3. Desempacota os arquivos com permissões executáveis corretas;
#   4. Abre a janela do Instalador Gráfico Glassmorphism (ELF nativo ou Python)
#      para que o usuário personalize atalhos, protocolo dav:// e firewall.
# ==============================================================================

set -euo pipefail

REPO_SLUG="DanteFerraz/DA-V__Distribuidor_Aamplo-Video"
INSTALL_HOME="${HOME}/.local/share/dav"
STAGE_TMP=""

cleanup() {
    if [ -n "${STAGE_TMP}" ] && [ -d "${STAGE_TMP}" ]; then
        rm -rf "${STAGE_TMP}" || true
    fi
}
trap cleanup EXIT

log_info() { printf "\033[1;36m[DA-V]\033[0m %s\n" "$*"; }
log_ok()   { printf "\033[1;32m[OK]\033[0m   %s\n" "$*"; }
log_warn() { printf "\033[1;33m[AVISO]\033[0m %s\n" "$*"; }
log_err()  { printf "\033[1;31m[ERRO]\033[0m  %s\n" "$*" >&2; }

echo "======================================================================"
echo "  DA-V — Desempacotador e Assistente de Instalação Linux (MonoTech)"
echo "======================================================================"

if [ "$(id -u)" -eq 0 ]; then
    log_err "Execute este script com seu usuário normal (sem sudo)."
    log_err "O instalador solicitará permissão administrativa (sudo/Polkit) apenas se necessário."
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ------------------------------------------------------------------------------
# 1. Validar sessão gráfica ativa (Wayland ou X11) para abrir o instalador Qt
# ------------------------------------------------------------------------------
if [ -n "${WAYLAND_DISPLAY:-}" ] || [ "${XDG_SESSION_TYPE:-}" = "wayland" ]; then
    log_info "Sessão gráfica detectada: Wayland (${WAYLAND_DISPLAY:-wayland-0})"
    # Mantém XDG_SESSION_TYPE/WAYLAND_DISPLAY intactos para captura PipeWire nativa,
    # mas prioriza XWayland (xcb) no Qt6 quando DISPLAY existir para evitar glitches de
    # decorações client-side no GNOME Wayland.
    if [ -n "${DISPLAY:-}" ]; then
        export QT_QPA_PLATFORM="${QT_QPA_PLATFORM:-xcb;wayland}"
    else
        export QT_QPA_PLATFORM="${QT_QPA_PLATFORM:-wayland;xcb}"
    fi
    IS_WAYLAND=1
elif [ -n "${DISPLAY:-}" ]; then
    log_info "Sessão gráfica detectada: X11 (${DISPLAY})"
    export QT_QPA_PLATFORM="${QT_QPA_PLATFORM:-xcb}"
    IS_WAYLAND=0
else
    log_err "Nenhuma sessão gráfica (DISPLAY / WAYLAND_DISPLAY) encontrada."
    log_err "Execute este script dentro do seu desktop Linux (GNOME, KDE, XFCE, Sway, etc.)."
    exit 1
fi

# ------------------------------------------------------------------------------
# 2. Verificar bibliotecas gráficas essenciais do sistema (Qt xcb-cursor / Wayland)
# ------------------------------------------------------------------------------
ensure_runtime_deps() {
    local need_source_deps="$1"
    if command -v apt-get >/dev/null 2>&1; then
        local missing_pkgs=()
        if ! dpkg -s libxcb-cursor0 >/dev/null 2>&1; then
            missing_pkgs+=("libxcb-cursor0")
        fi
        if [ "${IS_WAYLAND}" -eq 1 ] && ! command -v gst-launch-1.0 >/dev/null 2>&1; then
            missing_pkgs+=("python3-gi" "gstreamer1.0-pipewire" "gstreamer1.0-tools" "gstreamer1.0-plugins-base")
        fi
        if [ "${need_source_deps}" -eq 1 ]; then
            command -v python3 >/dev/null 2>&1 || missing_pkgs+=("python3")
            dpkg -s python3-venv >/dev/null 2>&1 || missing_pkgs+=("python3-venv")
            command -v ffmpeg >/dev/null 2>&1 || missing_pkgs+=("ffmpeg")
        fi
        if [ "${#missing_pkgs[@]}" -gt 0 ]; then
            log_info "Instalando bibliotecas de suporte da distribuição (${missing_pkgs[*]})..."
            if sudo apt-get update && sudo apt-get install -y "${missing_pkgs[@]}"; then
                log_ok "Dependências de sistema verificadas."
            else
                log_warn "Não foi possível instalar pacotes via apt automaticamente; prosseguindo."
            fi
        fi
    elif command -v dnf >/dev/null 2>&1 && [ "${need_source_deps}" -eq 1 ]; then
        if ! command -v python3 >/dev/null 2>&1; then
            sudo dnf install -y python3 python3-pip libxkbcommon-x11 || true
        fi
    elif command -v pacman >/dev/null 2>&1 && [ "${need_source_deps}" -eq 1 ]; then
        if ! command -v python3 >/dev/null 2>&1; then
            sudo pacman -Sy --noconfirm python python-pip xcb-util-cursor || true
        fi
    fi
}

# ------------------------------------------------------------------------------
# 3. Localizar arquivo .tar.gz, diretório já desempacotado ou baixar da Release
# ------------------------------------------------------------------------------
ARCHIVE_PATH=""
UNPACKED_SOURCE_DIR=""

# Prioridade 1: pacote passado explicitamente como argumento
if [ "${1:-}" != "" ] && [ -f "$1" ]; then
    ARCHIVE_PATH="$(cd "$(dirname "$1")" && pwd)/$(basename "$1")"
# Prioridade 2: script já está sendo executado dentro de uma pasta desempacotada do DA-V
elif [ -f "${SCRIPT_DIR}/DA-V_Instalador_Linux_x86_64" ] || [ -f "${SCRIPT_DIR}/scripts/dav_installer_linux.py" ]; then
    UNPACKED_SOURCE_DIR="${SCRIPT_DIR}"
else
    # Prioridade 3: procura .tar.gz na pasta atual, pasta do script, release_assets ou ~/Downloads
    for search_dir in "${PWD}" "${SCRIPT_DIR}" "${SCRIPT_DIR}/release_assets" "${HOME}/Downloads"; do
        if [ -d "${search_dir}" ]; then
            found_tar="$(find "${search_dir}" -maxdepth 1 -type f \( -name "DA-V*Linux*.tar.gz" -o -name "DA-V*linux*.tar.gz" -o -name "DA-V*.tgz" \) 2>/dev/null | sort -V | tail -n 1 || true)"
            if [ -n "${found_tar}" ] && [ -f "${found_tar}" ]; then
                ARCHIVE_PATH="${found_tar}"
                break
            fi
        fi
    done
fi

# Caso o usuário tenha baixado apenas o install_linux.sh isolado: baixa o .tar.gz oficial
if [ -z "${ARCHIVE_PATH}" ] && [ -z "${UNPACKED_SOURCE_DIR}" ]; then
    log_info "Nenhum pacote local encontrado. Consultando última release oficial no GitHub (${REPO_SLUG})..."
    STAGE_TMP="$(mktemp -d "${TMPDIR:-/tmp}/dav-setup-XXXXXX")"
    API_URL="https://api.github.com/repos/${REPO_SLUG}/releases/latest"
    DL_URL=""
    if command -v curl >/dev/null 2>&1; then
        DL_URL="$(curl -fsSL "${API_URL}" | grep -Eo 'https://[^"]+Linux[^"]+\.tar\.gz' | head -n 1 || true)"
    elif command -v wget >/dev/null 2>&1; then
        DL_URL="$(wget -qO- "${API_URL}" | grep -Eo 'https://[^"]+Linux[^"]+\.tar\.gz' | head -n 1 || true)"
    fi

    if [ -z "${DL_URL}" ]; then
        log_err "Não foi possível localizar um arquivo DA-V*Linux*.tar.gz local nem baixar do GitHub."
        log_err "Passe o caminho do arquivo manualmente: ./install_linux.sh DA-V_v5.0.0_Linux_x86_64.tar.gz"
        exit 1
    fi

    ARCHIVE_PATH="${STAGE_TMP}/$(basename "${DL_URL}")"
    log_info "Baixando pacote Linux: ${DL_URL}"
    if command -v curl >/dev/null 2>&1; then
        curl -fL --progress-bar -o "${ARCHIVE_PATH}" "${DL_URL}"
    else
        wget --show-progress -O "${ARCHIVE_PATH}" "${DL_URL}"
    fi
    log_ok "Download concluído: ${ARCHIVE_PATH}"
fi

# ------------------------------------------------------------------------------
# 4. Desempacotar o pacote e preparar execução do Instalador Gráfico
# ------------------------------------------------------------------------------
EXTRACTED_ROOT=""

if [ -n "${ARCHIVE_PATH}" ]; then
    log_info "Desempacotando pacote: $(basename "${ARCHIVE_PATH}")"
    if [ -z "${STAGE_TMP}" ]; then
        STAGE_TMP="$(mktemp -d "${TMPDIR:-/tmp}/dav-setup-XXXXXX")"
    fi
    EXTRACT_DEST="${STAGE_TMP}/unpacked"
    mkdir -p "${EXTRACT_DEST}"
    tar -xzf "${ARCHIVE_PATH}" -C "${EXTRACT_DEST}"

    # Identifica se o tarball possui subpasta raiz única (ex: DA-V-v5.0.0-Linux-x86_64/)
    first_sub="$(find "${EXTRACT_DEST}" -mindepth 1 -maxdepth 1 -type d | head -n 1 || true)"
    if [ -n "${first_sub}" ] && { [ -f "${first_sub}/DA-V_Instalador_Linux_x86_64" ] || [ -f "${first_sub}/scripts/dav_installer_linux.py" ]; }; then
        EXTRACTED_ROOT="${first_sub}"
    else
        EXTRACTED_ROOT="${EXTRACT_DEST}"
    fi
    log_ok "Arquivos extraídos com sucesso."
else
    EXTRACTED_ROOT="${UNPACKED_SOURCE_DIR}"
    log_info "Utilizando diretório local já desempacotado: ${EXTRACTED_ROOT}"
fi

# ------------------------------------------------------------------------------
# 5. Rota A (Binário ELF Pré-Compilado) vs Rota B (Pacote Portátil em Código-Fonte)
# ------------------------------------------------------------------------------
if [ -f "${EXTRACTED_ROOT}/DA-V_Instalador_Linux_x86_64" ]; then
    ensure_runtime_deps 0
    chmod +x "${EXTRACTED_ROOT}/DA-V_Instalador_Linux_x86_64"
    [ -f "${EXTRACTED_ROOT}/DA-V" ] && chmod +x "${EXTRACTED_ROOT}/DA-V"
    [ -f "${EXTRACTED_ROOT}/launch_dav.sh" ] && chmod +x "${EXTRACTED_ROOT}/launch_dav.sh"

    log_ok "Abrindo o Instalador Gráfico Glassmorphism do DA-V..."
    "${EXTRACTED_ROOT}/DA-V_Instalador_Linux_x86_64"
    exit 0
fi

if [ -f "${EXTRACTED_ROOT}/scripts/dav_installer_linux.py" ]; then
    ensure_runtime_deps 1

    # Copia para ~/.local/share/dav removendo artefatos de versões anteriores (ex: v4.9.0)
    REAL_EXT="$(cd "${EXTRACTED_ROOT}" && pwd)"
    PKG_VER="desconhecida"
    if [ -f "${EXTRACTED_ROOT}/VERSION" ]; then
        PKG_VER="$(tr -d '[:space:]' < "${EXTRACTED_ROOT}/VERSION")"
    fi
    log_info "Versão detectada no pacote: DA-V v${PKG_VER}"

    mkdir -p "$(dirname "${INSTALL_HOME}")"
    if [ "${REAL_EXT}" != "${INSTALL_HOME}" ]; then
        log_info "Atualizando arquivos base em ${INSTALL_HOME}..."
        mkdir -p "${INSTALL_HOME}"
        rm -rf "${INSTALL_HOME}/DA-V" "${INSTALL_HOME}/_internal" "${INSTALL_HOME}/DA-V_Instalador_Linux_x86_64" \
               "${INSTALL_HOME}/src" "${INSTALL_HOME}/scripts" "${INSTALL_HOME}/installer"
        cp -a "${EXTRACTED_ROOT}/." "${INSTALL_HOME}/"
    fi

    chmod +x "${INSTALL_HOME}/launch_dav.sh" 2>/dev/null || true
    chmod +x "${INSTALL_HOME}/build_linux.sh" 2>/dev/null || true

    # Provisiona ou atualiza ambiente virtual isolado (.venv)
    REQ_HASH=""
    if [ -f "${INSTALL_HOME}/requirements.txt" ] && command -v sha256sum >/dev/null 2>&1; then
        REQ_HASH="$(sha256sum "${INSTALL_HOME}/requirements.txt" | awk '{print $1}')"
    fi
    if [ ! -x "${INSTALL_HOME}/.venv/bin/python" ]; then
        log_info "Preparando ambiente Python isolado em ${INSTALL_HOME}/.venv..."
        python3 -m venv "${INSTALL_HOME}/.venv"
        "${INSTALL_HOME}/.venv/bin/python" -m pip install --upgrade pip
        "${INSTALL_HOME}/.venv/bin/python" -m pip install -r "${INSTALL_HOME}/requirements.txt"
        [ -n "${REQ_HASH}" ] && printf "%s\n" "${REQ_HASH}" > "${INSTALL_HOME}/.venv/.req_sha256"
        log_ok "Ambiente virtual configurado."
    elif [ -n "${REQ_HASH}" ] && [ "$(cat "${INSTALL_HOME}/.venv/.req_sha256" 2>/dev/null || true)" != "${REQ_HASH}" ]; then
        log_info "Sincronizando dependências Python da versão v${PKG_VER}..."
        "${INSTALL_HOME}/.venv/bin/python" -m pip install -q -r "${INSTALL_HOME}/requirements.txt"
        printf "%s\n" "${REQ_HASH}" > "${INSTALL_HOME}/.venv/.req_sha256"
    fi

    # Compila opcionalmente o core nativo C++23 se cmake e g++ estiverem presentes
    if [ ! -f "${INSTALL_HOME}/build/libdav_core.so" ] && [ -f "${INSTALL_HOME}/build_linux.sh" ] && command -v cmake >/dev/null 2>&1 && command -v g++ >/dev/null 2>&1; then
        log_info "Compilando biblioteca nativa C++23 (libdav_core.so)..."
        (cd "${INSTALL_HOME}" && ./build_linux.sh) || log_warn "Prosseguindo com pipeline Python/SIMD."
    fi

    log_ok "Abrindo o Instalador Gráfico Glassmorphism do DA-V para configuração..."
    cd "${INSTALL_HOME}"
    exec "${INSTALL_HOME}/.venv/bin/python" "${INSTALL_HOME}/scripts/dav_installer_linux.py"
fi

log_err "Estrutura do pacote inválida: instalador não encontrado em ${EXTRACTED_ROOT}."
exit 1
