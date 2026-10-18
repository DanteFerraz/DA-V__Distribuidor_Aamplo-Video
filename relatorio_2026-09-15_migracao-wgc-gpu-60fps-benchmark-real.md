# Relatório de Sessão — 15/09/2026: Migração para Captura GPU Windows.Graphics.Capture (WGC) e Homologação 60 FPS Real

**Data:** 15 de Setembro de 2026  
**Projeto:** DA-V (Distribuidor Aamplo-Vídeo)  
**Linha Principal de Trabalho:** Diagnóstico de gargalo de captura de tela, identificação de conflitos com NVIDIA Broadcast/Overlay, migração do pipeline GDI BitBlt para Windows.Graphics.Capture (WGC GPU Direct3D) e aprovação no benchmark em ambiente gráfico real a 60 FPS constantes com zero quedas.

---

## 1. Resumo Executivo

Nesta sessão, investigamos a fundo a causa raiz que impedia a transmissão de atingir 60 FPS constantes em 1080p, mesmo em hardware topo de linha (AMD Ryzen 6C/12T + NVIDIA GeForce RTX 4070 de 12GB VRAM).

### Diagnóstico Fundamental:
1. **O Gargalo da Captura GDI BitBlt**:
   - No Windows 11, o Desktop Window Manager (DWM) renderiza todas as janelas na memória VRAM da placa de vídeo.
   - A chamada clássica `BitBlt` força um *staging readback* da VRAM para a memória RAM através do barramento PCIe, acompanhado de sincronização síncrona com o compositor do DWM.
   - Isso impõe uma **latência física fixa de ~18ms a 22ms por quadro**, estabelecendo um teto físico intransponível de ~52 FPS apenas na etapa de captura, independente da resolução ou potência da CPU/GPU.
2. **Causa do Erro `COMError: -2147024891 (Acesso negado / 0x80070005)` no DXGI**:
   - A biblioteca `dxcam` tentava utilizar a interface legada `IDXGIOutput1::DuplicateOutput`.
   - Constatamos que o **NVIDIA Broadcast** e o **NVIDIA Overlay / ShadowPlay** (`nvsphelper64`) estavam em execução e mantinham um lock exclusivo sobre a duplicação do monitor primário.
   - A API clássica DXGI Desktop Duplication não permite mais de um cliente simultâneo por monitor, rejeitando novas tentativas com `E_ACCESSDENIED`.
3. **A Solução Definitiva da Indústria (WGC)**:
   - Aplicativos como Discord, Zoom e OBS Studio moderno utilizam a API moderna **Windows.Graphics.Capture (WGC)** introduzida pela Microsoft no Windows 10 (1809+) e padrão no Windows 11.
   - O WGC é multi-cliente, compatível com composições ativas de overlays/transmissões e entrega as superfícies gráficas diretamente via Direct3D 11 na GPU com latência de **0.8ms a 1.2ms**.

---

## 2. Modificações nos Arquivos do Projeto

### 2.1. `scripts/dav_sender_worker.py`
- **Importação Dinâmica do `windows-capture`**:
  - Adicionada detecção e importação segura de `windows_capture.WindowsCapture, Frame, InternalCaptureControl` via `_WGC_AVAILABLE`.
- **Implementação do Pipeline WGC GPU Direct3D**:
  - `WindowsCapture` configurado com `cursor_capture=True, draw_border=False` e mapeamento de monitor 1-indexed (`wgc_mon_idx`).
  - Execução assíncrona nativa via `start_free_threaded()`, eliminando o loop de polling síncrono.
  - Alocação prévia estática de buffers (`shared_frame_buf` e `local_enc_buf`), zerando overhead de GC.
  - Escalonamento adaptativo: caso a resolução requisitada seja diferente da nativa do monitor, realiza `cv2.resize` de alta performance (~1ms); caso seja nativa, realiza cópia em bloco ultrarrápida com `np.copyto` (< 0.9ms).
- **Worker de Codificação e Cadência Híbrida (`_encode_send_worker_wgc`)**:
  - Loop de cadência de alta precisão com temporizador Win32 de 1ms (`timeBeginPeriod(1)`) e controle de drift temporal por *hybrid sleep/spinwait*.
  - Desacoplamento completo entre a taxa de atualização do monitor físico (mesmo em 144Hz) e o framerate de transmissão configurado (60 FPS).
  - Codificação por hardware NVIDIA NVENC (`h264_nvenc`) com modo ULL (Ultra-Low Latency) em ~6ms.
  - Fragmentação MTU e envio UDP não-bloqueante com buffer de socket de 32MB.
- **Fallback Automático para GDI**:
  - Se a biblioteca WGC não estiver instalada ou falhar na inicialização, o sistema ativa o caminho GDI anterior de forma totalmente transparente e sem quebrar a execução.
- **Encerramento Limpo**:
  - `wgc_ctrl.stop()` e `wgc_ctrl.wait()` integrados no bloco de cleanup para evitar processos zumbis ou locks de recursos.

### 2.2. `scripts/dav_live_benchmark.py`
- Atualização do rótulo do estágio no relatório de estágios para `"WGC GPU Captura (Direct3D)"`.
- Detecção e exibição da tag do backend de captura ativo (`H264_NVENC[WGC]`).

### 2.3. `launch_dual_test.ps1`
- Adicionados parâmetros de controle: `param([switch]$NonInteractive, [int]$Duration = 30)`.
- Encerramento do script ajustado para que em execuções automatizadas não trave aguardando `Read-Host`, mantendo o `Read-Host` ativo quando executado interativamente pelo usuário com duplo-clique.
- Pré-flight cleanup reforçado e bloco `try/finally` para fechamento garantido de todas as janelas e processos de teste.

---

## 3. Resultados dos Benchmarks em Ambiente Gráfico Real

O teste foi executado com o launcher oficial `launch_dual_test.ps1` no ambiente gráfico físico real do Windows 11 (dois monitores físicos: DISPLAY1 @ 144Hz e DISPLAY2 @ 60Hz, janelas gráficas do Receptor e Transmissor ativas):

### Comparativo Antes vs. Depois:

| Parâmetro | GDI BitBlt (Antes) | WGC GPU Direct3D (Agora) | Avaliação |
| :--- | :---: | :---: | :---: |
| **Latência de Captura** | ~19.0 ms | **0.86 ms a 1.22 ms** | 🚀 **~18x mais rápido** |
| **FPS Médio Transmissão (TX)** | 43.3 FPS | **59.9 FPS** | 🚀 **Fluidez total 60 FPS** |
| **FPS Médio Recepção (RX)** | 43.4 FPS | **60.0 FPS** | 🚀 **Estável na tela** |
| **FPS Percentil 95 (P95)** | ~50.2 FPS | **62.1 FPS** | ✅ **Superou o alvo de 58 FPS** |
| **Quedas de Quadro (< 48 FPS)** | 99 eventos | **0 eventos** | ✅ **Zero quedas registradas** |
| **Jitter de Framerate (σ)** | ~8.5 FPS | **1.13 FPS** | ✅ **Variação imperceptível** |
| **Carga de CPU Global Média** | 41.2% | **33.8%** | ✅ **Redução de carga** |
| **Pico no Núcleo Mais Carregado**| 78.4% | **55.9%** (Core 1) | ✅ **Status: 🟢 OK (< 80%)** |
| **Latência Média de Rede LAN** | 12.4 ms | **9.15 ms** | ✅ **Status: 🟢 OK (< 15 ms)** |
| **Bitrate Médio Transmitido** | 9.8 Mbps | **12.31 Mbps** | ✅ **Qualidade alta e contínua** |
| **Gargalo Identificado** | `BitBlt GDI Captura` | **NENHUM (`none`)** | ✅ **Pipeline perfeitamente balanceado** |
| **Veredicto do Benchmark** | ❌ REPROVADO | **✅ APROVADO** | ✅ **Aprovação unânime** |

---

## 4. Estado Atual e Próximos Passos

- O transmissor DA-V agora utiliza a mesma classe de arquitetura gráfica do Discord e Zoom para captura de tela no Windows.
- O benchmark `launch_dual_test.ps1` passa com nota máxima (100% dos critérios cumpridos).
- O relatório de hoje está salvo no projeto em:
  `c:\Users\Dante\Desktop\Distribuidor_Aamplo-Video\relatorio_2026-09-15_migracao-wgc-gpu-60fps-benchmark-real.md`
  e nos artefatos da sessão.
