"""RF08/RF09/RF10/RF11 — Consumidor Kafka que indexa as questões no Elasticsearch.

Garantias:
  * commit manual do offset SOMENTE depois que o lote foi confirmado pelo Elasticsearch e as mensagens
    inválidas foram confirmadas na DLQ -> nenhuma mensagem confirmada é perdida (at-least-once);
  * `_id` = id determinístico da questão -> reprocessamento sobrescreve, não duplica (idempotência);
  * mensagens malformadas (JSON inválido, esquema inválido, rejeição 4xx do mapping) vão para a DLQ com
    cabeçalhos de diagnóstico e o fluxo principal continua;
  * falhas transitórias (ES fora do ar, 429/5xx) -> nova tentativa com backoff exponencial, sem commit.
Autenticação: Kafka via SASL/GSSAPI e Elasticsearch via SPNEGO, ambos como `indexer@ENADE.LOCAL`.
Métricas Prometheus em :8001/metrics (docs indexados, DLQ, duração do lote, lag do consumidor).
"""
from __future__ import annotations

import json
import signal
import time
from datetime import datetime, timezone

import redis
from confluent_kafka import Consumer, KafkaError, Producer, TopicPartition
from elasticsearch import ConnectionError as ESConnectionError
from elasticsearch import TransportError
from prometheus_client import Counter, Gauge, Histogram, start_http_server

from .config import CFG, redis_password
from .esquema import validar
from .kerberos import es_cliente, kafka_conf_base
from .logs import evento, obter_logger

LOG = obter_logger("indexer")
TAMANHO_LOTE = 200

M_DOCS = Counter("enade_indexer_docs_total", "Documentos indexados com sucesso")
M_DLQ = Counter("enade_indexer_dlq_total", "Mensagens enviadas para a DLQ", ["motivo"])
M_RETRY = Counter("enade_indexer_retentativas_total", "Retentativas por falha transitória do Elasticsearch")
M_LOTE = Histogram("enade_indexer_lote_segundos", "Duração do processamento de um lote",
                   buckets=(0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 30))
M_LAG = Gauge("enade_indexer_lag_mensagens", "Lag do grupo de consumo (soma das partições)")
M_ULTIMO = Gauge("enade_indexer_ultimo_commit_timestamp", "Epoch do último commit de offset")


class FalhaTransitoria(Exception):
    pass


class Indexador:
    def __init__(self) -> None:
        self.rodando = True
        self.consumer = Consumer(kafka_conf_base({
            "group.id": CFG.grupo_indexer,
            "client.id": "enade-indexer",
            "enable.auto.commit": False,
            "auto.offset.reset": "earliest",
            "max.poll.interval.ms": 900000,
            "session.timeout.ms": 30000,
        }))
        self.dlq = Producer(kafka_conf_base({"acks": "all", "enable.idempotence": True, "client.id": "enade-indexer-dlq"}))
        self.es = es_cliente()
        self.redis = redis.Redis(host=CFG.redis_host, port=CFG.redis_port, password=redis_password(),
                                 socket_timeout=5, decode_responses=True)
        self._ultimo_lag = 0.0

    # ------------------------------------------------------------------ DLQ
    def _para_dlq(self, msg, motivo: str, erro: str) -> None:
        headers = [("erro", erro[:900].encode()), ("motivo", motivo.encode()), ("etapa", b"indexer"),
                   ("topico_origem", msg.topic().encode()), ("particao_origem", str(msg.partition()).encode()),
                   ("offset_origem", str(msg.offset()).encode()),
                   ("ts", datetime.now(timezone.utc).isoformat().encode())]
        self.dlq.produce(CFG.topico_dlq, key=msg.key(), value=msg.value(), headers=headers)
        M_DLQ.labels(motivo).inc()

    # ------------------------------------------------------------------ Elasticsearch
    def _bulk(self, acoes: list[tuple]) -> list[tuple]:
        """Indexa; devolve [(msg, erro)] rejeitados permanentemente (4xx). Lança FalhaTransitoria se 429/5xx/conexão."""
        corpo = []
        for _, doc in acoes:
            corpo.append({"index": {"_index": CFG.es_alias, "_id": doc["id"]}})
            corpo.append(doc)
        try:
            resp = self.es.bulk(operations=corpo, refresh=False)
        except (ESConnectionError, TransportError) as exc:
            raise FalhaTransitoria(repr(exc)) from exc
        if not resp.get("errors"):
            return []
        rejeitados, transitorios = [], 0
        for (msg, _), item in zip(acoes, resp["items"]):
            r = item.get("index", {})
            st = r.get("status", 500)
            if st >= 300:
                if st == 429 or st >= 500:
                    transitorios += 1
                else:
                    rejeitados.append((msg, json.dumps(r.get("error"), ensure_ascii=False)))
        if transitorios:
            raise FalhaTransitoria(f"{transitorios} itens com 429/5xx")
        return rejeitados

    def _bulk_com_retentativa(self, acoes: list[tuple]) -> list[tuple]:
        espera = 1.0
        while True:
            try:
                return self._bulk(acoes)
            except FalhaTransitoria as exc:
                M_RETRY.inc()
                evento(LOG, "Elasticsearch indisponível; lote será reenviado (offset NÃO confirmado)",
                       nivel=30, erro=str(exc)[:300], espera_s=espera)
                if not self.rodando:
                    raise
                time.sleep(espera)
                espera = min(espera * 2, 30.0)

    # ------------------------------------------------------------------ lag
    def _atualizar_lag(self) -> None:
        atribuicoes = self.consumer.assignment()
        if not atribuicoes:
            return
        total = 0
        comprometidos = self.consumer.committed(atribuicoes, timeout=10)
        for tp in comprometidos:
            _, alto = self.consumer.get_watermark_offsets(TopicPartition(tp.topic, tp.partition), timeout=10)
            pos = tp.offset if tp.offset >= 0 else 0
            total += max(alto - pos, 0)
        M_LAG.set(total)
        self._ultimo_lag = time.time()

    # ------------------------------------------------------------------ laço principal
    def processar_lote(self, msgs) -> dict:
        t0 = time.perf_counter()
        acoes, invalidas = [], []
        agora = datetime.now(timezone.utc).isoformat(timespec="seconds")
        for m in msgs:
            if m.error():
                if m.error().code() != KafkaError._PARTITION_EOF:
                    evento(LOG, "erro do consumidor", nivel=40, erro=str(m.error()))
                continue
            try:
                bruto = json.loads(m.value())
                if not isinstance(bruto, dict):
                    raise ValueError("JSON não é um objeto")
            except (ValueError, TypeError, UnicodeDecodeError) as exc:
                invalidas.append((m, "json_invalido", str(exc)))
                continue
            bruto.pop("kafka", None)
            bruto.pop("indexado_em", None)
            doc, erro = validar(bruto)
            if doc is None:
                invalidas.append((m, "esquema_invalido", erro or ""))
                continue
            doc["kafka"] = {"topico": m.topic(), "particao": m.partition(), "offset": m.offset()}
            doc["indexado_em"] = agora
            acoes.append((m, doc))
        rejeitados = self._bulk_com_retentativa(acoes) if acoes else []
        for m, motivo, erro in invalidas:
            self._para_dlq(m, motivo, erro)
        for m, erro in rejeitados:
            self._para_dlq(m, "rejeitado_elasticsearch", erro)
        if invalidas or rejeitados:
            if self.dlq.flush(60) > 0:
                raise RuntimeError("DLQ não confirmou as mensagens; offset não será confirmado")
        self.consumer.commit(asynchronous=False)
        M_ULTIMO.set(time.time())
        indexados = len(acoes) - len(rejeitados)
        M_DOCS.inc(indexados)
        if indexados:
            try:
                self.redis.incr("indice:versao")  # invalidação do cache de buscas (ADR-08)
            except redis.RedisError as exc:
                evento(LOG, "falha ao invalidar cache (TTL cobrirá)", nivel=30, erro=str(exc))
        dur = time.perf_counter() - t0
        M_LOTE.observe(dur)
        res = {"mensagens": len(msgs), "indexados": indexados, "dlq": len(invalidas) + len(rejeitados),
               "segundos": round(dur, 3)}
        evento(LOG, "lote confirmado", **res)
        return res

    def executar(self) -> None:
        self.consumer.subscribe([CFG.topico_questoes],
                                on_assign=lambda c, ps: evento(LOG, "partições atribuídas",
                                                               particoes=[p.partition for p in ps]))
        evento(LOG, "indexer iniciado", topico=CFG.topico_questoes, grupo=CFG.grupo_indexer, alias=CFG.es_alias)
        try:
            while self.rodando:
                msgs = self.consumer.consume(num_messages=TAMANHO_LOTE, timeout=1.0)
                if msgs:
                    self.processar_lote(msgs)
                if time.time() - self._ultimo_lag > 10:
                    try:
                        self._atualizar_lag()
                    except Exception as exc:  # métrica auxiliar: não derruba o consumidor
                        evento(LOG, "falha ao calcular lag", nivel=30, erro=str(exc))
        except FalhaTransitoria:
            evento(LOG, "encerrando durante retentativa; lote será relido no próximo início", nivel=30)
        finally:
            self.consumer.close()
            self.dlq.flush(10)
            evento(LOG, "indexer encerrado")

    def parar(self, *_):
        self.rodando = False


def main() -> int:
    start_http_server(8001)
    idx = Indexador()
    signal.signal(signal.SIGTERM, idx.parar)
    signal.signal(signal.SIGINT, idx.parar)
    idx.executar()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
