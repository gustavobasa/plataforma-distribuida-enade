# Roteiro do vídeo de demonstração (máx. 5 min)

Objetivo exigido pelo enunciado: demonstrar **fluxo**, **busca interdisciplinar**, **cache** e **perfis**, incluindo o
**HTTP 403** de Estudante em rota restrita. Tempo-alvo: 4 min 30 s (margem de 30 s).

## Preparação (antes de gravar, fora do vídeo)
1. `docker compose up -d` e conferir `docker compose ps` (todos *healthy*).
2. Ter o acervo já extraído (`enade.extracao`) — a extração completa leva ~11 min e não cabe no vídeo.
3. Abrir: terminal na raiz do repositório; navegador em http://localhost:8000 (aba anônima para o Estudante e aba
   normal para o Professor); http://localhost:8000/docs.
4. Ter as senhas de teste à mão (no `.env`), **sem mostrá-las na tela**.
5. Zerar contadores do cache (Professor → aba Operação, ou `POST /api/admin/cache/zerar-contadores`).

## Cenas
| Tempo | Cena | O que mostrar / dizer |
|---|---|---|
| 0:00–0:25 | Arquitetura | `docker compose ps` com KDC, LDAP, Kafka, Elasticsearch, Redis, indexer, API, Prometheus saudáveis. Uma frase por camada. |
| 0:25–1:15 | Fluxo PDF → Kafka → Elasticsearch | Terminal: `docker compose run --rm ingestor python -m enade.produtor --anos 2023 --cursos engenharia_da_computacao` (40 questões). Em seguida, aba Operação (Professor): mensagens no tópico, lag voltando a 0 e documentos no índice. Mencionar que a autenticação no Kafka e no ES é Kerberos (`/health/ready` mostra `sasl/gssapi` e `kerberos/spnego`). |
| 1:15–1:35 | Rastreabilidade | Abrir uma questão: texto, fórmula renderizada (KaTeX), figura recortada, e o link "Origem: …pdf, página N" abrindo o PDF oficial na página. |
| 1:35–2:30 | Busca interdisciplinar | Buscar **"ética"**: resultados de vários cursos, destaque `<mark>`, facetas por curso/área/ano. Marcar "Agrupar questões idênticas entre cursos" e abrir "Questões equivalentes em outros cursos" de uma questão de Formação Geral (mesma questão em ~26 cursos). Buscar "idadismo" para mostrar sinônimo → "etarismo". Combinar filtros (ano 2022 + CE + área). |
| 2:30–3:15 | Cache Redis | Na linha de resumo, repetir a mesma busca: "cache MISS · ~20 ms" → "cache HIT · ~4 ms". Mostrar a aba Operação (hits/misses/hit rate, versão do índice) e o botão "Invalidar cache" → próxima busca volta a MISS. Citar o resultado do k6: p95 19,8 ms sem cache e 6,6 ms com cache. |
| 3:15–4:15 | Perfis e 403 | **Estudante** (aba anônima): busca funciona, detalhe da questão sem gabarito; clicar "Ver gabarito" → mensagem "Acesso negado (HTTP 403)". Mostrar o mesmo em `/docs` ou terminal: `curl -i -H "Authorization: Bearer <token-estudante>" localhost:8000/api/questoes/<id>/gabarito` → `HTTP/1.1 403 Forbidden`. **Professor**: mesmo botão mostra o gabarito; adicionar 2 questões à lista e exportar PDF (abrir o PDF com folha de respostas). |
| 4:15–4:30 | Encerramento | Resiliência em uma frase (falha induzida: 3.360/3.360 documentos, sem duplicata) e onde estão as evidências (`docs/STATUS.md`). |

## Dicas
- Gravar em 1280×720 com zoom do navegador em 110%.
- Não exibir o `.env` nem tokens completos na tela.
- Se algo demorar, cortar na edição; o enunciado desconsidera o que passar de 5 min.
