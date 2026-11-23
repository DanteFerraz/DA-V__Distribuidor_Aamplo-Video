---
doc_type: session-report
diataxis_quadrant: explanation
project: "DA-V (Distribuidor Amplo de Vídeo)"
session_date: 2026-11-23
main_line: "Instituição da licença GNU AGPLv3 com termos adicionais da Seção 7 (NOTICE obrigatório) e compliance de terceiros"
author: "Dante Ferraz"
status: "verified"
related_adrs:
  - "docs/decisions/0001-instituicao-licenca-agplv3-secao-7.md"
related_commits: []
---

# Relatório de sessão — 2026-11-23: Instituição da licença GNU AGPLv3 com termos adicionais da Seção 7 (NOTICE obrigatório) e compliance de terceiros

## Resumo executivo

A sessão realizou a auditoria jurídica-técnica completa das dependências e binários empacotados no DA-V e instituiu a licença **GNU Affero General Public License v3.0 ou posterior (`AGPL-3.0-or-later`)** suplementada pelos **Termos Adicionais da Seção 7 (alíneas 7(b) a 7(e)) e Seção 5(d)** sob modelo **100% gratuito e sem chaves de ativação**. Foram criados os artefatos normativos `LICENSE`, `NOTICE`, `TRADEMARK.md`, `THIRD_PARTY_LICENSES.md`, `LICENSES/` (`AGPL-3.0.txt`, `GPL-3.0.txt`, `LGPL-3.0.txt`), `third_party/kcp/LICENSE` e `[ADR-0001](../decisions/0001-instituicao-licenca-agplv3-secao-7.md)`, aplicados cabeçalhos SPDX em 201 arquivos-fonte autorais (`140` Python e `61` C/C++), atualizado o módulo `commercial` e o diálogo `AuthorShowcaseDialog` com exibição interativa de `NOTICE` e licenças de terceiros, e higienizado o empacotamento PyInstaller.

## Requisitos e objetivos endereçados

- **OBJ-01:** Instituir a licença `GNU AGPL-3.0-or-later` com suplemento obrigatório da Seção 7 (`7(b)` preservação de `NOTICE` e atribuição a Dante Ferraz / MonoTech, `7(c)` identificação de versões modificadas, `7(d)` vedação de endosso sem autorização e `7(e)` reserva de marcas e ícone oficial).
- **OBJ-02:** Adequar o módulo `src/dav/modules/commercial/` e a janela `AuthorShowcaseDialog` ao modelo 100% gratuito sem chaves de ativação, exibindo os Avisos Legais Apropriados (Seção 5(d)) e o inventário completo de licenças de terceiros (`PySide6`, `FFmpeg`, `x264`, `x265`, `KCP`, `OpenSSL 3`).
- **OBJ-03:** Embutir os artefatos de licença nos pacotes Windows e Linux e remover módulos Qt ociosos (`QtVirtualKeyboard`, `QtPdf`, `QtQuick`, `QtQml`, `QtWebEngineCore`) do bundle PyInstaller.

## Alterações realizadas por artefato

| Arquivo | Ação | Camada / Bloco C4 | Descrição objetiva da alteração |
| :--- | :--- | :--- | :--- |
| `LICENSE` | Modificado | `Governance / Legal` | Substituição pelo texto oficial da GNU AGPLv3 acrescido do adendo formal da Seção 7(b–e). |
| `NOTICE` | Criado | `Governance / Legal` | Declaração normativa de atribuição obrigatória a Dante Ferraz (MonoTech), origem, não-endosso e reserva de marcas. |
| `TRADEMARK.md` | Criado | `Governance / Legal` | Política de proteção dos nomes `DA-V`, `MonoTech` e do ícone oficial Glassmorphism (Seção 7(e)). |
| `THIRD_PARTY_LICENSES.md` | Criado | `Governance / Compliance` | Inventário detalhado e oferta de código-fonte de `PySide6/Qt6`, `PyAV/FFmpeg`, `x264/x265`, `KCP`, `OpenSSL 3` e demais dependências. |
| `LICENSES/AGPL-3.0.txt`, `GPL-3.0.txt`, `LGPL-3.0.txt` | Criado | `Governance / Compliance` | Textos integrais das licenças GNU aplicáveis ao projeto e suas bibliotecas dinâmicas. |
| `third_party/kcp/LICENSE` | Criado | `Third-Party / KCP` | Preservação formal da licença MIT do protocolo KCP (`skywind3000`). |
| `docs/decisions/0001-instituicao-licenca-agplv3-secao-7.md` | Criado | `Architecture / ADR` | Registro formal MADR 4.0 da decisão de licenciamento e estratégia de arquivamento privado do histórico MIT. |
| `src/dav/modules/commercial/*` | Modificado | `Commercial Slice` | Remoção de tokens legados e implementação de governança 100% gratuita com leitura e auditoria de `LICENSE`, `NOTICE` e `THIRD_PARTY_LICENSES.md`. |
| `src/dav/modules/presentation/author_dialog.py` | Modificado | `Presentation Slice` | Evolução de `AuthorShowcaseDialog` com 3 abas (`Autoria & Ecossistema`, `Licença & NOTICE (Seção 7)` e `Licenças de Terceiros`). |
| `scripts/dav_installer_win.py`, `scripts/dav_installer_linux.py` | Modificado | `Installers` | Exibição da licença `GNU AGPLv3 + Seção 7` na barra lateral e no card de boas-vindas. |
| `scripts/build_windows.ps1`, `scripts/build_linux_bundle.sh`, `scripts/build_linux_source_tarball.py`, `.github/workflows/release.yml` | Modificado | `Build & CI/CD` | Empacotamento de `LICENSE`, `NOTICE`, `TRADEMARK.md`, `THIRD_PARTY_LICENSES.md` e `LICENSES/` e exclusão de módulos Qt não utilizados. |
| `src/**`, `scripts/**`, `include/**`, `tests/**` | Modificado | `Codebase SPDX` | Aplicação do cabeçalho `SPDX-License-Identifier: AGPL-3.0-or-later` em 140 arquivos Python e 61 arquivos C/C++ autorais. |

## Decisões arquiteturais e justificativas

- **Decisão registrada:** Documentada integralmente em `[ADR-0001](../decisions/0001-instituicao-licenca-agplv3-secao-7.md)`. A adoção de `AGPL-3.0-or-later` com termos adicionais da Seção 7(b–e) protege simultaneamente o aplicativo desktop e o servidor `DAV-Rendezvous`, torna o arquivo `NOTICE` e os créditos de Dante Ferraz juridicamente irremovíveis e harmoniza a distribuição binária com `libx264`/`libx265` (`GPL-2.0-or-later`) e `PySide6` (`LGPL-3.0`).

## Evidências de verificação e testes

- **Suíte / Linter / Verificação:** `py -m pytest tests/ -v`
  - **Resultado observado:** `81 passed` (incluindo `test_mandatory_notice_and_third_party_compliance_files` e verificação das 3 abas em `test_presentation_author_dialog_instantiation`).
- **Suíte / Linter / Verificação:** `py scripts/gui_app.py --self-check`
  - **Resultado observado:** `DAV_SELF_CHECK_OK`
- **Suíte / Linter / Verificação:** `doc_lint.py` (`--type madr` e `--type session`)
  - **Resultado observado:** `[PASS]` em ambos os documentos.
- **Artefatos validados manualmente ou via ferramenta:** Pacotes `release_assets/DA-V_v4.9.0_Linux_Source_Portable.tar.gz`, `release_assets/DA-V_Instalador_Windows_x64.exe` e `release_assets/DA-V_v4.9.0_Windows_x64_Portable.zip` reconstruídos contendo todos os arquivos de governança e compliance.

## Riscos, dívida técnica e desvios conhecidos

- Nenhum desvio estrutural aberto nesta sessão.

## Próximos passos verificáveis

1. Concluir o arquivamento do repositório legado como privado (`DA-V__Archive_Legacy`) e publicar o repositório público limpo (`DA-V__Distribuidor_Aamplo-Video`) iniciando diretamente sob `AGPL-3.0-or-later` + Seção 7.
