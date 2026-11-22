#!/usr/bin/env bash
# Abre uma sessão na API local para um usuário de TESTE e imprime apenas o token de sessão (a senha é lida
# do .env e nunca é exibida). Uso: bash scripts/sessao-teste.sh estudante1|professor1
set -euo pipefail
cd "$(dirname "$0")/.."
case "${1:-}" in
  estudante*) VAR=LDAP_SENHA_ESTUDANTES ;;
  professor*) VAR=LDAP_SENHA_PROFESSORES ;;
  *) echo "uso: $0 estudante1|professor1" >&2; exit 2 ;;
esac
SENHA=$(grep -E "^$VAR=" .env | cut -d= -f2-)
curl -s -X POST localhost:8000/api/auth/login -H 'Content-Type: application/json' \
  -d "{\"usuario\":\"$1\",\"senha\":\"$SENHA\"}" | python -c "import sys,json;print(json.load(sys.stdin)['token'])"
