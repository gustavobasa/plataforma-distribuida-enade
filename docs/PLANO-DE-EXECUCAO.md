# Plano de Execução — Plataforma Distribuída de Busca do ENADE

Data do diagnóstico: 2026-11-22. Trabalho individual.

## 1. Diagnóstico do ambiente (medido em 2026-11-22)

| Item | Valor observado |
|---|---|
| SO | Windows 11 Pro (10.0.26300) |
| Docker | Docker Desktop, Engine 29.8.0, backend WSL2 (kernel 6.18) |
| Docker Compose | v5.5.1 |
| Recursos do Docker | 4 CPUs, 5,79 GiB de RAM |
| Disco livre (C:) | ~57 GB |
| Git | 2.53.0 (repositório inicializado nesta data, branch `main`) |
| Python local | 3.14.4 (usado apenas para exploração; o pipeline roda em contêiner Python 3.12) |
| Node | 24.21 (não usado) |
| Acesso à internet | `gov.br/inep` e `download.inep.gov.br` acessíveis |

Estado inicial da pasta: `CLAUDE.md`, `README.md.txt` (vazio), pastas vazias `codigo/`, `dados/`, `evidencias/`, `relatorio/` e o enunciado.

**Divergência registrada:** o CLAUDE.md cita `documento/enunciado.pdf`, mas o arquivo existente é
`documento/Documento sem título (9).pdf`. O conteúdo foi lido integralmente (7 páginas) e é o enunciado do trabalho.
Os requisitos RF01–RF25 e RNF01–RNF08 do PDF coincidem com os do CLAUDE.md. O PDF acrescenta como
**métricas obrigatórias do relatório**: volume do acervo (tabela), qualidade da extração (amostra ≥ 50),
vazão de ingestão (docs/s), **lag do consumidor Kafka**, latência p50/p95/p99 e **hit rate do Redis**.

## 2. Fontes de dados identificadas

- Página oficial: `https://www.gov.br/inep/pt-br/areas-de-atuacao/avaliacao-e-exames-educacionais/enade/provas-e-gabaritos/{ano}`
  (anos 2004–2023 e 2025; não há 2020 nem 2024).
- Padrão dos arquivos (2021–2025): `https://download.inep.gov.br/enade/provas_e_gabaritos/{ano}_PV_{curso}.pdf` (prova)
  e `{ano}_GB_{curso}.pdf` (gabarito definitivo). Há variantes `_ampliada`, `_super_ampliada`, `_ledor` (descartadas para não duplicar).
- Contagem observada de provas "padrão": 2021 = 30, 2022 = 26, 2023 = 28, 2025 = 53.
- 2019 e anteriores usam outro padrão de URL; o coletor descobre os links pela página do ano.
- Formato observado (2023): prova de 40 páginas, texto extraível (não é imagem), cabeçalho “QUESTÃO 0X”, alternativas “A … E”,
  discursivas “QUESTÃO DISCURSIVA 0X”, rodapé com marca d’água `VALIDINEP2023`. Problema conhecido: ligadura “ti” extraída como
  “ti ” ou “Ɵ” — exige normalização.

## 3. Arquitetura proposta

```
                    ┌──────────────── Camada transversal de segurança ────────────────┐
                    │  MIT Kerberos (KDC, realm ENADE.LOCAL)   OpenLDAP (dc=enade,dc=local) │
                    └──────────────────────────────────────────────────────────────────┘
 INEP (HTTPS) ─► [ingestor] ──SASL/GSSAPI──► [Kafka KRaft] ──SASL/GSSAPI──► [indexer] ──SPNEGO──► [Elasticsearch]
   PDFs locais     coleta, extração,          enade.questoes.v1 (3 part.)      bulk idempotente           índice enade-questoes
                   segmentação, produtor      enade.questoes.dlq (1 part.)     DLQ, commit manual          analisador PT-BR
                                                                                     │ invalida cache          ▲
                                                                                     ▼                         │ SPNEGO (Kerberos)
                                         navegador ◄── HTTP ──► [api FastAPI + web] ◄──► [Redis] cache/sessão/carrinho
                                                                 login LDAP (bind direto), perfis Estudante/Professor
```

Serviços Docker Compose (rede `enade-net`, domínio interno `enade.local`):

| Serviço | Imagem (fixada) | Papel | Porta no host |
|---|---|---|---|
| `kdc` | build próprio `debian:bookworm-slim` + MIT krb5 | KDC/kadmin; cria principals e keytabs em volume | — |
| `ldap` | `osixia/openldap:1.5.0` | diretório de usuários e grupos | 389 (opcional) |
| `kafka` | `apache/kafka:3.9.1` | broker+controller KRaft, SASL/GSSAPI, ACLs | — |
| `elasticsearch` | `docker.elastic.co/elasticsearch/elasticsearch:8.19.4` | índice e busca; realm Kerberos | 9200 |
| `redis` | `redis:7.4.2-alpine` | cache, sessão, carrinho (com senha) | — |
| `es-setup` | imagem da aplicação | job: template/índice, role mappings Kerberos | — |
| `kafka-setup` | `apache/kafka:3.9.1` | job: tópicos e ACLs | — |
| `ingestor` | imagem da aplicação (`python:3.12-slim-bookworm`) | job: coleta/extração/produção | — |
| `indexer` | imagem da aplicação | consumidor Kafka → Elasticsearch | — |
| `api` | imagem da aplicação | REST + OpenAPI + interface web | 8000 |
| `prometheus` | `prom/prometheus` (versão fixada) | coleta de métricas | 9090 |

## 4. Estrutura de diretórios

```
docker-compose.yml        .env.example        README.md
codigo/
  infra/kdc/              Dockerfile, kdc.conf, entrypoint (cria principals/keytabs)
  infra/krb5.conf         configuração de cliente Kerberos compartilhada
  infra/ldap/             LDIF da árvore (usuários e grupos sintéticos de teste)
  infra/kafka/            JAAS e script de inicialização
  infra/elasticsearch/    elasticsearch.yml, sinônimos PT-BR
  enade/                  pacote Python único (comum, coleta, extracao, produtor, indexer, api, web)
  testes/                 testes unitários e de integração (pytest)
scripts/                  scripts de operação (subir, ingerir, testes de falha, carga)
dados/pdfs/               PDFs baixados (ignorado no Git)
dados/extraidos/          JSON extraído (ignorado no Git)
dados/validacao/          amostra de validação manual (versionada)
dados/taxonomia/          competências/objetos de conhecimento com fonte
docs/                     STATUS, decisões, plano
evidencias/faseA..F/      logs e relatórios de execução
relatorio/                relatório SBC
```

## 5. Matriz RF/RNF → componente → teste

| Req. | Componente | Como será testado/evidenciado |
|---|---|---|
| RF01 | `enade.coleta` | log de download com URL, data, tamanho, SHA-256 |
| RF02 | `enade.extracao` | teste unitário de segmentação; contagem por prova vs. gabarito |
| RF03 | `enade.extracao` | campo `tipo_questao` (objetiva/discursiva) e `anulada` a partir do gabarito |
| RF04 | `enade.extracao.midia` | tabelas → Markdown (PyMuPDF `find_tables`); fórmulas/diagramas sinalizados; LLM opcional |
| RF05 | `enade.extracao` + `dados/taxonomia` | área/curso/ano/FG-CE do PDF; competências/objetos por classificador léxico declarado |
| RF06 | documento | campos `origem.pdf`, `origem.url`, `origem.paginas` |
| RF07 | `enade.produtor` | mensagens no tópico; offsets |
| RF08 | `enade.indexer` | contagem no índice = mensagens válidas |
| RF09/RNF04 | indexer + Kafka | `docker kill` do indexer/ES no meio da carga; contagem final; commit após bulk |
| RF10 | `_id` determinístico | reingestão do mesmo PDF; contagem igual |
| RF11 | DLQ | mensagens malformadas injetadas → tópico DLQ; fluxo continua |
| RF12–RF16 | `enade.api.busca` | testes de integração na API |
| RF17 | FastAPI OpenAPI | `/docs`, `/openapi.json`; testes de status HTTP |
| RF18 | cache Redis | hit/miss medidos; TTL; invalidação por versão do índice |
| RF19 | carrinho Redis | testes de API |
| RF20 | `enade/web` | navegação real no navegador + capturas |
| RF21 | exportação | arquivos PDF/JSON gerados |
| RF22 | Kerberos | `klist`, logs de autenticação do broker/ES, teste negativo sem ticket |
| RF23 | LDAP | login por bind direto; credencial errada → 401 |
| RF24/RF25 | autorização no backend | testes: estudante sem gabarito; 403 em rota restrita |
| RNF01 | k6 ou script Python | p50/p95/p99 com e sem cache |
| RNF02 | indexer | docs/s e tempo total registrados |
| RNF03 | amostra manual | ≥ 50 questões conferidas contra o PDF |
| RNF05 | docs | justificativa de partições/shards/réplicas |
| RNF06 | `/health`, `/metrics`, Prometheus | capturas e saídas |
| RNF07 | README + compose | subida em ambiente limpo |
| RNF08 | `.gitignore`, `.env` | varredura de segredos antes de commit |

## 6. Plano de testes

1. **Unitários (pytest, sem infraestrutura):** normalização de texto, segmentação de questões, parser de gabarito, id estável, validação de schema, classificador de competências, chave de cache.
2. **Integração (com Compose):** produtor→Kafka→indexer→ES; DLQ; idempotência; API (busca, filtros, agregações, paginação, highlight, cache, carrinho, exportação, 401/403).
3. **Segurança:** cliente sem ticket Kerberos rejeitado pelo Kafka e pelo ES; principal sem ACL rejeitado; login LDAP inválido → 401; estudante → 403.
4. **Falha induzida:** matar o indexer e o Elasticsearch durante a ingestão; verificar contagem final e lag.
5. **Carga:** latência p50/p95/p99 com e sem cache; hit rate do Redis.

## 7. Riscos específicos (Docker no Windows)

| Risco | Impacto | Mitigação |
|---|---|---|
| Memória (5,8 GiB) para ES + Kafka + demais | OOM / lentidão | heap ES 1 GB, Kafka 512 MB; um nó de cada; Grafana opcional |
| `vm.max_map_count` no WSL2 para ES | ES não inicia | modo single-node (sem bootstrap checks de produção); documentar `wsl -d docker-desktop sysctl` se necessário |
| Kerberos depende de nomes de host e relógio | falha de autenticação | FQDN fixos via `hostname`/aliases (`*.enade.local`), `rdns=false`, `dns_canonicalize_hostname=false`; relógio do WSL compartilhado |
| Realm Kerberos no ES exige licença Platinum | sem Kerberos no ES | licença **trial** autogerada (30 dias, gratuita); limitação documentada |
| librdkafka sem suporte GSSAPI no wheel | produtor/consumidor sem Kerberos | verificar `builtin.features`; alternativa: `kafka-python` + `gssapi` |
| SASL_PLAINTEXT não cifra o tráfego | confidencialidade | Kerberos garante autenticação mútua; TLS documentado como melhoria |
| OneDrive sincronizando a pasta do projeto | arquivos bloqueados, lentidão, finais de linha CRLF | dados e volumes em volumes Docker; `.gitattributes` com `eol=lf` para scripts |
| Caminho com acento e espaço (`Área de Trabalho`) | quebra de scripts | aspas em todos os scripts; bind mounts mínimos |
| Keytabs em bind mount do Windows | permissões | keytabs ficam em volume Docker nomeado, nunca no Git |
| PDFs heterogêneos (layout muda por ano) | extração incorreta | foco em 2021–2023 (layout homogêneo); taxa de acerto medida |
| Competências não vêm por questão no PDF | metadado RF05 inferido | classificador léxico explícito, marcado como "inferido" |

## 8. Fases

A (fundação) → B (coleta/extração) → C (Kafka/ES) → D (API/Redis/Web) → E (segurança fim a fim) → F (avaliação e relatório).
Como Kerberos é transversal e o maior risco técnico, ele é configurado já na Fase A (KDC, Kafka e ES autenticando), e a Fase E
cobre LDAP, perfis e testes de negação.
