"""RF22 — Testes de autenticação mútua Kerberos e autorização entre serviços.

Executar: docker compose --profile testes run --rm testes-kerberos
Usa os keytabs do volume `keytabs` montados em /keytabs (indexer e intruso). Nenhuma senha é usada.
"""
from __future__ import annotations

import os
import subprocess

import requests
from confluent_kafka import KafkaError, KafkaException, Producer
from confluent_kafka.admin import AdminClient
from requests_gssapi import REQUIRED, HTTPSPNEGOAuth

ES = os.environ.get("ES_URL", "http://elasticsearch.enade.local:9200")
KAFKA = os.environ.get("KAFKA_BOOTSTRAP", "kafka.enade.local:9092")


def _kinit(principal: str, keytab: str) -> dict:
    """Obtém TGT em um cache isolado e devolve o ambiente para os clientes GSSAPI."""
    cache = f"/tmp/krb5cc_{principal.split('@')[0]}"
    env = dict(os.environ, KRB5CCNAME=f"FILE:{cache}")
    env.pop("KRB5_CLIENT_KTNAME", None)
    subprocess.run(["kinit", "-k", "-t", keytab, principal], check=True, env=env)
    return env


def test_kdc_emite_ticket_e_klist():
    env = _kinit("indexer@ENADE.LOCAL", "/keytabs/indexer/indexer.keytab")
    saida = subprocess.run(["klist"], capture_output=True, text=True, env=env).stdout
    assert "krbtgt/ENADE.LOCAL@ENADE.LOCAL" in saida and "indexer@ENADE.LOCAL" in saida


def test_es_sem_credencial_401():
    assert requests.get(f"{ES}/_security/_authenticate", timeout=10).status_code == 401


def test_es_spnego_autenticacao_mutua(monkeypatch):
    env = _kinit("indexer@ENADE.LOCAL", "/keytabs/indexer/indexer.keytab")
    monkeypatch.setenv("KRB5CCNAME", env["KRB5CCNAME"])
    r = requests.get(f"{ES}/_security/_authenticate", auth=HTTPSPNEGOAuth(mutual_authentication=REQUIRED), timeout=10)
    assert r.status_code == 200
    corpo = r.json()
    assert corpo["username"] == "indexer@ENADE.LOCAL"
    assert corpo["authentication_realm"]["type"] == "kerberos"
    assert "enade_indexer" in corpo["roles"]
    # resposta mútua: o servidor provou sua identidade com o token no WWW-Authenticate (verificado pelo cliente)
    assert r.headers.get("WWW-Authenticate", "").startswith("Negotiate ")


def test_es_principal_sem_papel_403(monkeypatch):
    env = _kinit("intruso@ENADE.LOCAL", "/keytabs/testes/intruso.keytab")
    monkeypatch.setenv("KRB5CCNAME", env["KRB5CCNAME"])
    auth = HTTPSPNEGOAuth(mutual_authentication=REQUIRED)
    assert requests.get(f"{ES}/_security/_authenticate", auth=auth, timeout=10).status_code == 200  # autentica
    r = requests.get(f"{ES}/enade-questoes/_search", auth=HTTPSPNEGOAuth(mutual_authentication=REQUIRED), timeout=10)
    assert r.status_code == 403  # mas não tem autorização


def _conf(principal: str, keytab: str) -> dict:
    return {"bootstrap.servers": KAFKA, "security.protocol": "SASL_PLAINTEXT", "sasl.mechanisms": "GSSAPI",
            "sasl.kerberos.service.name": "kafka", "sasl.kerberos.principal": principal,
            "sasl.kerberos.keytab": keytab, "socket.timeout.ms": 10000}


def test_kafka_sem_sasl_rejeitado():
    adm = AdminClient({"bootstrap.servers": KAFKA, "socket.timeout.ms": 5000})
    try:
        md = adm.list_topics(timeout=8)
        assert not md.topics, "cliente sem SASL não deveria obter metadados"
    except KafkaException:
        pass


def test_kafka_principal_autorizado_le_metadados():
    md = AdminClient(_conf("indexer@ENADE.LOCAL", "/keytabs/indexer/indexer.keytab")).list_topics(timeout=20)
    assert "enade.questoes.v1" in md.topics


def test_kafka_intruso_sem_acl_nao_publica():
    erros = []
    p = Producer({**_conf("intruso@ENADE.LOCAL", "/keytabs/testes/intruso.keytab"), "message.timeout.ms": 15000})
    p.produce("enade.questoes.v1", b"ataque", on_delivery=lambda e, m: erros.append(e))
    p.flush(20)
    assert erros and erros[0] is not None
    assert erros[0].code() == KafkaError.TOPIC_AUTHORIZATION_FAILED
