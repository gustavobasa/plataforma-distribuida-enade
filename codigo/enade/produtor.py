"""RF07 — Produtor Kafka: publica as questões extraídas (JSONL) no tópico `enade.questoes.v1`.

* autenticação SASL/GSSAPI com o principal `ingestor@ENADE.LOCAL` (keytab);
* chave da mensagem = id determinístico da questão (mesma questão -> mesma partição; base da idempotência);
* `acks=all` + `enable.idempotence=true` (sem duplicatas por reenvio do produtor);
* validação de esquema antes de publicar: registros inválidos vão direto para a DLQ com o motivo.
* métricas: mensagens/s e tempo total gravados em /dados/metricas/produtor-<timestamp>.json (RNF02).

Uso: python -m enade.produtor --anos 2021 2022 2023 [--cursos slug ...]
"""
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from confluent_kafka import Producer

from .config import CFG
from .esquema import VERSAO_ESQUEMA, validar
from .kerberos import kafka_conf_base
from .logs import evento, obter_logger

LOG = obter_logger("produtor")


def criar_produtor() -> Producer:
    return Producer(kafka_conf_base({
        "acks": "all",
        "enable.idempotence": True,
        "compression.type": "zstd",
        "linger.ms": 20,
        "batch.num.messages": 500,
        "message.timeout.ms": 300000,
        "client.id": "enade-ingestor",
    }))


def publicar(arquivos: list[Path], produtor: Producer | None = None) -> dict:
    produtor = produtor or criar_produtor()
    estado = {"entregues": 0, "falhas": 0, "dlq": 0, "lidos": 0}

    def ao_entregar(err, msg):
        if err is not None:
            estado["falhas"] += 1
            evento(LOG, "falha na entrega", nivel=40, erro=str(err), chave=(msg.key() or b"").decode())
        else:
            estado["entregues"] += 1

    t0 = time.perf_counter()
    for arq in arquivos:
        for linha in arq.read_text(encoding="utf-8").splitlines():
            if not linha.strip():
                continue
            estado["lidos"] += 1
            bruto = json.loads(linha)
            doc, erro = validar({k: v for k, v in bruto.items() if not k.startswith("_")})
            headers = [("schema_versao", str(VERSAO_ESQUEMA).encode()), ("origem", arq.name.encode()),
                       ("content-type", b"application/json")]
            if doc is None:
                estado["dlq"] += 1
                produtor.produce(CFG.topico_dlq, key=str(bruto.get("id", "")).encode(),
                                 value=linha.encode(), headers=headers + [("erro", (erro or "")[:900].encode()),
                                                                          ("etapa", b"produtor")],
                                 on_delivery=ao_entregar)
            else:
                produtor.produce(CFG.topico_questoes, key=doc["id"].encode(),
                                 value=json.dumps(doc, ensure_ascii=False).encode(), headers=headers,
                                 on_delivery=ao_entregar)
            produtor.poll(0)
    pendentes = produtor.flush(120)
    dur = time.perf_counter() - t0
    estado.update({"pendentes_apos_flush": pendentes, "segundos": round(dur, 3),
                   "msgs_por_segundo": round(estado["entregues"] / dur, 1) if dur else None})
    return estado


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--anos", type=int, nargs="*", default=[2021, 2022, 2023])
    ap.add_argument("--cursos", nargs="*")
    ap.add_argument("--arquivos", nargs="*", help="JSONL específicos (sobrepõe --anos/--cursos)")
    args = ap.parse_args(argv)
    base = Path(CFG.dados_dir) / "extraidos"
    if args.arquivos:
        arquivos = [Path(a) for a in args.arquivos]
    else:
        arquivos = sorted(p for ano in args.anos for p in (base / str(ano)).glob("*.jsonl")
                          if not args.cursos or p.stem in args.cursos)
    if not arquivos:
        evento(LOG, "nenhum arquivo JSONL encontrado; rode antes `python -m enade.extracao`", nivel=40)
        return 1
    evento(LOG, "publicação iniciada", arquivos=len(arquivos), topico=CFG.topico_questoes)
    estado = publicar(arquivos)
    estado.update({"arquivos": len(arquivos), "fim": datetime.now(timezone.utc).isoformat(timespec="seconds")})
    met = Path(CFG.dados_dir) / "metricas"
    met.mkdir(parents=True, exist_ok=True)
    (met / f"produtor-{int(time.time())}.json").write_text(json.dumps(estado, indent=1), encoding="utf-8")
    evento(LOG, "publicação concluída", **estado)
    return 0 if estado["falhas"] == 0 and estado["pendentes_apos_flush"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
