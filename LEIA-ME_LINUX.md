# DA-V v3.2.0 — Guia Operacional e Técnico para Linux

Documentação dedicada à instalação, compilação e operação do **DA-V (Distribuidor Amplo de Vídeo)** em distribuições Linux modernas (**Ubuntu 22.04 / 24.04 / 26.04 LTS**, **Debian 12+**, **Fedora 40+** e **Arch Linux**).

---

## 1. Como o DA-V Opera no Linux

A edição Linux compartilha **exatamente o mesmo protocolo binário de rede e motor P2P Single-Socket** da edição Windows, garantindo interoperabilidade direta **Windows ↔ Linux** em qualquer direção (Linux transmitindo para Windows, Windows transmitindo para Linux ou Linux para Linux):

1. **Motor Unificado de Mídia (`scripts/dav_client.py` + `scripts/dav_sender_worker.py`):**
   - **Codificação:** Utiliza `h264_nvenc` automaticamente quando há GPU NVIDIA com drivers proprietários instalados; caso contrário, comuta sem intervenção para **`libx264` (`ultrafast` + `zerolatency` + `sliced-threads` multi-core)** via FFmpeg/PyAV, sustentando 60 FPS mesmo em CPUs integradas Intel/AMD.
   - **Escalonamento POSIX:** Aplica `os.nice(-10)` (quando permitido) e afinidade de núcleos via `os.sched_setaffinity` em um processo separado, isolando o loop de vídeo da interface gráfica Qt.
2. **Servidor Gráfico (Wayland e X11 Nativos):**
   - Como **Receptor (Assistir)**: Suporte nativo completo tanto em sessões **Wayland** (`QT_QPA_PLATFORM=wayland;xcb`) quanto **X11** (`QT_QPA_PLATFORM=xcb`).
   - Como **Transmissor (Compartilhar Tela)**: A partir da **v3.2.0**, o DA-V possui integração nativa com o **XDG Desktop Portal (`org.freedesktop.portal.ScreenCast`) + PipeWire**, transmitindo a 60 FPS diretamente no **Ubuntu GNOME (Wayland)**, KDE Plasma e Hyprland sem necessidade de migrar para Xorg! Na primeira transmissão Wayland, o sistema exibe a janela nativa de autorização ("Compartilhar Tela"). Em sessões X11, o DA-V utiliza captura direta via XShm/MSS.
3. **Core C++23 Opcional (`libdav_core.so` & `dav_daemon`):**
   - Implementa captura nativa **X11 MIT-SHM** (`XShmCreateImage` / `XShmGetImage`) e sockets POSIX de baixa latência, compatível com **GCC 13, 14 e 15** (incluindo Ubuntu 26.04 LTS).

---

## 2. Instalação de Dependências do Sistema

### Ubuntu 22.04 / 24.04 / 26.04 LTS e Debian 12+

```bash
sudo apt update && sudo apt install -y \
    build-essential cmake ninja-build \
    python3 python3-venv python3-pip python3-dev python3-gi \
    gstreamer1.0-pipewire gstreamer1.0-tools gstreamer1.0-plugins-base \
    libx11-dev libxext-dev libxfixes-dev libxrandr-dev \
    libgl1-mesa-dev libglib2.0-0 libegl1 \
    libxcb-cursor0 libxcb-xinerama0 libxcb-icccm4 libxcb-image0 \
    libxcb-keysyms1 libxcb-render-util0 libxcb-shape0 libxcb-xkb1 \
    libxkbcommon-x11-0 ffmpeg ufw git
```

### Arch Linux / Manjaro

```bash
sudo pacman -Syu --noconfirm \
    base-devel cmake ninja libx11 libxext libxrandr libxfixes \
    mesa ffmpeg python python-pip ufw git
```

### Fedora 40+ / RHEL 9 / Oracle Linux 9

```bash
sudo dnf install -y \
    gcc-c++ cmake ninja-build python3 python3-devel python3-pip \
    libX11-devel libXext-devel libXfixes-devel libXrandr-devel \
    mesa-libGL-devel libxkbcommon-x11 ffmpeg-free git
```

---

## 3. Execução Rápida e Integração ao Desktop

### Iniciar Diretamente (Provisionamento Automático da `.venv`)

```bash
chmod +x launch_dav.sh
./launch_dav.sh
```

Na primeira execução, o `launch_dav.sh` cria o ambiente `.venv`, instala os pacotes de `requirements.txt`, detecta `WAYLAND_DISPLAY` / `DISPLAY` e abre a interface gráfica.

### Assistente Gráfico de Instalação Linux (Menu de Aplicativos + `dav://` + UFW)

Para adicionar o DA-V ao lançador do GNOME/KDE, associar links de convite `dav://connect/PIN` via `xdg-mime` e configurar o firewall:

```bash
source .venv/bin/activate
python3 scripts/dav_installer_linux.py
```

> **Importante:** Sempre execute scripts da pasta `scripts/` a partir do diretório raiz do projeto (`python3 scripts/dav_installer_linux.py`) para que o pacote raiz seja resolvido corretamente pelo Python.

### Compilação Opcional do Backend C++23

```bash
chmod +x build_linux.sh
./build_linux.sh
```

Artefatos gerados em `build/`:
- `build/libdav_core.so`: Biblioteca compartilhada C-ABI.
- `build/dav_daemon`: Executável standalone do serviço C++23.

---

## 4. Comandos Úteis de Linha de Comando

```bash
# Executar toda a suíte de validação (unitários + P2P Hole-Punching + Blind Relay)
./launch_dav.sh --test

# Executar benchmark de latência e vazão
./launch_dav.sh --bench

# Rodar apenas o Transmissor em modo Headless / Servidor
./launch_dav.sh --daemon --port 9000 --pin 845-747 --fps 60
```

---

## 5. Portas de Rede e Firewall (UFW)

O DA-V v3.1 utiliza as seguintes portas UDP para pareamento local e P2P direto:

- **`9000:9020/udp`** (e faixa auxiliar `19000:19010/udp`): Streaming de vídeo a 60 FPS e sondas de perfuração de NAT (`DAV_P2P_SYN` / `DAV_P2P_ACK`).
- **`9005/udp`**: Descoberta automática de máquinas na mesma rede local (`LanBeaconService`).

Para liberar no Ubuntu/Debian com UFW ativo:

```bash
sudo ufw allow 9000:9020/udp comment 'DA-V P2P Video Stream'
sudo ufw allow 19000:19010/udp comment 'DA-V Auxiliary Ports'
sudo ufw allow 9005/udp comment 'DA-V LAN Discovery Beacon'
sudo ufw reload
```

---

## 6. Implantação do Servidor `DAV-Rendezvous` em VPS Linux (Oracle Cloud)

Para atualizar ou implantar o serviço de sinalização + **Blind Encrypted UDP Relay** em uma VPS Ubuntu/Oracle Linux:

1. Copie o repositório para `/opt/dav` na VPS e instale a unidade `systemd`:
   ```bash
   sudo cp /opt/dav/deploy/dav-rendezvous.service /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl enable --now dav-rendezvous
   sudo systemctl status dav-rendezvous
   ```
2. Libere no firewall da VPS **e** na *Security List / Network Security Group* do painel da nuvem (Oracle Cloud VCN):
   - **TCP `80`** (via Nginx Reverse Proxy para `127.0.0.1:8765`, com `proxy_buffering off;` para SSE) ou **TCP `8765`** direto.
   - **UDP `8768`** (indispensável para que o `RendezvousUdpGateway` responda sondas STUN reflexivas e opere o **Blind Encrypted UDP Relay** em redes com CGNAT Simétrico).
