#!/bin/bash
# Reposiciona o grupo do indexer no início do tópico (reprocessamento completo). O indexer deve estar parado.
set -euo pipefail
/opt/kafka/bin/kafka-consumer-groups.sh --bootstrap-server kafka.enade.local:9092 \
  --command-config /etc/kafka/custom/client-admin.properties \
  --group "${KAFKA_GROUP_INDEXER:-enade-indexer}" --topic "${KAFKA_TOPIC_QUESTOES:-enade.questoes.v1}" \
  --reset-offsets --to-earliest --execute
