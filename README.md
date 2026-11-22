# Plataforma Distribuída de Busca e Indexação do ENADE

Trabalho prático (individual) de Sistemas Distribuídos: coleta das provas oficiais do ENADE (INEP), extração de cada
questão como documento, publicação em **Apache Kafka**, indexação no **Elasticsearch**, API REST com cache e carrinho em
**Redis**, login via **LDAP** e autenticação mútua entre serviços via **Kerberos**.

> Estado atual: em desenvolvimento. O andamento real de cada requisito está em [docs/STATUS.md](docs/STATUS.md).

## Pré-requisitos
- Docker Desktop (testado com Engine 29.8, Compose v5.5) com pelo menos **4 CPUs e 6 GB de RAM** para o Docker.
- ~6 GB livres em disco para imagens + espaço para os PDFs (≈10 MB por prova).
- Acesso à internet para baixar imagens e as provas do INEP.

## Subir o ambiente
```powershell
# 1. gerar .env com senhas aleatórias (não versionado)
powershell -ExecutionPolicy Bypass -File scripts/gerar-env.ps1
# 2. subir infraestrutura e serviços
docker compose up -d --build
# 3. jobs de inicialização (tópicos/ACLs Kafka e árvore LDAP)
docker compose run --rm kafka-setup
docker compose run --rm ldap-setup
```

## Serviços
| Serviço | Função |
|---|---|
| `kdc` | MIT Kerberos, realm `ENADE.LOCAL`; cria principals e keytabs (volume `keytabs`) |
| `ldap` / `ldap-setup` | OpenLDAP `dc=enade,dc=local`, usuários/grupos de **teste** |
| `kafka` / `kafka-setup` | Kafka 3.9.1 KRaft, SASL/GSSAPI, ACLs por principal |
| `elasticsearch` | Elasticsearch 8.19.4 com realm Kerberos (SPNEGO) |
| `redis` | cache, sessão e carrinho (com senha) |

Documentação: [plano](docs/PLANO-DE-EXECUCAO.md) · [decisões](docs/DECISOES-ARQUITETURA.md) · [status](docs/STATUS.md).

## Limitações conhecidas
- O realm Kerberos do Elasticsearch é recurso de licença paga; usa-se a licença **trial** autogerada (30 dias, gratuita).
- Kafka usa `SASL_PLAINTEXT`: Kerberos autentica (mutuamente) mas não cifra o tráfego.
- Um nó por componente (limite de memória do laboratório); réplicas não são alocadas.
