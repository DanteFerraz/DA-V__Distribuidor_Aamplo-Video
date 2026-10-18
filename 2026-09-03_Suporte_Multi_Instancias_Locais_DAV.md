# Relatório de Sessão — 03 de Setembro de 2026
## Eliminação do Overshoot de Sleep no Windows e Pareamento Automático de PINs a 60.1 FPS no DA-V

> **Data:** 03 de Setembro de 2026  
> **Projeto:** DA-V (Distribuidor Aamplo · Video Distribution Hub)  
> **Versão:** 2.6.2-ZeroOvershoot-60FPS-Homologated  
> **Ambiente:** Windows 11 Pro (x64) · AMD Ryzen (12 Threads) · GPU NVIDIA GeForce RTX 4070 (12 GB GDDR6X) · Dual Monitor (1920x1080) · Python 3.13.2 · PySide6 · OpenGL Hardware · TUPÃ Telemetry  
> **Status:** 🏆 **CADÊNCIA PRECISA (ZERO SLEEP OVERSHOOT) IMPLEMENTADA — 275/275 QUADROS TRANSMITIDOS E RECEBIDOS A 60.1 FPS**  

---

### 1. Diagnóstico do Gargalo de Cadência no Windows

1. **Por que o Transmissor caía para 36-39 FPS:**
   - No Windows, chamadas de `time.sleep(val)` com `val < 4ms` sofrem arredondamento para a granularidade do relógio do sistema (~15.6ms), gerando *overshoot* e limitando o loop a ~36 FPS.
   - Refatoramos o loop em [`scripts/dav_sender_worker.py`](file:///c:/Users/Dante/Desktop/Distribuidor_Aamplo-Video/scripts/dav_sender_worker.py): apenas intervalos residuais `rem > 6ms` utilizam `time.sleep(rem - 5ms)`, enquanto os últimos milissegundos são resolvidos via *spinwait* de alta precisão em `time.perf_counter()`.
2. **Pareamento Automático de PINs:**
   - Em [`scripts/gui_app.py`](file:///c:/Users/Dante/Desktop/Distribuidor_Aamplo-Video/scripts/gui_app.py), instâncias iniciadas com `--auto-recv` ou `--auto-send` agora adotam automaticamente a credencial compartilhada `777-888` e configuram os IPs de loopback (`127.0.0.1`), dispensando qualquer digitação manual.

---

### 2. Resultados dos Testes de Homologação em Tempo Real

```text
[DA-V Sender] Capturing Monitor 2 (1920x1080 at 1920,0) -> Target 1920x1080 @ 60fps [h264_nvenc]
[HybridEncoder] NVIDIA NVENC (h264_nvenc) hardware encoder ACTIVE on RTX 4070!
Live Transmission Test: 60 FPS NVENC RTX 4070 -> UDP 9002...
  [TX Telemetry] Frames Sent:   31 | TX FPS:  61.2 | RX Received:   31 | Bitrate:  7.79 Mbps
  [TX Telemetry] Frames Sent:   62 | TX FPS:  60.1 | RX Received:   62 | Bitrate: 12.47 Mbps
  [TX Telemetry] Frames Sent:   92 | TX FPS:  59.9 | RX Received:   92 | Bitrate: 12.42 Mbps
  [TX Telemetry] Frames Sent:  123 | TX FPS:  60.1 | RX Received:  123 | Bitrate: 12.46 Mbps
  [TX Telemetry] Frames Sent:  153 | TX FPS:  60.0 | RX Received:  153 | Bitrate: 12.44 Mbps
  [TX Telemetry] Frames Sent:  183 | TX FPS:  60.0 | RX Received:  183 | Bitrate: 12.44 Mbps
  [TX Telemetry] Frames Sent:  213 | TX FPS:  60.0 | RX Received:  213 | Bitrate: 12.44 Mbps
  [TX Telemetry] Frames Sent:  244 | TX FPS:  60.0 | RX Received:  244 | Bitrate: 12.43 Mbps
  [TX Telemetry] Frames Sent:  275 | TX FPS:  60.1 | RX Received:  275 | Bitrate: 12.46 Mbps
Final Result: Sent 275 frames | Received 275 frames!

Taxa de Transmissão (TX) : 60.1 FPS cravados ✅
Taxa de Recepção (RX)    : 275 quadros entregues de 275 enviados (100% de entrega) ✅
Taxa de Descartes        : 0 quadros perdidos ✅
```

---

### 3. Arquivos Atualizados

- **[`scripts/dav_sender_worker.py`](file:///c:/Users/Dante/Desktop/Distribuidor_Aamplo-Video/scripts/dav_sender_worker.py):**  
  Loop de cadência de alta precisão sem *overshoot* de sleep.
- **[`scripts/gui_app.py`](file:///c:/Users/Dante/Desktop/Distribuidor_Aamplo-Video/scripts/gui_app.py):**  
  Pareamento automático de PIN e portas em modo automatizado.
- **[`launch_dual_test.bat`](file:///c:/Users/Dante/Desktop/Distribuidor_Aamplo-Video/launch_dual_test.bat):**  
  Inicializador direto com PIN pareado `777-888`.
