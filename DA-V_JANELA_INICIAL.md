# Plano de Implementação: GUI Desktop DA-V (Distribuidor Aamplo - Video)

## Visão Geral do Projeto
Implementação de uma interface gráfica desktop moderna (Dark Theme com estética AnyDesk/Parsec) utilizando **PySide6 (Qt for Python oficial sob licença LGPL v3)** integrada ao motor de rede e transporte de alto desempenho do **DA-V**.

A escolha de **PySide6** garante total segurança jurídica para criação de produtos comerciais gratuitos ou pagos de **código fechado (closed-source)** sem necessidade de pagamento de royalties ou licenças comerciais proprietárias.

A aplicação fornecerá:
1. **Descoberta na Rede Local (LAN Beacon):** Anúncio automático da presença do nó na rede local via datagramas leves de broadcast (`UDP:9005`), permitindo detecção instantânea de dispositivos vizinhos.
2. **Autenticação Segura (PIN / PSK Token):** Troca autenticada de vídeo com criptografia E2E `ChaCha20-Poly1305`, permitindo conexão segura apenas com PIN temporário gerado ou chave mestra.
3. **Modo Transmissor (Sender / Screen Sharing):** Captura em tempo real da tela (via Win32/DXGI), codificação H.264, fragmentação MTU e transmissão para o cliente autorizado.
4. **Modo Receptor (Receiver / Live Display):** Recepção de datagramas, decriptação, reconstrução de quadros no `FrameAssembler` e renderização de vídeo fluida a 60 FPS via `QPainter`/`QImage` com HUD de telemetria (FPS, Latência, Bitrate e QoS).

---

## Arquitetura da Solução

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                      DA-V GUI APPLICATION (PySide6 / LGPLv3)               │
│                                                                             │
│  ┌─────────────────────────┐  ┌──────────────────────────────────────────┐  │
│  │     Side Navigation     │  │            Main Workspace Area           │  │
│  │ ───────────────         │  │ ┌──────────────────────────────────────┐ │  │
│  │ [●] Meus Dados / Status │  │ │ Tab 1: Compartilhar Tela (Sender)    │ │  │
│  │ [▶] Assistir (Receiver) │  │ │ Tab 2: Conectar / Assistir (Viewer)  │ │  │
│  │ [☊] Dispositivos na LAN │  │ │ Tab 3: Telemetria & QoS em Tempo Real│ │  │
│  │ [⚙] Configurações       │  │ └──────────────────────────────────────┘ │  │
│  └─────────────────────────┘  └──────────────────────────────────────────┘  │
│                                                                             │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │                         Core Service Worker                           │  │
│  │  - Beacon UDP (Descoberta LAN na porta 9005)                           │  │
│  │  - Engine Sender (Captura de Tela + H.264 Encoder + Wire Packets)     │  │
│  │  - Engine Receiver (Socket UDP + ChaCha20 + Frame Assembler + Render)  │  │
│  │  - Auth Guard (Validação de PIN de 6 dígitos e Tag MAC Poly1305)       │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Componentes Propostos

### 1. [NEW] `scripts/gui_app.py`
Aplicação principal em **PySide6** com:
- **Painel de Identidade Local:** Exibe o IP da máquina, porta de escuta e um **PIN de Acesso de 6 dígitos** randômico (ex: `842 190`).
- **Lista de Dispositivos Conectáveis (LAN Discovery):** Detecta computadores na mesma rede rodando o DA-V e oferece o botão *"Solicitar Conexão"*.
- **Visualizador de Vídeo Integrado (`VideoCanvasWidget`):** Renderiza o fluxo de vídeo recebido com alta performance via `QPainter`/`QImage` em thread dedicada com suporte a tela cheia.
- **HUD de Métricas em Tempo Real:** Overlay visual exibindo FPS instantâneo, latência (ms), taxa de transferência (Mbps), quadros perdidos e status de criptografia.
- **Log Console Integrado:** Terminal embutido na GUI com filtros de nível de log (INFO, WARN, ERROR, DEBUG) para troubleshooting imediato.

### 2. [NEW] `src/discovery/lan_beacon.py`
Módulo de presença e descoberta de rede local:
- Transmissão periódica (a cada 2s) de beacons UDP em broadcast (`255.255.255.255:9005`).
- Escuta assíncrona de novos nós na LAN e manutenção da tabela de peers ativos com heartbeat e timeout de 6s.

### 3. [NEW] `src/capture/screen_grabber.py`
Capturador nativo de alta eficiência para Windows (via GDI/Win32 `ctypes` com buffer de memória contíguo para alimentar o encoder H.264 com baixíssimo consumo de CPU).

### 4. [NEW] `scripts/qt_compat.py`
Camada de abstração que prioriza `PySide6` e permite fallback transparente, garantindo portabilidade total.

---

## Fluxo de Autenticação e Conexão

1. **Início da Sessão:** Ao abrir o app, a máquina A gera um PIN de acesso de 6 dígitos (ex: `593-104`).
2. **Descoberta:** A máquina B vê o nó *"PC-A (192.168.1.50)"* na lista de dispositivos locais.
3. **Pedido de Conexão:** A máquina B digita o PIN do PC-A e clica em **Conectar**.
4. **Handshake e Chave Derivada:** Uma chave efêmera de 256 bits é gerada com o PIN e os pacotes de vídeo passam a ser criptografados com `ChaCha20-Poly1305`.
5. **Rejeição Automática:** Pacotes com MAC tag incorreta ou sem PIN válido são sumariamente descartados no kernel/socket sem processamento de vídeo.

---

## Verificação e Testes

### Teste 1: Execução e Estética da Interface
```powershell
py -3 scripts/gui_app.py
```
- Validar abertura imediata da janela, renderização da paleta Dark Mode e carregamento das interfaces de rede.

### Teste 2: Descoberta de Peers
- Abrir duas instâncias (ou em duas máquinas na LAN) e verificar o aparecimento mútuo na lista de dispositivos.

### Teste 3: Transmissão e Visualização de Tela
- Iniciar compartilhamento na máquina A e assistir na máquina B digitando o PIN.
- Validar renderização do vídeo a 60 FPS com latência LAN < 5ms.
