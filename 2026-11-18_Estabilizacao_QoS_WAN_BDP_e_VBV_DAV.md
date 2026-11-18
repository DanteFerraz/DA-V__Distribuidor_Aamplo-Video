# Relatório de Sessão — 18/11/2026
# Estabilização Integral de QoS WAN/LAN (BDP Base, Zona Hold SQP, VBV libx264 e Controle Assíncrono — DA-V v4.8)

**Data:** 18 de Novembro de 2026  
**Autor:** Dante Ferraz (MonoTech)  
**Projeto:** DA-V — Distribuidor Amplo de Vídeo  
**Repositório:** `https://github.com/DanteFerraz/DA-V__Distribuidor_Aamplo-Video`

---

## 1. Resumo do Trabalho Realizado

1. **Auditoria de Validação e Revisão Experimental sobre a Implementação Anterior (`v4.7` -> `v4.8`):**
   - Confronto experimental do plano de reengenharia Salsify v4.7 com o comportamento real do `VideoEncoder` (`libx264` vs. `h264_nvenc`) em `768p60`, da máquina de estados `SqpSenderController`, do transporte assíncrono em `subprocess_sender.py` / `sender_worker.py` e da telemetria em `main_window.py`.
   - Comprovado em execução direta que, no PyAV com `libx264`, `ctx.max_bit_rate` é somente leitura (`AttributeError`) e a simples mutação de `ctx.bit_rate` após `ctx.open()` não reduz a taxa em fluxo contínuo (`12.11 -> 12.12 Mbps`), enquanto `h264_nvenc` respeita dinamicamente `ctx.bit_rate`.

2. **Fechamento das Lacunas Remanescentes de QoS:**
   - **RTT Base Imune a Bufferbloat & Controle SQP em 3 Zonas (`src/dav/modules/transport_p2p/sqp_controller.py`):**
     - Adicionada janela deslizante `_rtt_window` de `15 s` (`base_rtt_ms`) para calcular `natural_bdp_frames`, impedindo que um surto de bufferbloat (`rtt_ms > 100 ms`) infle artificialmente o limiar de `skip_frame`.
     - Substituída a rampa agressiva de recuperação (`+12% + 300 kbps` por ACK) por controle em três zonas: **Congestão** (`owd > 5.0 ms` ou `loss > 2.5%` ou `rx_queue > 5`), **Hold** (`owd >= 2.5 ms` ou `loss >= 1%` ou `rx_queue >= 3`, eliminando oscilação serrilhada em gargalos WAN) e **Sondagem Suave** (`* 1.05 + 150 kbps`).
   - **Pacing de Keyframes Congestados (`src/dav/modules/transport_p2p/data_plane.py`):**
     - Mantido modo Cut-Through (`0 ms`) em enlaces limpos e P-frames em `<= 2 ms`, ampliando `max_span_sec` para `5 ms` exclusivamente em keyframes grandes (`k_data >= 30`) sob congestionamento ativo (`is_congested`), evitando descarte em rajada na fila de roteadores SOHO.
   - **Fechamento Seguro de Contexto e Histerese VBV no `libx264` (`src/dav/modules/codec/encoder.py`):**
     - Garantido `self.close()` antes de `self._init_encoder()` em variações sustentadas (`>= 20%`) no `libx264`, com histerese dedicada `_last_libx264_reopen_mono >= 1.20 s` para impedir reinicializações consecutivas sob flutuação transitória, mantendo `0.40 s` de resposta instantânea sem reabertura no `NVENC` e debounce de `0.60 s` em `request_keyframe()`.
   - **Concorrência Atômica de Endpoint e Paridade no `SenderWorker` (`src/dav/modules/stream_engine/subprocess_sender.py`, `src/dav/modules/stream_engine/sender_worker.py`):**
     - Substituído acesso separado a `(target_ip, target_port)` pela tupla atômica `_target_ep` em ambas as implementações (evitando mistura IP LAN + porta WAN durante migração em quente).
     - Adicionado `t_ctrl.join(timeout=0.3)` no encerramento do `subprocess_sender.py` e adicionada thread assíncrona `_control_rx_loop` (`select <= 2 ms`, `_ctrl_lock`, `_pair_started_mono`) com join limpo em `SenderWorker`.
   - **Sincronização da Telemetria TX na UI (`src/ui/main_window.py`):**
     - Alinhada a média de `mbps` registrada a cada `2.0 s` no log `[TELEMETRY-TX]` com o mesmo intervalo de cálculo de `smooth_fps`, `Quadros` e `Pacotes`, zerando os acumuladores TX/RX ao iniciar cada sessão.
   - **Testes de Regressão Adicionais (`tests/test_salsify_subms_perf.py`):**
     - Adicionado `test_sqp_base_rtt_immunity_and_hold_zone` validando a zona Hold sem serrilhado e a imunidade de `base_rtt_ms` contra inflação por bufferbloat.

---

## 2. Alterações de Arquivos

### Modificados Nesta Etapa (`18/11/2026`)
- `src/dav/modules/transport_p2p/sqp_controller.py`
- `src/dav/modules/transport_p2p/data_plane.py`
- `src/dav/modules/codec/encoder.py`
- `src/dav/modules/stream_engine/subprocess_sender.py`
- `src/dav/modules/stream_engine/sender_worker.py`
- `src/ui/main_window.py`
- `tests/test_salsify_subms_perf.py`
- `2026-11-18_Estabilizacao_QoS_WAN_BDP_e_VBV_DAV.md` (criado)

---

## 3. Verificações e Pacotes Gerados

1. **Suíte Completa (`py -m pytest tests/ -v`):** `77 passed in 13.10s` (0 falhas, 0 skips).
2. **Sanidade da Aplicação:** `py scripts/gui_app.py --self-check` retornou `DAV_SELF_CHECK_OK` (código de saída `0`); no passo `[2/4]` de `scripts/build_windows.ps1`, `dist/DA-V/DA-V.exe --self-check` concluiu com código de saída `0` (`Auto-teste do binario: SUCESSO`, binário compilado com `--windowed`).
3. **Empacotamento Final (`18/11/2026`):**
   - `dist/DA-V/DA-V.exe` (`6.959.089` bytes)
   - `release_assets/DA-V_Instalador_Windows_x64.exe` (`191.463.338` bytes)
   - `release_assets/DA-V_v4.0.0_Windows_x64_Portable.zip` (`146.051.914` bytes)
   - `release_assets/DA-V_v4.0.0_Linux_Source_Portable.tar.gz` (`336.516` bytes, `224` entradas)

---

## 4. Etapa Subsequente: Melhorias de UX, Sombreamento, Controles Flutuantes e Navegação Resiliente (DA-V v4.9)

### 4.1. Mudanças Implementadas
1. **Tokens e Sombreamento Vetorial/Tipográfico (`src/ui/glass/tokens.py`, `icons.py`, `paint.py`, `widgets.py`, `views.py`):**
   - Adicionados tokens `ICON_SHADOW_RGBA`, `ICON_SHADOW_OFFSET`, `TEXT_SHADOW_RGBA` e `TEXT_SHADOW_OFFSET` em `tokens.py`.
   - Extraído helper `_render_shadowed` em `icons.py` para renderizar camada dupla de sombra suave em `draw_menu`, `draw_gear`, `draw_refresh`, `draw_chart`, além dos novos ícones vetoriais `draw_speaker(muted=False/True)` e `draw_fullscreen_corners(is_fullscreen=False/True)`.
   - Adicionado `paint_shadowed_text` em `paint.py` e integrado em `GlassLabel` (com `contentsMargins` inferior para evitar recorte da sombra), `GlassButton` e `GlassSegmented`.
   - Mantida fidelidade aos 6 mockups de referência sem adição de botões extras nos cards `Modo Transmissor`, `Conectando...` e `Modo Espectador`.
2. **Controles Flutuantes de Transmissão (`VideoOverlayControls` em `widgets.py`, `__init__.py`, `main_window.py`, `qt_compat.py`):**
   - Criado widget `VideoOverlayControls` posicionado no canto inferior direito com `FocusPolicy.NoFocus`, exibido durante transmissão de vídeo recebida (`PAGE_VIDEO`) e durante envio ativo (`PAGE_SENDER` quando `is_sending == True`), com atualização de z-order em `_sync_layout_geometry()` e `_sync_overlay_controls_state()`.
   - Botão de Áudio (`ZONE_AUDIO`): sincronizado bidirecionalmente com `SettingsSheet.chk_audio_rx` (modo Espectador -> `DesktopAudioPlayer.set_muted`) e `chk_audio_tx` (modo Transmissor -> `StreamEngineService.set_sender_audio_muted`).
   - Botão de Tela Cheia (`ZONE_FULLSCREEN`): conectado a `_toggle_fullscreen()` com sincronização automática em `changeEvent(WindowStateChange)`.
3. **Correção Definitiva de Navegação (`ZONE_SWAP`) e Reinício de Transmissão (`main_window.py`, `views.py`, `service.py`):**
   - `_swap_mode()` agora protege transmissões ativas quando `mode == "sender"` e `is_sending == True`, mantendo o stream vivo e exibindo aviso temporário via `SenderHomePage.flash_warning(...)` (`flash_message`).
   - `_on_target_updated()` deixou de sobrescrever `settings_sheet.txt_send_ip` e `spn_send_port` após pareamento P2P (armazenando o par ativo em `_active_peer_endpoint`), preservando `txt_send_ip == ""` e porta padrão `default_port` para que reinícios em Modo PIN sempre executem descoberta STUN em `subprocess_sender.py`.
   - Adicionado controle de época `_sender_session_epoch` no registro assíncrono `_bg_register_sender()` para impedir corridas entre sessões, e adicionado `.join(timeout=0.8)` após `.terminate()` (com fallback `.kill()` + `.join(timeout=0.3)`) e limpeza de eventos/filas em `StreamEngineService.stop()`.

### 4.2. Arquivos Alterados Nesta Etapa
- `src/ui/qt_compat.py`
- `src/ui/glass/tokens.py`
- `src/ui/glass/icons.py`
- `src/ui/glass/paint.py`
- `src/ui/glass/widgets.py`
- `src/ui/glass/views.py`
- `src/ui/glass/__init__.py`
- `src/dav/modules/stream_engine/service.py`
- `src/ui/main_window.py`
- `tests/test_glass_ui.py`

### 4.3. Verificação Final Pós-Edição (`v4.9.0`)
1. `py -m pytest tests/ -v`: **`79 passed in 12.82s`** (0 falhas; inclui os novos testes em `tests/test_glass_ui.py` e validação de versão em `test_diagnostic_packager.py` e `test_updater.py`).
2. `py scripts/gui_app.py --self-check`: **`DAV_SELF_CHECK_OK`** (código de saída `0`).
3. **Atualização de Versão para `4.9.0` e Geração dos Artefatos de Release:**
   - Versão centralizada via `VERSION` (`4.9.0`) e `src/dav/__init__.py` (`get_version()`, `__version__`), propagada para `diagnostic_packager.py`, `author_dialog.py`, `updater/manifest.py`, `updater/service.py`, `updater/update_checker.py`, `main_window.py`, instaladores (`dav_installer_win.py`, `dav_installer_linux.py`) e guias/changelog (`README.md`, `CHANGELOG.md`, `LEIA-ME_LINUX.md`, `GUIA_RAPIDO_LINUX.md`).
   - Criado gerador reproduzível `scripts/build_linux_source_tarball.py` (LF POSIX + permissão `0755` em `.sh`).
   - `dist/DA-V/DA-V.exe` (`7.545.662` bytes; `--self-check` com `ExitCode = 0`)
   - `release_assets/DA-V_Instalador_Windows_x64.exe` (`197.821.653` bytes)
   - `release_assets/DA-V_v4.9.0_Windows_x64_Portable.zip` (`152.416.352` bytes; `VERSION` interno `4.9.0`)
   - `release_assets/DA-V_v4.9.0_Linux_Source_Portable.tar.gz` (`339.540` bytes; `234` arquivos, `sh_exec=True`, `LF` POSIX, `VERSION` interno `4.9.0`; observação: WSL2 não disponível neste host Windows por ausência de Hyper-V para compilação ELF nativa Linux, gerando o tarball portátil de código-fonte pronto para `./launch_dav.sh` ou `./scripts/build_linux_bundle.sh`).
