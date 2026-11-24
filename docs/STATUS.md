# STATUS do Projeto

Legenda: ⬜ não iniciado · 🟡 em andamento · ✅ concluído e testado · 🟠 parcial · ⛔ bloqueado

Última atualização: 2026-11-22 (Fases A–F executadas; pendências listadas no fim)

## Requisitos funcionais

| ID | Requisito | Estado | Evidência | Observação / pendência |
|---|---|---|---|---|
| RF01 | Coleta do acervo | 🟠 | `evidencias/faseB/01*-coleta*.log`; `enade/coleta.py` | 252 PDFs oficiais (84 provas + 84 gabaritos + 84 padrões de resposta) de **2021, 2022 e 2023**, com URL, tamanho e SHA-256. Anos 2004–2019 e 2025 não coletados (layouts diferentes / escopo de laboratório). PDFs locais: `python -m enade.extracao --local`. |
| RF02 | Segmentação | ✅ | `evidencias/faseB/03-resumo-extracao.txt`; `testes/test_unitarios.py` | 3.360 questões (40 por prova × 84). Texto-base, enunciado, alternativas e gabarito separados. Validação humana (RNF03): v1.1 com 58/59 questões sem erro. |
| RF03 | Tipos de questão / anuladas | ✅ | resumo de extração; teste `test_gabarito_regex` | 3.024 objetivas, 336 discursivas; 14 anuladas sinalizadas (`anulada=true`, não descartadas). |
| RF04 | Mídia não textual | 🟠 | `evidencias/faseB/05-figuras-vetor.txt`; `scripts/validar-mermaid.sh`; detalhe da questão na interface | Fórmulas → LaTeX (281 questões), tabelas → Markdown (280). Figuras (1.540) sem LLM, a partir dos vetores do PDF: 44 diagramas → Mermaid (44/44 compilam no mermaid-cli 10.9.1), 755 → Markdown com os textos; 741 sem texto extraível (579 imagens raster) ficam só como PNG. Acurácia semântica dos diagramas não medida por humano. Módulo com LLM implementado, não executado (custo). |
| RF05 | Metadados mínimos | 🟠 | `recursos/formacao_geral_2023.yaml`; teste `test_classificador_temas` | Área (mapeamento próprio), curso, ano, FG/CE (capa/seção da prova). Competências e objetos de conhecimento da Portaria Inep 289/2023 atribuídos por **classificador léxico (inferido)**; acurácia não medida. |
| RF06 | Rastreabilidade | ✅ | teste `test_rastreabilidade` | `origem.pdf`, `origem.url`, `origem.paginas`, `origem.sha256`, PDF do gabarito. |
| RF07 | Publicação Kafka | ✅ | `evidencias/faseC/01-ingestao-inicial.log` | Produtor idempotente (`acks=all`), chave = id, 3.360 msgs em 3,2 s (1.046 msg/s). |
| RF08 | Consumo e indexação | ✅ | idem; `/api/admin/ingestao` | 3.360 documentos indexados; lag voltou a 0 em ~10 s. |
| RF09 | Tolerância a falhas | ✅ | `evidencias/faseF/falha-20261122T213649Z.log` | SIGKILL no indexer e no Elasticsearch durante reprocessamento de 10.085 msgs: 3.360/3.360 docs, lag 0. |
| RF10 | Idempotência | ✅ | `evidencias/faseC/02-idempotencia-reprocessamento.log` | Republicação do mesmo acervo: +3.360 mensagens, variação de 0 documentos. |
| RF11 | DLQ | ✅ | `evidencias/faseC/03-dlq.txt` | 5 mensagens malformadas → DLQ com motivo e origem; fluxo seguiu. |
| RF12 | Filtros combináveis | ✅ | `test_filtros_combinados`, `test_filtro_competencia` | área, curso, ano, componente, tipo, competência, tema, grau, anulada. |
| RF13 | Full-text PT-BR | ✅ | `test_stemming_ptbr`, `test_sinonimos`, `test_busca_fulltext_highlight` | stopwords + stemmer `light_portuguese` + sinônimos (busca). |
| RF14 | Interdisciplinaridade | ✅ | `test_interdisciplinar_varios_cursos`, `test_colapsar_equivalentes`, `test_equivalentes_em_outros_cursos` | Busca por "ética" retorna cursos diversos; agrupamento de questões idênticas; "mais semelhantes" (MLT). |
| RF15 | Agregações | ✅ | `test_agregacoes`; aba Painel analítico | Histograma competência × ano, temas × ano, distribuição por curso. |
| RF16 | Paginação e highlight | ✅ | `test_paginacao`, highlight `<mark>` | |
| RF17 | OpenAPI e status | ✅ | `/docs`, `test_openapi_documentado`, `test_parametro_invalido_422` | 200/201/204/400/401/403/404/409/422/429/503. |
| RF18 | Cache Redis | ✅ | `test_cache_hit_e_invalidacao`; k6 | TTL 300 s + invalidação por versão do índice + perfil na chave. |
| RF19 | Carrinho Redis | ✅ | `test_carrinho_e_exportacao` | Por sessão, TTL deslizante, limite 200. |
| RF20 | Interface web | ✅ | navegação real no navegador (busca, detalhe com KaTeX, gabarito, painel, operação) | Login testado também com senha inválida. Capturas para o vídeo: pendente. |
| RF21 | Exportação PDF/JSON | ✅ | `test_carrinho_e_exportacao` | PDF com figuras, origem e folha de respostas; JSON completo. |
| RF22 | Kerberos entre serviços | ✅ | `evidencias/faseE/01-testes-kerberos.txt` (7 testes) | Kafka SASL/GSSAPI + ACLs; ES SPNEGO com autenticação mútua; principal sem papel → 403. Sem TLS (ver limitações). |
| RF23 | Login LDAP | ✅ | `test_login_invalido_401`, `test_perfis_vindos_do_ldap`, `test_login_injecao_ldap_rejeitada` | Bind direto no OpenLDAP; grupos definem o perfil. |
| RF24 | Perfis | ✅ | `test_estudante_nao_ve_gabarito_*`, `test_cache_nao_vaza_gabarito_entre_perfis` | Gabarito/padrão de resposta removidos no backend para Estudante. |
| RF25 | HTTP 403 | ✅ | `test_estudante_rotas_restritas_403` (7 rotas) | Demonstração em vídeo: pendente (roteiro em `docs/ROTEIRO-VIDEO.md`). |

## Requisitos não funcionais

| ID | Requisito | Estado | Evidência | Resultado |
|---|---|---|---|---|
| RNF01 | Latência p50/p95/p99 | ✅ | `evidencias/faseF/k6-resumo.json`, `k6-saida.txt` | Sem cache: p50 14,4 ms · p95 19,8 ms · p99 24,7 ms. Com cache: p50 4,1 ms · p95 6,6 ms · p99 11,7 ms (20 req/s, 60 s cada, 0 erros). |
| RNF02 | Vazão de ingestão | ✅ | `evidencias/faseF/ingestao-*.csv/log` | Produtor 1.046–2.645 msg/s; indexer ≈ 313 docs/s em processamento (3.360 docs em ~9 s); extração ≈ 7,6 s por prova (641 s para 84). |
| RNF03 | Qualidade da extração (≥ 50) | ✅ | `evidencias/faseB/06-validacao-manual.csv` (v1.0), `07-validacao-manual-v1.1.csv` (v1.1); relatório §8 | Validação humana de 60 questões (amostra estratificada, semente 2026). v1.0: texto 71,7%, 43/60 sem erro. v1.1 (mesma amostra, após corrigir texto-base x enunciado): segmentação, alternativas, gabarito, metadados e mídia 100%, texto 58/59 (98,3%); 58/59 sem erro (58/60 = 96,7% contando a Q25 de Com. Social 2022 como erro). A Q25 não aparecia; causa provável: o bloqueador de anúncios do avaliador ocultava a imagem (URL com "publicidade"); rota corrigida para usar o id da questão. Taxa da v1.1 é otimista: mesma amostra que orientou o ajuste. |
| RNF04 | Falha induzida | ✅ | `evidencias/faseF/falha-*.log` | Zero perda e zero duplicata. |
| RNF05 | Escalabilidade justificada | ✅ | `docs/DECISOES-ARQUITETURA.md` (ADR-01/03/04) | Discussão no relatório. |
| RNF06 | Health/logs/métricas | ✅ | `/health/ready`, `/metrics`, Prometheus `:9090`, logs JSON | |
| RNF07 | Reprodutibilidade | 🟡 | README | Falta executar o roteiro em ambiente limpo (`down -v` exige sua confirmação). |
| RNF08 | Sem segredos no Git | ✅ | `.gitignore`, varredura antes de cada commit | `.env` e keytabs fora do Git; cada serviço recebe só os próprios segredos. |

## Incidentes encontrados e corrigidos (para "Gargalos e Lições")
1. Wheel do `confluent-kafka` sem GSSAPI → librdkafka compilado com SASL.
2. Cadeia TLS incompleta no `download.inep.gov.br` → CA intermediária pública adicionada (verificação mantida).
3. Páginas em duas colunas (2021/2022) → detecção de colunas.
4. Gabaritos de 2022 com nomes diferentes das provas → pareamento pela ordem da página oficial.
5. Medicina 2023 com alternativas A–D → suporte a 4 alternativas.
6. Rótulo de rodapé "MATÉRIA" vazando para a alternativa E → faixa de rodapé descartada.
7. Sinônimos antes do stemming → inconsistência singular/plural (teste falhou) → ordem do analisador corrigida.
8. **API caía sob carga** ("double free or corruption"): `requests-gssapi` não é thread-safe → cliente ES por thread.
9. Nome do curso capturado de código de barras → nova heurística de cabeçalho/rodapé.

## Pendências e riscos
- RNF03: a Q25 (Com. Social 2022, id 03dd79c5) ainda não foi avaliada (imagem agora corrigida); uma questão de Eng. de Produção (b54d5a65) segue sem texto-base separado.
- RF04: imagens raster sem texto (579) não têm representação textual (exigiriam OCR/LLM); fidelidade dos 44 diagramas a medir.
- RF05: acurácia do classificador de competências não medida (poderia entrar na validação manual).
- Licença trial do Elasticsearch expira em 30 dias (realm Kerberos).
- Relatório SBC gerado (`relatorio/relatorio.pdf`, 9 páginas), com autor e validação manual (v1.0 e v1.1).
- Vídeo: roteiro pronto (`docs/ROTEIRO-VIDEO.md`); gravação depende do usuário.

## Próxima ação
1. Com autorização do usuário: `docker compose down -v` + roteiro do README do zero (RNF07).
2. Usuário: gravar o vídeo (`docs/ROTEIRO-VIDEO.md`).
