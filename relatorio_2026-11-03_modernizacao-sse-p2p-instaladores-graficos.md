# Relatório de Desenvolvimento: Modernização P2P, Sinalização Push Real-Time SSE e Instaladores Gráficos (DA-V)
**Data:** 03 de Novembro de 2026  
**Autor:** Dante Ferraz (`danteferraz06@gmail.com`)  
**Repositório:** [DA-V__Distribuidor_Aamplo-Video](https://github.com/DanteFerraz/DA-V__Distribuidor_Aamplo-Video)  
**Linha Principal de Trabalho:** Sinalização Push Instantânea via Server-Sent Events (SSE), Ciclo de Vida On-Demand (Standby 0% GPU), Experiência em 1 Clique e Instaladores Gráficos (Windows e Linux)

---

## 1. Visão Geral da Sessão

Nesta sessão, refinamos a fundo o ciclo de vida dos processos e a experiência de conexão do **DA-V (Distribuidor Amplo de Vídeo)**, reduzindo a fricção de conexão para padrões de usabilidade instantânea (estilo AnyDesk e Parsec), sem abrir mão dos 3 pilares invioláveis de alta performance da engine (Separação de Processos Multiprocessing sem GIL, Janela De-jitter de 40 quadros / 350ms e Sockets Simétricos para perfuração de NAT).

Principais objetivos atingidos:
1. **Sinalização em Tempo Real via Server-Sent Events (SSE):** Substituição do atraso de polling HTTP (2 segundos) por um canal Push na VPS Oracle Cloud (`129.148.26.150`), entregando o evento de pareamento em **1 a 54 ms**.
2. **Ciclo de Vida On-Demand do Subprocesso GPU (*Lazy Spin-Up*):** O transmissor agora inicializa em modo Standby (consumo de **0,0% de GPU e CPU**), ativando o loop de captura e o encoder NVENC apenas quando um receptor realmente conecta.
3. **Conexão em 1 Clique e Links de Convite (`dav://`):**
   - Criação do botão *"Copiar Convite"* (`dav://connect/PIN`).
   - Auto-higienização de links colados no campo de PIN do receptor.
   - Conexão em 1 clique direto na lista de dispositivos locais (LAN).
   - Suporte ao protocolo `dav://` na inicialização do app (`scripts/gui_app.py`), abrindo e conectando automaticamente ao clicar no link.
4. **Instaladores Gráficos Multiplataforma (Windows e Linux):**
   - **Windows:** Script de Setup Inno (`installer/windows/dav_setup.iss`) e assistente gráfico visual (`scripts/dav_installer_win.py`), com atalhos de Desktop, liberação de firewall do Windows Defender e registro de `dav://` no Registro do Windows.
   - **Linux:** Lançador de Desktop XDG (`installer/linux/dav.desktop`), gerador de pacote portátil AppImage (`installer/linux/build_appimage.sh`) e assistente visual de instalação (`scripts/dav_installer_linux.py`) com detecção de X11/Wayland e drivers NVIDIA/VAAPI.

---

## 2. Detalhamento Técnico das Modificações

### A. Microserviço Rendezvous na Nuvem (`src/signaling/server/dav_rendezvous.py`)
- Adicionado `asyncio.Event()` (`pair_event`) ao `SessionRecord`.
- Implementado endpoint HTTP SSE: `GET /p2p/events?pin={PIN}&token={TOKEN}`.
- O microserviço envia cabeçalhos `text/event-stream` com `X-Accel-Buffering: no` e comentários periódicos de keepalive.
- No instante em que `POST /p2p/resolve` é chamado pelo receptor, o evento `event: paired` é despachado imediatamente para o transmissor.
- Atualizado e validado no Nginx da VPS Oracle Cloud (`129.148.26.150`), com `proxy_buffering off;` e `proxy_read_timeout 3600s;`.

### B. Cliente de Sinalização P2P (`src/discovery/p2p_channel.py`)
- Substituído o loop rígido de polling HTTP por um leitor de streaming SSE em thread dedicada.
- Em caso de desconexão ou rede restritiva que bloqueie HTTP streaming, a engine ativa automaticamente o fallback suave de polling HTTP a cada 1.5s.

### C. Subprocesso GPU e Motor de Transmissão (`scripts/dav_sender_worker.py` e `scripts/dav_client.py`)
- Implementado o evento de controle de estado `is_streaming_active`.
- Ao iniciar com o IP vazio (modo PIN universal), o worker entra em modo Standby: threads de captura (GDI/WGC/X11) e codificadores NVENC dormem, mantendo **0% de GPU**.
- Na chegada do pacote de perfuração `DAV_P2P_SYN` ou do comando IPC `START_STREAM` / `UPDATE_TARGET`, `is_streaming_active.set()` acorda instantaneamente a captura e o streaming.
- Adicionados métodos `pause_sender()` e `resume_sender()` em `DavCoreEngine`.

### D. Interface Gráfica e Usabilidade (`src/ui/`)
- **`src/ui/widgets/header.py`:** Adicionado botão *"Copiar Convite"*, gerando o link direto `dav://connect/{PIN}` com feedback visual *"Link Copiado! ✓"*.
- **`src/ui/views/viewer_view.py`:** O campo de PIN agora aceita links completos colados (extraindo o PIN automaticamente sem erros) e possui placeholder descritivo.
- **`src/ui/main_window.py`:** O clique no botão "Conectar" de um peer na aba LAN agora dispara automaticamente a conexão direta (*1-Click Connect*).
- **`scripts/gui_app.py`:** Tratamento de argumentos URI para abrir o DA-V e conectar instantaneamente via links `dav://connect/PIN`.

### E. Instaladores Gráficos Multiplataforma e Pré-Compilação Windows
- **`installer/windows/dav_setup.iss`:** Instalador profissional do Windows (Inno Setup) com suporte a tema moderno, atalhos, liberação de firewall e registro de protocolo URI.
- **`scripts/dav_installer_win.py`:** Assistente gráfico em PySide6 redesenhado do zero (arquitetura Dark Obsidian & Electric Cyan, WCAG 2.2 AAA compliant), eliminando o tema nativo Aero do QWizard. Conta com Stepper lateral de 4 etapas, card de telemetria NVIDIA NVENC em tempo real, seleção de regras de firewall UDP e geração de atalhos nativos do Windows (`.lnk`) via WScript.Shell (eliminando scripts `.vbs` obsoletos).
- **`installer/linux/dav.desktop` & `installer/linux/build_appimage.sh`:** Lançador XDG com ícone e script gerador de AppImage portátil autocontido.
- **`scripts/dav_installer_linux.py`:** Assistente gráfico em PySide6 para instalação em distros Linux com detecção de sessão X11/Wayland e GPU.
- **`dist_installer/DA-V_Instalador.exe`:** Executável binário standalone oficial otimizado (~45.9 MB) gerado com PyInstaller. Elimina dependências desnecessárias, carrega instantaneamente e possui interface escura profissional com alto contraste.
- **`instalar_windows.bat`:** Script facilitador para execução com um clique no Windows.

### F. Correção de Compilação C++23 no GCC 15 / Ubuntu 26.04
- **`CMakeLists.txt` & `cmake/dependencies.cmake`:** Adicionado `${CMAKE_CURRENT_SOURCE_DIR}` às diretivas `target_include_directories` dos alvos `dav_core` e `dav_shared`. No GCC 15 / Ninja, os arquivos de código-fonte que importam com prefixo `"src/..."` falhavam na varredura de dependências sem o diretório raiz nos caminhos de busca (`-I`).
- **`set(CMAKE_CXX_SCAN_FOR_MODULES OFF)`:** Desativada a varredura experimental de módulos C++20 do GCC 15, garantindo compilação ágil e limpa baseada em headers.
- **`build_linux.sh`:** Adicionado suporte ao parâmetro `--clean` para limpeza de cache anterior (`./build_linux.sh --clean`).

---

## 3. Validação e Testes de Benchmark

Foram executados testes automatizados locais e contra a infraestrutura em nuvem na Oracle Cloud:

```bash
py -m pytest tests/test_dav_rendezvous.py tests/test_p2p_e2e.py -v -s
```
**Resultados dos Testes:**
- `test_rendezvous`: **6 de 6 testes APROVADOS (100% OK)**
  - Healthcheck: `PASSED`
  - Register: `PASSED`
  - Resolve & Pairing: `PASSED`
  - Sender Polling: `PASSED`
  - STUN Reflexive Probe: `PASSED`
  - Real-time Push via SSE (`/p2p/events`): **PASSED em 1.61 ms** (local) e **54.05 ms** (via WAN real na Oracle VPS).
- `test_p2p_e2e`: **4 de 4 etapas APROVADAS (100% OK)**
  - Hole-Punching UDP bidirecional completado.
  - Frame de vídeo 60 FPS entregue com sucesso pelo túnel P2P.

---

## 4. Governança e Autoria

- **Autor:** `Dante Ferraz <danteferraz06@gmail.com>`
- **Padrão Semântico:** `feat(p2p): real-time SSE push signaling, on-demand GPU standby and graphical installers`
- **Artefato de Planejamento:** [`plano_atualizacao_dav_v3.md`](file:///C:/Users/Dante/.gemini/antigravity/brain/a245e8c8-6bf6-49e9-a8e2-81c640f1f192/plano_atualizacao_dav_v3.md)

