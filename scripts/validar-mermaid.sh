#!/usr/bin/env bash
# RF04 — Valida a sintaxe dos diagramas Mermaid gerados pelo LLM compilando cada um com o mermaid-cli 10.9.1
# (mesma versão do mermaid usado na interface web).
# Resultado: /dados/llm/mmd/validacao.txt ("OK arquivo.mmd" / "ERRO arquivo.mmd") e erros.txt (mensagens do parser).
# Uso (raiz do repositório, Git Bash ou Linux): bash scripts/validar-mermaid.sh
set -euo pipefail
cd "$(dirname "$0")/.."
export MSYS_NO_PATHCONV=1
docker compose run --rm -T ingestor python -m enade.extracao.figuras_llm exportar-mermaid
SAIDA=$(docker run --rm --entrypoint sh -v enade_acervo:/dados:ro minlag/mermaid-cli:10.9.1 -c '
  cd /dados/llm/mmd
  for f in *.mmd; do
    [ -e "$f" ] || continue
    case "$f" in teste_*) continue ;; esac
    if /home/mermaidcli/node_modules/.bin/mmdc -p /puppeteer-config.json -q -i "$f" -o "/tmp/${f%.mmd}.svg" >/dev/null 2>/tmp/err; then
      echo "OK $f"
    else
      echo "ERRO $f"
      echo "#ERRO $f: $(head -c 300 /tmp/err | tr "\n" " ")"
    fi
  done')
printf '%s\n' "$SAIDA" | docker compose run --rm -T --entrypoint sh ingestor -c \
  'cat > /tmp/s.txt; grep -E "^(OK|ERRO) " /tmp/s.txt > /dados/llm/mmd/validacao.txt || true;
   grep "^#ERRO " /tmp/s.txt > /dados/llm/mmd/erros.txt || true;
   echo "válidos: $(grep -c "^OK " /dados/llm/mmd/validacao.txt)  inválidos: $(grep -c "^ERRO " /dados/llm/mmd/validacao.txt)"'
