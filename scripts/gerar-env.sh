#!/bin/sh
# Gera .env a partir de .env.example substituindo "trocar-*" por senhas aleatórias.
set -eu
cd "$(dirname "$0")/.."
[ -f .env ] && { echo ".env já existe; nada feito."; exit 0; }
while IFS= read -r line; do
  case "$line" in
    *=trocar-*) key=${line%%=*}; val=$(head -c 24 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c 24); echo "$key=$val" ;;
    *) echo "$line" ;;
  esac
done < .env.example > .env
echo ".env criado com senhas aleatórias."
