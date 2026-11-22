"""RF18 — Cache Redis de consultas frequentes.

Política (ADR-08):
  * chave determinística: cache:{nome}:v{versao_indice}:{perfil}:{sha256(parâmetros normalizados)};
  * expiração por TTL (CACHE_TTL_SECONDS, padrão 300 s);
  * invalidação por versão: o indexer incrementa `indice:versao` a cada lote indexado, então nenhuma
    resposta anterior à atualização volta a ser usada; professores podem forçar a invalidação via API;
  * o perfil faz parte da chave: a resposta de um Professor (com gabarito) nunca é servida a um Estudante.
Contadores `cache:hits`/`cache:misses` no Redis (persistentes) e métrica Prometheus para o hit rate.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Callable

import redis

from ..config import CFG
from ..logs import evento, obter_logger
from .estado import M_CACHE, redis_cli

LOG = obter_logger("api.cache")


def versao_indice() -> str:
    return redis_cli().get("indice:versao") or "0"


def chave(nome: str, perfil: str, params: dict) -> str:
    normal = json.dumps(params, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return f"cache:{nome}:v{versao_indice()}:{perfil}:{hashlib.sha256(normal.encode()).hexdigest()[:32]}"


def obter_ou_calcular(nome: str, perfil: str, params: dict, calcular: Callable[[], Any],
                      usar_cache: bool = True) -> tuple[Any, str]:
    """Retorna (valor, 'HIT'|'MISS'|'BYPASS'). Falha do Redis não derruba a busca (degrada para MISS)."""
    if not usar_cache:
        return calcular(), "BYPASS"
    try:
        k = chave(nome, perfil, params)
        bruto = redis_cli().get(k)
    except redis.RedisError as exc:
        evento(LOG, "Redis indisponível; consultando sem cache", nivel=30, erro=str(exc))
        return calcular(), "BYPASS"
    if bruto is not None:
        M_CACHE.labels("hit").inc()
        redis_cli().incr("cache:hits")
        return json.loads(bruto), "HIT"
    valor = calcular()
    try:
        redis_cli().setex(k, CFG.cache_ttl, json.dumps(valor, ensure_ascii=False))
        redis_cli().incr("cache:misses")
    except redis.RedisError:
        pass
    M_CACHE.labels("miss").inc()
    return valor, "MISS"


def invalidar() -> int:
    return int(redis_cli().incr("indice:versao"))


def estatisticas() -> dict:
    r = redis_cli()
    hits, misses = int(r.get("cache:hits") or 0), int(r.get("cache:misses") or 0)
    chaves = sum(1 for _ in r.scan_iter("cache:busca:*", count=500)) + \
        sum(1 for _ in r.scan_iter("cache:analitico:*", count=500))
    return {"hits": hits, "misses": misses, "hit_rate": round(hits / (hits + misses), 4) if hits + misses else None,
            "chaves_ativas": chaves, "versao_indice": versao_indice(), "ttl_segundos": CFG.cache_ttl}


def zerar_contadores() -> None:
    redis_cli().delete("cache:hits", "cache:misses")
