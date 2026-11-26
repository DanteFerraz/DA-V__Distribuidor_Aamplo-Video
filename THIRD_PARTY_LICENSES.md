# Licenças de Componentes de Terceiros (Third-Party Licenses) — DA-V

O **DA-V (Distribuidor Amplo de Vídeo)** é licenciado sob a **GNU Affero General Public License v3.0 ou posterior (`AGPL-3.0-or-later`)** com Termos Adicionais da Seção 7 ([LICENSE](LICENSE) e [NOTICE](NOTICE)).

Esta distribuição utiliza e interopera com bibliotecas de código aberto de terceiros cujos avisos de copyright e licenças estão detalhados abaixo. Os textos integrais das licenças da família GNU encontram-se no diretório [`LICENSES/`](LICENSES/).

---

## 1. Resumo de Componentes e Compatibilidade

| Componente | Versão Referência | Licença SPDX | Titular / Projeto | Modo de Integração |
| :--- | :--- | :--- | :--- | :--- |
| **PySide6 / Qt 6** (`Qt6Core`, `Qt6Gui`, `Qt6Widgets`, `Qt6Network`, `Qt6Multimedia`, `shiboken6`) | `6.11.x` | `LGPL-3.0-only OR GPL-3.0-only` | The Qt Company Ltd. | Linkagem dinâmica (DLLs / `.so` substituíveis em `_internal/PySide6/`) |
| **PyAV (`av`)** | `18.1.x` | `BSD-3-Clause` | Mike Boers & PyAV Contributors | Pacote Python |
| **FFmpeg** (`libavcodec`, `libavformat`, `libavutil`, `libswscale`, `libswresample`, `libavfilter`, `libavdevice`) | `7.x / 8.x` | `LGPL-3.0-or-later` (`--enable-version3`) | FFmpeg Developers | Bibliotecas compartilhadas dinâmicas (`av.libs/`) |
| **x264 (`libx264`)** | `r3100+` (API 165) | `GPL-2.0-or-later` | VideoLAN / x264 Developers | Biblioteca compartilhada dinâmica (`av.libs/`) combinada sob GPLv3/AGPLv3 Seção 13 |
| **x265 (`libx265`)** | `3.5+` | `GPL-2.0-or-later` | MulticoreWare, Inc. | Biblioteca compartilhada dinâmica (`av.libs/`) combinada sob GPLv3/AGPLv3 Seção 13 |
| **libopus** | `1.4+` | `BSD-3-Clause` | Xiph.Org Foundation / IETF | Biblioteca compartilhada dinâmica (`av.libs/`) |
| **dav1d (`libdav1d`)** | `1.4+` | `BSD-2-Clause` | VideoLAN and dav1d Authors | Biblioteca compartilhada dinâmica (`av.libs/`) |
| **SVT-AV1 (`libSvtAv1Enc`)** | `2.x` | `BSD-3-Clause-Clear` | Alliance for Open Media | Biblioteca compartilhada dinâmica (`av.libs/`) |
| **libvpx / libwebp / libsharpyuv** | `1.14+` | `BSD-3-Clause` | Google LLC / WebM Project | Bibliotecas compartilhadas dinâmicas (`av.libs/`) |
| **LAME (`libmp3lame`) / GNU libiconv** | `3.100` / `1.17` | `LGPL-2.1-or-later` | LAME Project / Free Software Foundation | Bibliotecas compartilhadas dinâmicas (`av.libs/`) |
| **OpenCORE AMR (`libopencore-amrnb`, `amrwb`)** | `0.1.6` | `Apache-2.0` | PacketVideo / Martin Storsjö | Bibliotecas compartilhadas dinâmicas (`av.libs/`) |
| **Intel oneVPL (`libvpl`)** | `2.x` | `MIT` | Intel Corporation | Biblioteca compartilhada dinâmica (`av.libs/`) |
| **GCC Runtime (`libgcc_s_seh`, `libstdc++`, `libwinpthread`)** | `13+` | `GPL-3.0-with-GCC-exception` / `MIT` | Free Software Foundation / MinGW-w64 | Runtime C/C++ dinâmico |
| **KCP (`third_party/kcp/ikcp.c`, `ikcp.h`)** | `1.7` | `MIT` | skywind3000 (`Linwei`) | Código-fonte C incluído em [`third_party/kcp/`](third_party/kcp/LICENSE) |
| **ViGEmClient (`third_party/vigem/x64/ViGEmClient.dll`)** | `1.21+` | `MIT` | Nefarius Software Solutions e.U. / ViGEm Contributors | Biblioteca binária x64 pré-compilada em [`third_party/vigem/`](LICENSES/MIT-ViGEmClient.txt) |
| **PySDL2 + SDL2 (`sdl2dll`)** | `0.9.17` / `2.32.x` | `Zlib / Public Domain` | Marcus von Appen / Sam Lantinga (SDL) | Captura universal de gamepads HID (DualShock 4, DualSense, Xbox, Genéricos) |
| **cryptography + OpenSSL 3** (`libcrypto-3`, `libssl-3`) | `46.x` / `3.x` | `Apache-2.0 OR BSD-3-Clause` | Python Cryptographic Authority / OpenSSL Project | Pacote Python + DLLs dinâmicas |
| **NumPy (`numpy`)** | `2.x` | `BSD-3-Clause` | NumPy Developers | Pacote Python |
| **Python MSS (`mss`)** | `10.x` | `MIT` | Mickaël Schoentgen (`BoboTiG`) | Pacote Python |
| **websockets** | `17.x` | `BSD-3-Clause` | Aymeric Augustin | Pacote Python |
| **psutil** | `7.x` | `BSD-3-Clause` | Giampaolo Rodola | Pacote Python |
| **comtypes** | `1.4.x` | `MIT` | Thomas Heller & Contributors | Pacote Python (Windows) |
| **windows-capture** | `2.x` | `MIT` | NiiightmareXD | Pacote Python (Windows WGC) |
| **Pillow (`PIL`)** | `13.x` | `MIT-CMU` | Jeffrey A. Clark & Contributors | Pacote Python |
| **cffi / pycparser** | `2.x` / `3.x` | `MIT` / `BSD-3-Clause` | Armin Rigo, Eli Bendersky | Pacotes Python |
| **PyInstaller Bootloader** | `6.22.x` | `GPL-2.0-or-later WITH Bootloader-exception` | PyInstaller Development Team | Bootloader de empacotamento executável |

---

## 2. Avisos Específicos e Oferta de Código-Fonte

### 2.1. Qt 6 & PySide6 (LGPLv3 / GPLv3)
Este programa utiliza **Qt 6** e **PySide6** (Copyright (C) The Qt Company Ltd. e outros contribuidores), licenciados sob a **GNU Lesser General Public License v3.0 (`LGPL-3.0-only`)** e **GNU General Public License v3.0 (`GPL-3.0-only`)**.
- Nos pacotes binários do DA-V, as bibliotecas compartilhadas do Qt (`.dll` no Windows e `.so` no Linux) são distribuídas como arquivos dinâmicos independentes dentro do diretório da aplicação (`_internal/PySide6/`), permitindo sua inspeção e substituição pelo usuário nos termos da Seção 4 da LGPLv3.
- O código-fonte oficial do Qt e do PySide6 está disponível em: https://code.qt.io/ e https://download.qt.io/official_releases/

### 2.2. FFmpeg, PyAV, x264 e x265 (LGPLv3 / GPLv2+)
Este software utiliza bibliotecas do projeto **FFmpeg** (https://ffmpeg.org/) empacotadas via **PyAV** (https://github.com/PyAV-Org/PyAV), bem como os codificadores **x264** (https://www.videolan.org/developers/x264.html) e **x265** (https://www.videolan.org/developers/x265.html), licenciados sob `LGPL-3.0-or-later` e `GPL-2.0-or-later`.
- O código-fonte completo do DA-V está disponível publicamente em https://github.com/DanteFerraz/DA-V__Distribuidor_Aamplo-Video.
- Os códigos-fonte correspondentes das bibliotecas binárias empacotadas nas wheels oficiais do PyAV encontram-se disponíveis nos repositórios oficiais https://github.com/PyAV-Org/PyAV, https://git.ffmpeg.org/ffmpeg.git e https://code.videolan.org/videolan/x264.

### 2.3. KCP Protocol (`third_party/kcp/`) — MIT License
```text
MIT License

Copyright (c) 2011-2017 skywind3000 (at) gmail.com

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

### 2.4. OpenSSL 3 & Python `cryptography` (Apache License 2.0 / BSD-3-Clause)
Este produto inclui software desenvolvido pelo **OpenSSL Project** para uso no OpenSSL Toolkit (https://www.openssl.org/) e pela **Python Cryptographic Authority** (https://github.com/pyca/cryptography), licenciados sob a **Apache License, Version 2.0**.
