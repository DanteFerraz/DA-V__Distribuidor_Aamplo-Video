---
doc_type: adr
diataxis_quadrant: explanation
adr_id: "0001"
title: "Instituição da licença GNU AGPLv3 com termos adicionais da Seção 7 (NOTICE obrigatório)"
status: "accepted"
date: 2026-11-23
decision-makers: "Dante Ferraz"
consulted: "Auditoria Jurídica-Técnica MonoTech"
informed: "Comunidade e usuários do DA-V"
---

# ADR-0001: Instituição da licença GNU AGPLv3 com termos adicionais da Seção 7 (NOTICE obrigatório)

## Context and problem statement

O **DA-V (Distribuidor Amplo de Vídeo)** foi inicialmente configurado com um arquivo `LICENSE` sob licença **MIT**, enquanto a filosofia institucional definida pelo autor (**Dante Ferraz / MonoTech**) estabelece que o software deve ser disponibilizado **100% gratuitamente e sem chaves de ativação**, com o objetivo de democratizar tecnologia de streaming P2P de ultra-baixa latência e consolidar a autoria técnica de Dante Ferraz.

A auditoria forense dos binários e dependências empacotados revelou dois problemas estruturais sob a licença MIT isolada:

1. **Risco de apropriação fechada e remoção de vitrine autoral:** A licença MIT permite que terceiros fechem o código-fonte do DA-V (e do servidor `DAV-Rendezvous` / Blind Relay), removam a janela interativa de autoria e comercializem derivados proprietários sem devolver melhorias à comunidade.
2. **Incompatibilidade de distribuição binária com dependências GPL/LGPL:** Os pacotes binários distribuídos pelo projeto incluem `PySide6` (`LGPL-3.0-only OR GPL-3.0-only`), bibliotecas `FFmpeg` (`LGPL-3.0-or-later`) e os codificadores `libx264` e `libx265` (`GPL-2.0-or-later`). Distribuir binários contendo bibliotecas `GPL-2.0-or-later` e `LGPL-3.0` exige conformidade com as condições da família GPLv3.

## Decision drivers

- Manter o DA-V **100% gratuito e aberto**, sem paywalls, sem limites de sessão e sem sistema de chaves de ativação.
- Garantir que o arquivo `NOTICE` e a atribuição autoral a **Dante Ferraz (MonoTech)** na interface gráfica sejam **juridicamente obrigatórios e irremovíveis** em qualquer redistribuição ou fork.
- Impedir que terceiros fechem o código-fonte do aplicativo desktop ou operem versões modificadas do servidor `DAV-Rendezvous` em nuvem (SaaS) sem disponibilizar o código-fonte.
- Assegurar 100% de compatibilidade legal com `PySide6` (Qt 6), `FFmpeg`, `libx264`, `libx265`, `OpenSSL 3` (`Apache-2.0`) e `KCP` (`MIT`).

## Considered options

- **Opção 1:** Manter licença `MIT` adicionando apenas `THIRD_PARTY_LICENSES.md`.
- **Opção 2:** Migrar para `Apache-2.0` com arquivo `NOTICE`.
- **Opção 3:** Instituir `GNU AGPL-3.0-or-later` suplementada pelos Termos Adicionais da Seção 7 (alíneas 7(b) a 7(e)) e Seção 5(d) (`NOTICE` e atribuição obrigatórios), acompanhada de `TRADEMARK.md` e `THIRD_PARTY_LICENSES.md`.

## Decision outcome

Escolhida a **Opção 3: GNU Affero General Public License v3.0 ou posterior (`AGPL-3.0-or-later`) com Termos Adicionais da Seção 7 (alíneas 7(b) a 7(e))**.

### Justificativa

1. **Preservação irremovível de autoria (`NOTICE` + UI):** As alíneas **7(b), 7(c), 7(d) e 7(e)** combinadas com a **Seção 5(d)** da GNU AGPLv3 permitem exigir legalmente a preservação integral do arquivo `NOTICE`, a exibição dos créditos de **Dante Ferraz (MonoTech)** na janela *"Sobre & Licenças"*, a marcação clara de versões modificadas e a reserva das marcas `"DA-V"` e `"MonoTech"`.
2. **Proteção Desktop + Nuvem (Seção 13):** A AGPLv3 protege tanto os binários desktop (Windows/Linux) quanto o microserviço `DAV-Rendezvous` (SSE + Blind Relay UDP) contra apropriação fechada em nuvem.
3. **Harmonização plena com dependências:** `libx264` e `libx265` (`GPL-2.0-or-later`) elevam-se para `GPL-3.0` e combinam-se nativamente com `AGPL-3.0` via Seção 13; `PySide6` (`LGPL-3.0`) e `OpenSSL 3` (`Apache-2.0`) são integralmente compatíveis.

### Consequências positivas

- O crédito autoral de **Dante Ferraz (MonoTech)** e o arquivo `NOTICE` tornam-se obrigatórios em todo o ecossistema e em qualquer fork.
- O módulo `src/dav/modules/commercial/` fica simplificado e alinhado à missão 100% gratuita, fornecendo governança de licenças e avisos de terceiros sem lógica artificial de tokens pagos.
- Os pacotes binários Windows e Linux passam a incluir `LICENSE`, `NOTICE`, `TRADEMARK.md`, `THIRD_PARTY_LICENSES.md` e `LICENSES/`, além de excluir módulos Qt ociosos (`QtVirtualKeyboard`, `QtPdf`, `QtQml`, `QtQuick`).

### Consequências negativas e mitigação

- Versões anteriores (`<= v4.9.0`) foram publicadas sob MIT. **Mitigação adotada:** Como o repositório possuía `0 stars` e `0 forks`, o repositório legado é arquivado como **Privado** (`DA-V__Archive_Legacy`) para preservação histórica do autor e o repositório público oficial (`DA-V__Distribuidor_Aamplo-Video`) passa a expor histórico limpo iniciando diretamente sob `AGPL-3.0-or-later` + Seção 7.
