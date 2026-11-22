FROM debian:bookworm-slim
RUN apt-get update \
 && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends krb5-kdc krb5-admin-server krb5-user \
 && rm -rf /var/lib/apt/lists/*
COPY kdc.conf /etc/krb5kdc/kdc.conf
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod 755 /usr/local/bin/entrypoint.sh && echo "*/admin@ENADE.LOCAL *" > /etc/krb5kdc/kadm5.acl
EXPOSE 88/tcp 88/udp
HEALTHCHECK --interval=5s --timeout=3s --retries=30 CMD test -f /keytabs/.ready && grep -q krb5kdc /proc/1/comm
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
