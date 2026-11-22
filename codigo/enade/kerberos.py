"""Clientes autenticados por Kerberos: Kafka (SASL/GSSAPI) e Elasticsearch (SPNEGO com autenticação mútua).

A identidade do serviço vem do keytab apontado por KRB5_CLIENT_KTNAME e do principal KRB5_PRINCIPAL.
Nenhuma senha é usada pelos serviços.
"""
from __future__ import annotations

from typing import Any

from .config import CFG


def kafka_conf_base(extra: dict[str, Any] | None = None) -> dict[str, Any]:
    if not CFG.krb_principal or not CFG.krb_keytab:
        raise RuntimeError("KRB5_PRINCIPAL e KRB5_CLIENT_KTNAME são obrigatórios para acessar o Kafka")
    conf: dict[str, Any] = {
        "bootstrap.servers": CFG.kafka_bootstrap,
        "security.protocol": "SASL_PLAINTEXT",
        "sasl.mechanisms": "GSSAPI",
        "sasl.kerberos.service.name": "kafka",
        "sasl.kerberos.principal": CFG.krb_principal,
        "sasl.kerberos.keytab": CFG.krb_keytab,
    }
    if extra:
        conf.update(extra)
    return conf


def es_cliente(timeout: int = 30):
    """Cliente Elasticsearch autenticado via SPNEGO/Kerberos com autenticação mútua obrigatória.

    ATENÇÃO: o objeto HTTPSPNEGOAuth guarda contexto GSSAPI e NÃO é thread-safe. Compartilhá-lo entre threads
    derrubou a API sob carga ("double free or corruption"). Use um cliente por thread (ver api/estado.py).
    `opportunistic_auth` envia o token Kerberos já na primeira requisição (evita o ida-e-volta 401 -> Negotiate).
    """
    from elasticsearch import Elasticsearch
    from requests_gssapi import REQUIRED, HTTPSPNEGOAuth

    return Elasticsearch(
        CFG.es_url,
        node_class="requests",
        http_auth=HTTPSPNEGOAuth(mutual_authentication=REQUIRED, opportunistic_auth=True),
        request_timeout=timeout,
        retry_on_timeout=True,
        max_retries=3,
    )
