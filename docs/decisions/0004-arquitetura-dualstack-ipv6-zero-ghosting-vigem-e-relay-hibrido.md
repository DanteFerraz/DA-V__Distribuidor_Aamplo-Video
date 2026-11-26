---
status: "accepted"
date: 2026-11-26
decision-makers: ["Dante Ferraz"]
consulted: []
informed: []
---

# Adotar arquitetura Dual-Stack IPv6, pipeline Zero-Ghosting, Block-FEC e ViGEm nativo pré-compilado

## Context and problem statement

Os testes de campo da release `v5.1.0` evidenciaram quatro falhas estruturais distintas: travamento superior a duas horas no GitHub Actions ao instalar `vgamepad` a partir de tarball fonte (`sdist`), falha de conexão em redes institucionais sob NAT simétrico devido ao loop de re-pareamento de `1,2 s` e bloqueio da porta UDP `8768`, impossibilidade de conexão com hosts estritamente IPv6-Only e corrupção visual inter-quadro H.264 ("quadros gravados") provocada por Mega-IDRs sem proteção FEC, salto de cadência para `99 FPS` sob entrada de gamepad e descarte de P-frames intermediários no receptor.

## Decision drivers

* Garantir build determinístico e rápido no GitHub Actions (Windows x64 e Linux x64) preservando emulação real de Xbox 360 e DualShock 4 nos instaladores oficiais.
* Permitir conectividade confiável com hosts IPv6-Only, redes Dual-Stack e firewalls institucionais que bloqueiam portas UDP externas, mantendo criptografia ponta a ponta ChaCha20-Poly1305.
* Eliminar artefatos de corrupção de referência H.264/HEVC (DPB desincronizado) em links WAN com perda de pacotes e RTT elevado (~100 ms), sem degradar a latência sub-milissegundo em LAN.
* Manter aderência estrita às fronteiras modulares do MonoTech Core Kernel v2.0 e compatibilidade retroativa com clientes `v5.1`.

## Considered options

* Opção 1: Adotar socket único Dual-Stack (`AF_INET6` + `IPV6_V6ONLY=0`) centralizado em `dualstack.py` com STUN IPv6 (`0x02`), síntese NAT64 RFC 7050, link direto `dav://[ipv6]:porta/PIN`, Blind Relay híbrido (UDP `8768` + HTTP-Stream `80/443`), Block-RS FEC (`algo=2`), Gate Zero-Ghosting ponta a ponta e `ViGEmClient.dll` x64 pré-compilado versionado no Git sob adaptador `ctypes`.
* Opção 2: Manter dois sockets separados (`AF_INET` e `AF_INET6`) por worker, exigir servidor TURN comercial externo e continuar excluindo `vgamepad` do instalador Windows CI.
* Opção 3: Manter estado atual (`v5.1.0`) e orientar usuários a configurar VPN externa e instalar `vgamepad` manualmente.

## Decision outcome

Chosen option: "Opção 1", because preserva a arquitetura Single-Socket STUN/Hole-Punching do DA-V com sobrecarga mínima de complexidade, elimina em definitivo o tempo de build do `vgamepad` no CI, habilita conexão direta sem NAT entre hosts com IPv6 Global (além de ponte Cross-Family e HTTP-Stream em firewalls institucionais) e impede matematicamente a entrega de P-frames órfãos ou corrompidos ao decodificador H.264/HEVC.

### Consequences

* Good, because instaladores Windows gerados no GitHub Actions passam a incluir suporte nativo completo a Xbox 360 e DualShock 4 virtuais com zero tempo de compilação extra e instalador MSI offline embutido.
* Good, because hosts IPv6-Only passam a conectar tanto diretamente (`dav://[ipv6]:porta/PIN`) quanto via PIN (NAT64 RFC 7050 ou VPS Dual-Stack), e Mega-IDRs acima de `200` fragmentos recebem reconstrução Reed-Solomon `GF(2^8)` por sub-blocos (`algo=2`).
* Good, because o receptor mantém o último quadro íntegro congelado até a chegada de um IDR limpo com `flush()` de DPB e pedido autenticado `WsMsgType.PLI_REQ = 0x0E`, erradicando macroblocos gravados na tela.
* Bad, because o repositório Git passa a versionar `~1,0 MB` de binários pré-compilados MIT em `third_party/vigem/` (`ViGEmClient.dll` e `ViGEmBusSetup_x64.msi`) mediante exceção controlada no `.gitignore`.
* Bad, because o fallback de Blind Relay HTTP-Stream e o suporte a PIN IPv6 nativo exigem atualização do `dav_rendezvous.py` (v3.2.0) e liberação de regras de firewall/VCN na VPS Oracle Cloud conforme `deploy/DEPLOY_VPS_ORACLE.md`.

### Confirmation

Conformidade verificada continuamente pela suíte `tests/test_v52_resilience_and_zero_ghosting.py`, pela suíte de fronteiras arquiteturais `tests/test_architecture_boundaries.py`, pelo teste ponta a ponta `tests/test_p2p_e2e.py` e pelo auto-teste de inicialização `scripts/gui_app.py --self-check`. As assinaturas de runtime do `PyAV 18.1.0`, `PySide6 6.11.2` e `ViGEmClient.dll` x64 foram validadas diretamente contra os binários instalados (Context7 MCP indisponível nesta sessão, registrado conforme diretriz de fallback offline da skill `monotech-arch`).

## Pros and cons of the options

### Opção 1

* Good, because unifica IPv4 e IPv6 em um único descritor `select()`, reutiliza o mesmo protocolo AEAD sobre UDP e HTTP-Stream sem dependências externas na VPS e mantém `algo=0/1` 100% retrocompatível com pares `v5.1`.
* Neutral, because requer normalização explícita de endereços `::ffff:x.x.x.x` no Winsock/Linux, isolada no módulo `dualstack.py`.
* Bad, because adiciona `~1,0 MB` de binários pré-compilados de terceiros (licença MIT) ao histórico do repositório.

### Opção 2

* Good, because separa completamente o código de envio IPv4 e IPv6 em descritores independentes.
* Bad, because duplica loops de rede, locks e temporizadores de Hole-Punching, introduz custo operacional recorrente de infraestrutura TURN externa e mantém quebrada a emulação de controles nos instaladores Windows oficiais.

### Opção 3

* Good, because evita alterações na camada de transporte e empacotamento.
* Bad, because mantém falhas reprodutíveis em redes institucionais, bloqueio total para amigos em redes IPv6-Only, ghosting H.264 sob perda WAN e ausência de `ViGEmClient` nas releases oficiais Windows.
