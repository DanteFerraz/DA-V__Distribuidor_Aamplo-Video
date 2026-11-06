# Changelog — DA-V (Distribuidor Amplo de Vídeo)

Todas as mudanças arquiteturais, melhorias de protocolo e marcos de governança relevantes do projeto estão documentados neste arquivo, seguindo [Semantic Versioning](https://semver.org/lang/pt-BR/).

---

## [3.2.1] — 2026-11-06

### Corrigido
- **Renderização de Resoluções Não Múltiplas de 32 Bytes no Receptor (`1366x768`, `1600x900`, `3440x1440`):** Em resoluções cuja largura em bytes BGR24 (`width * 3`) não é divisível por 32 (como `1366 * 3 = 4098`, alinhado pelo FFmpeg/AVX2 para `linesize = 4128`), `AVFrame.to_ndarray(format="bgr24")` retornava uma visão NumPy não-contígua (`C_CONTIGUOUS = False`), disparando `BufferError: memoryview: underlying buffer is not C-contiguous` ao construir `QImage(bgr.data, ...)` em `DecodeWorker`. `HybridDecoder._convert_frame_to_bgr` e `DecodeWorker._decode_run` agora normalizam buffers não-contíguos via `np.ascontiguousarray` (operação zero-custo quando já contíguo).
- **Atualização Segura com Aplicação Aberta (`dav_installer_win.py`):** O instalador Windows encerra automaticamente instâncias anteriores de `DA-V.exe` antes de extrair os novos binários, evitando bloqueio de DLLs em uso.
- **Sincronia de Estado Conectado e Versão Empacotada:** `ViewerView` sincroniza `video_canvas.is_connected` ao conectar e o arquivo `VERSION` passa a ser embutido nos binários PyInstaller.

---

## [3.2.0] — 2026-11-06

### Adicionado
- **Captura Nativa Wayland via XDG Desktop Portal + PipeWire (`src/capture/linux_wayland_portal.py`):** Elimina a tela preta (`0.02 Mbps` / `1 KB/quadro`) sob Ubuntu GNOME e compositores Wayland (Mutter/KWin/Hyprland). O motor negocia a sessão `org.freedesktop.portal.ScreenCast` via DBus de sistema com ambiente higienizado (desacoplado do `_MEIPASS` em binários PyInstaller), herda o descritor PipeWire Unix e transmite quadros BGRx em baixa latência via GStreamer (`pipewiresrc`) com leitura em double-buffer constante a 60 FPS.
- **Sentinela Automático Anti-Tela-Preta no XWayland:** Caso o fallback X11 (`mss`) detecte quadros vazios (zeros absolutos por isolamento do compositor), comuta a quente e automaticamente para o capturador nativo PipeWire Portal.
- **Resolução Nativa sem Escala (Notebooks 1366x768):** `SenderView` e `DavMainWindow` detectam automaticamente a resolução física do monitor primário quando for menor que 1080p, evitando *upscaling* 2x via CPU e dobrando o FPS e a nitidez.
- **Escala SIMD em Passe Único no FFmpeg (`libswscale`):** `HybridEncoder` unifica o redimensionamento e a conversão de espaço de cores `bgr0 -> yuv420p` em uma única passagem C/AVX2 acelerada.
- **Multi-Core Adaptativo no `libx264`:** Escalonamento automático de threads para compressão H.264 por software (`threads=min(8, os.cpu_count())` e `sliced-threads=1`), sustentando 60 FPS em CPUs modestas.
- **HUD Dinâmico no Receptor:** Telemetria da interface com cálculo em tempo real de `KB/quadro`, rótulo `Latência Rede` e resolução do fluxo recebido, removendo strings estáticas de GPU no cliente receptor.

---

## [3.1.1] — 2026-11-06

### Corrigido
- **Instaladores Autossuficientes (Windows & Linux):** `DA-V_Instalador_Windows_x64.exe` e `DA-V_Instalador_Linux_x86_64` agora trazem embutido o pacote completo da aplicação compilada (`DA-V.exe` / `DA-V` ELF + runtime PySide6 + FFmpeg/PyAV + SIMD), extraindo-o automaticamente em `%LOCALAPPDATA%\Programs\DA-V` (Windows) e `~/.local/share/dav` (Linux). Corrige a falha em que o atalho da Área de Trabalho apontava para o diretório temporário de download sem iniciar o aplicativo.
- **Isolamento Multiprocesso em Binário Congelado:** Adicionado `multiprocessing.freeze_support()` e importação diferida de Qt em `scripts/gui_app.py`, garantindo que o subprocesso `DAV-Sender-Engine` inicie em `< 80 ms` sem reabrir janelas duplicadas.
- **Atalhos Nativos e Ícone Oficial:** Resolução dinâmica de `Desktop` e `Menu Iniciar` via `WScript.Shell.SpecialFolders` (compatível com pastas sincronizadas pelo OneDrive) e adição dos ícones oficiais `installer/dav_icon.ico` e `installer/dav_icon.png`.
- **Renderização Mermaid na Página Principal:** Padronizados conectores `sequenceDiagram` e `flowchart` no `README.md`.

---

## [3.1.0] — 2026-11-06

### Adicionado
- **STUN RFC 5389 Single-Socket:** A descoberta de IP e porta pública externa agora ocorre diretamente no mesmo descritor de arquivo (`socket`) usado pela transmissão e recepção de vídeo, preservando o mapeamento na tabela NAT do roteador e classificando empiricamente o NAT (`cone` vs `symmetric`).
- **Coleta Multi-Candidato (ICE-Lite Nativo):** Sondagem concorrente de interfaces locais físicas (`LAN`), malhas virtuais (`Overlay` `100.64.0.0/10` Tailscale/WireGuard), endpoint público STUN (`WAN`) e predição sequencial de portas adjacentes.
- **Blind Encrypted UDP Relay Real (`DAV_RLY1`):** Implementado no `RendezvousUdpGateway` (`dav_rendezvous.py`, porta `8768/udp`) encaminhamento em memória `O(1)` de datagramas já criptografados ponta a ponta quando ambos os nós operam sob CGNAT Simétrico estrito.
- **Recuperação Instantânea de Keyframe (PLI):** O Receptor solicita quadro IDR + cabeçalhos `SPS/PPS` sob demanda (`DAV_P2P_PLI`) caso ingresse no meio de uma transmissão ou sofra perda no pacote inicial de abertura do NAT.
- **Fallback Automático `libx264` Zero-Latency:** Em máquinas Linux ou Windows sem GPU NVIDIA dedicada, o `HybridEncoder` comuta automaticamente para `libx264` (`ultrafast` + `zerolatency` + `sliced-threads`) via PyAV, sem depender de OpenCV.
- **Pipeline Oficial CI/CD Multiplataforma:** Workflow GitHub Actions (`.github/workflows/release.yml`) para compilação nativa e publicação automática de artefatos Windows (`x64`) e Linux (`x86_64`) a cada tag `v*`.
- **Unidade Systemd de Produção:** Adicionado `deploy/dav-rendezvous.service` para implantação resiliente na VPS Oracle Cloud.

### Corrigido
- Eliminada divergência de protocolo binário (*split-brain*) entre Windows e Linux unificando o motor padrão multiprocesso/SIMD nos dois sistemas operacionais.
- Corrigida rejeição de pacotes de controle menores que 32 bytes no loop de recepção (`dav_client.py`) e adicionada validação estrita de versão/SSRC do cabeçalho RTP-like de 32 bytes.
- Desativado `SIO_UDP_CONNRESET` (`WinError 10054`) nos sockets UDP do Windows durante rajadas de Hole-Punching.
- Corrigido tratamento de convites `dav://connect/<PIN>` para iniciar diretamente em Modo PIN Universal em vez de `127.0.0.1`.
- Unificadas as faixas de portas nos scripts de Firewall Windows/Linux (`UDP 9000-9020`, `19000-19010` e `9005`).

---

## [3.0.0] — 2026-11-03

### Adicionado
- Pareamento instantâneo via **Server-Sent Events (SSE)** (`< 50 ms`) no servidor Rendezvous com fallback resiliente para HTTP Polling.
- Modo **Standby On-Demand** no Transmissor (0% de uso de GPU/captura enquanto aguarda pareamento).
- Instaladores gráficos nativos em tema *Dark Obsidian* para Windows (`dav_installer_win.py`) e Linux (`dav_installer_linux.py`) com associação do protocolo `dav://`.
- Portabilidade C++23 para GCC 15 no Ubuntu 26.04 LTS (`libdav_core.so` e `dav_daemon`).

---

## [1.0.0] — 2026-09-15

### Adicionado
- Captura nativa Windows Graphics Capture (WGC Direct3D), DXGI Desktop Duplication e X11 MIT-SHM.
- Codificação de hardware NVIDIA NVENC (`p1` Ultra-Low Latency) a 1080p 60 FPS cravados.
- Interface Desktop modular em PySide6 com telemetria TUPÃ em tempo real e descoberta automática LAN Beacon.

