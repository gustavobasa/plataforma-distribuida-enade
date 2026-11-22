# STATUS do Projeto

Legenda: ⬜ não iniciado · 🟡 em andamento · ✅ concluído e testado · 🟠 parcial · ⛔ bloqueado

Última atualização: 2026-11-22 (Fase A iniciada)

## Requisitos funcionais

| ID | Requisito | Estado | Evidência | Pendência |
|---|---|---|---|---|
| RF01 | Coleta do acervo | ⬜ | — | — |
| RF02 | Segmentação | ⬜ | — | — |
| RF03 | Tipos de questão / anuladas | ⬜ | — | — |
| RF04 | Mídia não textual | ⬜ | — | — |
| RF05 | Metadados mínimos | ⬜ | — | — |
| RF06 | Rastreabilidade PDF/página | ⬜ | — | — |
| RF07 | Publicação Kafka | ⬜ | — | — |
| RF08 | Consumo e indexação | ⬜ | — | — |
| RF09 | Tolerância a falhas | ⬜ | — | — |
| RF10 | Idempotência | ⬜ | — | — |
| RF11 | DLQ | ⬜ | — | — |
| RF12 | Filtros combináveis | ⬜ | — | — |
| RF13 | Full-text PT-BR | ⬜ | — | — |
| RF14 | Interdisciplinaridade | ⬜ | — | — |
| RF15 | Agregações | ⬜ | — | — |
| RF16 | Paginação e highlight | ⬜ | — | — |
| RF17 | OpenAPI e status HTTP | ⬜ | — | — |
| RF18 | Cache Redis | ⬜ | — | — |
| RF19 | Carrinho Redis | ⬜ | — | — |
| RF20 | Interface web | ⬜ | — | — |
| RF21 | Exportação PDF/JSON | ⬜ | — | — |
| RF22 | Kerberos entre serviços | 🟡 | — | — |
| RF23 | Login LDAP | ⬜ | — | — |
| RF24 | Perfis | ⬜ | — | — |
| RF25 | HTTP 403 | ⬜ | — | — |

## Requisitos não funcionais

| ID | Requisito | Estado | Evidência | Pendência |
|---|---|---|---|---|
| RNF01 | Latência p50/p95/p99 | ⬜ | — | — |
| RNF02 | Vazão de ingestão | ⬜ | — | — |
| RNF03 | Qualidade da extração (≥ 50) | ⬜ | — | — |
| RNF04 | Falha induzida | ⬜ | — | — |
| RNF05 | Escalabilidade justificada | 🟡 | docs/DECISOES-ARQUITETURA.md | — |
| RNF06 | Health/logs/métricas | ⬜ | — | — |
| RNF07 | Reprodutibilidade | ⬜ | — | — |
| RNF08 | Sem segredos no Git | 🟡 | .gitignore | — |

## Riscos e pendências
Ver `docs/PLANO-DE-EXECUCAO.md` §7.

## Próxima ação
Fase A: subir KDC, LDAP, Kafka (GSSAPI), Elasticsearch (Kerberos), Redis com health checks.
