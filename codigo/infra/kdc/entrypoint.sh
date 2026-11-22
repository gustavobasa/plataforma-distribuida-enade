#!/bin/sh
# Inicializa o realm ENADE.LOCAL, cria principals de serviço e exporta keytabs
# (um subdiretório por serviço, para que cada contêiner monte apenas o seu).
set -eu
REALM="${KRB5_REALM:-ENADE.LOCAL}"
: "${KDC_MASTER_PASSWORD:?defina KDC_MASTER_PASSWORD no .env}"
APP_UID="${KEYTAB_OWNER_UID:-1000}"

rm -f /keytabs/.ready
if [ ! -f /var/lib/krb5kdc/principal ]; then
    echo "[kdc] criando banco do realm $REALM"
    kdb5_util create -s -r "$REALM" -P "$KDC_MASTER_PASSWORD" >/dev/null
    # banco novo => keytabs antigos ficam inválidos
    rm -rf /keytabs/*
fi

# principal | diretório | arquivo
add_principal() {
    princ="$1"; dir="$2"; file="$3"
    if ! kadmin.local -q "getprinc $princ" 2>/dev/null | grep -q "Principal: $princ@"; then
        kadmin.local -q "addprinc -randkey $princ" >/dev/null
        echo "[kdc] principal criado: $princ@$REALM"
    fi
    mkdir -p "/keytabs/$dir"
    if [ ! -s "/keytabs/$dir/$file" ]; then
        kadmin.local -q "ktadd -k /keytabs/$dir/$file $princ" >/dev/null
        echo "[kdc] keytab exportado: $dir/$file ($princ)"
    fi
}

add_principal "kafka/kafka.enade.local"          kafka         kafka.keytab
add_principal "HTTP/elasticsearch.enade.local"   elasticsearch http.keytab
add_principal "ingestor"                         ingestor      ingestor.keytab
add_principal "indexer"                          indexer       indexer.keytab
add_principal "api"                              api           api.keytab
add_principal "admin"                            admin         admin.keytab
# principal válido no realm, mas sem nenhuma permissão: usado em testes negativos
add_principal "intruso"                          testes        intruso.keytab

chown -R "$APP_UID:$APP_UID" /keytabs
find /keytabs -type d -exec chmod 750 {} \;
find /keytabs -type f -name '*.keytab' -exec chmod 600 {} \;
touch /keytabs/.ready
echo "[kdc] principals:"; kadmin.local -q listprincs | grep "@$REALM"
exec krb5kdc -n
