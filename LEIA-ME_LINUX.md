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

## 2. Pré-Requisitos do Sistema

### Ubuntu 22.04 / 24.04 LTS & Debian 12
```bash
sudo apt update && sudo apt install -y \
    build-essential \
    cmake \
    ninja-build \
    libx11-dev \
    libxext-dev \
    libgl1-mesa-glx \
    libglib2.0-0 \
    python3 \
    python3-venv \
    python3-pip \
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

O DA-V opera utilizando as seguintes portas padrão:
- **Porta UDP 9200**: Transporte de vídeo em tempo real (KCP / UDP de baixa latência).
- **Porta TCP 8799**: Sinalização WAN / P2P Rendezvous e troca de candidatos ICE.
- **Porta TCP 9100**: Exposição de telemetria e métricas padrão Prometheus.

Para liberar o tráfego via UFW:
```bash
sudo ufw allow 9200/udp comment 'DAV Video Stream'
sudo ufw allow 8799/tcp comment 'DAV Signaling'
sudo ufw allow 9100/tcp comment 'DAV Prometheus'
```

---

## 6. Integração com TCD (Transmissor e Coletor de Dados)

Quando utilizado em conjunto com o TCD:
1. O TCD atua como nó de sinalização WAN e retransmissão de acervo de mídia de alto desempenho.
2. O DA-V consulta o TCD via WebSocket para descoberta de canais e peers na rede local ou WAN.
3. Para iniciar ambos no mesmo host Linux, utilize o serviço do TCD (`systemctl start tcd`) e inicie o DA-V via `./launch_dav.sh`.
