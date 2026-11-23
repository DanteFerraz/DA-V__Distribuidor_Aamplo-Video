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
| `src/dav/modules/transport_p2p/sqp_controller.py`, `data_plane.py`, `fec_engine.py`, `crypto_pake.py`, `lan_beacon.py` | Criado / Modificado | `transport_p2p` | Controle SQP em 3 zonas com `base_rtt_ms`, multiplexação PAKE, `cut_through` sem FEC em P-frames com perda zero, detecção `ref_gap` contra interpolação de P-frames órfãos e parada determinística por `Event` no beacon. |
| `src/dav/modules/audio/*`, `src/ui/audio_sink.py` | Criado | `audio` | Captura/resampler/Opus/ASRC 48 kHz e adaptador `DesktopAudioPlayer` com silenciamento instantâneo. |
| `src/dav/modules/codec/encoder.py` | Modificado | `codec` | Preservação do perfil H.264 de baixa latência sem estrangulamento VBV por padrão (`_vbv_clamp_active=False`) e recuperação IDR instantânea (`force=True`, debounce `80 ms`). |
| `src/dav/modules/stream_engine/service.py`, `subprocess_sender.py`, `sender_worker.py`, `receiver_worker.py` | Criado / Modificado | `stream_engine` | Subprocesso TX sem descarte/estrangulamento de quadros por quadro, supressão de pacotes de áudio em silêncio, bloqueio de P-frames órfãos com PLI imediato (`150 ms`) no receptor e `join` síncrono em `stop()`. |
| `src/ui/glass/tokens.py`, `icons.py`, `paint.py`, `widgets.py`, `views.py`, `__init__.py` | Modificado | `ui.glass` | Tokens e renderização com drop-shadow vetorial/tipográfico, `VideoOverlayControls`, `SenderHomePage.flash_warning` e limpeza automática de `_CACHE` em `aboutToQuit`. |
| `src/ui/main_window.py`, `src/ui/bridge.py`, `src/ui/qt_compat.py`, `src/dav/modules/telemetry/tupa_checker.py` | Modificado | `ui / telemetry` | Integração de controles flutuantes, proteção em `_swap_mode()`, controle de época `_sender_session_epoch`, preservação de `txt_send_ip` em `_on_target_updated()`, timers canceláveis e parada imediata por `Event` no `TupaHealthChecker`. |
| `scripts/build_linux_source_tarball.py`, `scripts/build_linux_bundle.sh`, `scripts/build_windows.ps1`, `.github/workflows/release.yml` | Criado / Modificado | `build / ci` | Gerador POSIX LF reproduzível `.tar.gz`, build Windows v4.9.0 com encerramento prévio de `DA-V.exe`, restrição `opencv-python-headless>=4.10.0,<5.1.0` e variáveis `DAV_HEADLESS_SYNTHETIC=1` / `PYTHONFAULTHANDLER=1` no CI Linux. |
| `tests/test_glass_ui.py`, `tests/test_salsify_subms_perf.py`, `tests/test_audio_pipeline.py`, `tests/test_pake_crypto.py`, `tests/test_sqp_fec.py`, `tests/test_architecture_boundaries.py` | Criado / Modificado | `tests` | Cobertura de UX, proteção `ZONE_SWAP`, reinício PIN P2P, fidelidade visual sem estrangulamento VBV, bloqueio `ref_gap` de P-frames órfãos, áudio Opus e PAKE AEAD. |

## Decisões arquiteturais e justificativas

- **Preservação de configuração manual vs. endpoint efêmero P2P:** Armazenar o endpoint remoto confirmado durante o handshake em `_active_peer_endpoint` em vez de sobrescrever `txt_send_ip` e `spn_send_port` evita que reinícios subsequentes em Modo PIN saltem a descoberta STUN em `subprocess_sender.py` ou tentem vincular portas NAT remotas.
- **Proteção não-destrutiva no botão central (`ZONE_SWAP`):** Bloquear a troca de modo apenas enquanto `mode == "sender"` e `is_sending == True`, com feedback temporário de aviso em vermelho suave no card, elimina desligamentos acidentais sem adicionar diálogos modais bloqueantes ou alterar o layout das referências.
- **Drop-shadow em `QPainter` compartilhado (`paint_shadowed_text` e `_render_shadowed`):** Renderizar dupla camada suave diretamente nos helpers compartilhados evita overhead e recorte de `QGraphicsDropShadowEffect` sob `WA_TranslucentBackground` e garante consistência entre `GlassLabel`, `GlassButton`, `GlassSegmented`, `FloatingNavPill` e `VideoOverlayControls`.
- **Fidelidade visual 1 ms sem estrangulamento VBV nem interpolação de P-frames órfãos:** Manter o encoder H.264 sem `bufsize = bitrate // 3` e sem redução dinâmica de taxa por quadro no loop de envio evita a explosão do quantizador (`QP 45–51`) em cenas detalhadas com `sliced-threads=1`; no receptor, detectar lacunas de sequência (`ref_gap`) e aguardar um IDR limpo (`request_keyframe(force=True)`) elimina artefatos de predição inter-quadro sobre referências perdidas.
- **Teardown determinístico de threads e timers Qt:** Cancelar timers de inicialização, limpar `_CACHE` de `QPixmap` em `aboutToQuit` e substituir `time.sleep` por `threading.Event.wait` nos serviços de background elimina corridas de encerramento sob `QT_QPA_PLATFORM=offscreen`.

## Evidências de verificação e testes

- **Suíte unitária e de integração:** `py -m pytest tests/ -v`
  - **Resultado observado:** `80 passed in 11.19s` (executado após as edições finais; 0 falhas, 0 skips).
- **Suíte P2P e Relay end-to-end:** `py tests/test_p2p_e2e.py`
  - **Resultado observado:** todos os 3 cenários aprovados (Single-Socket STUN, P2P Direto H.264 e Blind Encrypted UDP Relay).
- **Sanidade GUI e carregamento de versão:** `py scripts/gui_app.py --self-check`
  - **Resultado observado:** `DAV_SELF_CHECK_OK`.
- **Compilação Windows e empacotamento multiplataforma:** `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/build_windows.ps1` e `py scripts/build_linux_source_tarball.py`
  - **Resultado observado:** `dist/DA-V/DA-V.exe` (`6.973.120` bytes, `--self-check` `ExitCode=0`), `release_assets/DA-V_Instalador_Windows_x64.exe` (`191.485.485` bytes), `release_assets/DA-V_v4.9.0_Windows_x64_Portable.zip` (`146.074.262` bytes) e `release_assets/DA-V_v4.9.0_Linux_Source_Portable.tar.gz` (`341.504` bytes, `234` arquivos).
- **Compilação ELF Linux local:** Não executada localmente porque WSL2 neste host reportou ausência de Hyper-V (`HCS_E_HYPERV_NOT_INSTALLED`); compensada via empacotamento portátil POSIX e pipeline GitHub Actions em `ubuntu-24.04`.

## Riscos, dívida técnica e desvios conhecidos

- Os artefatos binários nativos Linux (`DA-V` ELF, `libdav_core.so`, `DA-V_Instalador_Linux_x86_64`) e Windows assinados pelo workflow oficial dependem da execução dos runners `ubuntu-24.04` e `windows-latest` após o push da branch e da tag `v4.9.0`.

## Próximos passos verificáveis

1. Acompanhar os jobs `build-linux`, `build-windows` e `publish-release` no GitHub Actions após o push da tag `v4.9.0` até conclusão com status verde.
2. Validar o download e execução dos instaladores publicados na GitHub Release `v4.9.0` em hosts Windows 11 e Linux Ubuntu Wayland/X11.
