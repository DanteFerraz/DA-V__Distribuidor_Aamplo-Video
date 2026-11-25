---
status: accepted
date: 2026-11-24
decision-makers: Dante Ferraz Oliveira Paiva (MonoTech)
---

# ADR-0003: Arquitetura da fatia universal_input para tradução do teclado do cliente e múltiplos controles P2P

## Context and problem statement

Na versão `v5.0.0`, o módulo `remote_desktop` introduziu o canal binário `PT_INPUT` de 24 bytes baseado exclusivamente em códigos físicos USB HID (`KEY_DOWN` e `KEY_UP`). Em sessões reais entre máquinas com layouts distintos (por exemplo, cliente ABNT2 `pt-BR` conectado a host `en-US` ou Wayland/X11), teclas mortas (*dead keys*) como `~` (`Qt.Key_Dead_Tilde`), acentos compostos (`ã`, `õ`, `é`) e símbolos dependentes de `AltGr` falhavam ou produziam caracteres incorretos no host. Além disso, usuários precisavam conectar múltiplos controles (PlayStation DualShock 4, PlayStation DualSense, Xbox e gamepads genéricos DirectInput/HID) a partir de um ou vários acessos remotos simultâneos no mesmo PC host, com botão rápido de ativar/desativar na transmissão e um testador capaz de vibrar fisicamente o controle do cliente remoto.

## Decision drivers

* Preservar rigorosamente as fronteiras do **MonoTech Core Kernel v2.0** (fatias verticais puras isentas de `PySide6` ou `src.ui`, comunicando-se via contratos `Protocol` e `EventBus`).
* Reproduzir fielmente o teclado do cliente conectado na transmissão interativa (incluindo `~` isolado, `~/`, `ã`, `ç`, `/`, `?`, `|` e `AltGr`) independentemente do sistema operacional ou layout configurado no host, mantendo `KEY_DOWN`/`KEY_UP` HID de latência zero para movimentação em jogos (`WASD`) e atalhos (`Ctrl+~`, `Ctrl+C`, `Alt+Tab`).
* Manter compatibilidade binária estrita com o pacote `PT_INPUT` de 24 bytes (`!BBBBiiIQ`), evitando aumento de cabeçalho ou bloqueio *Head-of-Line*.
* Suportar DualShock 4, DualSense, Xbox, Switch Pro e controles genéricos USB/Bluetooth, permitindo até 4 pares P2P simultâneos no mesmo PIN e até 8 slots virtuais no host com retorno háptico (*Force-Feedback* / vibração remota).

## Considered options

* **Opção 1: Manter apenas scancodes HID e exigir que o usuário iguale manualmente o layout de teclado entre cliente e host, limitando controles a XInput local.**
* **Opção 2: Criar a 11ª fatia vertical `src/dav/modules/universal_input/` combinando tradução híbrida HID + Unicode (`EvType.KEY_UNICODE = 10`), estado normalizado de controles em 24 bytes (`EvType.GAMEPAD_STATE = 11`), sessões CPace multi-peer e canal de vibração remota (`GAMEPAD_RUMBLE` / `GAMEPAD_RUMBLE_ACK`).**
* **Opção 3: Tunelar dispositivos USB brutos via USB/IP sobre TCP.**

## Decision outcome

Escolhida a **Opção 2** (fatia vertical `universal_input` integrada ao protocolo `PT_INPUT` de 24 bytes e ao canal `PT_WORKSPACE`), pois atende integralmente à tradução automática do teclado do cliente e à agregação multi-controle com latência sub-milissegundo em LAN e WAN UDP, sem os travamentos de kernel e sensibilidade a jitter de USB/IP sobre TCP.

### Consequências positivas

* O `ClientKeyboardTranslator` captura a composição nativa do sistema operacional do cliente (`WA_InputMethodEnabled` + `inputMethodEvent` no `VideoCanvasWidget`) e envia `EvType.KEY_UNICODE` para símbolos e *dead keys* resolvidos (`~`, `ã`, `ç`), injetados atomicamente via `SendInput(KEYEVENTF_UNICODE)` UTF-16LE no Windows, `NotifyKeyboardKeysym` no Wayland XDG Portal, `XChangeKeyboardMapping` no X11 e sequências XKB em `/dev/uinput` no Linux.
* O `UniversalGamepadCapturer` unifica leitura e vibração via `SDL2` (`SDL_GameController`, `SDL_Joystick`, `SDL_Haptic` e HIDAPI PS4/PS5 Rumble) com contingência nativa `XInput`/`WinMM` no Windows e `evdev` (`FF_RUMBLE`) no Linux.
* O `VirtualGamepadHub` instancia `VDS4Gamepad` para DualShock 4/DualSense (preservando clique do Touchpad) e `VX360Gamepad` para Xbox/Genéricos via `ViGEmBus` no Windows (ou `/dev/uinput` com `EV_FF` no Linux), escalando até 8 slots distribuídos entre múltiplos acessos P2P autenticados por nonce CPace em [subprocess_sender.py](../../src/dav/modules/stream_engine/subprocess_sender.py) e [sender_worker.py](../../src/dav/modules/stream_engine/sender_worker.py).
* O botão vetorial `ZONE_GAMEPAD` em [widgets.py](../../src/ui/glass/widgets.py) permite ativar/pausar controles instantaneamente como o botão de mouse, e o `GamepadTesterWidget` em [sheets.py](../../src/ui/glass/sheets.py) aciona a vibração física do controle remoto com confirmação de RTT em tempo real.

### Consequências negativas e mitigações

* No Windows, a criação de controles virtuais de kernel requer o driver assinado `ViGEmBus` instalado no host. Para mitigar isso, `VirtualGamepadHub` degrada graciosamente para slots diagnósticos sem interromper a sessão (mantendo o testador de vibração remota funcional) e oferece botão de instalação assistida via `winget` + UAC no próprio `GamepadTesterWidget`.
