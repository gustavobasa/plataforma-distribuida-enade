"""Configuração centralizada lida de variáveis de ambiente (nunca de arquivos versionados)."""
from __future__ import annotations

import os
from dataclasses import dataclass


def _env(nome: str, padrao: str | None = None) -> str:
    valor = os.environ.get(nome, padrao)
    if valor is None:
        raise RuntimeError(f"variável de ambiente obrigatória ausente: {nome}")
    return valor


@dataclass(frozen=True)
class Config:
    kafka_bootstrap: str = _env("KAFKA_BOOTSTRAP", "kafka.enade.local:9092")
    topico_questoes: str = _env("KAFKA_TOPIC_QUESTOES", "enade.questoes.v1")
    topico_dlq: str = _env("KAFKA_TOPIC_DLQ", "enade.questoes.dlq")
    grupo_indexer: str = _env("KAFKA_GROUP_INDEXER", "enade-indexer")
    krb_principal: str = _env("KRB5_PRINCIPAL", "")
    krb_keytab: str = _env("KRB5_CLIENT_KTNAME", "")
    es_url: str = _env("ES_URL", "http://elasticsearch.enade.local:9200")
    es_alias: str = _env("ES_ALIAS", "enade-questoes")
    es_indice: str = _env("ES_INDICE", "enade-questoes-v1")
    redis_host: str = _env("REDIS_HOST", "redis.enade.local")
    redis_port: int = int(_env("REDIS_PORT", "6379"))
    ldap_url: str = _env("LDAP_URL", "ldap://ldap.enade.local:389")
    ldap_base: str = _env("LDAP_BASE", "dc=enade,dc=local")
    cache_ttl: int = int(_env("CACHE_TTL_SECONDS", "300"))
    sessao_ttl: int = int(_env("SESSION_TTL_SECONDS", "3600"))
    dados_dir: str = _env("DADOS_DIR", "/dados")


def redis_password() -> str:
    return _env("REDIS_PASSWORD")


def ldap_readonly_password() -> str:
    return _env("LDAP_READONLY_PASSWORD")


CFG = Config()
