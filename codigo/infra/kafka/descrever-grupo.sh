#!/bin/bash
# Mostra offsets confirmados, fim do log e lag por partição do grupo do indexer.
/opt/kafka/bin/kafka-consumer-groups.sh --bootstrap-server kafka.enade.local:9092 \
  --command-config /etc/kafka/custom/client-admin.properties \
  --describe --group "${KAFKA_GROUP_INDEXER:-enade-indexer}" 2>/dev/null | grep -E "TOPIC|enade"
