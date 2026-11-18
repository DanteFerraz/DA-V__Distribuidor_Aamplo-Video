---
doc_type: session-report
diataxis_quadrant: explanation
project: "DA-V (Distribuidor Amplo de Video)"
session_date: 2026-11-18
main_line: "Estabilizacao Salsify/SQP, melhorias de UX Glassmorphism e release v4.9.0"
author: "Dante Ferraz"
status: "verified"
related_adrs: []
related_commits: []
---

# Relatório de sessão — 2026-11-18: Estabilização Salsify/SQP, UX Glassmorphism e release v4.9.0

## Resumo executivo

Consolidada a arquitetura modular com controle de congestionamento Salsify/SQP em três zonas, áudio Opus 48 kHz de baixa latência, melhorias de experiência do usuário na camada Glassmorphism (sombreamento vetorial/tipográfico e botões flutuantes de áudio e tela cheia), proteção contra interrupção acidental de transmissão na barra superior, atualização unificada para a versão `4.9.0` e empacotamento Windows e Linux para publicação em Git.

## Requisitos e objetivos endereçados

- **OBJ-01:** Estabilizar controle Salsify/SQP em enlaces WAN/LAN mantendo `base_rtt_ms` imune a surtos de bufferbloat (`15 s`), zona de retenção (Hold), pacing cut-through para P-frames, burst-guard em keyframes congestionados e histerese VBV segura no encoder `libx264` (`>= 1.20 s`) e `h264_nvenc`.
- **OBJ-02:** Aplicar sombreamento projetado (`drop-shadow`) em todos os ícones vetoriais e rótulos/botões da interface Glassmorphism mantendo fidelidade visual às seis telas de referência.
- **OBJ-03:** Implementar controles flutuantes no canto inferior direito (`VideoOverlayControls`) para ativar/desativar áudio (`ZONE_AUDIO`) e alternar tela cheia (`ZONE_FULLSCREEN`) com sincronização bidirecional entre `SettingsSheet`, `DesktopAudioPlayer`, `StreamEngineService` e janela principal.
- **OBJ-04:** Corrigir a falha em que clicar no botão central da barra superior (`ZONE_SWAP`) interrompia a transmissão ativa e impedia reinícios futuros em Modo PIN P2P, preservando `txt_send_ip` e `spn_send_port` e garantindo teardown síncrono do subprocesso transmissor.
- **OBJ-05:** Centralizar a versão `4.9.0`, gerar o pacote portátil Linux (`DA-V_v4.9.0_Linux_Source_Portable.tar.gz`) e os artefatos Windows (`DA-V.exe`, instalador autossuficiente e ZIP portátil).

## Alterações realizadas por artefato

| Arquivo | Ação | Camada / Bloco C4 | Descrição objetiva da alteração |
| :--- | :--- | :--- | :--- |
| `VERSION`, `src/dav/__init__.py` | Modificado | `kernel / core` | Definida versão canônica `4.9.0` com função central `get_version()` e `__version__`. |
| `src/dav/modules/transport_p2p/sqp_controller.py`, `data_plane.py`, `fec_engine.py`, `crypto_pake.py` | Criado / Modificado | `transport_p2p` | Controle SQP em 3 zonas com `base_rtt_ms`, multiplexação vídeo/áudio PAKE, pré-empção de áudio e FEC GF(2^8). |
| `src/dav/modules/audio/*`, `src/ui/audio_sink.py` | Criado | `audio` | Captura/resampler/Opus/ASRC 48 kHz e adaptador `DesktopAudioPlayer` com silenciamento instantâneo. |
| `src/dav/modules/codec/encoder.py` | Modificado | `codec` | Clamping VBV seguro no `libx264` via reabertura com histerese e debounce de PLI. |
| `src/dav/modules/stream_engine/service.py`, `subprocess_sender.py`, `sender_worker.py` | Criado / Modificado | `stream_engine` | Subprocesso TX lockless, tupla atômica `_target_ep` e `join` síncrono após `terminate()` em `stop()`. |
| `src/ui/glass/tokens.py`, `icons.py`, `paint.py`, `widgets.py`, `views.py`, `__init__.py` | Modificado | `ui.glass` | Tokens e renderização com drop-shadow vetorial/tipográfico, `VideoOverlayControls` e `SenderHomePage.flash_warning`. |
| `src/ui/main_window.py`, `src/ui/qt_compat.py` | Modificado | `ui` | Integração de controles flutuantes, proteção em `_swap_mode()`, controle de época `_sender_session_epoch` e preservação de `txt_send_ip` em `_on_target_updated()`. |
| `scripts/build_linux_source_tarball.py`, `scripts/build_windows.ps1`, `.github/workflows/release.yml` | Criado / Modificado | `build / ci` | Gerador POSIX LF reproduzível `.tar.gz`, build Windows v4.9.0 e inclusão de `-r requirements.txt` no workflow Linux CI. |
| `tests/test_glass_ui.py`, `tests/test_salsify_subms_perf.py`, `tests/test_audio_pipeline.py`, `tests/test_pake_crypto.py`, `tests/test_sqp_fec.py`, `tests/test_architecture_boundaries.py` | Criado / Modificado | `tests` | Cobertura completa de UX, proteção `ZONE_SWAP`, reinício PIN P2P, QoS WAN, áudio Opus, PAKE AEAD e fronteiras arquiteturais. |

## Decisões arquiteturais e justificativas

- **Preservação de configuração manual vs. endpoint efêmero P2P:** Armazenar o endpoint remoto confirmado durante o handshake em `_active_peer_endpoint` em vez de sobrescrever `txt_send_ip` e `spn_send_port` evita que reinícios subsequentes em Modo PIN saltem a descoberta STUN em `subprocess_sender.py` ou tentem vincular portas NAT remotas.
- **Proteção não-destrutiva no botão central (`ZONE_SWAP`):** Bloquear a troca de modo apenas enquanto `mode == "sender"` e `is_sending == True`, com feedback temporário de aviso em vermelho suave no card, elimina desligamentos acidentais sem adicionar diálogos modais bloqueantes ou alterar o layout das referências.
- **Drop-shadow em `QPainter` compartilhado (`paint_shadowed_text` e `_render_shadowed`):** Renderizar dupla camada suave diretamente nos helpers compartilhados evita overhead e recorte de `QGraphicsDropShadowEffect` sob `WA_TranslucentBackground` e garante consistência entre `GlassLabel`, `GlassButton`, `GlassSegmented`, `FloatingNavPill` e `VideoOverlayControls`.

## Evidências de verificação e testes

- **Suíte unitária e de integração:** `py -m pytest tests/ -v`
  - **Resultado observado:** `79 passed in 12.82s` (executado após as edições de código e atualização de versão para `4.9.0`; 0 falhas, 0 skips).
- **Sanidade GUI e carregamento de versão:** `py scripts/gui_app.py --self-check`
  - **Resultado observado:** `DAV_SELF_CHECK_OK` e `VER: 4.9.0`.
- **Compilação Windows e empacotamento multiplataforma:** `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/build_windows.ps1` e `py scripts/build_linux_source_tarball.py`
  - **Resultado observado:** `dist/DA-V/DA-V.exe` (`7.545.662` bytes, `--self-check` `ExitCode=0`), `release_assets/DA-V_Instalador_Windows_x64.exe` (`197.821.653` bytes), `release_assets/DA-V_v4.9.0_Windows_x64_Portable.zip` (`152.416.352` bytes, `VERSION` interno `4.9.0`) e `release_assets/DA-V_v4.9.0_Linux_Source_Portable.tar.gz` (`339.540` bytes, `234` arquivos, `sh_exec=True`, sem `\r\n`).
- **Compilação ELF Linux local:** Não executada localmente porque WSL2 neste host reportou ausência de Hyper-V (`HCS_E_HYPERV_NOT_INSTALLED`); compensada via empacotamento portátil POSIX e pipeline GitHub Actions em `ubuntu-24.04`.

## Riscos, dívida técnica e desvios conhecidos

- Os artefatos binários nativos Linux (`DA-V` ELF, `libdav_core.so`, `DA-V_Instalador_Linux_x86_64`) e Windows assinados pelo workflow oficial dependem da execução dos runners `ubuntu-24.04` e `windows-latest` após o push da branch e da tag `v4.9.0`.

## Próximos passos verificáveis

1. Acompanhar os jobs `build-linux`, `build-windows` e `publish-release` no GitHub Actions após o push da tag `v4.9.0` até conclusão com status verde.
2. Validar o download e execução dos instaladores publicados na GitHub Release `v4.9.0` em hosts Windows 11 e Linux Ubuntu Wayland/X11.
