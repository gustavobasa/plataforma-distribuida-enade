"""RF11 — Injeta mensagens malformadas no tópico principal para demonstrar o encaminhamento à DLQ.

Tipos injetados (todos marcados com chave "teste-invalida-*", não são dados do ENADE):
  1. bytes que não são JSON;  2. JSON que não é objeto;  3. objeto sem campos obrigatórios;
  4. id inconsistente com (ano, curso, tipo, número);  5. campo desconhecido rejeitado pelo mapping estrito.
Uso (no contêiner ingestor): python -m enade.ferramentas.injetar_invalidas
"""
from __future__ import annotations

import json

from confluent_kafka import Producer

from ..config import CFG
from ..esquema import id_questao
from ..kerberos import kafka_conf_base


def mensagens() -> list[tuple[str, bytes]]:
    valido_base = {
        "ano": 2099, "area": "Teste", "curso": "TESTE SINTÉTICO", "curso_slug": "teste_sintetico", "grau": "Bacharelado",
        "componente": "CE", "tipo_questao": "objetiva", "numero": 1, "rotulo": "Questão 01",
        "enunciado": "registro sintético de teste", "gabarito_status": "indisponivel",
        "origem": {"pdf": "sintetico.pdf", "paginas": [1]}, "grupo_equivalencia": "0" * 16,
        "extracao": {"versao": "teste", "confianca": "baixa", "alertas": ["sintetico"], "extraido_em": "2026-01-01T00:00:00Z"},
    }
    id_ok = id_questao(2099, "teste_sintetico", "objetiva", 1)
    sem_campos = {"id": "abc", "ano": 2023}
    id_errado = dict(valido_base, id="0123456789abcdef01234567")
    campo_extra = dict(valido_base, id=id_ok, campo_que_nao_existe_no_mapping="x")
    return [
        ("teste-invalida-1", b"\x00\xffisto nao e json{"),
        ("teste-invalida-2", json.dumps([1, 2, 3]).encode()),
        ("teste-invalida-3", json.dumps(sem_campos).encode()),
        ("teste-invalida-4", json.dumps(id_errado).encode()),
        ("teste-invalida-5", json.dumps(campo_extra).encode()),
    ]


def main() -> int:
    p = Producer(kafka_conf_base({"acks": "all", "enable.idempotence": True}))
    entregues = []
    for chave, valor in mensagens():
        p.produce(CFG.topico_questoes, key=chave.encode(), value=valor,
                  on_delivery=lambda e, m: entregues.append((m.key().decode(), m.partition(), m.offset(), e)))
    p.flush(30)
    for k, part, off, err in entregues:
        print(f"injetada {k} -> {CFG.topico_questoes}[{part}]@{off} erro={err}")
    return 0 if all(e is None for *_, e in entregues) and len(entregues) == 5 else 1


if __name__ == "__main__":
    raise SystemExit(main())
