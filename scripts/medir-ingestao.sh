#!/usr/bin/env bash
# RNF02 — Mede a vazão de ingestão (produtor e indexer) e registra o lag do consumidor ao longo do tempo.
# Publica todos os JSONL extraídos no Kafka enquanto amostra, a cada ~1 s, o lag do grupo e a contagem do índice
# (via /api/admin/ingestao, autenticado como Professor).
# Saídas: evidencias/faseF/ingestao-<ts>.csv (série temporal) e ingestao-<ts>.log (resumo)
# Uso: bash scripts/medir-ingestao.sh [argumentos extras do produtor, ex.: --anos 2023]
set -euo pipefail
cd "$(dirname "$0")/.."
export MSYS_NO_PATHCONV=1 PYTHONIOENCODING=utf-8
TS=$(date -u +%Y%m%dT%H%M%SZ)
CSV="evidencias/faseF/ingestao-$TS.csv"; LOG="evidencias/faseF/ingestao-$TS.log"
mkdir -p evidencias/faseF
SENHA=$(grep -E '^LDAP_SENHA_PROFESSORES=' .env | cut -d= -f2-)
TOKEN=$(curl -s -X POST localhost:8000/api/auth/login -H 'Content-Type: application/json' \
  -d "{\"usuario\":\"professor1\",\"senha\":\"$SENHA\"}" | python -c "import sys,json;print(json.load(sys.stdin)['token'])")
amostra() {
  curl -s localhost:8000/api/admin/ingestao -H "Authorization: Bearer $TOKEN" | python -c \
    "import sys,json,time;d=json.load(sys.stdin);print(f\"{time.time():.3f},{d['lag_total']},{d['documentos_no_indice']},{d['mensagens_no_topico']},{d['dlq_mensagens']}\")"
}
echo "epoch,lag_total,documentos_no_indice,mensagens_no_topico,dlq_mensagens" > "$CSV"
amostra >> "$CSV"
( while true; do amostra >> "$CSV" 2>/dev/null || true; sleep 1; done ) &
AMOSTRADOR=$!
trap 'kill $AMOSTRADOR 2>/dev/null || true' EXIT

echo "$(date -u +%FT%TZ) publicando: produtor $*" | tee -a "$LOG"
docker compose run --rm -T ingestor python -m enade.produtor "$@" 2>&1 | grep -E "publicação" | tee -a "$LOG"
# espera o consumidor alcançar o fim do tópico
sleep 3
while true; do
  L=$(tail -1 "$CSV" | cut -d, -f2)
  [ "$L" = "0" ] && break
  sleep 1
done
sleep 2
kill $AMOSTRADOR 2>/dev/null || true
python - "$CSV" <<'EOF' | tee -a "$LOG"
import csv, sys
linhas = [r for r in csv.DictReader(open(sys.argv[1]))]
t = [float(r["epoch"]) for r in linhas]; docs = [int(r["documentos_no_indice"]) for r in linhas]
lag = [int(r["lag_total"]) for r in linhas]; msgs = [int(r["mensagens_no_topico"]) for r in linhas]
i0 = next((i for i, m in enumerate(msgs) if m > msgs[0]), 0)   # primeira amostra com mensagens novas
i1 = next((i for i in range(i0, len(lag)) if lag[i] == 0 and i > i0), len(lag) - 1)
dur = t[i1] - t[max(i0 - 1, 0)]
novas = msgs[i1] - msgs[0]
print(f"mensagens publicadas nesta execução: {novas}")
print(f"documentos no índice: antes={docs[0]} depois={docs[-1]} (variação {docs[-1]-docs[0]})")
print(f"lag máximo observado: {max(lag)} mensagens")
print(f"tempo do início da publicação até lag=0: {dur:.1f} s  ->  vazão ponta a ponta ≈ {novas/dur:.1f} msgs/s")
EOF
