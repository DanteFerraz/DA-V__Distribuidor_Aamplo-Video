# Relatorio de Sessao — 17/11/2026
# Implementacao da Arquitetura Salsify/SQP/FEC/PAKE, Unificacao Data Plane e Pipeline de Audio (DA-V)

**Data:** 17 de Novembro de 2026  
**Autor:** Dante Ferraz (MonoTech)  
**Projeto:** DA-V — Distribuidor Amplo de Video  
**Repositorio:** `https://github.com/DanteFerraz/DA-V__Distribuidor_Aamplo-Video`

---

## 1. Resumo do Trabalho Realizado

1. **Ingestao Completa de Contexto (`dante-context`):**
   - Leitura integral de todos os documentos `.md` do repositorio `Distribuidor_Aamplo-Video` (`README.md`, `CHANGELOG.md`, `LEIA-ME_LINUX.md`, `client_walkthrough.md` e relatorios de sessao de `2026-08-30` a `2026-11-16`), alem da inspecao direta dos modulos de transporte, QoS, criptografia e codec (`src/dav/modules/transport_p2p/packetizer.py`, `src/dav/modules/stream_engine/sender_worker.py`, `src/dav/modules/stream_engine/receiver_worker.py`, `src/qos/fec.hpp`, `src/qos/fec.cpp`, `src/crypto/crypto_channel.hpp`, `src/qos/adaptive_bitrate.hpp`, `src/transport/bandwidth_estimator.hpp`, `src/codec/hybrid_codec.py`, `src/core/dav_api.cpp`, `scripts/dav_sender_worker.py` e `scripts/dav_client.py`).

2. **Auditoria Forense das Tres Criticas Tecnicas no Codigo v4.0.0:**
   - **Controle de Congestionamento e FEC:** Confirmado que `src/qos/fec.cpp` continha um stub incompleto em `FecHandler::try_recover` e nao estava integrado ao loop real Python, enquanto `packetizer.py` e `sender_worker.py` enviavam fragmentos em rajada sem micro-pacing e com bitrate fixo no `HybridEncoder`.
   - **Criptografia derivada de PIN curto:** Confirmado que `build_key_vector(pin)` em `packetizer.py` e `derive_pin_key` em `dav_api.cpp` aplicavam mascara XOR estatica repetida derivada diretamente dos 6 digitos do PIN com tag fixa `DAV_POLY1305_TAG`, sem troca efemera PAKE/X25519.
   - **Divergencia C++23 vs. Python:** Confirmada a separacao entre o motor monolitico em `src/core/dav_api.cpp` e o pipeline ativo em `src/dav/modules/` + `scripts/dav_sender_worker.py` / `scripts/dav_client.py`.

3. **Elaboracao do Plano Arquitetural e Estudo de Audio:**
   - Documento completo gerado no artefato `plano_arquitetura_salsify_sqp_pake_audio_dav.md`, cobrindo:
     - **Pilar 1:** Controle de congestionamento acoplado ao quadro (Salsify + Google SQP) com feedback de gradiente de atraso unidirecional ($\Delta d_k$), orcamento de bytes por quadro e micro-pacing.
     - **Pilar 2:** FEC intra-quadro sistematico adaptativo (`XOR` + matriz de Cauchy Reed-Solomon em $GF(2^8)$).
     - **Pilar 3:** Handshake `SPAKE2` / `X25519` em 1-RTT sobre o socket UDP unico + `ChaCha20-Poly1305` AEAD real com nonce deterministico de 96 bits e cabecalho de 32B autenticado como `AAD`.
     - **Pilar 4:** Consolidacao do `libdav_core` C++23 como acelerador C-ABI de *Hot-Path Data Plane* invocado pelas fatias `src/dav/modules/` (com fallback Python/NumPy bit-identico).
     - **Estudo de Audio em Tempo Real:** Captura loopback (WASAPI Event-Driven / Process Loopback no Windows e PipeWire Monitor no Linux), compressao Opus `48 kHz` low-delay (`5–10 ms`, LBRR + PLC), multiplexacao por `Payload Type = 0x02` com fila de prioridade estrita, compensacao de *clock skew* via ASRC ($\pm 0,2\%$) e sincronia labial A/V.

4. **Implementacao Integral das 4 Fases Aprovadas (Motor v4.5.0 / Pacote v4.0.0):**
   - **Fase 1 — Handshake PAKE (`CPace-X25519`) e AEAD Real (`ChaCha20-Poly1305`):**
     - Criado `src/dav/modules/transport_p2p/crypto_pake.py` com `PakeSession` (acordo de chaves efemeras X25519 autenticado por PIN via HKDF-SHA256 com confirmacao HMAC-SHA256 em tempo constante; pacotes `DAV_P2P_SYN2` de 65 bytes e `DAV_P2P_ACK2` de 81 bytes), `PacketCipher` (RFC 8439 ChaCha20-Poly1305 com nonce deterministico de 96 bits `salt96 ^ (SSRC || frame_id || seq_num)` e autenticacao dos 32 bytes do cabecalho como `AAD`) e `ReplayWindow(64)`.
     - Atualizado `src/dav/modules/transport_p2p/packetizer.py` com tipos de carga unificados (`PT_VIDEO = 0x00`, `PT_FEC = 0x01`, `PT_AUDIO = 0x02`, `PT_CONTROL = 0x03`), flags (`FLAG_AEAD_CHACHA20 = 0x10`, `FLAG_AUDIO_LBRR = 0x20`, `FLAG_PIR = 0x40`), `DAV_DEFAULT_MTU = 1300`, `pack_datagram`, `pack_frame` (preservando compatibilidade legada com `key_vector`) e `unpack_and_decrypt`.
   - **Fase 2 — FEC Adaptativo em $GF(2^8)$ e Controle Salsify/SQP Acoplado ao Codec:**
     - Criado `src/dav/modules/transport_p2p/fec_engine.py` com `FecEncoder`, `FecDecoder` (caminho rapido XOR para `M=1` e Cauchy Reed-Solomon em $GF(2^8)$ com polinomio `0x11d` para `M >= 2`, metadado `FEC_META_FORMAT = "!HBBHH"` de 8 bytes preservando tamanho exato de shards de cauda menores) e `AdaptiveFecPolicy`.
     - Criado `src/dav/modules/transport_p2p/sqp_controller.py` com `SqpAckData` (`DAV_SQP1`, 30 bytes), `SqpReceiverTracker` (gradiente de atraso inter-frame sem dependencia de sincronia absoluta de relogios, dispersao intra-frame e perda deslizante), `SqpSenderController` (sondagem/backoff estilo SQP + `allocate_frame_budget` estilo Salsify com descarte controlado de quadro saturado) e `MicroPacer` (preempcao de `PT_AUDIO`/`PT_CONTROL` sobre rajadas de video e FEC).
     - Atualizados `src/codec/hybrid_codec.py`, `src/dav/modules/codec/base.py` e `src/dav/modules/codec/encoder.py` com `update_rate_budget(bitrate_kbps, pir_mode=False)` atuando dinamicamente sobre `ctx.bit_rate`.
   - **Fase 3 — Unificacao do Data Plane e Paridade C++23 (`libdav_core`):**
     - Criados `src/dav/modules/transport_p2p/data_plane.py` (`DataPlaneSender`, `DataPlaneReceiver`) e `src/dav/modules/transport_p2p/native_bridge.py` (`NativeDataPlaneBridge`), e corrigida a exportacao `MAGIC_RLY1` em `src/dav/modules/transport_p2p/__init__.py`.
     - Refatorados `src/dav/modules/stream_engine/sender_worker.py`, `src/dav/modules/stream_engine/receiver_worker.py`, `scripts/dav_sender_worker.py` e `scripts/dav_client.py` para operar sobre `DataPlaneSender` e `DataPlaneReceiver`, eliminando duplicacao de empacotamento/criptografia nos scripts e workers.
     - Atualizados os fontes C++23 em `include/dav/dav_api.h`, `src/core/dav_api.cpp`, `src/packetizer/packet.hpp`, `src/qos/fec.hpp`, `src/qos/fec.cpp`, `src/crypto/crypto_channel.hpp`, `src/crypto/crypto_channel.cpp` e `src/session/session.cpp` para alinhar o cabecalho de 32 bytes (`to_wire_bytes` / `from_wire_bytes`), implementar RFC 8439 ChaCha20-Poly1305 AEAD sem dependencias externas (Poly1305 em limbos de 26 bits), implementar `encode_gf256_raw` / `recover_gf256_raw` / `FecHandler::try_recover` e exportar as funcoes stateless `dav_aead_seal_raw`, `dav_aead_open_raw`, `dav_fec_encode_gf256` e `dav_fec_recover_gf256` (com `dav_get_version()` atualizada para `"DA-V v4.5.0 (Unified C-ABI Data Plane)"`).
   - **Fase 4 — Modulo Modular de Audio em Tempo Real, Integracao na UI e Empacotamento:**
     - Criado o modulo `src/dav/modules/audio/` (`__init__.py`, `capturer.py`, `codec_opus.py`, `jitter_asrc.py`, `player.py`, `service.py`, `manifest.py`), cobrindo captura Windows WASAPI Loopback + reamostragem automatica para 48 kHz estereo `s16`, captura Linux via monitor PipeWire/PulseAudio, `SyntheticAudioCapturer` para testes determinísticos, codificacao/decodificacao Opus via PyAV (`libopus`) em quadros de 10 ms com LBRR e PLC, buffer de jitter Welford + ASRC PI ($\pm 0,25\%$) com `lip_sync_delta_ms`, e reproducao em `DesktopAudioPlayer` via `PySide6.QtMultimedia.QAudioSink`.
     - Registrado `"src.dav.modules.audio.manifest"` em `src/dav/kernel/registry.py`.
     - Integrados controles e sinalizacao de audio e selo `"PAKE AEAD"` em `src/ui/glass/sheets.py`, `src/ui/widgets/canvas.py` e `src/ui/main_window.py` (`audio_tx_toggled`, `audio_rx_toggled`, `_on_audio_pkt`, `DesktopAudioPlayer`).
     - Atualizados `requirements.txt`, `scripts/build_windows.ps1`, `scripts/build_linux_bundle.sh` e `.github/workflows/release.yml` para contemplar `cryptography`, `comtypes` e os modulos ocultos do PyInstaller (`src.dav.modules.audio.manifest` e dependencias).

5. **Unificacao Arquitetural Hexagonal + Fatias Verticais Puras (v4.6):**
   - **Fase 1 — Evolucao do `MonoTech Core Kernel` (`src/dav/kernel/`):**
     - Criado `src/dav/kernel/contracts.py` com protocolos formais `@runtime_checkable` (`ICaptureService`, `ICodecService`, `ITransportService`, `IAudioService`, `IStreamEngineService`, `ITelemetryService`) e topicos canonicos do `EventBus` (`EVENT_VIDEO_FRAME_RX`, `EVENT_AUDIO_FRAME_RX`, `EVENT_STREAM_ROUTE_LOCKED`, `EVENT_STREAM_STATS`, `EVENT_STREAM_STOPPED`, `EVENT_LAN_PEERS_UPDATED`, `EVENT_TUPA_SNAPSHOT`, `EVENT_LOG_MESSAGE`).
     - Atualizado `src/dav/kernel/registry.py` com container singleton `get_service(name)` e `get_export(module_name, symbol)` e padronizados todos os 9 manifestos `src/dav/modules/*/manifest.py` com `MANIFEST = ModuleManifest(...)`, `service_factory` e `exports["service"]`.
   - **Fase 2 — Absorcao Integral dos Modulos Legados nas Fatias Verticais (`src/dav/modules/`):**
     - Criados `src/dav/modules/capture/wayland_portal.py`, `src/dav/modules/transport_p2p/signaling_client.py`, `src/dav/modules/transport_p2p/lan_beacon.py`, `src/dav/modules/telemetry/stage_probe.py` e `src/dav/modules/telemetry/tupa_checker.py`, consolidando `CaptureService`, `CodecService`, `TransportService` e `TelemetryService` (e convertendo `src/capture/linux_wayland_portal.py`, `src/codec/hybrid_codec.py`, `src/discovery/p2p_channel.py`, `src/discovery/lan_beacon.py`, `src/telemetry/tupa_checker.py` e `scripts/dav_stage_probe.py` em shims enxutos de compatibilidade).
   - **Fase 3 — Unificacao do `StreamEngineService` e Fim do Dual-Engine:**
     - Criado `src/dav/modules/stream_engine/subprocess_sender.py` encapsulando o host multiprocesso GIL-free (`SenderTransportEndpoint` e `run_sender_subprocess`) dentro da fatia `stream_engine`, sem nenhuma dependencia de `scripts/` ou `PySide6`.
     - Evoluidos `SenderWorker` (`src/dav/modules/stream_engine/sender_worker.py`), `ReceiverWorker` (`src/dav/modules/stream_engine/receiver_worker.py`) e `StreamEngineService` (`src/dav/modules/stream_engine/service.py`) para integrar `AudioService` e unificar a API reativa de fatia com a API desktop/CLI (`start_sender`, `start_receiver`, `prepare_receiver_socket`, `wait_sender_endpoint`, `pair_sender_peer`, `set_sender_audio_muted`, `update_sender_target`, `stop`).
     - Reduzidos `scripts/dav_client.py` e `scripts/dav_sender_worker.py` a wrappers CLI enxutos delegando para `src.dav.modules.stream_engine`.
   - **Fase 4 — Desacoplamento Estrito da Camada de Apresentacao (`src/ui/`):**
     - Criados `src/ui/qt_compat.py` e `src/ui/audio_sink.py` (`DesktopAudioPlayer` / `QtAudioSinkPlayer`), mantendo shims em `scripts/qt_compat.py` e `src/dav/modules/audio/player.py`.
     - Refatorados `scripts/gui_app.py` e `src/ui/main_window.py` para injetar `kernel=kernel_registry` no construtor de `DavMainWindow` e resolver `stream_engine`, `transport_p2p`, `audio` e `telemetry` via `self.kernel.get_service(...)`, eliminando 100% dos imports de `scripts.*` dentro de `src/`.
   - **Fase 5 — Governanca Arquitetural Automatizada (`tests/test_architecture_boundaries.py`):**
     - Criada suite `tests/test_architecture_boundaries.py` validando via AST que nenhum arquivo em `src/` importa `scripts.*`, que `src/dav/kernel/` nao importa `src.dav.modules` nem `src.ui`, que as 7 fatias de dominio puras nao importam `src.ui` nem `PySide6`, e que todos os 9 manifestos resolvem singletons aderentes aos `Protocol`s do Kernel.

6. **Reengenharia Salsify/SQP Cut-Through Sub-Milissegundo (`< 0.5 ms` @ 60 FPS — v4.7):**
   - **Separacao de Sequencias e Dominio de Nonces (`data_plane.py`, `crypto_pake.py`, `crypto_channel.cpp`):**
     - Eliminado o compartilhamento de `_seq_num` entre `PT_AUDIO` e `PT_VIDEO`/`PT_FEC` em `DataPlaneSender` (criados `_next_video_seq()` e `_next_audio_seq()` independentes).
     - Adicionada separacao de dominio AEAD por `payload_type` no nonce ChaCha20-Poly1305 (`ssrc ^ (payload_type << 24)`) e janelas `ReplayWindow` independentes por fluxo em `PacketCipher` (além da paridade equivalente em `CryptoChannel::encrypt_packet` / `decrypt_packet` no C++23), zerando a falsa perda de ~16% que derrubava o bitrate para `800 kbps`.
   - **`MicroPacer` Cut-Through e Gradiente OWD pelo 1o Fragmento (`sqp_controller.py`, `data_plane.py`):**
     - Introduzido modo `cut_through=True` padrao (0.0 ms de sleep na thread de encode com drenagem prioritaria de `PT_AUDIO`/`PT_CONTROL` a cada 6 pacotes, reduzindo o tempo medio de `send_video_frame` em P-frames de 18 KB de `9.897 ms` para **`0.077 ms`**), com micro-espacamento limitado a no maximo `2.0 ms` apenas sob congestionamento WAN ativo.
     - Atualizado `SqpReceiverTracker.on_frame_completed` para calcular `owd_gradient` pelo `first_rx_us` do quadro e filtro `Windowed Min-OWD` (120 amostras exclusivas do fragmento 0 de `PT_VIDEO`), medindo `0.308 ms` em loopback com expiracao de quadros pendentes reduzida para `120 ms` e `rx_queue_ahead` preciso.
   - **Piso HD, Histerese no Encoder e FEC Zero-Overhead (`sqp_controller.py`, `encoder.py`, `fec_engine.py`, `receiver_worker.py`):**
     - Definido piso minimo de alta definicao (`max(4500 kbps, 45% do bitrate alvo)`, ou seja, `5.4 Mbps` para streams de `12 Mbps`), tolerancia de burst `2.5x` antes de `skip_frame`, recuperacao rapida (`+12% + 300 kbps`) e remocao do `time.sleep(0.001)` em `except socket.timeout` no `ReceiverWorker`.
     - Adicionada histerese no `VideoEncoder.update_rate_budget` (so altera `ctx.bit_rate` se variacao `>= 12%` e intervalo `>= 400 ms`), e ajustado `AdaptiveFecPolicy` para zero paridade FEC em P-frames com rede limpa (`loss_rate < 0.005`) e 1 paridade XOR rapida apenas em keyframes IDR.
   - **Benchmark Automatizado (`tests/test_salsify_subms_perf.py`):**
     - Criados testes validando 120 quadros de video 1080p60 + 240 quadros de audio Opus intercalados com `0.0%` de perda, `12000 kbps` constantes, `0` frame skips, tempo medio de envio Cut-Through `< 0.5 ms` e histerese no `VideoEncoder`.

7. **Auditoria Forense de Logs Reais e Fechamento Integral de Lacunas de QoS (v4.8):**
   - **Analise Forense dos 3 Bundles de Diagnostico (`21-26-07`, `21-33-28`, `21-34-56`):**
     - Identificado que no fluxo Linux TX -> Windows RX (`844-857`), `libx264` sem `vbv-maxrate`/`vbv-bufsize` ignorou `update_rate_budget()` e disparou para `24.20 Mbps`, causando `702.31 ms` de bufferbloat WAN, perda parcial de fragmentos (`203.6 pkts/quadro completo`), cascata de `PLI` e queda para `8.4 FPS` no RX e `28.3 FPS` no TX.
     - Identificado que no fluxo Windows TX (`584-155` e `390-495`), os platos quantizados em `44.3–45.8 FPS` (por 22 s a `24 KB/quadro`, `9.50 Mbps`, `20.00 pkts/quadro`) e `29.9–30.3 FPS` foram causados pelo limite fixo `inflight > 2.5 * per_frame_cap_bytes` sem considerar o BDP da WAN (`RTT >= 44 ms`) somado ao atraso de `poll_control()` sincrono a 60 Hz (`+16.67 ms`).
   - **Implementacao das 7 Correcoes de QoS WAN/LAN:**
     - `src/dav/modules/transport_p2p/sqp_controller.py`: `allocate_frame_budget()` passou a dimensionar `natural_bdp_bytes` pelo RTT real (`rtt_ms / frame_ms`), descontando de `raw_budget` apenas o `excess_inflight` acima do BDP natural e exigindo congestionamento comprovado (`is_congested` ou `rx_queue_frames >= 4` ou `owd >= 8.0 ms`) antes de permitir `skip_frame = True`.
     - `src/dav/modules/stream_engine/subprocess_sender.py` e `src/dav/modules/stream_engine/sender_worker.py`: Adicionada thread assincrona dedicada `DAV-Control-RX` (`select.select` `<= 2 ms`), lock nao-bloqueante em `poll_control()` e drenagem imediata pre-`allocate_budget()`, eliminando o atraso de `+16.67 ms` na leitura de `SQP_ACK`.
     - `src/dav/modules/codec/encoder.py`: Inicializados `ctx.bit_rate`, `ctx.framerate`, `maxrate` (`1.15x`) e `bufsize` (`1/3`) no `NVENC` e no `libx264` (`vbv-maxrate` e `vbv-bufsize`), com reconfiguracao efetiva do `libx264` em mudancas `>= 20%` e debounce de `0.60 s` em `request_keyframe()` contra tempestades de `PLI`.
     - `src/dav/modules/transport_p2p/fec_engine.py`: Eliminada a zona morta de `0.1%–1.0%` em `AdaptiveFecPolicy.choose_parity()`, ativando paridade XOR rapida (`m = 1`, `< 10 us`) em P-frames a partir de `loss_rate >= 0.001` (1 pacote perdido em 256) ou jitter WAN `owd_gradient_ms >= 1.5 ms`.
     - `src/dav/modules/stream_engine/receiver_worker.py` e `src/dav/modules/transport_p2p/data_plane.py`: Cooldown adaptativo de `PLI` (`0.45 s` normal / `0.90 s` sob bufferbloat `> 80 ms`) e expiracao adaptativa de montagem (`120–220 ms`).
     - `src/dav/modules/stream_engine/subprocess_sender.py`, `src/dav/modules/stream_engine/sender_worker.py` e `src/dav/modules/stream_engine/receiver_worker.py`: Sondagem continua de upgrade `WAN P2P Direto -> LAN Direto` (`_send_lan_upgrade_probe` a cada `200 ms` nos primeiros `6.0 s` pos-confirmacao PAKE).
     - `src/ui/bridge.py`: Reduzida fila `DecodeWorker._q` de `maxsize=32` (`533 ms`) para `maxsize=8` (`133 ms`) com drenagem de backlog em picos.

---

## 2. Alteracoes de Arquivos

### Criados
- `src/dav/kernel/contracts.py`
- `src/dav/modules/capture/wayland_portal.py`
- `src/dav/modules/transport_p2p/crypto_pake.py`
- `src/dav/modules/transport_p2p/fec_engine.py`
- `src/dav/modules/transport_p2p/sqp_controller.py`
- `src/dav/modules/transport_p2p/data_plane.py`
- `src/dav/modules/transport_p2p/native_bridge.py`
- `src/dav/modules/transport_p2p/signaling_client.py`
- `src/dav/modules/transport_p2p/lan_beacon.py`
- `src/dav/modules/audio/__init__.py`
- `src/dav/modules/audio/capturer.py`
- `src/dav/modules/audio/codec_opus.py`
- `src/dav/modules/audio/jitter_asrc.py`
- `src/dav/modules/audio/player.py`
- `src/dav/modules/audio/service.py`
- `src/dav/modules/audio/manifest.py`
- `src/dav/modules/stream_engine/subprocess_sender.py`
- `src/dav/modules/telemetry/stage_probe.py`
- `src/dav/modules/telemetry/tupa_checker.py`
- `src/ui/qt_compat.py`
- `src/ui/audio_sink.py`
- `tests/test_pake_crypto.py`
- `tests/test_sqp_fec.py`
- `tests/test_audio_pipeline.py`
- `tests/test_architecture_boundaries.py`
- `tests/test_salsify_subms_perf.py`

### Modificados
- `src/dav/kernel/__init__.py`
- `src/dav/kernel/registry.py`
- `src/dav/modules/capture/linux_capturer.py`
- `src/dav/modules/capture/service.py`
- `src/dav/modules/capture/manifest.py`
- `src/dav/modules/codec/base.py`
- `src/dav/modules/codec/encoder.py`
- `src/dav/modules/codec/decoder.py`
- `src/dav/modules/codec/manifest.py`
- `src/dav/modules/transport_p2p/__init__.py`
- `src/dav/modules/transport_p2p/blind_relay.py`
- `src/dav/modules/transport_p2p/crypto_pake.py`
- `src/dav/modules/transport_p2p/data_plane.py`
- `src/dav/modules/transport_p2p/fec_engine.py`
- `src/dav/modules/transport_p2p/packetizer.py`
- `src/dav/modules/transport_p2p/sqp_controller.py`
- `src/dav/modules/transport_p2p/service.py`
- `src/dav/modules/transport_p2p/manifest.py`
- `src/dav/modules/stream_engine/__init__.py`
- `src/dav/modules/stream_engine/sender_worker.py`
- `src/dav/modules/stream_engine/receiver_worker.py`
- `src/dav/modules/stream_engine/service.py`
- `src/dav/modules/stream_engine/manifest.py`
- `src/dav/modules/telemetry/__init__.py`
- `src/dav/modules/telemetry/service.py`
- `src/dav/modules/telemetry/manifest.py`
- `src/dav/modules/commercial/manifest.py`
- `src/dav/modules/presentation/author_dialog.py`
- `src/dav/modules/presentation/manifest.py`
- `src/dav/modules/updater/update_dialog.py`
- `src/dav/modules/updater/manifest.py`
- `src/capture/linux_wayland_portal.py`
- `src/codec/hybrid_codec.py`
- `src/discovery/p2p_channel.py`
- `src/discovery/lan_beacon.py`
- `src/telemetry/tupa_checker.py`
- `src/ui/bridge.py`
- `src/ui/main_window.py`
- `src/ui/glass/icons.py`
- `src/ui/glass/nav_pill.py`
- `src/ui/glass/paint.py`
- `src/ui/glass/sheets.py`
- `src/ui/glass/views.py`
- `src/ui/glass/widgets.py`
- `src/ui/views/discovery_view.py`
- `src/ui/views/sender_view.py`
- `src/ui/views/troubleshoot_view.py`
- `src/ui/views/tupa_view.py`
- `src/ui/views/viewer_view.py`
- `src/ui/widgets/canvas.py`
- `src/ui/widgets/cards.py`
- `src/ui/widgets/header.py`
- `src/ui/widgets/sidebar.py`
- `scripts/gui_app.py`
- `scripts/qt_compat.py`
- `scripts/dav_sender_worker.py`
- `scripts/dav_client.py`
- `scripts/dav_stage_probe.py`
- `scripts/build_windows.ps1`
- `scripts/build_linux_bundle.sh`
- `include/dav/dav_api.h`
- `src/core/dav_api.cpp`
- `src/packetizer/packet.hpp`
- `src/qos/fec.hpp`
- `src/qos/fec.cpp`
- `src/crypto/crypto_channel.hpp`
- `src/crypto/crypto_channel.cpp`
- `src/session/session.cpp`
- `requirements.txt`
- `.github/workflows/release.yml`

---

## 3. Verificacoes, Builds e Limitacoes Observadas

1. **Suite de Testes (`pytest`):**
   - Executado `py -m pytest tests/ -q` apos todas as alteracoes de QoS WAN/LAN (v4.8): **76 passed in 12.87s** (incluindo os 8 testes de benchmark sub-milissegundo e QoS WAN/VBV/FEC em `tests/test_salsify_subms_perf.py`, os 5 testes de governanca arquitetural em `tests/test_architecture_boundaries.py`, mais `tests/test_pake_crypto.py`, `tests/test_sqp_fec.py`, `tests/test_audio_pipeline.py` e regressao E2E P2P/Blind Relay em `tests/test_p2p_e2e.py`).
   - Medicao direta no benchmark `DataPlaneSender`/`DataPlaneReceiver` (120 quadros de video + 240 quadros de audio Opus): `video_ok=120/120`, `audio_ok=240/240`, `skips=0`, `avg_p_send_ms=0.077 ms`, `loss_rate=0.0000`, `est_kbps=12000`, `lat_ms=0.308 ms`; e em simulacao `WAN RTT = 50 ms` (180 quadros de 25.8 KB): `sent_frames=180/180`, `skips=0` (60.0 FPS cravados).
2. **Verificacao de Execucao & Empacotamento Windows (`build_windows.ps1`):**
   - `dist/DA-V/DA-V.exe --self-check`: `DAV_SELF_CHECK_OK`, codigo de saida `0`.
   - Artefatos gerados:
     - `dist/DA-V/DA-V.exe` (`7531450` bytes)
     - `release_assets/DA-V_Instalador_Windows_x64.exe` (`197802140` bytes)
     - `release_assets/DA-V_v4.0.0_Windows_x64_Portable.zip` (`152396145` bytes)
3. **Empacotamento Linux Portatil:**
   - Gerado pacote portatil de codigo-fonte Linux atualizado: `release_assets/DA-V_v4.0.0_Linux_Source_Portable.tar.gz` (`335129` bytes, `224` entradas).
4. **Limitacoes Transparentes do Ambiente Local:**
   - **Compilacao C++23 (`libdav_core`):** Este host Windows nao possui Visual Studio / MSVC / CMake / `g++` instalado localmente; portanto, as atualizacoes em C++23 (`packet.hpp`, `fec.cpp`, `crypto_channel.cpp`, `dav_api.cpp`, `session.cpp`) nao foram compiladas localmente e dependem da compilacao nativa em ambiente com toolchain C++23 (ou CI GitHub Actions).
   - **Binario Linux ELF (.AppImage / bundle ELF):** O ambiente WSL2 neste computador retornou `HCS_E_HYPERV_NOT_INSTALLED`, impossibilitando gerar o binario Linux congelado localmente; por esse motivo foi disponibilizado o tarball de fontes atualizado `DA-V_v4.0.0_Linux_Source_Portable.tar.gz` acompanhado de `scripts/build_linux_bundle.sh`.
