# DA-V v4.9.0 — Guia Rapido Linux

Guia objetivo para instalar, executar e gerar o pacote compilado `.tar.gz` do **DA-V (Distribuidor Amplo de Video)** no Linux (Ubuntu 22.04/24.04/26.04, Debian 12+, Fedora 40+ e Arch Linux), com suporte completo a **X11**, **Wayland (PipeWire / XDG Portal)** e **P2P Single-Socket + Blind Relay**.

---

## 1. Pacotes e Diferenca Importante

- **`release_assets/DA-V_v4.9.0_Linux_Source_Portable.tar.gz`** *(gerado neste host Windows)*:
  Pacote portatil em codigo-fonte com finais de linha POSIX (`LF`), permissoes executaveis e todos os scripts prontos para rodar no Linux via `./launch_dav.sh` ou compilar os binarios nativos com `./scripts/build_linux_bundle.sh`. **Nao contem binarios ELF pre-compilados.**
- **`release_assets/DA-V_v4.9.0_Linux_x86_64.tar.gz`** *(gerado em host Linux ou CI Ubuntu)*:
  Pacote completo com os binarios ELF compilados (`DA-V`, `libdav_core.so`, `dav_daemon` e `DA-V_Instalador_Linux_x86_64`).

---

## 2. Pre-Requisitos no Sistema Linux

### Ubuntu / Debian
```bash
sudo apt update && sudo apt install -y \
  build-essential cmake ninja-build \
  python3 python3-venv python3-pip python3-dev python3-gi \
  gstreamer1.0-pipewire gstreamer1.0-tools gstreamer1.0-plugins-base \
  libx11-dev libxext-dev libxfixes-dev libxrandr-dev \
  libgl1 libegl1 libxcb-cursor0 libxkbcommon-x11-0 \
  libxcb-icccm4 libxcb-image0 libxcb-keysyms1 libxcb-randr0 \
  libxcb-render-util0 libxcb-shape0 libxcb-xinerama0 libxcb-xfixes0 \
  libdbus-1-3 ffmpeg
```

### Fedora 40+
```bash
sudo dnf install -y \
  gcc-c++ cmake ninja-build python3 python3-devel python3-pip \
  python3-gobject gstreamer1-plugin-pipewire \
  libX11-devel libXext-devel libXfixes-devel libXrandr-devel \
  mesa-libGL-devel libxkbcommon-x11 ffmpeg-free
```

### Arch Linux
```bash
sudo pacman -Syu --noconfirm \
  base-devel cmake ninja python python-pip python-gobject \
  gst-plugin-pipewire libx11 libxext libxfixes libxrandr \
  mesa libxkbcommon-x11 ffmpeg
```

---

## 3. Executar Direto do `.tar.gz` Portatil (Sem Compilacao Manual)

```bash
tar -xzf DA-V_v4.9.0_Linux_Source_Portable.tar.gz
cd DA-V-v4.9.0-Linux-Source
chmod +x launch_dav.sh
./launch_dav.sh
```

Na primeira execucao, o script cria `.venv`, instala as dependencias de `requirements.txt`, detecta automaticamente `WAYLAND_DISPLAY` ou `DISPLAY` e abre a janela principal do DA-V.

Modos uteis via CLI:
```bash
./launch_dav.sh --test                          # Executa a suite pytest e E2E
./launch_dav.sh --daemon --port 9000 --pin 845-747
./launch_dav.sh --auto-recv --pin 845-747       # Conecta direto como Receptor
```

---

## 4. Compilar a Versao ELF Completa + `.tar.gz` no Linux

Dentro do diretorio do projeto (clonado ou extraido do tarball portatil):

```bash
chmod +x build_linux.sh launch_dav.sh scripts/build_linux_bundle.sh
./scripts/build_linux_bundle.sh
```

Para pular os testes durante uma recompilacao rapida:
```bash
./scripts/build_linux_bundle.sh --skip-tests
```

Artefatos gerados ao final:
- `dist/DA-V/DA-V` (executavel ELF principal + `libdav_core.so`)
- `release_assets/DA-V_Instalador_Linux_x86_64` (instalador grafico XDG + protocolo `dav://`)
- `release_assets/DA-V_v4.9.0_Linux_x86_64.tar.gz` (pacote final redistribuivel)

Para instalar no sistema apos gerar ou extrair o pacote compilado:
```bash
chmod +x DA-V_Instalador_Linux_x86_64
./DA-V_Instalador_Linux_x86_64
```

---

## 5. Como Gerar a Compilacao ELF a Partir Deste Windows (Opcional)

1. **Via WSL2 Ubuntu neste mesmo PC:**
   Abra o PowerShell como **Administrador** e execute:
   ```powershell
   wsl.exe --install --no-distribution
   ```
   Reinicie o Windows, entre no `Ubuntu` e execute dentro da pasta do projeto:
   ```bash
   ./scripts/build_linux_bundle.sh
   ```

2. **Via GitHub Actions (`.github/workflows/release.yml`):**
   Envie os commits locais (`git push origin main` e uma tag `v4.0.0` apontando para o commit atual) para o job `build-linux` em `ubuntu-24.04` compilar e publicar automaticamente os artefatos Linux e Windows.

---

## 6. Firewall (UFW) e Captura no Wayland

```bash
sudo ufw allow 9000:9020/udp comment 'DA-V P2P Stream'
sudo ufw allow 19000:19010/udp comment 'DA-V Auxiliary Ports'
sudo ufw allow 9005/udp comment 'DA-V LAN Discovery'
sudo ufw reload
```

Em sessoes **Wayland** (Ubuntu GNOME / KDE Plasma), na primeira transmissao o sistema exibira a caixa de dialogo nativa do **XDG Desktop Portal** pedindo autorizacao para compartilhar a tela via PipeWire.
