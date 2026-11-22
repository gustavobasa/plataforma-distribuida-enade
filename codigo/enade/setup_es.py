"""Bootstrap do Elasticsearch (job es-setup), executado com o superusuário `elastic` apenas na inicialização.

* cria o índice `enade-questoes-v1` (mapping explícito, analisadores PT-BR) e o alias `enade-questoes`;
* cria papéis de menor privilégio e mapeia os principals Kerberos (realm kerb1) para eles:
    indexer@ENADE.LOCAL -> enade_indexer (escrita no índice)
    api@ENADE.LOCAL     -> enade_api     (somente leitura)
  Qualquer outro principal válido no realm (ex.: intruso@ENADE.LOCAL) autentica mas não tem papel -> HTTP 403.
Idempotente: pode ser executado várias vezes.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import requests

from .config import CFG
from .logs import evento, obter_logger

LOG = obter_logger("es-setup")
MAPPING = Path(__file__).resolve().parent / "recursos" / "indice_questoes.json"

PAPEIS = {
    "enade_indexer": {
        "cluster": ["monitor"],
        "indices": [{"names": ["enade-questoes*"],
                     "privileges": ["create_doc", "index", "write", "view_index_metadata"]}],
    },
    "enade_api": {
        "cluster": ["monitor"],
        "indices": [{"names": ["enade-questoes*"], "privileges": ["read", "view_index_metadata"]}],
    },
}
MAPEAMENTOS = {
    "kerberos-indexer": ("indexer@ENADE.LOCAL", ["enade_indexer"]),
    "kerberos-api": ("api@ENADE.LOCAL", ["enade_api"]),
}


def main() -> int:
    s = requests.Session()
    s.auth = ("elastic", os.environ["ELASTIC_PASSWORD"])
    base = CFG.es_url.rstrip("/")
    for i in range(60):
        try:
            r = s.get(f"{base}/_cluster/health", timeout=5)
            if r.ok and r.json()["status"] in ("green", "yellow"):
                break
        except requests.RequestException:
            pass
        evento(LOG, "aguardando Elasticsearch", tentativa=i + 1)
        time.sleep(3)
    else:
        evento(LOG, "Elasticsearch indisponível", nivel=40)
        return 1

    if "--recriar" in sys.argv[1:]:
        # usado apenas no experimento de falha/reprocessamento: o índice é derivado do tópico Kafka
        s.delete(f"{base}/{CFG.es_indice}")
        evento(LOG, "índice removido para reprocessamento completo", indice=CFG.es_indice)
    if s.head(f"{base}/{CFG.es_indice}").status_code == 404:
        r = s.put(f"{base}/{CFG.es_indice}", json=json.loads(MAPPING.read_text(encoding="utf-8")))
        r.raise_for_status()
        evento(LOG, "índice criado", indice=CFG.es_indice)
    else:
        evento(LOG, "índice já existe", indice=CFG.es_indice)
    r = s.post(f"{base}/_aliases", json={"actions": [
        {"add": {"index": CFG.es_indice, "alias": CFG.es_alias, "is_write_index": True}}]})
    r.raise_for_status()

    for nome, corpo in PAPEIS.items():
        s.put(f"{base}/_security/role/{nome}", json=corpo).raise_for_status()
    for nome, (principal, papeis) in MAPEAMENTOS.items():
        corpo = {"enabled": True, "roles": papeis, "rules": {"all": [
            {"field": {"realm.name": "kerb1"}}, {"field": {"username": principal}}]}}
        s.put(f"{base}/_security/role_mapping/{nome}", json=corpo).raise_for_status()
    evento(LOG, "papéis e role mappings Kerberos aplicados", papeis=list(PAPEIS), mapeamentos=list(MAPEAMENTOS))
    return 0


if __name__ == "__main__":
    sys.exit(main())
