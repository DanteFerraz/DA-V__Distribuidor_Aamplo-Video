# DA-V: Distribuidor Amplo de Vídeo — Guia Operacional Linux

Guia canônico de instalação, compilação nativa C++23 e execução do ecossistema **DA-V** em distribuições Linux (Ubuntu 22.04/24.04, Debian 12, Arch Linux, Oracle Linux 9 / RHEL).

---

## 1. Visão Geral da Portabilidade Linux

O DA-V foi projetado com arquitetura modular desacoplada:
1. **Core C++23 (`libdav_core.so` & `dav_daemon`)**:
   - Captura de tela nativa X11 com aceleração via extensão MIT-SHM (`XShmCreateImage`, `XShmGetImage`) com zero-copy para o buffer de ring SPSC lock-free.
   - Fallback de captura de vídeo sintético/MSS caso executado em ambientes de teste sem display ativo ou containers Docker.
   - Sockets POSIX com `SO_REUSEPORT`, `SO_REUSEADDR` e `TCP_NODELAY`.
2. **Worker e Pipeline Python 3 (`scripts/dav_sender_worker.py`)**:
   - Pacing de 60 FPS garantido via relógio de precisão `time.perf_counter()`.
   - Prioridade de processo elevada via POSIX `os.nice(-10)`.
   - Afinidade de núcleos de CPU via `os.sched_setaffinity` para isolar threads de captura, encoding H.264 e encriptação ChaCha20-Poly1305.
   - Encriptação autenticada AEAD de 256 bits com integridade de pacotes e recuperação FEC.
3. **Interface Gráfica PySide6 (`scripts/gui_app.py`)**:
   - Suporte transparente a servidores X11 (`QT_QPA_PLATFORM=xcb`) e Wayland (`QT_QPA_PLATFORM=wayland`).
   - Diagnóstico automático e liberação de portas de firewall via `ufw` e `iptables`.

---

## 2. Pré-Requisitos do Sistema (Ubuntu 24.04 / 26.04 LTS & Debian 12)

```bash
sudo apt update && sudo apt install -y \
    build-essential \
    cmake \
    ninja-build \
    libx11-dev \
    libxext-dev \
    libxfixes-dev \
    libxrandr-dev \
    libgl1-mesa-dev \
    libglib2.0-0 \
    libegl1 \
    libxcb-cursor0 \
    libxcb-xinerama0 \
    libxcb-icccm4 \
    libxcb-image0 \
    libxcb-keysyms1 \
    libxcb-render-util0 \
    libxcb-shape0 \
    libxcb-xkb1 \
    libxkbcommon-x11-0 \
    ffmpeg \
    python3 \
    python3-venv \
    python3-pip \
    python3-dev \
    ufw
```

### Arch Linux
```bash
sudo pacman -Syu --noconfirm \
    base-devel \
    cmake \
    ninja \
    libx11 \
    libxext \
    mesa \
    python \
    python-pip
```

---

## 3. Compilação do Backend C++23

Execute o script de compilação automatizada:
```bash
chmod +x build_linux.sh
./build_linux.sh
```

O script detecta o compilador (`g++-13`, `g++`, `clang++`), configura o CMake em modo `Release` e gera:
- `build/libdav_core.so`: Biblioteca compartilhada C-ABI.
- `build/dav_daemon`: Daemon standalone do serviço.

---

## 4. Execução do DA-V

### Inicialização Automática (Interface Gráfica)
```bash
chmod +x launch_dav.sh
./launch_dav.sh
```

O `launch_dav.sh` gerencia automaticamente o ambiente virtual Python (`.venv`), instala dependências de `requirements.txt` e configura a plataforma gráfica Qt.

### Inicialização em Modo Daemon (Headless / Servidor de Captura)
```bash
./launch_dav.sh --daemon --port 9200 --monitor 0 --fps 60
```

### Execução da Suíte de Testes no Linux
```bash
./launch_dav.sh --test
```

### Benchmark de Latência e Vazão
```bash
./launch_dav.sh --bench
```

---

## 5. Portas de Rede e Firewall

O DA-V opera utilizando as seguintes portas padrão na arquitetura moderna P2P:
- **Portas UDP 19000-19010**: Transporte de pacotes de vídeo de ultra-baixa latência (60 FPS P2P hole-punching).
- **Porta UDP 9005**: Descoberta e anúncios de peers na Rede Local (LAN Beacon multicast/broadcast).
- **Sinalização WAN**: HTTPS/SSE direto no servidor Rendezvous (Oracle Cloud VPS `129.148.26.150:5000/p2p/`).

Para liberar o tráfego via UFW no Ubuntu:
```bash
sudo ufw allow 19000:19010/udp comment 'DAV Video Stream P2P'
sudo ufw allow 9005/udp comment 'DAV LAN Beacon'
sudo ufw reload
```

---

## 6. Integração com TCD (Transmissor e Coletor de Dados)

Quando utilizado em conjunto com o TCD:
1. O TCD atua como nó de sinalização WAN e retransmissão de acervo de mídia de alto desempenho.
2. O DA-V consulta o TCD via WebSocket para descoberta de canais e peers na rede local ou WAN.
3. Para iniciar ambos no mesmo host Linux, utilize o serviço do TCD (`systemctl start tcd`) e inicie o DA-V via `./launch_dav.sh`.
