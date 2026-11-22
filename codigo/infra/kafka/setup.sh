#!/bin/bash
# Cria tópicos e ACLs de forma idempotente. Executado pelo serviço kafka-setup.
set -euo pipefail
BS="kafka.enade.local:9092"
CFG="/etc/kafka/custom/client-admin.properties"
BIN=/opt/kafka/bin
T_MAIN="${KAFKA_TOPIC_QUESTOES:-enade.questoes.v1}"
T_DLQ="${KAFKA_TOPIC_DLQ:-enade.questoes.dlq}"
GROUP="${KAFKA_GROUP_INDEXER:-enade-indexer}"

$BIN/kafka-topics.sh --bootstrap-server $BS --command-config $CFG --create --if-not-exists \
  --topic "$T_MAIN" --partitions 3 --replication-factor 1 \
  --config retention.ms=-1 --config min.insync.replicas=1
$BIN/kafka-topics.sh --bootstrap-server $BS --command-config $CFG --create --if-not-exists \
  --topic "$T_DLQ" --partitions 1 --replication-factor 1 --config retention.ms=-1

acl() { $BIN/kafka-acls.sh --bootstrap-server $BS --command-config $CFG --add "$@" >/dev/null; }
# produtor: escreve no tópico principal (e DLQ para registros que já falham na validação de origem)
acl --allow-principal User:ingestor --operation Write --operation Describe --topic "$T_MAIN"
acl --allow-principal User:ingestor --operation Write --operation Describe --topic "$T_DLQ"
# consumidor/indexador: lê o principal, escreve na DLQ, usa o grupo de consumo
acl --allow-principal User:indexer --operation Read --operation Describe --topic "$T_MAIN"
acl --allow-principal User:indexer --operation Write --operation Describe --topic "$T_DLQ"
acl --allow-principal User:indexer --operation Read --operation Describe --group "$GROUP"
# API: somente leitura de metadados (lag do consumidor, tamanho da DLQ) para observabilidade
acl --allow-principal User:api --operation Describe --topic "$T_MAIN"
acl --allow-principal User:api --operation Describe --operation Read --topic "$T_DLQ"
acl --allow-principal User:api --operation Describe --group "$GROUP"
acl --allow-principal User:api --operation Describe --operation Read --group "enade-api-monitor"

echo "== tópicos"; $BIN/kafka-topics.sh --bootstrap-server $BS --command-config $CFG --describe
echo "== ACLs";   $BIN/kafka-acls.sh --bootstrap-server $BS --command-config $CFG --list
