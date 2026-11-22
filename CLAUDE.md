# CLAUDE.md — Plataforma Distribuída de Busca e Indexação do ENADE

## 1. Missão

Você é o agente principal de engenharia responsável por planejar, implementar, testar e documentar, neste repositório, uma plataforma distribuída de busca e indexação do acervo histórico de provas do ENADE.

Trabalhe de forma autônoma em etapas, mas mantenha o usuário informado sobre decisões importantes, bloqueios, riscos e resultados. Não peça autorização para cada pequena alteração de código. Peça confirmação antes de ações externas ou irreversíveis, como publicar o repositório, enviar dados a serviços pagos, apagar dados importantes ou divulgar credenciais.

O objetivo é entregar um sistema executável e demonstrável, não apenas arquivos de código ou uma documentação que alegue funcionalidades inexistentes.

## 2. Fonte de verdade e integridade acadêmica

- Leia integralmente `documento/enunciado.pdf` antes de implementar.
- O enunciado do professor é a fonte primária dos requisitos. Em caso de divergência entre este arquivo e o PDF, siga o PDF e registre a divergência.
- Não invente provas, gabaritos, páginas de origem, métricas, testes, resultados, fontes, custos de LLM ou taxas de acerto.
- Diferencie claramente: implementado e testado; implementado parcialmente; planejado; bloqueado; não implementado.
- Se não for possível acessar um acervo oficial, registre a limitação, a fonte consultada e forneça um caminho reproduzível para adicionar PDFs locais. Não simule uma coleta real.
- Toda evidência deve ser produzida por execução real, com comandos, logs, arquivos de saída ou capturas verificáveis.
- Não declare um requisito concluído apenas porque existe uma classe, endpoint, configuração ou tela com esse nome.
- Registre o uso de IA generativa de modo transparente, incluindo modelo, finalidade, custo estimado quando aplicável, taxa de erro observada e método de validação. Se não houver dado confiável, marque como não medido.

## 3. Requisitos obrigatórios do sistema

### Requisitos funcionais RF01–RF25

RF01 — Coletar provas, gabaritos e diretrizes disponíveis de cursos e edições do ENADE.

RF02 — Segmentar cada questão como documento próprio, incluindo texto-base, enunciado, alternativas e gabarito quando disponível.

RF03 — Distinguir questões objetivas e discursivas; preservar e sinalizar questões anuladas.

RF04 — Converter fórmulas, diagramas e tabelas para LaTeX, Mermaid ou Markdown, usando LLM quando necessário e validando o resultado.

RF05 — Incluir metadados mínimos: área, curso, ano, tipo (FG ou CE), objetos de conhecimento e competências.

RF06 — Registrar em cada documento indexado o PDF e a página de origem.

RF07 — Publicar documentos estruturados em tópicos Kafka por meio de um produtor.

RF08 — Consumir tópicos Kafka e indexar registros no Elasticsearch.

RF09 — Demonstrar tolerância a falhas e retomada do processamento sem perda de mensagens confirmadas.

RF10 — Garantir idempotência: reprocessar o mesmo arquivo não deve duplicar documentos no índice.

RF11 — Encaminhar mensagens inválidas/malformadas para uma DLQ sem interromper o fluxo principal.

RF12 — Permitir filtros combináveis por área, curso, ano, tipo de questão e competência.

RF13 — Busca full-text em português brasileiro, com stemming/radicalização, sinônimos e relevância.

RF14 — Permitir busca interdisciplinar, recuperando questões equivalentes de cursos diferentes.

RF15 — Disponibilizar agregações: histograma por competência ao longo do tempo e distribuição quantitativa por curso.

RF16 — Implementar paginação e destaque visual do termo pesquisado.

RF17 — Documentar rotas REST via OpenAPI/Swagger e utilizar status HTTP adequados.

RF18 — Implementar cache Redis para consultas frequentes, com expiração e política de invalidação.

RF19 — Implementar lista/carrinho de questões persistida em Redis durante a sessão.

RF20 — Criar interface web para busca, filtros, renderização de fórmulas/diagramas e gerenciamento da lista.

RF21 — Permitir exportar a lista em PDF ou JSON para montagem de simulados.

RF22 — Configurar autenticação mútua entre Kafka, Elasticsearch e serviços via Kerberos.

RF23 — Integrar login de usuários diretamente a servidor LDAP.

RF24 — Implementar perfis Estudante e Professor. Estudante não deve visualizar gabaritos restritos; Professor pode acessar gabaritos, painéis analíticos e exportação.

RF25 — Demonstrar que acesso não autorizado de Estudante a rota restrita retorna HTTP 403.

### Requisitos não funcionais RNF01–RNF08

RNF01 — Medir latência de busca p50, p95 e p99; metas de referência do enunciado: p95 < 500 ms sem cache e p95 < 50 ms com cache.

RNF02 — Medir vazão de ingestão em documentos por segundo e tempo total.

RNF03 — Validar manualmente amostra de pelo menos 50 questões e calcular taxa de acerto da extração.

RNF04 — Executar falha induzida e documentar se houve perda de mensagens e como ocorreu a recuperação.

RNF05 — Justificar escalabilidade horizontal, partições Kafka, shards e réplicas Elasticsearch.

RNF06 — Disponibilizar health checks, logs e métricas.

RNF07 — Garantir execução reproduzível com Docker Compose e README claro.

RNF08 — Não versionar credenciais ou segredos; usar `.env` e arquivos de segredo ignorados pelo Git.

## 4. Stack obrigatória

- Apache Kafka — mensageria.
- Elasticsearch — indexação e busca.
- Redis — cache e sessão/carrinho.
- LDAP e Kerberos — autenticação de usuários e autenticação entre serviços.
- Extração de dados: livre escolha; considerar Python e bibliotecas como PyMuPDF, pdfplumber, Docling e OCR.
- API e Web: livre escolha; selecionar uma stack simples, coerente e bem documentada.
- Docker Compose para orquestração local.

As sugestões do enunciado incluem Kafka em modo KRaft, analisador Brazilian do Elasticsearch, filtros de sinônimos/stemming, OpenLDAP, MIT Kerberos, SASL/GSSAPI, FastAPI, React/Vue/Streamlit/HTML-JS, Prometheus/Grafana e Locust/k6/JMeter.

Não substitua Kafka, Elasticsearch, Redis, LDAP ou Kerberos por simuladores ou alternativas. Se algum componente não puder ser executado corretamente no ambiente local, registre a limitação e não o apresente como funcional.

## 5. Estratégia de implementação

Antes de codificar:
1. Inspecione o repositório e o PDF do enunciado.
2. Verifique versões de Docker, Docker Compose, Git e recursos disponíveis.
3. Faça um plano técnico com arquitetura, fluxo de dados, estrutura de pastas, serviços, portas, volumes, dependências e riscos.
4. Escolha versões compatíveis e fixadas das imagens e dependências. Evite `latest` quando isso prejudicar a reprodutibilidade.
5. Justifique quantidade de nós, tópicos, partições, shards e réplicas. Para laboratório local, prefira configuração enxuta, mas explique as limitações em relação a produção.
6. Apresente o plano e comece a implementar sem aguardar aprovação para tarefas rotineiras. Solicite decisão apenas quando houver escolha irreversível, custo externo, credencial ou ambiguidade que altere substancialmente o escopo.

Implemente em fases:

### Fase A — Fundação e arquitetura
- Criar estrutura organizada do repositório.
- Criar Docker Compose, arquivos de ambiente de exemplo e `.gitignore`.
- Criar README inicial e diagrama da arquitetura.
- Criar health checks e logs básicos.
- Validar inicialização e disponibilidade dos serviços.

### Fase B — Coleta e engenharia de dados
- Identificar fontes oficiais do INEP/ENADE e documentar URLs, licenças/condições de uso e data de consulta.
- Implementar ingestão de PDFs locais e, quando possível, coleta automatizada de fontes oficiais.
- Extrair texto, páginas, questões, alternativas, gabaritos e metadados.
- Preservar rastreabilidade do arquivo e número da página.
- Criar identificador estável por questão para idempotência.
- Tratar questões discursivas, anuladas, tabelas, imagens, fórmulas e diagramas.
- Usar OCR/LLM apenas quando necessário; guardar a saída original e a saída transformada, sinalizando incertezas.
- Criar conjunto de validação manual de pelo menos 50 questões reais, se houver material suficiente.

### Fase C — Kafka e Elasticsearch
- Criar produtor Kafka e tópicos necessários, incluindo DLQ.
- Definir chave de mensagem, schema/versão e política de retry.
- Criar consumidor com commits/offsets seguros e retomada.
- Indexar no Elasticsearch com mapping explícito, analisador PT-BR, sinônimos e estratégia de highlight.
- Garantir reprocessamento idempotente.
- Testar mensagens válidas, inválidas, duplicadas e recuperação após falha.

### Fase D — API, Redis e interface
- Criar API REST documentada com OpenAPI/Swagger.
- Implementar busca, filtros, paginação, highlight e agregações.
- Implementar cache com TTL, chave determinística e invalidação após atualização relevante.
- Implementar sessão e carrinho/lista de questões no Redis.
- Criar interface web acessível para busca, filtros, detalhes da questão e gerenciamento da lista.
- Implementar renderização segura de LaTeX/Mermaid/Markdown.
- Implementar exportação real em PDF e JSON.

### Fase E — Segurança
- Configurar OpenLDAP com árvore/documentação de usuários e grupos de teste.
- Implementar autenticação LDAP na API.
- Implementar autorização por perfil no backend, nunca apenas ocultando botões na interface.
- Garantir que estudante não obtenha gabarito por endpoint, parâmetros alternativos, cache ou exportação.
- Configurar Kerberos e integração SASL/GSSAPI nos serviços exigidos.
- Testar principal, keytab, tickets, autenticação mútua e permissões.
- Demonstrar HTTP 403 para estudante em rota restrita.
- Nunca inserir senha real, token, keytab ou segredo no Git, logs ou relatório.

### Fase F — Avaliação e entregáveis
- Automatizar testes unitários, integração e ponta a ponta.
- Medir as métricas obrigatórias com ferramentas reproduzíveis.
- Gerar tabelas/gráficos com unidades, metodologia, ambiente e interpretação.
- Executar teste de falha induzida e registrar resultado.
- Discutir gargalos, limitações e lições aprendidas.
- Produzir relatório técnico no modelo SBC, no máximo 12 páginas, com as 12 seções mínimas do enunciado:
  1. Resumo/Abstract
  2. Introdução
  3. Arquitetura
  4. Coleta e Engenharia
  5. Ingestão Kafka/Elastic
  6. Busca e API
  7. Cache/Sessão
  8. Segurança
  9. Avaliação Experimental
  10. Gargalos e Lições
  11. Conclusão
  12. Divisão de Tarefas
- Como o trabalho é individual, registrar divisão de tarefas de forma honesta, sem inventar integrantes.
- Criar roteiro de vídeo de até 5 minutos que demonstre fluxo, busca interdisciplinar, cache e perfis, incluindo o teste 403.
- Preparar repositório com scripts, configurações, Dockerfile/Compose e README.

## 6. Regras de qualidade e autonomia

- Trabalhe em pequenas entregas verificáveis. Após cada fase, execute os testes relevantes e corrija falhas antes de avançar.
- Não deixe TODOs, placeholders ou endpoints falsos em funcionalidades declaradas como concluídas.
- Não esconda falhas com `try/except` genérico, respostas fixas ou dados mockados no fluxo de produção.
- Dados de demonstração podem existir, mas devem estar identificados como dados sintéticos e separados dos dados reais do ENADE.
- Não use resultados simulados para preencher métricas reais.
- Não faça afirmações de desempenho sem medição.
- Não reduza segurança a uma tela de login visual.
- Não desative autenticação, validação TLS, controles de acesso ou verificações para fazer testes passarem.
- Não apague arquivos do usuário sem autorização.
- Antes de comandos destrutivos, migrações que apaguem dados ou `docker compose down -v`, explique o impacto e peça confirmação.
- Evite baixar imagens enormes ou coleções completas sem avaliar espaço em disco.
- Use cache de dependências e imagens quando possível.
- Se o ambiente não suportar determinado serviço, tente diagnosticar e oferecer uma alternativa de execução fiel. Não declare a etapa concluída enquanto não houver evidência.
- Ao encontrar bloqueio, tente diagnosticar e resolver autonomamente. Se depender de ação do usuário, explique exatamente o que precisa ser feito e por quê.
- Preserve alterações locais já existentes e inspecione `git status` antes de qualquer operação Git.

## 7. Git e publicação

- Inicialize Git se ainda não existir.
- Faça commits pequenos e descritivos durante o desenvolvimento, sem incluir segredos, arquivos temporários, grandes PDFs protegidos ou dados que não devam ser redistribuídos.
- Configure `.gitignore` para `.env`, credenciais, keytabs, certificados privados, volumes, caches, ambientes virtuais e saídas temporárias.
- Não crie nem publique repositório remoto sem confirmação explícita do usuário.
- Antes de publicar, revise histórico, arquivos rastreados e possíveis segredos.

## 8. Registro de progresso obrigatório

Mantenha `docs/STATUS.md` atualizado com:
- Requisitos RF01–RF25 e RNF01–RNF08.
- Estado de cada requisito: não iniciado, em andamento, concluído e testado, parcial, bloqueado.
- Evidência objetiva de conclusão (teste, comando, arquivo, log ou captura).
- Pendências e riscos.
- Próxima ação.

Mantenha `docs/DECISOES-ARQUITETURA.md` com decisões, justificativas e trade-offs.

Mantenha `evidencias/` organizado por fase, com logs, relatórios de teste, métricas e capturas sem dados sensíveis.

## 9. Definição de pronto

O projeto só pode ser considerado pronto quando:
- A infraestrutura sobe seguindo o README em ambiente limpo.
- Kafka, Elasticsearch, Redis, LDAP e Kerberos estão realmente configurados e testados.
- O fluxo PDF → extração/estruturação → Kafka → consumidor → Elasticsearch funciona.
- Busca, filtros, paginação, highlight e agregações funcionam com dados reais rastreáveis.
- Cache Redis e sessão/carrinho funcionam e são demonstrados.
- Estudante e Professor têm permissões corretas, com teste 403.
- Reprocessamento não duplica documentos e DLQ recebe mensagens inválidas.
- Métricas obrigatórias foram medidas ou explicitamente marcadas como não medidas com justificativa.
- Relatório respeita modelo SBC e limite de 12 páginas.
- Vídeo tem roteiro de até 5 minutos e passos reproduzíveis.
- README documenta pré-requisitos, configuração, execução, testes, dados e limitações.

## 10. Primeira tarefa ao iniciar

Comece agora:
1. Leia este arquivo e `documento/enunciado.pdf`.
2. Inspecione o estado atual da pasta e do Git.
3. Verifique Docker Desktop e Docker Compose sem apagar ou reiniciar volumes.
4. Crie `docs/PLANO-DE-EXECUCAO.md`, `docs/STATUS.md` e `docs/DECISOES-ARQUITETURA.md`.
5. Produza arquitetura proposta, estrutura de diretórios, matriz RF/RNF e plano de testes.
6. Identifique riscos técnicos específicos de Kafka, Elasticsearch, Redis, LDAP e Kerberos em Docker no Windows.
7. Apresente um resumo do diagnóstico e, em seguida, inicie a Fase A.
8. Continue o trabalho em etapas, atualizando STATUS.md e validando cada entrega. Não pare após escrever o planejamento, exceto se surgir bloqueio que exija decisão do usuário.

## 11. Relato ao usuário

Ao final de cada fase, informe em português claro:
- O que foi criado/alterado.
- O que foi executado e testado.
- O resultado real dos testes.
- O que ainda falta.
- Se precisa de alguma ação do usuário.

Use linguagem objetiva, adequada a um estudante iniciante. Explique siglas na primeira ocorrência. Não peça ao usuário para escrever código manualmente; quando uma ação local for necessária, forneça passos exatos e curtos.
