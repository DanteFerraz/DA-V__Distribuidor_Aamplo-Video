# Relatório Técnico de Sessão — 2026-11-06: Arquitetura P2P Nativa Single-Socket, Blind Encrypted UDP Relay, Documentação Arquitetural, Governança e Releases Windows/Linux (`v3.1.0`)

**Projeto:** DA-V (*Distribuidor Amplo de Vídeo*)  
**Autoria:** Dante Ferraz (MonoTech)  
**Data:** 06 de Novembro de 2026  
**Versão Consolidada:** `v3.1.1` (evoluída a partir de `v3.1.0`)  

---

## 1. Síntese Executiva da Jornada

Nesta sessão foi projetada, implementada, validada em rede real e publicada a **Alternativa B** da arquitetura P2P nativa do **DA-V**, eliminando integralmente as causas estruturais que impediam a transmissão remota entre Windows e Linux através de NAT doméstico e CGNAT Simétrico, sem recorrer a pilhas pesadas de terceiros (`aiortc`/`libjuice`/WebRTC).

Além da reconstrução do motor de transporte P2P, todo o repositório passou por **humanização técnica do código-fonte**, padronização de **governança e versionamento SemVer (`v3.1.0`)**, reescrita autoral dos manifestos `README.md` e `LEIA-ME_LINUX.md` com diagramas de arquitetura de software (Mermaid + especificação binária do protocolo de fio de 32 bytes), e implantação da esteira oficial de **builds multiplataforma Windows (`x64`) e Linux (`x86_64`)** tanto localmente quanto via GitHub Actions Releases.

---

## 2. Diagnóstico Raiz Resolvido e Arquitetura Implementada (Alternativa B)

### 2.1 Falhas Estruturais Eliminadas
1. **Assimetria de Porta STUN (Two-Socket Mismatch):** Anteriormente, a consulta STUN criava um socket UDP efêmero separado, descobria uma porta pública temporária e o fechava antes de o loop de mídia abrir outro socket. Em roteadores NAT *Port-Translating* e CGNAT, a porta anunciada no Rendezvous nunca coincidia com o descritor real de transmissão/recepção.
2. **Divergência de Motores entre Windows e Linux:** No Linux, a presença de `build/libdav_core.so` desviava a UI para uma via C-ABI sem suporte ao modo *Standby P2P* (`target_ip=""`) nem ao decodificador PyAV H.264/HEVC.
3. **Ausência de Fallback Real para CGNAT Simétrico:** Em operadoras de fibra/5G com alocação aleatória de porta por destino (NAT Simétrico), o *UDP Hole-Punching* direto é bloqueado pelo firewall de borda da operadora.
4. **Falta de Recuperação Instantânea de Keyframe (`PLI`):** Quando os primeiros fragmentos do IDR inicial se perdiam durante a abertura do furo NAT, o receptor aguardava o próximo ciclo completo de GOP para exibir imagem.

### 2.2 Solução de Engenharia Consolidada no `v3.1.0`
- **Single-Socket STUN (RFC 5389):** A função `discover_socket_endpoint(bound_sock)` executa sondas STUN com validação de Transaction ID de 96 bits diretamente sobre o **mesmo descritor de arquivo (`fd`)** que transmitirá ou receberá os pacotes de vídeo, preservando o mapeamento NAT externo e classificando automaticamente o roteador (`cone` vs. `symmetric`).
- **Hole-Punching Bidirecional Multicandidato Lock-Once:** Troca simultânea de vetores `Overlay/VPN` (`100.64.0.0/10`), `LAN` física (filtrando pontes virtuais Docker/WSL/VirtualBox/VMware) e `WAN` STUN (+ predição sequencial de portas adjacentes), com trava determinística no primeiro caminho autenticado.
- **Zero-Knowledge Blind Encrypted UDP Relay (`DAV_RLY1`):** Se o caminho direto não convergir em `850 ms` (cenário CGNAT Simétrico estrito), Transmissor e Receptor encapsulam os datagramas cifrados com o cabeçalho `DAV_RLY1` (17 bytes) rumo à porta `:8768/udp` do `dav_rendezvous.py`, que encaminha os pacotes em memória em $O(1)$ sem possuir a chave derivada do PIN (`ChaCha20-Poly1305` ponta a ponta intacto).
- **Picture Loss Indication (`DAV_P2P_PLI`) e Repetição SPS/PPS:** Solicitação automática de quadro IDR imediato (`pict_type = 1`) na abertura do túnel P2P ou após descartes consecutivos, combinada com `repeat-headers=1` e fallback transparente `NVENC` -> `libx264` (`zerolatency`).

---

## 3. Detalhamento de Alterações por Arquivo

### Motor de Rede P2P, Sinalização e Codec
- `src/discovery/p2p_channel.py`: Implementação de `discover_socket_endpoint()` (Single-Socket RFC 5389 STUN com dupla sonda para detecção de NAT Simétrico), `get_local_candidates()` com filtro anti-interfaces virtuais, `build_peer_candidates()`, `send_stun_keepalive()`, `wrap_relay_packet()` (`DAV_RLY1`) e cliente assíncrono `P2PChannelClient` humanizado.
- `src/signaling/server/dav_rendezvous.py`: Evolução para `v3.1.0` com `RendezvousUdpGateway` unificando servidor STUN reflexivo e **Blind Encrypted UDP Relay (`DAV_RLY1`)** na porta `:8768/udp`, suporte a múltiplos candidatos e telemetria de pacotes reencaminhados em `/health`.
- `src/codec/hybrid_codec.py`: Humanização completa, injeção de `repeat-headers=1` e `forced-idr=1` no `h264_nvenc`/`hevc_nvenc`, fallback automático em CPU para `libx264` (`ultrafast` + `zerolatency`) via PyAV, e método `request_keyframe()` compatível com PyAV 18+.
- `scripts/dav_sender_worker.py`: Nova máquina de estados `SenderTransportEndpoint` com pré-bind UDP, STUN no descritor real, eventos IPC (`ENDPOINT_READY`, `P2P_LOCKED`), rajadas `DAV_P2P_SYN`, resposta instantânea a `DAV_P2P_PLI`, keepalive STUN a cada `15 s` em *Standby*, comutação automática para `DAV_RLY1`, MTU seguro de `1320 bytes`, proteção `SIO_UDP_CONNRESET` no Windows e entrypoint `main()`.
- `scripts/dav_client.py`: Unificação do motor Python/SIMD + PyAV entre Windows e Linux (`DAV_USE_NATIVE_CORE=1` mantido como *opt-in* para C-ABI), adição de `wait_sender_endpoint()`, `pair_sender_peer()` e `prepare_receiver_socket()`, interceptação de controle P2P antes da checagem de cabeçalho de 32 bytes, validação estrita de protocolo (`version == 1`, `ssrc == 0xDA0001`), envio automático de `DAV_P2P_PLI` e fallback para Blind Relay.

### Interface Gráfica, Instaladores Autossuficientes e Núcleo C++23 (`v3.1.1`)
- `src/ui/main_window.py` e `scripts/gui_app.py`: Integração do Single-Socket STUN na abertura de sessões Transmissor e Receptor, correção do tratamento de deep-links `dav://connect/<PIN>` (`p2p_uri_mode=True` preservando `target_ip=""`), isolamento multiprocesso em binário congelado (`multiprocessing.freeze_support()` + importação diferida de Qt para partida rápida do `DAV-Sender-Engine`), modo `--self-check`, fallback inline de Firewall para executáveis congelados e ícone nativo.
- `src/ui/views/sender_view.py` e `src/ui/views/troubleshoot_view.py`: Humanização textual de rótulos de codec (agnósticos de modelo fixo de GPU), atualização do card de fragmentação MTU (`1320 bytes`), alinhamento das faixas de firewall e diretório de logs em `%LOCALAPPDATA%\DA-V\logs` / `~/.local/state/dav/logs` quando congelado.
- `scripts/dav_installer_win.py`, `scripts/dav_installer_linux.py`, `installer/dav_icon.ico`, `installer/dav_icon.png` e `scripts/setup_firewall.ps1`: Evolução dos instaladores para **instaladores autossuficientes com payload compilado embutido** (`dav_app_payload.zip` no Windows extraindo `DA-V.exe` + `_internal` em `%LOCALAPPDATA%\Programs\DA-V`; `dav_app_payload_linux.tar.gz` no Linux extraindo `DA-V` ELF em `~/.local/share/dav`), criação de atalhos funcionais tanto na Área de Trabalho quanto no Menu Iniciar via `WScript.Shell.SpecialFolders` (com ícone `dav_icon.ico`), associação `dav://` direta ao binário instalado e unificação das regras de firewall (`UDP 9000-9020, 19000-19010, 9005`).
- `CMakeLists.txt`, `include/dav/dav_api.h`, `src/core/dav_api.cpp`, `src/capture/windows/dxgi_capturer.cpp`, `src/codec/sw_encoder.cpp`, `src/qos/qos_engine.cpp`, `launch_dav.sh`: Atualização de versão para `3.1.0`, separação de `ARCHIVE_OUTPUT_NAME` (`dav_core_static`) e macro `DAV_STATIC_LIB` para linkagem limpa no MSVC C++23 e GCC 14/15, e inclusão explícita de `<cstring>` e `<algorithm>`.

### Documentação Arquitetural, Testes, Governança e CI/CD
- `README.md` e `LEIA-ME_LINUX.md`: Reescritos com prosa técnica autoral, diagramas Mermaid da arquitetura multiprocesso e do fluxo Single-Socket STUN / Blind Relay (com setas `->>` / `-->>` e rótulos pipe `|...|` validados contra o parser oficial MermaidJS e âncoras de navegação alinhadas ao GitHub), especificação binária do cabeçalho de 32 bytes, benchmarks reais e guia operacional Windows/Linux/Cloud.
- `tests/test_p2p_e2e.py`, `tests/test_codec_encoder.py`, `tests/test_packetizer_crypto.py`, `tests/test_qos_engine.py`: Suíte E2E cobrindo preservação do descritor STUN, transmissão/decodificação H.264 via P2P direto e simulação estrita de CGNAT Simétrico com fallback `DAV_RLY1`, além de limpeza integral de avisos do `pytest`.
- `VERSION`, `CHANGELOG.md`, `.gitattributes`, `deploy/dav-rendezvous.service`, `.github/workflows/release.yml`: Governança SemVer `3.1.0`, normalização `LF` para scripts POSIX, unidade `systemd` oficial para a VPS de sinalização/relay e pipeline multiplataforma GitHub Actions compilando e publicando builds nativos Windows (`x64`) e Linux (`x86_64`) automaticamente no GitHub Releases.

---

## 4. Validação Experimental e Resultados Obtidos

1. **Suíte Automatizada Unitária e E2E (`pytest tests/ -v`):**
   - `7 passed in 5.73s` com **0 warnings** (`test_codec_encoder`, `test_dav_rendezvous`, `test_single_socket_stun_preserves_descriptor`, `test_p2p_direct_engine_h264_e2e`, `test_p2p_symmetric_cgnat_blind_relay_fallback`, `test_packetizer_crypto`, `test_qos_engine`).
2. **Prova Real em Nuvem + Hardware (`Oracle Cloud 129.148.26.150:80` + Google STUN + WGC + NVENC):**
   - Descoberta Single-Socket STUN mapeando portas externas reais (`Cone NAT`), pareamento via PIN na nuvem Oracle e decodificação contínua de **42 quadros reais 720p H.264 NVENC em `0.70 s` (`60.0 FPS`)**.
3. **Builds Gerados e Pipeline de Release:**
   - Pacote local Windows (`DA-V_Instalador_Windows_x64.exe` + `DA-V_v3.1.0_Windows_x64.zip`) e pacote Linux (`DA-V_v3.1.0_Linux_x86_64.tar.gz` com scripts `LF` e permissões `0755`) gerados em `dist_installer/`, acompanhados do workflow `.github/workflows/release.yml` disparado pela tag `v3.1.0`.

