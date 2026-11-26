# Guia operacional de deploy do Rendezvous Dual-Stack e Relay na Oracle Cloud VPS

Este guia atualiza o microserviço `dav_rendezvous.py` (v3.2.0) na instância Linux da Oracle Cloud para habilitar:

1. **Multi-peer com `since_index`** (elimina o polling repetido no servidor legado).
2. **Blind Relay UDP `8768/udp` Cross-Family (`IPv4 <-> IPv6`)** em socket Dual-Stack `[::]`.
3. **Blind Relay HTTP-Stream (`80/443`)** via `/p2p/relay_stream` + `/p2p/relay_push` para redes institucionais que bloqueiam UDP externo.
4. **Suporte nativo a clientes IPv6-Only por PIN** após ativar IPv6 na VCN da Oracle Cloud.

## 1. Atualizar o código na VPS e reiniciar o serviço systemd

```bash
cd /opt/dav
git pull origin main
sudo systemctl restart dav-rendezvous.service
sudo systemctl status dav-rendezvous.service --no-pager
curl -s http://127.0.0.1:8765/p2p/health
```

A resposta deve conter `"version": "3.2.0"`, `"dualstack": true` e `"http_relay": true`.

## 2. Liberar UDP `8768` no firewall do SO e na VCN da Oracle Cloud

No servidor Linux (Ubuntu/Oracle Linux):

```bash
# Caso utilize iptables (padrao Oracle Cloud Ubuntu)
sudo iptables -I INPUT 6 -p udp --dport 8768 -j ACCEPT
sudo ip6tables -I INPUT 6 -p udp --dport 8768 -j ACCEPT 2>/dev/null || true
sudo netfilter-persistent save 2>/dev/null || true

# Caso utilize UFW
sudo ufw allow 8768/udp 2>/dev/null || true
```

No console web da Oracle Cloud (**Networking -> Virtual Cloud Networks -> Sub-rede -> Security List -> Ingress Rules**):

- Adicione regra de entrada **Stateless=No**, Source CIDR `0.0.0.0/0`, IP Protocol **UDP**, Destination Port Range **`8768`**.
- (Para IPv6) Adicione regra equivalente com Source CIDR `::/0`, IP Protocol **UDP**, Destination Port Range **`8768`** (e TCP `80`/`443`).

## 3. Configuração recomendada no Nginx para HTTP-Stream / WebSocket Relay

No bloco `location /p2p/` do Nginx (`/etc/nginx/sites-enabled/...`):

```nginx
location /p2p/ {
    proxy_pass http://127.0.0.1:8765/p2p/;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection $http_connection;
    proxy_buffering off;
    proxy_cache off;
    proxy_read_timeout 3600s;
}
```

Recarregue o Nginx após validar:

```bash
sudo nginx -t && sudo systemctl reload nginx
```

## 4. Ativação opcional de IPv6 nativo na VPS (para PIN direto em hosts IPv6-Only sem NAT64)

1. No console da Oracle Cloud: **VCN -> CIDR Blocks -> Add IPv6 CIDR** (bloco `/56` gratuito) e associe um `/64` à sub-rede pública e um endereço IPv6 à VNIC da instância.
2. Adicione `listen [::]:80;` no `server {}` do Nginx.
3. Aponte um domínio DNS com registros `A` (IPv4) e `AAAA` (IPv6) ou informe `DAV_RENDEZVOUS_HOST_V6=<ipv6_da_vps>` no cliente.
