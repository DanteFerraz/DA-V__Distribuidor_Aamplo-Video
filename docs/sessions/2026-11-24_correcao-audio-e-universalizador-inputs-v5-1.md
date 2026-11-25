---
doc_type: session-report
date: 2026-11-24
project: DA-V (Distribuidor Amplo de Vídeo)
version: 5.1.0
author: Dante Ferraz Oliveira Paiva (MonoTech)
---

# Relatório de sessão 2026-11-24 — Correção de áudio e universalizador de entradas v5.1.0

## Resumo executivo

Nesta sessão foi diagnosticada e corrigida em definitivo a falha de transmissão/reprodução de áudio observada após a atualização `v5.0.0`, além de projetada e implementada a 11ª fatia vertical do **MonoTech Core Kernel v2.0** (`src/dav/modules/universal_input/`) para a versão **DA-V v5.1.0**. O novo subsistema entrega tradução fiel ao teclado do cliente conectado (incluindo envio literal e composto de `~`, *dead keys*, `AltGr` e símbolos ABNT2/US), universalizador multi-controle compatível com PlayStation DualShock 4, PlayStation DualSense, Xbox, Switch Pro e gamepads genéricos DirectInput/HID em múltiplos acessos P2P simultâneos, botão flutuante de ativar/desativar controles ao lado do botão de mouse e testador de controles com vibração remota confirmada por RTT.

## Alterações realizadas

### Diagnóstico e blindagem do pipeline de áudio (`audio` e `src/ui/audio_sink.py`)

* Identificadas cinco causas raízes combinadas para a interrupção de áudio:
  1. `DesktopAudioPlayer.stop()` destruía permanentemente `OpusAudioDecoder._codec_ctx = None` ao desconectar, trocar de modo ou reconectar o receptor.
  2. `_audio_tx_worker` em [subprocess_sender.py](../../src/dav/modules/stream_engine/subprocess_sender.py) descartava 19 de cada 20 quadros durante silêncio na área de trabalho, desalinhando a sequência de `frame_id` em relação ao `AudioJitterAsrcBuffer`.
  3. Transições para o *Secure Desktop* do Windows UAC ao ativar o Modo Interativo invalidavam o `IAudioCaptureClient` (`AUDCLNT_E_DEVICE_INVALIDATED`) sem loop de reconexão em `WinWasapiLoopbackCapturer`, além de DACs `int24`/`int32` não serem convertidos antes do reamostrador.
  4. Em sessões Linux PipeWire sem `parec`, `pw-record` sem `--raw` e em modo bloqueante estagnava em monitores ociosos.
  5. `QAudioSink` carecia de negociação automática para `Float32` e reconexão em *hot-plug* (`audioOutputsChanged`).
* Aplicadas correções em [capturer.py](../../src/dav/modules/audio/capturer.py), [codec_opus.py](../../src/dav/modules/audio/codec_opus.py), [jitter_asrc.py](../../src/dav/modules/audio/jitter_asrc.py), [audio_sink.py](../../src/ui/audio_sink.py), [subprocess_sender.py](../../src/dav/modules/stream_engine/subprocess_sender.py) e [sender_worker.py](../../src/dav/modules/stream_engine/sender_worker.py).

### Nova fatia vertical `universal_input` e protocolo binário `24B`

* Criada a fatia pura [service.py](../../src/dav/modules/universal_input/service.py) registrada sob o contrato `IUniversalInputService` em [contracts.py](../../src/dav/kernel/contracts.py) e [registry.py](../../src/dav/kernel/registry.py):
  * [models.py](../../src/dav/modules/universal_input/models.py): `ControllerKind`, `GamepadButtonMask` (16 bits incluindo `TOUCHPAD_CLICK`), `ClientKeyboardProfileDTO`, `UniversalKeyActionDTO`, `GamepadStateDTO` (empacotamento exato em 24 bytes), `GamepadSlotDTO`, `RumbleRequestDTO` e `RumbleAckDTO`.
  * [keyboard_translator.py](../../src/dav/modules/universal_input/keyboard_translator.py): `ClientKeyboardTranslator` (híbrido HID para jogos/atalhos + `KEY_UNICODE` para caracteres compostos e `~` do layout do cliente) e `HostKeyboardReproducer` (UTF-16LE, XKB KeySyms e sequências `evdev` ABNT2/US).
  * [gamepad_normalizer.py](../../src/dav/modules/universal_input/gamepad_normalizer.py) e [gamepad_capturer.py](../../src/dav/modules/universal_input/gamepad_capturer.py): normalização e captura via `SDL2` (`SDL_GameController`, `SDL_Joystick`, `SDL_Haptic`, HIDAPI PS4/PS5 Rumble) com contingência nativa `XInput`/`WinMM`, Linux `evdev` (`FF_RUMBLE`) e backend sintético determinístico.
  * [gamepad_virtual_hub.py](../../src/dav/modules/universal_input/gamepad_virtual_hub.py): alocação dinâmica de até 8 controles virtuais no host (`ViGEmBus` `VDS4Gamepad`/`VX360Gamepad` no Windows; `/dev/uinput` com `EV_FF` no Linux) e disparo de pulsos de vibração remota por slot ou em broadcast.
* Estendidos [protocol.py](../../src/dav/modules/remote_desktop/protocol.py), [keymap.py](../../src/dav/modules/remote_desktop/keymap.py), [security_gate.py](../../src/dav/modules/remote_desktop/security_gate.py), [injector_win32.py](../../src/dav/modules/remote_desktop/injector_win32.py), [injector_linux.py](../../src/dav/modules/remote_desktop/injector_linux.py) e [wayland_portal.py](../../src/dav/modules/capture/wayland_portal.py) para suportar `EvType.KEY_UNICODE`, `EvType.GAMEPAD_STATE`, `allow_gamepad` e injeção universal sem alterar os 24 bytes do quadro `PT_INPUT`.
* Atualizados [dav_rendezvous.py](../../src/signaling/server/dav_rendezvous.py), [signaling_client.py](../../src/dav/modules/transport_p2p/signaling_client.py), [subprocess_sender.py](../../src/dav/modules/stream_engine/subprocess_sender.py), [sender_worker.py](../../src/dav/modules/stream_engine/sender_worker.py), [receiver_worker.py](../../src/dav/modules/stream_engine/receiver_worker.py) e [service.py](../../src/dav/modules/stream_engine/service.py) para múltiplos receptores autenticados simultaneamente no mesmo PIN.

### Interface Glassmorphism, botão de controle e testador de vibração remota

* Adicionado ícone vetorial `draw_gamepad` em [icons.py](../../src/ui/glass/icons.py) e zona interativa `ZONE_GAMEPAD` em `VideoOverlayControls` ([widgets.py](../../src/ui/glass/widgets.py)), posicionada ao lado do botão de mouse para ativar e pausar controles em um clique.
* Integrados `WA_InputMethodEnabled`, `inputMethodEvent` e `ClientKeyboardTranslator` em [canvas.py](../../src/ui/widgets/canvas.py).
* Construído o `GamepadTesterWidget` em [sheets.py](../../src/ui/glass/sheets.py) e conectado em [main_window.py](../../src/ui/main_window.py), permitindo testar e vibrar controles remotos com exibição ao vivo do `GAMEPAD_RUMBLE_ACK` e RTT.
* Atualizados `VERSION` (`5.1.0`), [requirements.txt](../../requirements.txt), [build_windows.ps1](../../scripts/build_windows.ps1), [build_linux_bundle.sh](../../scripts/build_linux_bundle.sh), [install_linux.sh](../../install_linux.sh), [release.yml](../../.github/workflows/release.yml), [CHANGELOG.md](../../CHANGELOG.md), [README.md](../../README.md) e registrado o [ADR-0003](../decisions/0003-arquitetura-fatia-universal-input-e-multi-gamepad.md).

## Evidências de verificação e testes

* Governança arquitetural AST ([test_architecture_boundaries.py](../../tests/test_architecture_boundaries.py)) atualizada e validada para todas as 11 fatias verticais do MonoTech Core Kernel v2.0 (`IUniversalInputService` singleton e ausência total de importações de UI nas fatias puras).
* Pipeline de áudio ([test_audio_pipeline.py](../../tests/test_audio_pipeline.py)) validado cobrindo sobrevivência do decodificador Opus após ciclos `stop()` -> `start()`, reancoragem pós-mute e conversão PCM 24-bit/32-bit/5.1.
* Suíte dedicada [test_universal_input.py](../../tests/test_universal_input.py) validando tradução `~` / `~/` / `ã` / `AltGr` / `Ctrl+~` / `WASD`, normalização DualShock 4, DualSense, Xbox e Genéricos em 24 bytes, conexão simultânea de múltiplos pares P2P com múltiplos controles e ciclo completo de vibração remota (`Host -> GAMEPAD_RUMBLE -> Cliente vibra -> GAMEPAD_RUMBLE_ACK`).
* Validação sintática Bash (`install_linux.sh` e `scripts/build_linux_bundle.sh`), `--self-check` da aplicação gráfica e auditoria `doc_lint.py` aprovadas sem erros.

## Próximos passos verificáveis

1. Executar compilação local do instalador Windows `v5.1.0` com `powershell -ExecutionPolicy Bypass -File scripts/build_windows.ps1` quando desejado para geração dos binários em `release_assets/`.
2. Realizar commit estruturado e tag anotada `v5.1.0` para disparo automático da pipeline multi-OS no GitHub Actions (`build-linux`, `build-windows` e `publish-release`).
3. Validar em campo no host Windows o fluxo assistido de instalação do driver `ViGEmBus` com controles físicos DualSense/DualShock 4 via Bluetooth e USB.
