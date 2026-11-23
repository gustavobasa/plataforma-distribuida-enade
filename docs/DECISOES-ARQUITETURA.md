# Decisões de Arquitetura (ADR resumidas)

Formato: decisão — justificativa — trade-off. Atualizado a cada fase.

## ADR-01 — Um nó de cada componente no laboratório
- **Decisão:** 1 broker/controller Kafka (KRaft combinado), 1 nó Elasticsearch, 1 Redis, 1 KDC, 1 OpenLDAP.
- **Justificativa:** o Docker Desktop disponível tem 4 CPUs e 5,8 GiB de RAM; ES e Kafka são as cargas dominantes de memória.
- **Trade-off:** sem alta disponibilidade real; réplicas não podem ser alocadas em um único nó (índice com `number_of_replicas: 0`).
  A escalabilidade horizontal é garantida pelo desenho (partições e shards), não pela topologia do laboratório (ver ADR-04).

## ADR-02 — Kafka 3.9.1 em modo KRaft com SASL/GSSAPI
- **Decisão:** `apache/kafka:3.9.1`, sem ZooKeeper, listeners autenticados via Kerberos, `StandardAuthorizer` com ACLs por principal.
- **Justificativa:** KRaft é o modo recomendado; a imagem oficial Apache é configurável por variáveis de ambiente.
- **Trade-off:** `SASL_PLAINTEXT` autentica, mas não cifra. TLS (`SASL_SSL`) fica como melhoria.

## ADR-03 — Tópicos, chave e partições
- `enade.questoes.v1`: 3 partições, chave = `id` da questão (hash estável) → mesma questão sempre na mesma partição (ordem por questão).
  3 partições permitem até 3 consumidores paralelos no mesmo grupo.
- `enade.questoes.dlq`: 1 partição; volume baixo, ordem de chegada útil para diagnóstico.
- `replication.factor=1` (um broker). Em produção: RF=3 e `min.insync.replicas=2`.
- Produtor com `acks=all` e `enable.idempotence=true`.

## ADR-04 — Elasticsearch: índice, shards e réplicas
- Índice `enade-questoes-v1` atrás do alias `enade-questoes`; 1 shard primário, 0 réplicas (um nó).
- Justificativa: o acervo previsto (milhares de questões, dezenas de MB) cabe com folga em 1 shard (recomendação geral: 10–50 GB por shard).
  O alias permite reindexar para um índice com mais shards sem mudar a API.
- Analisador `pt_br_custom`: tokenizer padrão, `lowercase`, `asciifolding` (preservando original), stopwords `_brazilian_`, sinônimos
  (`synonym_graph` no tempo de busca) e `stemmer` `light_portuguese`/`brazilian`.

## ADR-05 — Kerberos no Elasticsearch via realm `kerberos` (licença trial)
- **Decisão:** habilitar o realm Kerberos (SPNEGO) do ES; serviços Python autenticam com `requests-gssapi` e autenticação mútua obrigatória.
- **Justificativa:** é o mecanismo nativo do ES para Kerberos.
- **Trade-off/limitação:** o realm Kerberos é recurso pago; usa-se a licença `trial` autogerada (30 dias, sem custo). Após expirar, o
  realm deixa de funcionar. Isso será registrado no relatório e no README.

## ADR-06 — Idempotência
- `id` = SHA-256 de `(ano, curso_slug, tipo_prova, numero_questao)` truncado; usado como chave Kafka e `_id` no ES.
- Reprocessar o mesmo PDF gera os mesmos ids → `index` sobrescreve em vez de duplicar.

## ADR-07 — Commit de offset após indexação (at-least-once + idempotência ⇒ efeito exatamente-uma-vez)
- Consumidor com `enable.auto.commit=false`; commit síncrono apenas depois que o bulk no ES foi confirmado.
- Falha no meio → mensagens não confirmadas são relidas; como o `_id` é determinístico, não há duplicação.

## ADR-08 — Cache e invalidação
- Chave = `cache:busca:v{versao_indice}:{perfil}:{sha256(parâmetros normalizados)}`; TTL configurável (padrão 300 s).
- O indexer incrementa `indice:versao` no Redis após cada bulk confirmado ⇒ chaves antigas deixam de ser usadas e expiram pelo TTL.
- O perfil faz parte da chave para impedir que uma resposta de Professor (com gabarito) seja servida a Estudante.

## ADR-09 — Stack da aplicação
- Python 3.12 em uma única imagem (`codigo/enade`) para ingestor, indexer e API — reduz build e mantém utilitários comuns.
- FastAPI (OpenAPI automático), `ldap3` (bind LDAP direto), `redis-py`, `elasticsearch-py` 8 com nó `requests` + `requests-gssapi`,
  PyMuPDF para extração, ReportLab para PDF.
- Interface: HTML/JS sem build, servido pela API, com KaTeX (fórmulas), Mermaid (diagramas) e sanitização com DOMPurify.

## ADR-10 — Competências e objetos de conhecimento (RF05)
- Os PDFs não informam a competência de cada questão. A taxonomia vem das portarias/diretrizes do INEP (fonte registrada em
  `dados/taxonomia/`) e a atribuição é feita por classificador léxico determinístico. O campo é marcado como `inferido` e sua
  qualidade será medida na amostra manual.

## ADR-11 — librdkafka compilado com Cyrus SASL
- **Problema observado:** o wheel binário do `confluent-kafka` 2.10.0 não traz GSSAPI ("No provider for SASL mechanism GSSAPI").
- **Decisão:** estágio de build que compila o librdkafka 2.10.0 com `--enable-sasl` e instala o `confluent-kafka` sem wheel.
- **Trade-off:** build ~2 min mais longo; ganho: Kerberos real no produtor/consumidor Python, sem trocar de biblioteca.

## ADR-12 — Cadeia TLS do INEP
- `download.inep.gov.br` envia só o certificado folha. Em vez de desativar a verificação TLS, o projeto versiona a CA
  intermediária pública (RNP ICPEdu GR46 OV TLS CA 2025, emitida pela GlobalSign Root R46, obtida pela URL AIA do
  próprio certificado) e a acrescenta ao bundle do `certifi`.

## ADR-13 — Extração determinística (sem LLM) e suas limitações
- PyMuPDF `rawdict` para reconstruir linhas; correções específicas dos PDFs do INEP (espaço espúrio de ligadura,
  fonte Symbol, índices/expoentes por tamanho e linha de base -> LaTeX inline), detecção de duas colunas (2021/2022),
  tabela de distribuição da capa para FG/CE, alternativas A–E ou A–D (Medicina 2023), tabelas com borda -> Markdown.
- Figuras e diagramas são recortados como PNG e exibidos/exportados; **não** são convertidos para Mermaid (exigiria LLM).
- Sem LLM o custo é zero e o resultado é reprodutível; a qualidade é medida na amostra manual (RNF03).

## ADR-14 — Esquema estrito e validação dupla
- O mesmo modelo Pydantic (`extra="forbid"`) valida no produtor e no consumidor; o mapping do ES é `dynamic: strict`.
  Campos desconhecidos são erro explícito e a mensagem vai para a DLQ, nunca são descartados em silêncio.

## ADR-15 — Ordem do analisador de busca
- `lowercase → stop (_brazilian_) → asciifolding → stemmer light_portuguese → synonym_graph` (só na busca).
- Sinônimos depois do stemming fazem as regras do dicionário serem radicalizadas pelo mesmo analisador; assim
  "desigualdade" e "desigualdades" expandem para os mesmos sinônimos (falha encontrada pelo teste de integração).

## ADR-16 — Segredos por serviço
- Os contêineres não recebem o `.env` inteiro: cada serviço recebe só as variáveis de que precisa
  (ex.: só o `es-setup` conhece `ELASTIC_PASSWORD`; só a API conhece a senha da conta LDAP somente leitura).
- Cada serviço monta apenas o próprio subdiretório de keytab (volume `keytabs` com `subpath`).

## ADR-17 — Figuras: conversão determinística dos vetores do PDF (sem LLM)
- **Decisão:** reconstruir diagramas a partir dos objetos vetoriais (formas com texto = nós; linhas, curvas e hastes
  unidas por extremidades = ligações; triângulos pequenos preenchidos = pontas de seta) e gerar `flowchart` Mermaid;
  demais figuras recebem seus textos em Markdown (pesquisáveis).
- **Justificativa:** o RF04 admite LLM apenas "se preciso"; o usuário optou por custo zero. É reprodutível e roda em
  ~90 s para as 1.540 figuras.
- **Validação:** todo Mermaid é compilado no mermaid-cli 10.9.1 (44/44 OK); aceite exige maioria de nós rotulados e
  ligados, o que reduz falsos positivos (ilustrações com círculos, colunas empilhadas).
- **Trade-off:** imagens raster (579 sem texto) não são convertidas; circuitos e gráficos viram só texto; a fidelidade
  semântica depende de heurísticas (há falsos positivos em listas com colchetes). Um módulo com LLM (Claude via
  Batches) ficou implementado como alternativa paga, não executado.
