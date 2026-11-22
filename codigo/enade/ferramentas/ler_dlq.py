"""Lista as mensagens da DLQ (tópico de erros) com os cabeçalhos de diagnóstico. Somente leitura.

Uso (no contêiner api, principal api@ENADE.LOCAL com ACL de leitura na DLQ): python -m enade.ferramentas.ler_dlq
"""
from __future__ import annotations

import json
import uuid

from confluent_kafka import Consumer, TopicPartition

from ..config import CFG
from ..kerberos import kafka_conf_base


def main() -> int:
    c = Consumer(kafka_conf_base({"group.id": "enade-api-monitor", "enable.auto.commit": False,
                                  "client.id": f"ler-dlq-{uuid.uuid4().hex[:6]}"}))
    md = c.list_topics(CFG.topico_dlq, timeout=10).topics[CFG.topico_dlq]
    tps = []
    for p in md.partitions:
        baixo, alto = c.get_watermark_offsets(TopicPartition(CFG.topico_dlq, p), timeout=10)
        if alto > baixo:
            tps.append(TopicPartition(CFG.topico_dlq, p, baixo))
    c.assign(tps)
    total = sum(c.get_watermark_offsets(TopicPartition(t.topic, t.partition))[1] - t.offset for t in tps)
    lidas = 0
    while lidas < total:
        m = c.poll(5)
        if m is None:
            break
        if m.error():
            continue
        lidas += 1
        h = {k: v.decode(errors="replace") for k, v in (m.headers() or [])}
        print(json.dumps({"offset": m.offset(), "chave": (m.key() or b"").decode(errors="replace"),
                          "motivo": h.get("motivo"), "etapa": h.get("etapa"), "origem": f"{h.get('topico_origem')}"
                          f"[{h.get('particao_origem')}]@{h.get('offset_origem')}", "erro": (h.get("erro") or "")[:160]},
                         ensure_ascii=False))
    c.close()
    print(f"total na DLQ: {total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
