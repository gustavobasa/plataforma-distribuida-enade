#!/usr/bin/env bash
# RF09 / RNF04 — Experimento de falha induzida durante a indexação.
#
# Procedimento (reprodutível):
#   1. para o indexer, recria o índice vazio e reposiciona o grupo de consumo no início do tópico;
#   2. inicia o indexer e, com ~30% indexado, MATA o processo (SIGKILL, sem desligamento gracioso);
#   3. reinicia o indexer; com ~60% indexado, MATA o Elasticsearch (SIGKILL) por ~30 s;
#   4. religa o Elasticsearch e espera o lag do consumidor zerar;
#   5. compara: documentos no índice x ids distintos publicados (sem perda e sem duplicata).
# Saída: evidencias/faseF/falha-<timestamp>.log
# Uso (Git Bash ou Linux, na raiz do repositório): bash scripts/experimento-falha.sh
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p evidencias/faseF
LOG="evidencias/faseF/falha-$(date -u +%Y%m%dT%H%M%SZ).log"
export MSYS_NO_PATHCONV=1

log() { echo "$(date -u +%Y-%m-%dT%H:%M:%S.%3NZ) $*" | tee -a "$LOG"; }
contar() {
  docker compose exec -T elasticsearch sh -c \
    'curl -s -u "elastic:$ELASTIC_PASSWORD" "localhost:9200/enade-questoes/_count" | sed -E "s/.*\"count\":([0-9]+).*/\1/"' 2>/dev/null || echo "?"
}
grupo() { docker compose run --rm --no-deps -T --entrypoint bash kafka-setup /etc/kafka/custom/descrever-grupo.sh 2>/dev/null; }
lag_total() { grupo | awk 'NR>1 && $6 ~ /^[0-9]+$/ {s+=$6} END {print s+0}'; }
esperar_contagem() {  # espera até o índice atingir $1 documentos
  local alvo=$1
  while true; do
    local n; n=$(contar)
    [[ "$n" =~ ^[0-9]+$ ]] && (( n >= alvo )) && { echo "$n"; return; }
    sleep 0.5
  done
}

ESPERADO=$(docker compose run --rm --no-deps -T ingestor sh -c 'cat /dados/extraidos/*/*.jsonl | wc -l' 2>/dev/null | tr -d '\r ')
log "ids distintos publicados (JSONL válidos) = $ESPERADO"
log "== estado inicial do grupo"; grupo | tee -a "$LOG"

log "1) parando indexer, recriando índice e reposicionando offsets no início"
docker compose stop indexer >/dev/null
docker compose run --rm --no-deps -T es-setup python -m enade.setup_es --recriar >>"$LOG" 2>&1
docker compose run --rm --no-deps -T --entrypoint bash kafka-setup /etc/kafka/custom/reset-offsets.sh >>"$LOG" 2>&1
log "documentos no índice após recriação: $(contar)"

T0=$(date +%s.%N)
log "2) iniciando indexer"
docker compose start indexer >/dev/null
N=$(esperar_contagem $((ESPERADO * 30 / 100)))
log "   índice com $N docs -> SIGKILL no indexer (falha abrupta)"
docker compose kill -s SIGKILL indexer >/dev/null
log "   offsets confirmados no momento da queda:"; grupo | tee -a "$LOG"
log "   documentos no índice após a queda: $(contar)"
sleep 5

log "3) reiniciando indexer"
docker compose start indexer >/dev/null
N=$(esperar_contagem $((ESPERADO * 60 / 100)))
log "   índice com $N docs -> SIGKILL no Elasticsearch"
docker compose kill -s SIGKILL elasticsearch >/dev/null
sleep 30
log "   Elasticsearch fora do ar há 30 s; lag do consumidor = $(lag_total) (offsets não avançam sem confirmação do ES)"

log "4) religando Elasticsearch"
docker compose start elasticsearch >/dev/null
until [ "$(docker inspect -f '{{.State.Health.Status}}' "$(docker compose ps -q elasticsearch)")" = "healthy" ]; do sleep 2; done
log "   Elasticsearch saudável; aguardando lag zerar"
while true; do
  L=$(lag_total); [ "$L" = "0" ] && break; sleep 2
done
T1=$(date +%s.%N)
sleep 3
FINAL=$(contar)
log "5) lag = 0. documentos no índice = $FINAL; esperado = $ESPERADO"
grupo | tee -a "$LOG"
REPROC=$(docker compose logs --no-log-prefix --since "$(date -u -d @"${T0%.*}" +%Y-%m-%dT%H:%M:%SZ)" indexer 2>/dev/null \
  | grep -o '"indexados": [0-9]*' | awk '{s+=$2} END {print s+0}')
log "   operações de indexação confirmadas desde o início do experimento (soma dos lotes no log; > esperado indica reprocessamento): $REPROC"
log "   retentativas por ES indisponível (log): $(docker compose logs --no-log-prefix indexer 2>/dev/null | grep -c 'Elasticsearch indisponível' || true)"
DUR=$(awk "BEGIN {printf \"%.1f\", $T1 - $T0}")
log "   tempo total com falhas: ${DUR}s"
if [ "$FINAL" = "$ESPERADO" ]; then
  log "RESULTADO: SEM PERDA e SEM DUPLICATA ($FINAL de $ESPERADO documentos)"
else
  log "RESULTADO: DIVERGÊNCIA ($FINAL de $ESPERADO documentos) — investigar"
  exit 1
fi
