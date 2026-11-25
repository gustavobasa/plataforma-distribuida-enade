# Plataforma Distribuída de Busca e Indexação do ENADE

Trabalho prático de Sistemas Distribuídos. A plataforma coleta as provas oficiais do ENADE no portal do
INEP, extrai cada questão como um documento estruturado, publica os documentos no **Apache Kafka**, indexa no
**Elasticsearch** e oferece uma API REST + interface web com cache e lista de questões no **Redis**, login de usuários
no **OpenLDAP** e autenticação mútua entre serviços via **Kerberos** (MIT).

- Acervo atual: **84 provas (2021, 2022 e 2023) → 3.360 questões**, cada uma com PDF e página de origem.
- Estado detalhado e evidências de cada requisito: [docs/STATUS.md](docs/STATUS.md).
- Decisões e justificativas: [docs/DECISOES-ARQUITETURA.md](docs/DECISOES-ARQUITETURA.md) · Plano: [docs/PLANO-DE-EXECUCAO.md](docs/PLANO-DE-EXECUCAO.md).

## Arquitetura

```
 INEP (HTTPS) ─► ingestor ──SASL/GSSAPI──► Kafka (KRaft) ──SASL/GSSAPI──► indexer ──SPNEGO──► Elasticsearch
  coleta+extração  produtor    enade.questoes.v1 (3 partições)    consumidor, DLQ        índice PT-BR
                               enade.questoes.dlq (1 partição)        │ invalida cache          ▲ SPNEGO
                                                                      ▼                         │
                        navegador ◄──HTTP──► api (FastAPI + web) ◄──► Redis (cache, sessão, carrinho)
                                             └─ login: bind no OpenLDAP; perfis Estudante / Professor
 Kerberos (KDC, realm ENADE.LOCAL): principals kafka/…, HTTP/elasticsearch…, ingestor, indexer, api
 Observabilidade: /health/ready, /metrics (Prometheus em :9090), logs JSON (docker compose logs)
```

## Pré-requisitos
- Docker Desktop com **≥ 4 CPUs e ≥ 6 GB de RAM** para o Docker (testado: Engine 29.8, Compose v5.5, Windows 11 + WSL2).
- ~8 GB de disco (imagens) + ~1 GB para o acervo (PDFs, JSON e figuras ficam no volume Docker `acervo`).
- Internet para baixar imagens, dependências e as provas do INEP.

## Como executar (passo a passo)

Todos os comandos são executados na raiz do repositório (PowerShell ou Git Bash).

1. **Gerar o `.env`** com senhas aleatórias (o arquivo não vai para o Git):
   ```powershell
   powershell -ExecutionPolicy Bypass -File scripts/gerar-env.ps1
   ```
   (Linux/Git Bash: `sh scripts/gerar-env.sh`). As senhas dos usuários de teste ficam em `LDAP_SENHA_ESTUDANTES` e
   `LDAP_SENHA_PROFESSORES` dentro do `.env`.

2. **Subir a plataforma** (KDC, LDAP, Kafka, Elasticsearch, Redis, jobs de setup, indexer, API, Prometheus):
   ```powershell
   docker compose up -d --build
   ```
   O primeiro build leva ~5 min (compila o librdkafka com suporte a Kerberos). Os jobs `kafka-setup`, `ldap-setup` e
   `es-setup` rodam sozinhos e criam tópicos/ACLs, árvore LDAP e índice/papéis.

3. **Coletar e extrair as provas** (~15 min para 2021–2023):
   ```powershell
   docker compose run --rm ingestor python -m enade.coleta --anos 2021 2022 2023
   docker compose run --rm ingestor python -m enade.extracao --anos 2021 2022 2023
   ```
   Para um teste rápido use, por exemplo, `--anos 2023 --cursos engenharia_da_computacao`.
   PDFs locais: copie para `dados/locais/` e rode
   `docker compose run --rm ingestor python -m enade.extracao --local /dados/locais/prova.pdf --ano 2023 --curso meu_curso --gabarito /dados/locais/gabarito.pdf`.

4. **Publicar no Kafka** (o indexer consome e indexa automaticamente):
   ```powershell
   docker compose run --rm ingestor python -m enade.produtor
   ```

5. **Usar**: abra http://localhost:8000 e entre como `estudante1` ou `professor1` (senhas no `.env`).
   Documentação OpenAPI/Swagger: http://localhost:8000/docs · Prometheus: http://localhost:9090.

## Testes e medições

| O que | Comando |
|---|---|
| Unitários (sem infraestrutura) | `docker compose run --rm --no-deps ingestor python -m pytest -q testes/test_unitarios.py` |
| Integração da API (RF12–RF25) | `docker compose --profile testes run --rm testes` |
| Kerberos/ACL (RF22) | `docker compose --profile testes run --rm testes-kerberos` |
| DLQ (RF11) | `docker compose run --rm ingestor python -m enade.ferramentas.injetar_invalidas` e `docker compose exec api python -m enade.ferramentas.ler_dlq` |
| Vazão e lag (RNF02) | `bash scripts/medir-ingestao.sh` (Git Bash) |
| Falha induzida (RF09/RNF04) | `bash scripts/experimento-falha.sh` (recria o índice e reprocessa o tópico) |
| Latência p50/p95/p99 (RNF01) | `docker compose --profile carga run --rm k6` |
| Validação manual da extração (RNF03) | entre como Professor e abra http://localhost:8000/validacao |
| Ambiente limpo (RNF07) sem apagar a instalação atual | `docker compose stop`; num clone novo, defina `COMPOSE_PROJECT_NAME=enadelimpo` e `ENADE_REDE=enadelimpo-net` e siga os passos 1–4 (volumes e rede próprios) |

Resultados medidos (ambiente do laboratório, 4 vCPU/5,8 GB): ver [docs/STATUS.md](docs/STATUS.md) e `evidencias/`.

## Usuários e perfis de teste (sintéticos)
| Usuário | Grupo LDAP | Perfil | Pode |
|---|---|---|---|
| `estudante1`, `estudante2` | `cn=estudantes,ou=grupos,dc=enade,dc=local` | Estudante | buscar, ver questões **sem gabarito**, montar lista |
| `professor1` | `cn=professores,ou=grupos,dc=enade,dc=local` | Professor | tudo acima + gabarito, painel analítico, exportação PDF/JSON, operação |

Rotas restritas acessadas por Estudante retornam **HTTP 403** (ex.: `GET /api/questoes/{id}/gabarito`).

## Estrutura
```
docker-compose.yml        .env.example         scripts/ (gerar-env, medir-ingestao, experimento-falha, carga/k6)
codigo/Dockerfile         codigo/requirements.txt
codigo/enade/             coleta.py · extracao/ · esquema.py · produtor.py · indexer.py · setup_es.py · api/ · ferramentas/
codigo/infra/             kdc/ · krb5.conf · kafka/ · elasticsearch/ · ldap/ · prometheus/ · certs/ (CA pública do INEP)
codigo/testes/            unitários, integração, Kerberos
dados/                    validacao/amostra.json · locais/ (PDFs locais) — o acervo baixado fica no volume Docker
docs/  evidencias/  relatorio/
```

## Dados e licenças
- Fonte: provas, gabaritos e padrões de resposta publicados pelo INEP em
  `https://www.gov.br/inep/pt-br/areas-de-atuacao/avaliacao-e-exames-educacionais/enade/provas-e-gabaritos/{ano}`
  (consulta em 2026-11-22). Os PDFs **não** são versionados; o coletor os baixa novamente com hash SHA-256 registrado.
- Taxonomia de competências/temas: Portaria Inep nº 289/2023 (arts. 5º e 6º).
- Usuários LDAP são sintéticos, apenas para teste.

## Limitações conhecidas (honestas)
- **Anos coletados:** 2021–2023 (84 provas). Edições 2004–2019 e 2025 não foram processadas.
- **Figuras (RF04):** convertidas sem LLM a partir dos vetores do PDF (`python -m enade.extracao.figuras_vetor`,
  depois `bash scripts/validar-mermaid.sh` e `python -m enade.extracao.figuras_llm aplicar`): 44 diagramas viram
  Mermaid (todos compilam) e 755 figuras viram Markdown com seus textos. Imagens raster sem texto (579) ficam só
  como PNG. Fórmulas viram LaTeX quando o PDF tem texto (índices, expoentes, símbolos). Há um módulo opcional
  com LLM (`enade.extracao.figuras_llm`, pago, exige `ANTHROPIC_API_KEY`) que não foi executado.
- **Competências por questão** são inferidas por classificador léxico (o INEP não publica esse vínculo); a acurácia
  ainda não foi medida.
- **Kerberos no Elasticsearch** usa a licença *trial* (30 dias). Depois disso o realm Kerberos para de funcionar.
- **Sem TLS interno:** Kafka usa `SASL_PLAINTEXT` e o ES HTTP sem TLS — Kerberos autentica (mutuamente), mas não cifra.
- **Um nó** de cada componente (limite de memória): sem réplicas reais.
- A pasta do projeto está no OneDrive; por isso o acervo fica em volume Docker (evita sincronizar ~1 GB).
