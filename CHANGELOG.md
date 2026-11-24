# Changelog — DA-V (Distribuidor Amplo de Vídeo)

Todas as mudanças arquiteturais, melhorias de protocolo e marcos de governança relevantes do projeto estão documentados neste arquivo, seguindo [Semantic Versioning](https://semver.org/lang/pt-BR/).

---

## [5.0.0] — 2026-11-24

### Módulo completo de compartilhamento de área de trabalho (`src/dav/modules/remote_desktop/`)
- **10ª fatia vertical no MonoTech Core Kernel:** Implementação completa de controle remoto bidirecional e espaço de trabalho compartilhado (`protocol.py`, `keymap.py`, `security_gate.py`, `injector_base.py`, `injector_win32.py`, `injector_linux.py`, `elevation.py`, `workspace_agent.py`, `service.py`, `manifest.py`), preservando a arquitetura P2P Single-Socket com PAKE CPace-X25519 + ChaCha20-Poly1305 AEAD sobre LAN Direto, WAN STUN e CGNAT Blind Relay (`DAV_RLY1`).
- **Canal de entrada sub-milissegundo (`PT_INPUT = 0x04`) e meta Input-to-Photon <= 15 ms:** Pacote compacto de 24 bytes (`!BBBBiiIQ`) sem bloqueio *Head-of-Line*, envio redundante `2x` para transições críticas (cliques/teclas), remoção do `sleep(0.05)` no loop reverso (`select(..., 0.002)` + `input_wake_evt` + DSCP EF `IP_TOS=0xB8`), coalescência de ponteiro a `250 Hz` no receptor e injeção nativa (`user32.SendInput` 40B no Windows; cascata `/dev/uinput`, XDG `RemoteDesktop` Portal e `libXtst.so.6` no Linux).
- **Segurança Zero-Trust, Switch de Modo Interativo e Broker Administrativo (UAC / Polkit):** Sessões iniciam em modo *Somente Visualização* por padrão, com `GlassToggleSwitch` de **Transmissão Interativa** no `SenderHomePage`, revogação de emergência `Ctrl+Alt+Shift+Esc`, `StuckKeyWatchdog` (soltura automática em perda de foco ou timeout de 350 ms) e micro-broker isolado (`--elevated-input-broker`, autenticado via HMAC-SHA256) acionado sob demanda por UAC (`ShellExecuteW("runas")`) no Windows e Polkit (`pkexec`) no Linux.
- **Canal confiável de área de trabalho (`PT_WORKSPACE = 0x05`) e telemetria TUPÃ:** Sincronização bidirecional de Clipboard deduplicada por SHA-256, transferência P2P de arquivos por *Drag & Drop* com verificação SHA-256 e proteção contra *path traversal*, terminal remoto persistente estilo LTSP (`PtyShellManager` + aba `Terminal` na `StatsSheet`) e nova sonda `TupaInputLatencyProbe` no `TupaView`.

### Redesign Glassmorphism dos instaladores e automação Linux
- **Design System Glassmorphism unificado nos instaladores (`src/ui/glass/installer_shell.py`):** Novo `DavGlassInstallerDialog` compartilhado por `scripts/dav_installer_win.py` e `scripts/dav_installer_linux.py` com gradiente atmosférico, `GlassCard(dark=True)`, Stepper lateral em pílula neon, ícones vetoriais sombreados, estilo `Fusion` + paleta escura (`apply_glass_app_theme`) imune a temas claros de sistema (GNOME Adwaita).
- **Desempacotador e assistente Linux (`install_linux.sh`):** Script shell automatizado que detecta pacotes locais ou diretório já desempacotado, valida dependências gráficas X11/Wayland/PipeWire, atualiza `~/.local/share/dav` de forma limpa e abre o instalador gráfico Glassmorphism.

---

## [4.9.0] — 2026-11-18

### Governança Jurídica, Licenciamento GNU AGPLv3 + Seção 7 (NOTICE) e Compliance
- **Instituição da Licença GNU AGPLv3 com Termos Adicionais da Seção 7 (`AGPL-3.0-or-later`):** Substituição da licença anterior pelo texto oficial da **GNU Affero General Public License v3.0** suplementado pelas alíneas **7(b) a 7(e)** e **Seção 5(d)** (`LICENSE` e `NOTICE`), tornando juridicamente obrigatória a preservação do arquivo `NOTICE` e da atribuição autoral a **Dante Ferraz (MonoTech)** na interface gráfica e em qualquer redistribuição ou serviço em rede.
- **Compliance Integral de Componentes de Terceiros e Marca:** Adicionados `NOTICE`, `TRADEMARK.md`, `THIRD_PARTY_LICENSES.md`, `LICENSES/` (`AGPL-3.0.txt`, `GPL-3.0.txt`, `LGPL-3.0.txt`), `third_party/kcp/LICENSE` e cabeçalhos padronizados SPDX em todos os módulos Python e C/C++ autorais; atualizado o diálogo *"Sobre o Autor & Tecnologias"* (`AuthorShowcaseDialog`) com abas dedicadas ao `NOTICE` obrigatório e às licenças de terceiros (`PySide6/Qt6`, `FFmpeg`, `x264/x265`, `KCP`, `OpenSSL 3`).
- **Ícone Oficial Glassmorphism Multiplataforma:** Novo ícone multirresolução (`installer/dav_icon.ico` no padrão Win32 `BMP/DIB + PNG` e `installer/dav_icon.png`) integrado ao aplicativo e aos atalhos de Área de Trabalho/Menu em Windows e Linux com invalidação automática de cache de ícones do Shell.

### Experiência do Usuário (UX), Sombreamento e Navegação Resiliente
- **Controles Vetoriais Flutuantes na Transmissão (`VideoOverlayControls`):** Adicionados botões de **Ativar/Desativar Áudio** (`draw_speaker`) e **Tela Cheia** (`draw_fullscreen_corners`) no canto inferior direito com sombreamento projetado e sincronização bidirecional com `SettingsSheet.chk_audio_rx`, `chk_audio_tx`, `DesktopAudioPlayer`, `StreamEngineService.set_sender_audio_muted` e eventos de janela (`F11` / `Esc`).
- **Sombreamento (`Drop-Shadow`) Vetorial e Tipográfico:** Adicionados tokens de sombra (`tokens.py`) e camada dupla de sombra suave em todos os ícones vetoriais (`icons.py`) e textos (`paint_shadowed_text` em `paint.py`, aplicado em `GlassLabel`, `GlassButton` e `GlassSegmented`), preservando integralmente o layout dos cards principais.
- **Correção Definitiva de Navegação (`ZONE_SWAP`) e Reinício de Transmissão:** O botão central da barra superior (`_swap_mode`) protege transmissões ativas contra interrupção acidental (`flash_warning`); `_on_target_updated` preserva `txt_send_ip` e `spn_send_port` após pareamento P2P para garantir descoberta STUN e registro limpo no reinício; adicionado `_sender_session_epoch` em `_bg_register_sender` e `join(timeout=0.8)` após `terminate()` em `StreamEngineService.stop()`.

### Motor Salsify / SQP, Áudio Opus Low-Delay e Estabilização WAN (v4.7–v4.8)
- **Subprocesso TX Lockless & Pacing Cut-Through / Burst-Guard:** Desacoplamento de fila de áudio Opus 48 kHz + pré-empção no micro-pacer e FEC adaptado para links WAN com perda.
- **Controle SQP em 3 Zonas & BDP Imune a Bufferbloat:** Janela deslizante de RTT base (`15 s`), zona de retenção (Hold) sem serrilhado e histerese VBV segura para `libx264` e `h264_nvenc`.

---

## [4.0.0] — 2026-11-11

### Arquitetura & Modularização Completa (MonoTech Core Kernel v2.0)
- **Migração Modular em Fatias Verticais (`src/dav/`):** Refatoração integral do monólito em fatias modulares desacopladas e autônomas:
  - `src/dav/kernel/`: Núcleo funcional corporativo contendo `result.py` (`ServiceResult[T]`, `FrameDTO`, `RouteDTO`, `TelemetryDTO`), `registry.py` (`ModuleRegistry` & `ModuleManifest` com descoberta dinâmica e ciclo de vida topológico), `event_bus.py` (Barramento de eventos thread-safe não-bloqueante), `buffer_pool.py` (`L1BufferPool` com memória contígua `O(1)` e fallback seguro), `circuit_breaker.py` (Máquina de estados `CLOSED`, `OPEN`, `HALF_OPEN` para isolamento de latência e falhas de rede externa), e `config.py` (`ConfigEngine` hierárquico com suporte a `dav.toml` e variáveis de ambiente).
  - `src/dav/modules/capture/`: Fatia de captura de tela com fábrica multiplataforma (`WindowsCapturer` com WGC Direct3D / MSS, `LinuxCapturer` com Wayland PipeWire Portal / X11 sentinela anti-black-frame, e `SyntheticCapturer` para ambientes de testes e CI/CD).
  - `src/dav/modules/codec/`: Fatia de compressão e descompressão de vídeo com suporte a aceleração por hardware NVIDIA NVENC, CPU multi-core `libx264` AVX2 sliced-threads, escala e conversão de espaço de cores SIMD em passe único (`bgra -> yuv420p`), e decodificador PyAV com garantia estrita de buffers C-contíguos para qualquer resolução (ex: notebooks `1366x768`).
  - `src/dav/modules/transport_p2p/`: Fatia de rede P2P Single-Socket contendo cabeçalho binário de 32 bytes (`DAV_SSRC`), vetor criptográfico simétrico SIMD derivado do PIN, fragmentador/remontador MTU 1320 com autenticação, consulta STUN RFC 5389 sobre o mesmo socket de mídia, agregador de candidatos ICE-lite (LAN, Overlay Tailscale, WAN STUN, portas adjacentes) e tunelamento Blind Relay UDP (`DAV_RLY1`).
  - `src/dav/modules/stream_engine/`: Motor de streaming ativo desacoplado (`SenderWorker` e `ReceiverWorker`) com cadência precisa de 60/120 FPS, recuperação instantânea de quadros-chave sob demanda (PLI), chaveamento dinâmico LAN Direto / WAN P2P / Blind Relay e orquestrador de alto nível `StreamEngineService`.
  - `src/dav/modules/commercial/`: Governança autoral e módulo aberto (**MonoTech Community Edition 100% Free**): resolução até 4K UHD, 120 FPS, duração de sessão ilimitada, aceleração por hardware irrestrita, sem paywalls ou limitações artificiais, vitrine autoral oficial com atribuição canônica a **Dante Ferraz** e verificador de licenças criptográfico opcional para clusters empresariais.
  - `src/dav/modules/telemetry/`: Observabilidade de streaming em tempo real com sondas de rede baseadas no protocolo **TUPÃ** (cálculo instantâneo de jitter RFC 3550, RTT, perda de pacotes e vazão) e exportador resiliente protegido por CircuitBreaker para o Hub **SDE v2.0** na Oracle Cloud VPS.
  - `src/dav/modules/presentation/`: Diálogo interativo e modal nativo PySide6 *"Sobre o Autor & Tecnologias"* acessível via barra de navegação lateral.

### Segurança, Testes & Governança
- **Snapshot de Transição Seguro:** Criado branch `snapshot-v3.2.1-pre-modularizacao` e tag `v3.2.1-snapshot`, com preservação em arquivo comprimido (`backups/snapshot_v3.2.1_pre_modularizacao/dav_v3.2.1_source_snapshot.zip`) e inventário arquitetural detalhado (`ARCH_V3_SNAPSHOT.md`).
- **Suíte de Testes Automatizados (30/30 Passando):** 100% dos testes unitários e de integração aprovados em tempo recorde (`tests/test_kernel.py`, `tests/test_media_slices.py`, `tests/test_stream_engine.py`, `tests/test_commercial.py`, `tests/test_telemetry.py`, `tests/test_presentation.py`, `tests/test_p2p_e2e.py`, etc.).
- **Compatibilidade Regressiva Total:** Mantida integridade dos scripts de inicialização legados (`scripts/gui_app.py`, `scripts/dav_client.py`).

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

