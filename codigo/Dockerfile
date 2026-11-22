# Imagem única da aplicação: ingestor (coleta/extração/produtor), indexer (consumidor) e API web.
#
# O wheel binário do confluent-kafka NÃO inclui SASL/GSSAPI (Kerberos). Por isso compilamos o
# librdkafka a partir do código-fonte com Cyrus SASL e instalamos o confluent-kafka sem wheel binário.
FROM python:3.12-slim-bookworm AS rdkafka
ARG LIBRDKAFKA_VERSION=2.10.0
RUN apt-get update \
 && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
      build-essential curl ca-certificates libsasl2-dev libssl-dev zlib1g-dev libzstd-dev liblz4-dev \
 && rm -rf /var/lib/apt/lists/*
RUN curl -fsSL -o /tmp/rdkafka.tgz https://github.com/confluentinc/librdkafka/archive/refs/tags/v${LIBRDKAFKA_VERSION}.tar.gz \
 && mkdir /tmp/rdkafka && tar -xzf /tmp/rdkafka.tgz -C /tmp/rdkafka --strip-components=1 \
 && cd /tmp/rdkafka && ./configure --prefix=/opt/rdkafka --enable-sasl --enable-ssl --disable-debug-symbols \
 && make -j"$(nproc)" && make install

FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1 \
    LD_LIBRARY_PATH=/opt/rdkafka/lib C_INCLUDE_PATH=/opt/rdkafka/include LIBRARY_PATH=/opt/rdkafka/lib
RUN apt-get update \
 && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
      krb5-user libkrb5-dev libsasl2-2 libsasl2-modules-gssapi-mit libssl3 zlib1g libzstd1 liblz4-1 gcc curl \
 && rm -rf /var/lib/apt/lists/*
COPY --from=rdkafka /opt/rdkafka /opt/rdkafka
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir --no-binary confluent-kafka -r requirements.txt
# Bibliotecas da interface web, versões fixadas e verificadas por SHA-256 (funciona offline após o build)
COPY vendor.sha256 /tmp/vendor.sha256
RUN set -eu; mkdir -p /app/vendor/katex && cd /app/vendor \
 && curl -fsSL -o purify.min.js https://cdnjs.cloudflare.com/ajax/libs/dompurify/3.1.6/purify.min.js \
 && curl -fsSL -o marked.min.js https://cdnjs.cloudflare.com/ajax/libs/marked/12.0.2/marked.min.js \
 && curl -fsSL -o mermaid.min.js https://cdnjs.cloudflare.com/ajax/libs/mermaid/10.9.1/mermaid.min.js \
 && curl -fsSL -o /tmp/katex.tgz https://registry.npmjs.org/katex/-/katex-0.16.9.tgz \
 && sha256sum -c /tmp/vendor.sha256 \
 && tar -xzf /tmp/katex.tgz -C /tmp \
 && cp -r /tmp/package/dist/katex.min.js /tmp/package/dist/katex.min.css /tmp/package/dist/fonts \
          /tmp/package/dist/contrib/auto-render.min.js katex/ \
 && rm -rf /tmp/katex.tgz /tmp/package /tmp/vendor.sha256
RUN useradd -u 1000 -m app && mkdir -p /dados && chown app:app /dados
COPY --chown=app:app infra/certs ./certs
COPY --chown=app:app enade ./enade
COPY --chown=app:app testes ./testes
USER app
EXPOSE 8000 8001
CMD ["python", "-m", "enade.api"]
