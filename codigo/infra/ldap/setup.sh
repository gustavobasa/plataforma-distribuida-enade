#!/bin/bash
# Cria a árvore de usuários/grupos de TESTE (sintéticos) no OpenLDAP. Idempotente (-c).
# As senhas vêm de variáveis de ambiente (.env), nunca do Git.
set -euo pipefail
: "${LDAP_ADMIN_PASSWORD:?}" "${LDAP_SENHA_ESTUDANTES:?}" "${LDAP_SENHA_PROFESSORES:?}"
H="ldap://ldap.enade.local:389"
BASE="dc=enade,dc=local"
ADMIN="cn=admin,$BASE"

for i in $(seq 1 30); do
  ldapsearch -x -H "$H" -D "$ADMIN" -w "$LDAP_ADMIN_PASSWORD" -b "$BASE" -s base >/dev/null 2>&1 && break
  echo "aguardando LDAP ($i)"; sleep 2
done

TMP=$(mktemp)
cat > "$TMP" <<LDIF
dn: ou=usuarios,$BASE
objectClass: organizationalUnit
ou: usuarios

dn: ou=grupos,$BASE
objectClass: organizationalUnit
ou: grupos

dn: uid=estudante1,ou=usuarios,$BASE
objectClass: inetOrgPerson
uid: estudante1
cn: Estudante Um (teste)
sn: Um
mail: estudante1@enade.local

dn: uid=estudante2,ou=usuarios,$BASE
objectClass: inetOrgPerson
uid: estudante2
cn: Estudante Dois (teste)
sn: Dois
mail: estudante2@enade.local

dn: uid=professor1,ou=usuarios,$BASE
objectClass: inetOrgPerson
uid: professor1
cn: Professor Um (teste)
sn: Um
mail: professor1@enade.local

dn: cn=estudantes,ou=grupos,$BASE
objectClass: groupOfNames
cn: estudantes
description: Perfil Estudante - busca sem gabarito restrito
member: uid=estudante1,ou=usuarios,$BASE
member: uid=estudante2,ou=usuarios,$BASE

dn: cn=professores,ou=grupos,$BASE
objectClass: groupOfNames
cn: professores
description: Perfil Professor - gabaritos, painel analitico e exportacao
member: uid=professor1,ou=usuarios,$BASE
LDIF
ldapadd -c -x -H "$H" -D "$ADMIN" -w "$LDAP_ADMIN_PASSWORD" -f "$TMP" 2>&1 | grep -vE "Already exists|^$" || true
rm -f "$TMP"

for u in estudante1 estudante2; do
  ldappasswd -x -H "$H" -D "$ADMIN" -w "$LDAP_ADMIN_PASSWORD" -s "$LDAP_SENHA_ESTUDANTES" "uid=$u,ou=usuarios,$BASE"
done
ldappasswd -x -H "$H" -D "$ADMIN" -w "$LDAP_ADMIN_PASSWORD" -s "$LDAP_SENHA_PROFESSORES" "uid=professor1,ou=usuarios,$BASE"
echo "== árvore LDAP"
ldapsearch -x -LLL -H "$H" -D "$ADMIN" -w "$LDAP_ADMIN_PASSWORD" -b "$BASE" dn member
