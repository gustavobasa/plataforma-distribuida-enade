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
RUN useradd -u 1000 -m app && mkdir -p /dados && chown app:app /dados
COPY --chown=app:app enade ./enade
COPY --chown=app:app testes ./testes
USER app
CMD ["python", "-m", "enade.api"]
