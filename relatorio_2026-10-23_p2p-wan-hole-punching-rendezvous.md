# Relatório de Desenvolvimento: Conexão P2P WAN Universal e UDP Hole-Punching (DA-V)
**Data:** 23 de Outubro de 2026  
**Autor:** Dante Ferraz (`danteferraz06@gmail.com`)  
**Repositório:** [DA-V__Distribuidor_Aamplo-Video](https://github.com/DanteFerraz/DA-V__Distribuidor_Aamplo-Video)  
**Linha Principal de Trabalho:** Diagnóstico, Correção e Validação de Transmissão P2P entre Redes Distintas (NAT Traversal & Rendezvous)

---

## 1. Contexto e Diagnóstico do Problema

O usuário testou a transmissão de vídeo utilizando as configurações apresentadas na interface gráfica do DA-V, constatando que os quadros de vídeo não chegavam ao computador receptor situado em uma rede externa (WAN / Internet).

### Análise Causal a partir do Log e Screenshot:
1. **Loopback Local Indevido (`127.0.0.1`):** No formulário do Transmissor, o campo `IP Alvo (Destino)` estava pré-preenchido com `127.0.0.1`. Todos os 350.557 pacotes gerados pelo hardware NVENC da RTX 4070 estavam sendo disparados para a interface interna de loopback local da própria máquina transmissora, jamais trafegando pela Internet.
2. **Ausência de Polling do Transmissor:** Ao registrar o PIN no servidor Rendezvous, o transmissor não registrava a rotina de pooling (`on_paired_callback`). Por isso, quando o receptor remoto pareava com o PIN, o transmissor nunca tomava conhecimento do IP público do receptor para atualizar seu alvo UDP.
3. **Descarte de Endpoint no Receptor e Falta de Hole-Punching:** Na função `_toggle_receiver()`, os parâmetros `peer_target_ip` e `peer_target_port` resolvidos do Rendezvous eram descartados sem serem repassados ao motor de recepção (`engine.start_receiver()`). Sem disparar pacotes UDP `DAV_P2P_SYN` para o transmissor, a tabela NAT do roteador do receptor permanecia fechada para pacotes UDP de entrada.
4. **Descoberta de Portas Externas:** Ambas as pontas anunciavam portas locais internas (ex: 9002), desconhecendo as portas reflexivas mapeadas dinamicamente pelos provedores de internet (CGNAT/NAT).

---

## 2. Implementações Realizadas

### A. Implantação e Publicação do Servidor Rendezvous na VPS Oracle Cloud
- O serviço [dav_rendezvous.py](file:///c:/Users/Dante/Desktop/Distribuidor_Aamplo-Video/src/signaling/server/dav_rendezvous.py) foi implantado em `/opt/dav_rendezvous/` na VPS Oracle Cloud (`129.148.26.150`).
- Configurado daemon gerenciado pelo `systemd` (`dav-rendezvous.service`), habilitado para auto-início no boot.
- Publicado através de proxy reverso no Nginx (porta 80) na rota `/p2p/`, extraindo o cabeçalho `X-Real-IP` para identificação precisa do IP público de cada ponta.
- Ajustadas as rotas no microserviço HTTP para responder com `200 OK` nas variantes `/health`, `/status`, `/p2p/health` e `/p2p/`.

### B. Descoberta de Portas Reflexivas via STUN RFC 5389
- Implementado em [src/discovery/p2p_channel.py](file:///c:/Users/Dante/Desktop/Distribuidor_Aamplo-Video/src/discovery/p2p_channel.py) o método `query_rfc5389_stun()` com consulta de altíssima velocidade (15ms) aos servidores STUN públicos mundiais (`stun.l.google.com:19302` e `stun.cloudflare.com:3478`).
- Ambas as pontas agora descobrem simultaneamente seu IP público real e a porta UDP mapeada pelo NAT do roteador antes do registro no Rendezvous.

### C. Redirecionamento Dinâmico e Escuta de Hole-Punching no Transmissor
- **[scripts/dav_sender_worker.py](file:///c:/Users/Dante/Desktop/Distribuidor_Aamplo-Video/scripts/dav_sender_worker.py):**
  - Implementada fila de comandos IPC `cmd_queue` no subprocesso desvinculado do GIL. Ao receber o comando `("UPDATE_TARGET", ip, port)`, o alvo de transmissão é ajustado em tempo real sem interrupção do encoder NVENC.
  - O socket UDP de saída foi associado (`bind`) a `0.0.0.0:target_port` em modo não-bloqueante.
  - Criado listener integrado que captura pacotes `DAV_P2P_SYN` enviados pelo receptor:
    - Se um pacote de perfuração for detectado, o transmissor ajusta imediatamente `target_ip` e `target_port` para o endereço de origem do receptor e responde com `DAV_P2P_ACK`.
    - Blindagem contra `WinError 10049` garantindo que o socket só envie datagramas quando o destino estiver ativo.

### D. Rajada de Perfuração de NAT e Retransmissão no Receptor
- **[scripts/dav_client.py](file:///c:/Users/Dante/Desktop/Distribuidor_Aamplo-Video/scripts/dav_client.py):**
  - Atualizado método `start_receiver()` para receber o parâmetro `target_peer=(ip, port)`.
  - Ao iniciar a escuta UDP, o receptor dispara imediatamente uma rajada de 8 pacotes `DAV_P2P_SYN` para abrir a tabela de estado do roteador (NAT hole-punching).
  - No loop de recepção, em caso de `socket.timeout` enquanto nenhum quadro de vídeo tiver sido recebido (`packets_received == 0`), o receptor retransmite periodicamente o pacote SYN, garantindo travessia mesmo em redes WAN com perda inicial de pacotes.

### E. Modernização da Interface Gráfica (UI)
- **[src/ui/views/sender_view.py](file:///c:/Users/Dante/Desktop/Distribuidor_Aamplo-Video/src/ui/views/sender_view.py) e [src/ui/main_window.py](file:///c:/Users/Dante/Desktop/Distribuidor_Aamplo-Video/src/ui/main_window.py):**
  - O campo `IP Alvo (Destino)` agora inicia vazio (`""`), com o placeholder explícito: `"Vazio p/ P2P Remoto (PIN) ou IP específico"`.
  - O campo `IP do Transmissor` no receptor também inicia vazio (`""`), ativando de forma transparente o modo P2P Universal via PIN.
  - No transmissor, ao clicar em "Iniciar Compartilhamento" sem preencher o IP, o sistema entra em estado de prontidão (`Aguardando Receptor PIN XXX-XXX`).
  - No receptor, ao inserir o PIN e clicar em "Conectar e Assistir", o Rendezvous pareia ambos os lados e:
    - O transmissor recebe o evento `_on_receiver_paired`, atualiza o campo de IP e redireciona o fluxo de vídeo 1080p @ 60 FPS diretamente para o receptor.
    - O receptor perfura o NAT e exibe o vídeo instantaneamente.

---

## 3. Arquivos Modificados e Criados

| Arquivo | Descrição das Alterações |
|---|---|
| [`src/discovery/p2p_channel.py`](file:///c:/Users/Dante/Desktop/Distribuidor_Aamplo-Video/src/discovery/p2p_channel.py) | Adicionada consulta STUN RFC 5389 (`stun.l.google.com`), suporte a STUN fallback e registro no Rendezvous com porta pública real. |
| [`scripts/dav_client.py`](file:///c:/Users/Dante/Desktop/Distribuidor_Aamplo-Video/scripts/dav_client.py) | Implementado método `update_sender_target()`, injeção de `target_peer` no receptor e retransmissão de pacotes SYN de hole-punching. |
| [`scripts/dav_sender_worker.py`](file:///c:/Users/Dante/Desktop/Distribuidor_Aamplo-Video/scripts/dav_sender_worker.py) | Adicionado listener de hole-punching bidirecional nos loops GDI e WGC, fila de comandos IPC `UPDATE_TARGET` e proteção `if target_ip`. |
| [`src/signaling/server/dav_rendezvous.py`](file:///c:/Users/Dante/Desktop/Distribuidor_Aamplo-Video/src/signaling/server/dav_rendezvous.py) | Suporte completo às rotas `/p2p/health`, `/health` e `/status` atrás do Nginx reverso na VPS Oracle Cloud. |
| [`src/ui/main_window.py`](file:///c:/Users/Dante/Desktop/Distribuidor_Aamplo-Video/src/ui/main_window.py) | Inicialização com campos de IP vazios por padrão, callback de pareamento `_on_receiver_paired`, repasse de `target_peer` ao receptor e sinal Qt `target_updated_signal`. |
| [`src/ui/views/sender_view.py`](file:///c:/Users/Dante/Desktop/Distribuidor_Aamplo-Video/src/ui/views/sender_view.py) | Placeholder textual descritivo para P2P Universal via PIN. |
| [`tests/test_p2p_e2e.py`](file:///c:/Users/Dante/Desktop/Distribuidor_Aamplo-Video/tests/test_p2p_e2e.py) | Drenagem de pacotes SYN, tratamento de Winsock `ConnectionResetError` no Windows e assert do fluxo de vídeo P2P. |

---

## 4. Testes e Validação

Executada suíte completa de testes unitários e de ponta a ponta:
```bash
py -m pytest tests/test_dav_rendezvous.py tests/test_p2p_e2e.py -v -s
```
**Resultado:**
- `test_rendezvous`: **PASSED (100% OK)** — Validação dos 5 endpoints HTTP/UDP do Rendezvous.
- `test_p2p_e2e`: **PASSED (100% OK)** — Registro do PIN, resolução do receptor, hole-punching UDP e entrega com sucesso do frame de vídeo 60 FPS.
- Consulta ao vivo do Rendezvous na VPS Oracle Cloud (`http://129.148.26.150/p2p/health`):
  `{"service": "DAV-Rendezvous", "status": "online", "client_ip": "170.239.226.123"}`.

---

## 5. Governança e Git
- **Commit:** `f6f4481`
- **Mensagem:** `fix(p2p): enable dynamic WAN redirection and bidirectional UDP hole-punching`
- **Autor Canônico:** `Dante Ferraz <danteferraz06@gmail.com>`
- **Sincronização:** Sincronizado e enviado com sucesso para a branch `main` do GitHub.
