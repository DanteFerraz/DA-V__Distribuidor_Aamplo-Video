---
doc_type: session-report
diataxis_quadrant: explanation
project: "DA-V (Distribuidor Amplo de Vídeo)"
session_date: 2026-11-24
main_line: "Implementação do módulo de área de trabalho remota sub-15 ms, broker administrativo UAC/Polkit e redesign Glassmorphism dos instaladores (v5.0.0)"
author: "Dante Ferraz"
status: "verified"
related_adrs:
  - "0002-arquitetura-compartilhamento-area-de-trabalho-e-broker-admin.md"
related_commits: []
---

# Relatório de sessão — 2026-11-24: Implementação do módulo de área de trabalho remota sub-15 ms, broker administrativo UAC/Polkit e redesign Glassmorphism dos instaladores (v5.0.0)

## Resumo executivo

Esta sessão estruturou e implementou a versão `5.0.0` do **DA-V**, introduzindo a 10ª fatia vertical oficial do kernel (`src/dav/modules/remote_desktop/`) para compartilhamento interativo completo de área de trabalho entre Windows 10/11 e Linux (Wayland e X11) com meta *Input-to-Photon* `<= 15 ms` em LAN e teto inicial `<= 30 ms` em WAN. Também foram adicionados o switch de Transmissão Interativa com gatilho isolado de privilégio administrativo (UAC/Polkit), a sonda TUPÃ de latência interativa e a unificação visual dos instaladores Windows e Linux sob o motor `src/ui/glass/`.

## Requisitos e objetivos endereçados

- **OBJ-01:** Implementar controle remoto bidirecional de mouse e teclado em sub-milissegundo sobre o mesmo socket UDP autenticado por PAKE CPace-X25519 + ChaCha20-Poly1305 AEAD (`PT_INPUT = 0x04`, 24 bytes), compatível com LAN Direto, WAN STUN e CGNAT Blind Relay (`DAV_RLY1`).
- **OBJ-02:** Eliminar o atraso reverso de `50 ms` na thread de recepção de controle do Transmissor, substituindo o `sleep(0.05)` por `select(..., 0.002)` contínuo e gatilho de captura antecipada (`input_wake_evt`).
- **OBJ-03:** Instituir modelo Zero-Trust (*Somente Visualização* por padrão) com switch de **Transmissão Interativa** diretamente na tela do Modo Transmissor, revogação instantânea via `Ctrl+Alt+Shift+Esc` e `StuckKeyWatchdog` contra teclas ou botões presos.
- **OBJ-04:** Implementar trigger multiplataforma de autorização administrativa no Windows (`ShellExecuteW("runas")` UAC) e no Linux (`pkexec` Polkit + `/dev/uinput`) via micro-broker isolado (`--elevated-input-broker`) sem derrubar a transmissão ativa nem a sessão PipeWire/WASAPI do usuário.
- **OBJ-05:** Fornecer canal confiável com retransmissão seletiva ordenada (`PT_WORKSPACE = 0x05`) para área de transferência deduplicada por SHA-256, transferência direta P2P de arquivos sanitizada contra *path traversal* e terminal persistente estilo LTSP (`pty` / PowerShell).
- **OBJ-06:** Redesenhar os instaladores gráficos de Windows e Linux utilizando o Design System Glassmorphism atual da aplicação (`src/ui/glass/installer_shell.py`).

## Alterações realizadas por artefato

| Arquivo | Ação | Camada / Bloco C4 | Descrição objetiva da alteração |
| :--- | :--- | :--- | :--- |
| `VERSION` | Modificado | Raiz / Release | Atualização da versão canônica de `4.9.0` para `5.0.0`. |
| `src/dav/kernel/contracts.py` | Modificado | `kernel` | Adição de `IRemoteDesktopService` e dos 5 eventos canônicos `EVENT_REMOTE_*` no barramento. |
| `src/dav/kernel/__init__.py` | Modificado | `kernel` | Exportação pública de `IRemoteDesktopService` e dos novos tópicos de área remota. |
| `src/dav/modules/transport_p2p/packetizer.py` | Modificado | `transport_p2p` | Definição de `PT_INPUT = 0x04` e `PT_WORKSPACE = 0x05` no cabeçalho binário de 32 bytes. |
| `src/dav/modules/transport_p2p/crypto_pake.py` | Modificado | `transport_p2p` | Pré-alocação de `ReplayWindow(512)` para `PT_INPUT` e `ReplayWindow(256)` para `PT_WORKSPACE`. |
| `src/dav/modules/transport_p2p/data_plane.py` | Modificado | `transport_p2p` | Métodos `build_input_datagram`, `build_workspace_datagram`, `send_workspace_datagram` e decifragem reversa em `DataPlaneSender` e `DataPlaneReceiver`. |
| `src/dav/modules/remote_desktop/protocol.py` | Criado | `remote_desktop` | Struct `InputEventPacket` (24 bytes `!BBBBiiIQ`), `pack_input_echo` e máquina ARQ seletiva `WorkspaceChannel`. |
| `src/dav/modules/remote_desktop/keymap.py` | Criado | `remote_desktop` | Tabela bidirecional USB HID Usage IDs entre Qt, Win32 Set-1 ScanCode, Linux `evdev` e X11 XKB. |
| `src/dav/modules/remote_desktop/security_gate.py` | Criado | `remote_desktop` | Validador Zero-Trust `SecurityGate`, deduplicador de transições redundantes `2x`, *token-bucket* e `panic_revoke_all`. |
| `src/dav/modules/remote_desktop/injector_base.py` | Criado | `remote_desktop` | Contrato `BaseInputInjector`, `StuckKeyWatchdog` e `NullSyntheticInjector` para testes determinísticos. |
| `src/dav/modules/remote_desktop/injector_win32.py` | Criado | `remote_desktop` | Injeção nativa `user32.SendInput` alinhada em 40 bytes (x64) com mapeamento `VirtualScreen` multi-monitor. |
| `src/dav/modules/remote_desktop/injector_linux.py` | Criado | `remote_desktop` | Cascata nativa Linux sem subprocessos por evento (`/dev/uinput`, XDG `RemoteDesktop` Portal e `libXtst.so.6`). |
| `src/dav/modules/remote_desktop/elevation.py` | Criado | `remote_desktop` | Broker isolado `ElevatedInputBroker` e cliente `ElevatedProxyInjector` autenticados via `HMAC-SHA256` para UAC (`runas`) e Polkit (`pkexec`). |
| `src/dav/modules/remote_desktop/workspace_agent.py` | Criado | `remote_desktop` | Sincronização de Clipboard SHA-256, transferência P2P de arquivos com validação SHA-256 e `PtyShellManager` persistente. |
| `src/dav/modules/remote_desktop/service.py` | Criado | `remote_desktop` | Fachada `RemoteDesktopService` aderente ao protocolo `IRemoteDesktopService`. |
| `src/dav/modules/remote_desktop/manifest.py` | Criado | `remote_desktop` | Registro singleton da 10ª fatia vertical no `ModuleRegistry`. |
| `src/dav/modules/capture/wayland_portal.py` | Modificado | `capture` | Negociação combinada opcional `org.freedesktop.portal.RemoteDesktop` + `ScreenCast` com fallback automático. |
| `src/dav/modules/stream_engine/subprocess_sender.py` | Modificado | `stream_engine` | Remoção do `sleep(0.05)` em `_control_rx_worker`, `select(..., 0.002)`, `input_wake_evt`, DSCP EF (`IP_TOS=0xB8`) e comandos IPC remotos. |
| `src/dav/modules/stream_engine/sender_worker.py` | Modificado | `stream_engine` | Recepção sub-2 ms de `PT_INPUT`/`PT_WORKSPACE`, eco `WS_INPUT_ECHO` e housekeeping do `StuckKeyWatchdog`. |
| `src/dav/modules/stream_engine/receiver_worker.py` | Modificado | `stream_engine` | Envio imediato de `PT_INPUT` com redundância `2x` em transições críticas, heartbeat de 150 ms e cálculo de latência *Input-to-Photon*. |
| `src/dav/modules/stream_engine/service.py` | Modificado | `stream_engine` | Orquestração unificada de permissões, elevação Admin, Clipboard, arquivos e terminal remoto no `EventBus`. |
| `scripts/gui_app.py` | Modificado | Launcher | Despacho rápido headless da flag `--elevated-input-broker` antes da inicialização do `QApplication`. |
| `src/dav/modules/telemetry/tupa_probes.py` | Modificado | `telemetry` | Adição de `TupaInputLatencyProbe` calibrada para `<= 15 ms` (ótimo) e `<= 30 ms` (aceitável). |
| `src/ui/views/tupa_view.py` | Modificado | `ui/telemetry` | Barra dedicada *Input-to-Photon (Remoto)* no painel de benchmark ao vivo do TUPÃ. |
| `src/ui/widgets/canvas.py` | Modificado | `ui/widgets` | Transformação geométrica inversa (`fit`, `stretch`, `native`), coalescência de ponteiro a `250 Hz`, `Ctrl+Alt+M` (modo relativo), `focusOutEvent` e *Drag & Drop* de arquivos. |
| `src/ui/glass/icons.py` | Modificado | `ui/glass` | Novos ícones vetoriais sombreados (`draw_cursor_control`, `draw_check`, `draw_chip`, `draw_display`, `draw_shield`, `draw_alert`). |
| `src/ui/glass/widgets.py` | Modificado | `ui/glass` | Novo componente `GlassToggleSwitch`, botão vetorial de cursor no `VideoOverlayControls` e remoção de `WA_TranslucentBackground` em `GlassCard` filho para compatibilidade Wayland. |
| `src/ui/glass/qss.py` | Modificado | `ui/glass` | Adição de `apply_glass_app_theme` (`Fusion` + paleta petrol-glass) imunizando o app e os instaladores contra temas claros de sistema (GNOME Adwaita). |
| `src/ui/glass/views.py` | Modificado | `ui/glass` | Inclusão do switch de **Transmissão Interativa** e botão **Autorizar Privilégio Admin (UAC / Polkit)** em `SenderHomePage`. |
| `src/ui/glass/sheets.py` | Modificado | `ui/glass` | Grupo de permissões granulares na `SettingsSheet` e nova aba `Terminal` (`RemoteWorkspaceView`) na `StatsSheet`. |
| `src/ui/main_window.py` | Modificado | `ui` | Integração reativa de permissões, atalho global `Ctrl+Alt+Shift+Esc`, elevação Admin automática na primeira ativação e sincronização de Clipboard. |
| `src/ui/__init__.py` | Modificado | `ui` | Carregamento preguiçoso PEP 562 (`__getattr__`) evitando importação ansiosa de `DavMainWindow` nos instaladores. |
| `src/ui/glass/__init__.py` | Modificado | `ui/glass` | Carregamento preguiçoso PEP 562 para manter o binário `--onefile` do instalador desacoplado de `src.dav`. |
| `src/ui/glass/installer_shell.py` | Criado | `ui/glass` | Shell multiplataforma `DavGlassInstallerDialog` com gradiente atmosférico, `GlassCard(dark=True)` e Stepper vetorial resiliente a Wayland/X11. |
| `scripts/dav_installer_win.py` | Modificado | Installer | Migração do instalador Windows para `DavGlassInstallerDialog` + `apply_glass_app_theme`, preservando firewall, registro `dav://` e invalidação de cache de ícones. |
| `scripts/dav_installer_linux.py` | Modificado | Installer | Migração do instalador Linux para `DavGlassInstallerDialog` + `apply_glass_app_theme`, guarda contra binário `DA-V` legado e integração XDG/UFW. |
| `install_linux.sh` | Criado | Installer / Linux | Script shell com priorização do diretório extraído, limpeza de artefatos legados em `~/.local/share/dav`, verificação Wayland/X11 e abertura do instalador Glassmorphism. |
| `launch_dav.sh` | Modificado | Launcher / Linux | Seleção segura de `QT_QPA_PLATFORM` (`xcb;wayland` sob XWayland mantendo `WAYLAND_DISPLAY` para PipeWire). |
| `CHANGELOG.md` | Modificado | Documentação | Registro formal da release `[5.0.0] — 2026-11-24`. |
| `README.md` | Modificado | Documentação | Atualização da versão `v5.0.0`, diagrama arquitetural com a 10ª fatia `remote_desktop` e instruções de instalação Linux com `install_linux.sh`. |
| `LEIA-ME_LINUX.md` | Modificado | Documentação | Atualização do guia operacional Linux para `v5.0.0` com instruções de uso em 1 comando via `install_linux.sh`. |
| `scripts/build_linux_source_tarball.py` | Modificado | Build / Linux | Inclusão de `install_linux.sh` com permissão `0755` e quebras de linha `LF` no pacote portátil `.tar.gz`. |
| `scripts/build_windows.ps1` | Modificado | Build / CI | Inclusão de `remote_desktop.manifest` e submódulos `src.ui.glass.*` no empacotamento PyInstaller. |
| `scripts/build_linux_bundle.sh` | Modificado | Build / CI | Inclusão de `remote_desktop.manifest` e submódulos `src.ui.glass.*` no bundle Linux ELF. |
| `.github/workflows/release.yml` | Modificado | Build / CI | Alinhamento do pipeline multi-OS (Ubuntu 24.04 e Windows Server) com os novos módulos da v5.0.0. |
| `tests/test_architecture_boundaries.py` | Modificado | Testes | Governança AST ampliada para validar as 10 fatias verticais e pureza de domínio de `remote_desktop`. |
| `tests/test_glass_ui.py` | Modificado | Testes | Testes de renderização offscreen de `GlassToggleSwitch`, `VideoOverlayControls` (3 zonas) e instaladores Glass. |
| `tests/test_remote_desktop.py` | Criado | Testes | Suíte unitária e E2E cobrindo protocolo 24B, PAKE AEAD bidirecional, `SecurityGate`, `StuckKeyWatchdog`, ARQ de arquivos SHA-256, PTY, broker HMAC e orçamento *Input-to-Photon*. |
| `docs/decisions/0002-arquitetura-compartilhamento-area-de-trabalho-e-broker-admin.md` | Criado | Decisões (ADR) | Registro MADR 4.0 documentando a arquitetura de subcanais `PT_INPUT`/`PT_WORKSPACE` e broker administrativo isolado. |

## Decisões arquiteturais e justificativas

- **Decisão registrada:** [ADR-0002](../decisions/0002-arquitetura-compartilhamento-area-de-trabalho-e-broker-admin.md) formaliza a separação entre `PT_INPUT` (24 bytes sem bloqueio HoL) e `PT_WORKSPACE` (ARQ seletivo ordenado) sobre o socket UDP único PAKE AEAD, bem como o uso do micro-processo `--elevated-input-broker` via UAC/Polkit para contornar restrições UIPI e `/dev/uinput` sem reiniciar a sessão gráfica do usuário.

## Evidências de verificação e testes

- **Suíte unitária, fronteiras AST e integração completa:** `py -m pytest tests/ -q`
  - **Resultado observado:** `92 passed in 16.94s` (incluindo os 9 novos testes de `tests/test_remote_desktop.py` com medição real de loopback `input_rtt_ms < 15.0 ms` e `input_to_photon_ms <= 30.0 ms`, além dos testes dos novos instaladores Glassmorphism em `tests/test_glass_ui.py`).
- **Validação sintática dos scripts Linux (Git Bash):** `bash -n install_linux.sh && bash -n launch_dav.sh`
  - **Resultado observado:** sintaxe POSIX/Bash válida sem erros e pacote `release_assets/DA-V_v5.0.0_Linux_Source_Portable.tar.gz` gerado (`255 arquivos`, `LF`, permissões `+x`).
- **Validação E2E P2P (STUN Single-Socket, H.264 Direto e CGNAT Blind Relay):** `py tests/test_p2p_e2e.py`
  - **Resultado observado:** `TODOS OS CENÁRIOS P2P APROVADOS COM 100% DE ÊXITO`.
- **Auto-teste de inicialização do launcher desktop:** `py scripts/gui_app.py --self-check`
  - **Resultado observado:** `DAV_SELF_CHECK_OK` (`ExitCode = 0`).
- **Compilação binária completa Windows x64 (`PyInstaller 6.22.3`):** `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/build_windows.ps1`
  - **Resultado observado:** `BUILD CONCLUIDA COM SUCESSO` (`ExitCode = 0`), gerando `dist/DA-V/DA-V.exe` (aprovado em `--self-check` e no teste funcional de `--elevated-input-broker`), `release_assets/DA-V_Instalador_Windows_x64.exe` e `release_assets/DA-V_v5.0.0_Windows_x64_Portable.zip`.
- **Auditoria documental MADR 4.0:** `doc_lint.py docs/decisions/0002-arquitetura-compartilhamento-area-de-trabalho-e-broker-admin.md --type madr`
  - **Resultado observado:** `[PASS] Auditoria dante-docs (madr)`.
- **Inspeção visual por renderização DirectWrite:** Geradas capturas reais das etapas 1, 2 e 4 de `DavModernInstaller` e da tela `SenderHomePage` com `GlassToggleSwitch` ativo, confirmando alinhamento simétrico das pílulas neon, legibilidade WCAG 2.2 e ausência de truncamento tipográfico.

## Riscos, dívida técnica e desvios conhecidos

- Em telas protegidas do desktop seguro do Windows (`Winlogon` / caixa modal do próprio UAC), o kernel NT bloqueia injeção mesmo de processos em *High Integrity Level* sem um serviço `LocalSystem` assinado com `uiAccess=true`. Para todas as demais janelas administrativas da sessão interativa do usuário, o `ElevatedInputBroker` atende integralmente sem instalar serviços permanentes.

## Próximos passos verificáveis

1. Executar teste interativo em rede local real entre uma estação Windows 11 e uma estação Linux Wayland/X11 para aferir a distribuição p95 da barra *Input-to-Photon (Remoto)* no painel `TupaView`.
2. Efetuar o commit da release `v5.0.0` e publicar a tag `v5.0.0` para disparar o pipeline multi-OS (`.github/workflows/release.yml`) com builds Windows x64 e Linux ELF x86_64.
3. Avaliar na Fase 3 a criação opcional de monitores virtuais isolados (IddSampleDriver / PipeWire Virtual Output) para sessões multiusuário independentes do monitor físico.
