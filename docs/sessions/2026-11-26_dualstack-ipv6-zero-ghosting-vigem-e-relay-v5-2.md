---
doc_type: session-report
diataxis_quadrant: explanation
project: "DA-V (Distribuidor Amplo de Vídeo)"
session_date: 2026-11-26
main_line: "Diagnóstico forense v5.1.0, suporte Dual-Stack IPv6, pipeline Zero-Ghosting, Relay híbrido e ViGEm nativo (v5.2.0)"
author: "Dante Ferraz"
status: "verified"
related_adrs:
  - "docs/decisions/0004-arquitetura-dualstack-ipv6-zero-ghosting-vigem-e-relay-hibrido.md"
related_commits: []
---

# Relatório de sessão — 2026-11-26: Diagnóstico v5.1.0, Dual-Stack IPv6, Zero-Ghosting e ViGEm pré-compilado (v5.2.0)

## Resumo executivo

A sessão auditou a diff da release `v5.1.0` (`d9c99ad..f53fc7b`), os três pacotes de logs de campo e o vídeo gravado em operação real, identificando a causa raiz das falhas em rede institucional (NAT simétrico + loop de sinalização de `1,2 s` + porta UDP `8768` inacessível na VPS), dos artefatos de quadros gravados em H.264 (Mega-IDRs sem FEC, pico de `99 FPS` induzido por `GAMEPAD_STATE`, descarte de P-frames no `DecodeWorker` e escape de `450 ms` no `ReceiverWorker`), da exclusão de `vgamepad` no CI Windows e da incompatibilidade com hosts IPv6-Only. Todas as correções foram implementadas e elevadas para a versão `5.2.0` com 100% de aprovação na suíte automatizada (`108 passed`, `test_p2p_e2e.py` e `DAV_SELF_CHECK_OK`).

## Requisitos e objetivos endereçados

- **OBJ-01:** Revalidar a atualização `v5.1.0` e eliminar o travamento superior a duas horas no CI Windows versionando `ViGEmClient.dll` x64 e `ViGEmBusSetup_x64.msi` pré-compilados no Git sob adaptador `ctypes` nativo.
- **OBJ-02:** Corrigir as falhas de conexão em redes institucionais sob NAT simétrico eliminando o loop de re-pareamento de `1,2 s`, blindando sessões PAKE ativas contra `SYN2` espúrio e introduzindo Blind Relay híbrido (UDP `8768` + HTTP-Stream/WebSocket sobre porta `80/443`).
- **OBJ-03:** Erradicar a corrupção visual inter-quadro H.264 ("quadros gravados na tela") com Block-RS FEC (`algo=2`) para Mega-IDRs (`> 200` fragmentos), trava estrita de cadência TX (`<= FPS`), `WsMsgType.PLI_REQ = 0x0E`, `VideoDecoder.flush()`/`is_corrupt` e Gate Zero-Ghosting ponta a ponta em `ReceiverWorker` e `DecodeWorker`.
- **OBJ-04:** Implementar suporte completo a hosts estritamente IPv6-Only e redes Dual-Stack (`AF_INET6` com `IPV6_V6ONLY=0`, STUN RFC 5389 IPv6 `0x02`, síntese NAT64 RFC 7050, parser/UI para `dav://[ipv6]:porta/PIN`, MTU seguro `1180 B` e Blind Relay Cross-Family `IPv4 <-> IPv6`).

## Alterações realizadas por artefato

| Arquivo | Ação | Camada / Bloco C4 | Descrição objetiva da alteração |
| :--- | :--- | :--- | :--- |
| `third_party/vigem/x64/ViGEmClient.dll` | Criado | Third-Party / Windows Input | Biblioteca x64 pré-compilada (MIT, 130 KB) versionada no Git para zerar tempo de build no CI. |
| `third_party/vigem/install/x64/ViGEmBusSetup_x64.msi` | Criado | Third-Party / Windows Input | Instalador offline (856 KB) do driver ViGEmBus para instalação assistida em 1 clique via UAC. |
| `src/dav/modules/universal_input/vigem_ctypes.py` | Criado | Fatia `universal_input` | Adaptador puro em `ctypes` com structs `c_ubyte`, conexão `VBus` lazy, `WINFUNCTYPE` retido contra GC e desplugue determinístico. |
| `src/dav/modules/universal_input/gamepad_virtual_hub.py` | Modificado | Fatia `universal_input` | Prioriza `vigem_ctypes` nativo, atualiza diagnóstico de driver e usa MSI offline antes de `winget`. |
| `.gitignore`, `.gitattributes`, `requirements.txt`, `.github/workflows/release.yml`, `scripts/build_windows.ps1` | Modificado | Build / CI & Compliance | Exceção `!third_party/vigem/**`, atributos binários, remoção de `vgamepad` do pip, restauração de `pip install -r requirements.txt` e empacotamento PyInstaller de `ViGEmClient.dll` + MSI. |
| `LICENSES/MIT-ViGEmClient.txt`, `THIRD_PARTY_LICENSES.md` | Criado / Modificado | Governança Jurídica | Registro da licença MIT do `ViGEmClient` e créditos de `PySDL2`/`SDL2`. |
| `src/dav/modules/transport_p2p/dualstack.py` | Criado | Fatia `transport_p2p` | Primitivos Dual-Stack (`create_dualstack_udp_socket`, `format_sendto_addr`, `normalize_recv_addr`, `parse_host_port`, `format_endpoint_display`, `effective_mtu_for_ip`, `synthesize_nat64_ipv6`). |
| `src/dav/modules/transport_p2p/signaling_client.py`, `stun.py`, `candidates.py`, `service.py`, `lan_beacon.py` | Modificado | Fatia `transport_p2p` | STUN RFC 5389 IPv6 (`0x02`), candidatos `ipv6` globais priorizados sobre WAN IPv4, fallback NAT64 RFC 7050 / `DAV_RENDEZVOUS_HOST_V6` e deduplicação de 60 s eliminando o loop de `1,2 s`. |
| `src/dav/modules/transport_p2p/crypto_pake.py` | Modificado | Fatia `transport_p2p` | Blindagem `mark_valid_rx()` rejeitando `SYN2` espúrio com nonce novo durante sessões AEAD ativas (`< 4,0 s`). |
| `src/dav/modules/transport_p2p/fec_engine.py`, `data_plane.py` | Modificado | Fatia `transport_p2p` | Block-RS FEC `algo=2` (sub-blocos de 160 shards para Mega-IDRs até 4096 fragmentos), `set_target_mtu_for_ip` (`1180 B` IPv6) e renovação de atividade PAKE. |
| `src/dav/modules/transport_p2p/http_tunnel_relay.py`, `src/signaling/server/dav_rendezvous.py`, `deploy/DEPLOY_VPS_ORACLE.md` | Criado / Modificado | Sinalização & Relay VPS | Blind Relay HTTP-Stream/WebSocket em Python stdlib (`/p2p/relay_stream`, `/p2p/relay_push`, `/p2p/ws_relay`), bind Dual-Stack `[::]` com Relay Cross-Family `IPv4 <-> IPv6` e guia operacional da VPS. |
| `src/dav/modules/remote_desktop/protocol.py` | Modificado | Fatia `remote_desktop` | Adicionado `WsMsgType.PLI_REQ = 0x0E` para pedido de IDR autenticado sobre AEAD. |
| `src/dav/modules/codec/encoder.py`, `decoder.py` | Modificado | Fatia `codec` | GOP de 2 s no NVENC, `VideoDecoder.flush()`, detecção `frame.is_corrupt` e sinalização `last_decode_corrupted`. |
| `src/dav/modules/stream_engine/subprocess_sender.py`, `sender_worker.py`, `receiver_worker.py`, `service.py` | Modificado | Fatia `stream_engine` | Dual-Stack completo, `PAIR_PEER` idempotente, remoção de `GAMEPAD_STATE` de `input_wake_evt`, piso de cadência `0.96 * frame_interval`, Relay HTTP automático em `1,70 s`, remoção do escape de `450 ms` no `ReceiverWorker` e `request_receiver_pli()`. |
| `src/ui/bridge.py`, `src/ui/glass/views.py`, `src/ui/glass/sheets.py`, `src/ui/main_window.py` | Modificado | Interface Desktop (PySide6) | `DecodeWorker` Zero-Ghosting (fast-catchup preservando DPB, `flush()` em IDR e callback `on_pli_needed`), parser/UI para `[ipv6]:porta` e `dav://[ipv6]:porta/PIN`, resolução DNS `AF_UNSPEC` (`AAAA`) e botão **Copiar Link Direto IPv6**. |
| `tests/test_v52_resilience_and_zero_ghosting.py` | Criado | Verificação Automatizada | 10 testes de regressão cobrindo ViGEm nativo, deduplicação legada, blindagem PAKE, Block-FEC 450 KB, Zero-Ghosting RX/Decode, cadência gamepad, IPv6/STUN/NAT64, Dual-Stack loopback e Relay HTTP + Cross-Family UDP. |
| `VERSION`, `CHANGELOG.md`, `docs/decisions/0004-...md` | Criado / Modificado | Governança & Release | Bump para `5.2.0`, registro no changelog e ADR MADR 4.0 formalizado. |
| `commit_msg.txt` | Removido | Raiz do repositório | Limpeza de arquivo temporário não rastreado remanescente da release anterior. |

## Decisões arquiteturais e justificativas

- **Decisão registrada:** [ADR-0004](../decisions/0004-arquitetura-dualstack-ipv6-zero-ghosting-vigem-e-relay-hibrido.md) — detalha a adoção do socket único Dual-Stack (`AF_INET6` + `IPV6_V6ONLY=0`), da síntese NAT64 RFC 7050 + link direto `dav://[ipv6]:porta/PIN`, do Blind Relay híbrido UDP/HTTP-Stream, do Block-RS FEC (`algo=2`), do Gate Zero-Ghosting e do versionamento de `ViGEmClient.dll` pré-compilado.

## Evidências de verificação e testes

- **Suíte Pytest completa:** `py -m pytest tests/ -v` (com `DAV_HEADLESS_SYNTHETIC=1` e `QT_QPA_PLATFORM=offscreen`)
  - **Resultado observado:** `108 passed, 2 warnings in 19.13s` (100% de aprovação em todas as fatias, incluindo os 10 novos testes da `v5.2.0`).
- **Validação P2P ponta a ponta:** `py tests/test_p2p_e2e.py`
  - **Resultado observado:** `TODOS OS CENÁRIOS P2P APROVADOS COM 100% DE ÊXITO!` (3/3 aprovados; socket Dual-Stack `[::]` comprovou descoberta simultânea de Tailscale IPv4/IPv6, LAN IPv4 e IPv6 Global + 547 datagramas encaminhados via Blind Relay).
- **Auto-teste de inicialização da aplicação:** `py scripts/gui_app.py --self-check`
  - **Resultado observado:** `DAV_SELF_CHECK_OK` (exit code 0).
- **Auditoria documental (`doc_lint.py`):** executada sobre `ADR-0004` (`--type madr`), `deploy/DEPLOY_VPS_ORACLE.md` (`--type general`) e este relatório (`--type session`).

## Estado da infraestrutura e serviços

| Serviço / Nó | Alvo lógico | Estado observado | Observações |
| :--- | :--- | :--- | :--- |
| Rendezvous HTTP/SSE (Oracle Cloud VPS) | `129.148.26.150:80` (`/p2p/health`) | Online (versão legada) | Responde HTTP 200 sem campos `version`/`since_index`/`http_relay`; requer `git pull` + `systemctl restart dav-rendezvous.service`. |
| Gateway STUN / Blind Relay UDP (Oracle Cloud VPS) | `129.148.26.150:8768/udp` | Offline / Filtrado | Sondas `DAV_STUN` e `DAV_RLY1` sofreram timeout de 3 s a partir da rede residencial; liberar `8768/udp` em `iptables` e Security List da VCN conforme `deploy/DEPLOY_VPS_ORACLE.md`. |

## Riscos, dívida técnica e desvios conhecidos

- O servidor Context7 MCP não estava conectado nesta sessão; assinaturas de `PyAV 18.1.0`, `PySide6 6.11.2` e `ViGEmClient.dll` x64 foram validadas diretamente contra os binários instalados e cobertas pela suíte automatizada.
- Enquanto a VPS Oracle Cloud não executar o deploy descrito em `deploy/DEPLOY_VPS_ORACLE.md`, clientes atrás de NAT simétrico institucional não terão acesso ao Blind Relay UDP `8768` nem ao novo `/p2p/relay_stream` na VPS (porém, conexões diretas IPv6 via `dav://[ipv6]:porta/PIN` e correções Zero-Ghosting/ViGEm já operam imediatamente).
- Os 4 arquivos originais de arte em `design/blocks_components/` permaneceram intocados na árvore de trabalho conforme orientação prévia.

## Próximos passos verificáveis

1. Executar os comandos de `deploy/DEPLOY_VPS_ORACLE.md` na VPS `129.148.26.150` e confirmar `http_relay: true`, `dualstack: true` em `/p2p/health` e resposta imediata a `DAV_STUN` na porta `8768/udp`.
2. Efetuar o commit versionado da `v5.2.0` (excluindo os 4 arquivos de arte de `design/blocks_components/`) e publicar a tag `v5.2.0` para disparar o workflow `.github/workflows/release.yml` com build rápido incluindo `ViGEmClient.dll`.
3. Realizar teste de campo em rede institucional e com o host IPv6-Only validando o fluxo de vídeo sem ghosting e o controle virtual no instalador oficial Windows.
