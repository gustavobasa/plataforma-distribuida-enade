"""Recursos compartilhados da API (clientes criados uma única vez por processo) e métricas."""
from __future__ import annotations

import threading
from functools import lru_cache

import redis
from prometheus_client import Counter, Histogram

from ..config import CFG, redis_password
from ..kerberos import es_cliente

M_REQ = Histogram("enade_api_requisicao_segundos", "Latência das requisições HTTP", ["rota", "metodo", "status"],
                  buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5))
M_CACHE = Counter("enade_api_cache_total", "Consultas ao cache Redis", ["resultado"])  # hit | miss
M_ES = Histogram("enade_api_es_segundos", "Latência das consultas ao Elasticsearch", ["operacao"],
                 buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5))


@lru_cache(maxsize=1)
def redis_cli() -> redis.Redis:
    return redis.Redis(host=CFG.redis_host, port=CFG.redis_port, password=redis_password(),
                       socket_timeout=3, decode_responses=True, health_check_interval=30)


_local = threading.local()


def es():
    """Cliente Elasticsearch autenticado como api@ENADE.LOCAL (Kerberos/SPNEGO, papel somente leitura).
    Um cliente por thread: o contexto GSSAPI do requests-gssapi não é seguro para uso concorrente."""
    cli = getattr(_local, "es", None)
    if cli is None:
        cli = _local.es = es_cliente(timeout=15)
    return cli
