---
doc_type: adr
diataxis_quadrant: explanation
adr_id: "0002"
title: "Arquitetura de área de trabalho remota sub-15 ms e broker isolado de privilégio administrativo"
status: "accepted"
date: 2026-11-24
decision-makers: "Dante Ferraz"
consulted: "Engenharia de Sistemas MonoTech e Telemetria TUPÃ"
informed: "Comunidade e usuários do DA-V"
---

# ADR-0002: Arquitetura de área de trabalho remota sub-15 ms e broker isolado de privilégio administrativo

## Context and problem statement

Na evolução do **DA-V v5.0** de um distribuidor unidirecional de vídeo/áudio para uma plataforma completa de **compartilhamento interativo de área de trabalho** entre **Windows 10/11** e **Linux (Wayland e X11)**, surgiram três problemas arquiteturais centrais:

1. **Meta rigorosa de latência interativa (*Input-to-Photon* `<= 15 ms` em LAN e `<= 30 ms` em WAN):** Invocar processos externos ou transportar eventos de mouse e teclado sobre canais TCP/TLS separados adicionaria bloqueios de *Head-of-Line* (HoL) e sobrecarga de escalonamento incompatíveis com 60–120 FPS. Além disso, a thread reversa de controle possuia um `sleep(0.05)` durante transmissões ativas que introduzia até `50 ms` de latência artificial no sentido `Receptor -> Transmissor`.
2. **Isolamento de privilégio de sistema operacional (UIPI no Windows e `/dev/uinput` / Wayland no Linux):** No Windows, um processo em nível de usuário padrão é impedido pelo *User Interface Privilege Isolation* (UIPI) de enviar `SendInput` para janelas elevadas como Administrador. No Linux, elevar toda a interface gráfica Qt como `root` quebra o acesso aos sockets de sessão do usuário (`PipeWire`, `Wayland` e `PulseAudio` em `XDG_RUNTIME_DIR`), enquanto `/dev/uinput` exige privilégio administrativo.
3. **Convivência entre comandos de alta frequência e fluxos confiáveis de área de trabalho:** Cliques e coordenadas de ponteiro a `250 Hz` exigem entrega imediata sem fila, ao passo que transferência direta de arquivos P2P, área de transferência (*Clipboard*) e execução persistente de shell remoto estilo LTSP exigem ordenação estrita e integridade sem perdas.

## Decision drivers

- Atingir latência *Input-to-Photon* `<= 15 ms` em rede local e `<= 30 ms` em WAN regional, aproveitando o socket UDP único já autenticado via **PAKE CPace-X25519 + ChaCha20-Poly1305 AEAD** e compatível com **Blind Relay `DAV_RLY1`**.
- Manter segurança **Zero-Trust** (*Somente Visualização* por padrão), controlada por um switch explícito de **Transmissão Interativa** no Transmissor e revogável instantaneamente via atalho físico `Ctrl+Alt+Shift+Esc` com liberação automática de teclas presas (`StuckKeyWatchdog`).
- Viabilizar elevação administrativa sob demanda no Windows (**UAC `runas`**) e no Linux (**Polkit `pkexec`**) sem reiniciar a interface gráfica, sem derrubar a transmissão ativa e sem corromper a sessão de áudio/vídeo do usuário comum.
- Preservar o desacoplamento estrito entre fatias de domínio (`src/dav/modules/remote_desktop/`) e camada de apresentação (`src/ui/`), unificando também os instaladores Windows e Linux sob o motor visual `src/ui/glass/`.

## Considered options

- **Opção 1:** Executar comandos de mouse/teclado via invocação de utilitários de shell por evento (`xdotool`, `ydotool` ou scripts PowerShell) sobre um túnel SSH/TCP paralelo.
- **Opção 2:** Reiniciar integralmente o aplicativo gráfico `DA-V` como Administrador/`root` quando o usuário desejar controlar janelas privilegiadas.
- **Opção 3:** Arquitetura híbrida em 2 subcanais autenticados sobre o mesmo túnel UDP PAKE AEAD (`PT_INPUT = 0x04` binário de 24 bytes sem bloqueio + `PT_WORKSPACE = 0x05` com ARQ seletivo ordenado para Clipboard, arquivos e PTY persistente) combinada a um micro-broker isolado de privilégio (`--elevated-input-broker`) autenticado via `HMAC-SHA256` em `127.0.0.1`.

## Decision outcome

Escolhida a **Opção 3: Subcanais `PT_INPUT` (24 bytes) + `PT_WORKSPACE` (ARQ seletivo) sobre PAKE AEAD combinados ao Broker Isolado de Privilégio (`ElevatedInputBroker`)**.

### Justificativa

1. **Latência sub-milissegundo no plano de controle:** A substituição do `sleep(0.05)` por `select(..., 0.002)` dedicado, somada ao gatilho de captura antecipada (`input_wake_evt`) e ao struct fixo `InputEventPacket` de `24 bytes` com janelas anti-replay independentes (`ReplayWindow(512)`), reduz o tempo de recepção e injeção nativa (`SendInput` / `/dev/uinput` / `RemoteDesktop` / `XTest`) para `< 0,3 ms`.
2. **Elevação limpa sem quebra de sessão (`runas` UAC / `pkexec` Polkit):** Apenas o micro-processo `--elevated-input-broker` (sem GUI Qt, `< 15 MB` RAM) é elevado via UAC no Windows (*High Integrity Level*) ou Polkit no Linux (`/dev/uinput`). Ele autentica-se com o processo principal via desafio-resposta `HMAC-SHA256` usando arquivo de token `0600` descartável e encerra-se automaticamente caso o PID pai finalize.
3. **Execução remota estilo LTSP sem custo de fork:** Para automação e comandos remotos quando `allow_shell=True`, o `PtyShellManager` mantém uma sessão persistente de terminal (`pty` no Linux e PowerShell persistente no Windows) transportada pelo canal confiável `PT_WORKSPACE`.

### Consequências positivas

- O controle remoto opera nativamente em **LAN Direto**, **WAN STUN P2P** e **CGNAT Blind Relay** sem exigir abertura de portas TCP extras.
- A sonda `TupaInputLatencyProbe` e o painel **TUPÃ** medem continuamente o RTT de input (`WS_INPUT_ECHO`) e a métrica *Input-to-Photon* frente às metas de `15 ms` e `30 ms`.
- Os instaladores de Windows e Linux passam a compartilhar `src/ui/glass/installer_shell.py` com carregamento preguiçoso PEP 562, eliminando ~700 linhas duplicadas de QSS legado.

### Consequências negativas e mitigação

- Na tela segura de logon/UAC do Windows (`Winlogon Desktop`), o kernel NT exige um serviço `LocalSystem` assinado com `uiAccess=true`. **Mitigação adotada:** O `ElevatedInputBroker` em *High Integrity Level* cobre todas as janelas administrativas da sessão de usuário (Gerenciador de Tarefas, instaladores, terminais elevados) sem instalar serviços permanentes em segundo plano; caso o usuário cancele o prompt UAC/Polkit, o sistema opera de forma transparente em modo usuário padrão.
