# Relatório de Sessão — 2026-09-15
## Trabalho Realizado: Correção de Decodificação de Vídeo e Estabilização do Benchmark Real (DA-V)

---

## Resumo Executivo

Durante a sessão, foi identificado, diagnosticado e corrigido o problema crítico que impedia a exibição visual do vídeo no receptor do DA-V (canvas permanecia preto apesar de telemetria indicando transmissão ativa). Também foi corrigido o script de lançamento do benchmark (`launch_dual_test.ps1`) e implementado um mecanismo de limpeza de processos para estabilizar os testes.

---

## Problema 1: Tela Preta no Receptor (Vídeo Não Decodificado)

### Sintoma Observado
- O HUD de telemetria do receptor exibia FPS altos (~58-60) e bitrate correto (~11-12 Mbps)
- O canvas do receptor permanecia 100% preto — nenhum pixel visível
- O benchmark reportava quadros recebidos mas todos eram frame preto

### Análise de Causa Raiz

**Causa: `BitBlt` GDI em subprocesso spawned sem associação ao desktop interativo**

O `_sender_subprocess` é instanciado via `multiprocessing.get_context("spawn")`. No Windows, processos filhos gerados por `spawn` não herdam automaticamente o desktop interativo da sessão (`WinSta0\Default`).

Quando a thread de captura (`_capture_worker`) chamava `gdi32.BitBlt(...)`:
- A API retornava `ok=1` (sem erro aparente)
- Porém o buffer DIBSection permanecia preenchido com zeros (`non_zeros=0`)
- O NVENC codificava frames 100% pretos (~90 bytes/frame)
- O receptor decodificava e renderizava frames pretos em alta velocidade

### Evidências Empíricas

| Condição | BitBlt ok | Bytes nao-zero |
|:---------|:----------|:---------------|
| Subprocesso SEM `SetThreadDesktop` | 1 | 0 (100% preto) |
| Subprocesso COM `SetThreadDesktop` | 1 | 7.614.655 (pixels reais) |
| Thread de captura SEM `SetThreadDesktop` | 1 | 0 (100% preto) |
| Thread de captura COM `SetThreadDesktop` | 1 | 7.988.608 (pixels reais) |

O mesmo comportamento se repetia para a thread de captura dentro do subprocesso — cada thread OS requer vinculação independente ao desktop.

### Correção Aplicada — `scripts/dav_sender_worker.py`

**1. Em `_sender_subprocess` (entry point do processo):**
```python
_u32_sub = ctypes.windll.user32
_u32_sub.SetProcessDPIAware()
_h_desk_sub = _u32_sub.OpenDesktopW("Default", 0, False, 0x01FF)
if _h_desk_sub:
    _u32_sub.SetThreadDesktop(_h_desk_sub)
    print("[DA-V Sender] Subprocess attached to WinSta0\\Default (desktop handle valid).")
```

**2. Em `_capture_worker` (thread de captura, antes de qualquer BitBlt):**
```python
if sys.platform == "win32":
    try:
        _u32_cap = ctypes.windll.user32
        _h_desk_cap = _u32_cap.OpenDesktopW("Default", 0, False, 0x01FF)
        if _h_desk_cap:
            _u32_cap.SetThreadDesktop(_h_desk_cap)
    except Exception:
        pass
```

### Resultado Pos-Correcao (Validacao Automatizada)

```
Frame  BitBlt   Tempo(ms)  Bytes nao-zero    Pixel[540,960]
------------------------------------------------------------
    1      OK      22.316       7,622,364  [132, 151, 163, 255]
    2      OK      20.817       7,868,207  [23, 18, 17, 255]
    3      OK      14.593       7,865,726  [84, 84, 84, 255]
    4      OK      19.171       7,865,726  [84, 84, 84, 255]
    5      OK      16.838       7,865,665  [113, 113, 113, 255]

[OK] CORRECAO VALIDADA: Captura GDI retorna pixels reais no subprocesso spawned!
```

**Todos os 5 frames capturados contem mais de 7,6 milhoes de bytes nao-zero.**

---

## Problema 2: Erro de Sintaxe no `launch_dual_test.ps1` (Linha 2)

### Sintoma
```
System.Management.Automation.Internal.Host.InternalHost.UI.RawUI.WindowTitle :
O termo '...' nao e reconhecido como nome de um cmdlet
```

### Causa
A linha 2 do script tentava usar o tipo .NET completo como comando direto.

### Correcao
```powershell
$host.UI.RawUI.WindowTitle = 'DA-V Live Benchmark Launcher'
```

---

## Problema 3: 11 Quedas de Frames (Processos Zumbis)

### Causa
Ao interromper o script com Ctrl+C, os processos `gui_app.py` lançados via `Start-Process` continuavam em execução, retendo as portas UDP 9000 e 9002. Ao relançar, ocorria concorrência de transmissor/receptor e disputas pelo encoder NVENC.

### Correcoes no `launch_dual_test.ps1`

1. **Pre-flight cleanup**: Encerra processos Python anteriores antes de abrir as janelas
2. **Captura de handles com `-PassThru`**: Obtém PID das janelas abertas
3. **Bloco `try/finally`**: Garante limpeza na conclusão normal E em caso de Ctrl+C

---

## Arquivos Modificados

| Arquivo | Tipo | Mudanca |
|:--------|:-----|:--------|
| `scripts/dav_sender_worker.py` | MODIFY | `OpenDesktopW` + `SetThreadDesktop` em `_sender_subprocess` e `_capture_worker` |
| `launch_dual_test.ps1` | MODIFY | Correcao linha 2, pre-flight cleanup, try/finally para cleanup garantido |

---

## Status das Correcoes

| Item | Status |
|:-----|:-------|
| Causa raiz da tela preta identificada | Confirmada |
| `SetThreadDesktop` em processo spawned | Implementado |
| `SetThreadDesktop` em thread de captura | Implementado |
| Validacao automatizada (5 frames reais) | Aprovada |
| Sintaxe PowerShell linha 2 corrigida | Corrigida |
| Pre-flight cleanup de processos | Implementado |
| Cleanup garantido (try/finally) | Implementado |
| Validacao no ambiente grafico real | Aguardando execucao manual pelo usuario |

---

## Proximo Passo

O usuario deve executar:
```powershell
cd C:\Users\Dante\Desktop\Distribuidor_Aamplo-Video
.\launch_dual_test.ps1
```

E verificar visualmente se:
1. A janela do **Receptor** exibe o conteudo real do monitor no canvas (sem tela preta)
2. O script abre sem erro na linha 2
3. O benchmark de 30s conclui com >= 58 FPS e 0 quedas

---

*Sessao: 2026-09-15 | Trabalho principal: Correcao de decodificacao de video e estabilizacao do benchmark real DA-V*
