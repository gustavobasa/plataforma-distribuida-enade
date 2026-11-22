"""Observabilidade (RNF06): verificação de dependências e estado da ingestão (lag do consumidor, DLQ, índice)."""
from __future__ import annotations

from functools import lru_cache

from confluent_kafka import Consumer, TopicPartition
from confluent_kafka.admin import AdminClient
from ldap3 import NONE, Connection, Server

from ..config import CFG, ldap_readonly_password
from ..kerberos import kafka_conf_base
from .estado import es


def ldap_ok() -> dict:
    try:
        c = Connection(Server(CFG.ldap_url, get_info=NONE, connect_timeout=3),
                       user=f"cn=readonly,{CFG.ldap_base}", password=ldap_readonly_password(), auto_bind=True)
        c.unbind()
        return {"ok": True}
    except Exception as exc:  # health check
        return {"ok": False, "erro": type(exc).__name__}


@lru_cache(maxsize=1)
def _admin() -> AdminClient:
    return AdminClient(kafka_conf_base({"client.id": "enade-api-monitor"}))


@lru_cache(maxsize=1)
def _consumer() -> Consumer:
    return Consumer(kafka_conf_base({"group.id": "enade-api-monitor", "enable.auto.commit": False,
                                     "client.id": "enade-api-monitor"}))


def kafka_ok() -> dict:
    try:
        md = _admin().list_topics(topic=CFG.topico_questoes, timeout=5)
        t = md.topics.get(CFG.topico_questoes)
        return {"ok": t is not None and t.error is None, "particoes": len(t.partitions) if t else 0,
                "autenticacao": "sasl/gssapi"}
    except Exception as exc:  # health check
        return {"ok": False, "erro": type(exc).__name__}


def _marcas(topico: str) -> dict[int, tuple[int, int]]:
    md = _admin().list_topics(topic=topico, timeout=10).topics[topico]
    return {p: _consumer().get_watermark_offsets(TopicPartition(topico, p), timeout=10) for p in md.partitions}


def ingestao() -> dict:
    from confluent_kafka import ConsumerGroupTopicPartitions
    marcas = _marcas(CFG.topico_questoes)
    tps = [TopicPartition(CFG.topico_questoes, p) for p in marcas]
    fut = _admin().list_consumer_group_offsets([ConsumerGroupTopicPartitions(CFG.grupo_indexer, tps)])
    commit = {tp.partition: tp.offset for tp in list(fut.values())[0].result().topic_partitions}
    particoes = []
    for p, (baixo, alto) in sorted(marcas.items()):
        c = commit.get(p, -1)
        particoes.append({"particao": p, "inicio": baixo, "fim": alto, "commit": c,
                          "lag": alto - (c if c >= 0 else baixo)})
    dlq = _marcas(CFG.topico_dlq)
    contagem = es().count(index=CFG.es_alias)["count"]
    return {"topico": CFG.topico_questoes, "grupo": CFG.grupo_indexer, "particoes": particoes,
            "lag_total": sum(p["lag"] for p in particoes),
            "mensagens_no_topico": sum(alto - baixo for baixo, alto in marcas.values()),
            "dlq_mensagens": sum(alto - baixo for baixo, alto in dlq.values()),
            "documentos_no_indice": contagem}
