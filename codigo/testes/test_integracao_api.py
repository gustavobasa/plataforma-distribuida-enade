"""Testes de integração ponta a ponta contra a API em execução (requer o ambiente no ar e o índice populado).

Executar: docker compose --profile testes run --rm testes
"""
from __future__ import annotations

import os

import httpx
import pytest

API = os.environ.get("API_URL", "http://api:8000")
SENHA_EST = os.environ.get("LDAP_SENHA_ESTUDANTES", "")
SENHA_PROF = os.environ.get("LDAP_SENHA_PROFESSORES", "")


def login(usuario: str, senha: str) -> httpx.Client:
    c = httpx.Client(base_url=API, timeout=30)
    r = c.post("/api/auth/login", json={"usuario": usuario, "senha": senha})
    assert r.status_code == 200, r.text
    c.headers["Authorization"] = f"Bearer {r.json()['token']}"
    return c


@pytest.fixture(scope="module")
def est():
    return login("estudante1", SENHA_EST)


@pytest.fixture(scope="module")
def prof():
    return login("professor1", SENHA_PROF)


@pytest.fixture(scope="module")
def uma_questao(prof):
    r = prof.get("/api/busca", params={"tipo": "objetiva", "anulada": "false", "por_pagina": 1, "ano": 2023,
                                       "componente": "FG"})
    return r.json()["itens"][0]


# ------------------------------------------------------------------ RF23 / RF17
def test_login_invalido_401():
    r = httpx.post(f"{API}/api/auth/login", json={"usuario": "estudante2", "senha": "senha-errada"})
    assert r.status_code == 401


def test_login_injecao_ldap_rejeitada():
    r = httpx.post(f"{API}/api/auth/login", json={"usuario": "*)(uid=*", "senha": "x"})
    assert r.status_code == 401


def test_sem_autenticacao_401():
    assert httpx.get(f"{API}/api/busca", params={"q": "ética"}).status_code == 401


def test_perfis_vindos_do_ldap(est, prof):
    assert est.get("/api/auth/eu").json()["perfil"] == "estudante"
    assert prof.get("/api/auth/eu").json()["perfil"] == "professor"


def test_openapi_documentado():
    spec = httpx.get(f"{API}/openapi.json").json()
    assert "/api/busca" in spec["paths"] and "/api/questoes/{qid}/gabarito" in spec["paths"]
    assert "403" in spec["paths"]["/api/questoes/{qid}/gabarito"]["get"]["responses"]


def test_parametro_invalido_422(est):
    assert est.get("/api/busca", params={"por_pagina": 500}).status_code == 422
    assert est.get("/api/busca", params={"componente": "XX"}).status_code == 422


# ------------------------------------------------------------------ RF12–RF16
def test_busca_fulltext_highlight(est):
    r = est.get("/api/busca", params={"q": "desigualdade social"})
    assert r.status_code == 200
    d = r.json()
    assert d["total"] > 0
    assert any("<mark>" in f for item in d["itens"] for f in item["destaques"])


def test_stemming_ptbr(est):
    """'desigualdades' (plural) deve recuperar documentos com 'desigualdade' (radicalização)."""
    a = est.get("/api/busca", params={"q": "desigualdades", "cache": "false"}).json()["total"]
    b = est.get("/api/busca", params={"q": "desigualdade", "cache": "false"}).json()["total"]
    assert a > 0 and a == b


def test_sinonimos(est):
    """'idadismo' só existe no dicionário de sinônimos (etarismo); deve recuperar questões sobre etarismo."""
    d = est.get("/api/busca", params={"q": "idadismo", "cache": "false"}).json()
    assert d["total"] > 0
    assert any("etarismo" in f.lower() for i in d["itens"] for f in i["destaques"])


def test_interdisciplinar_varios_cursos(est):
    """RF14: uma busca por 'ética' retorna questões de cursos diferentes."""
    d = est.get("/api/busca", params={"q": "ética", "por_pagina": 50}).json()
    assert len({i["curso_slug"] for i in d["itens"]}) >= 3
    assert len(d["facetas"]["curso"]) >= 5


def test_filtros_combinados(est):
    p = {"ano": 2022, "componente": "CE", "tipo": "objetiva", "area": "Ciências Sociais Aplicadas", "por_pagina": 50}
    d = est.get("/api/busca", params=p).json()
    assert d["total"] > 0
    for i in d["itens"]:
        assert (i["ano"], i["componente"], i["tipo_questao"], i["area"]) == (2022, "CE", "objetiva", "Ciências Sociais Aplicadas")


def test_filtro_competencia(est):
    d = est.get("/api/busca", params={"competencia": "C7", "por_pagina": 20}).json()
    assert d["total"] > 0 and all("C7" in i["competencias_ids"] for i in d["itens"])


def test_paginacao(est):
    p1 = est.get("/api/busca", params={"q": "saúde", "pagina": 1}).json()
    p2 = est.get("/api/busca", params={"q": "saúde", "pagina": 2}).json()
    assert p1["paginas"] >= 2
    assert {i["id"] for i in p1["itens"]}.isdisjoint({i["id"] for i in p2["itens"]})


def test_colapsar_equivalentes(est):
    d = est.get("/api/busca", params={"componente": "FG", "ano": 2023, "colapsar": "true", "por_pagina": 50}).json()
    assert d["total"] <= 10  # 10 questões de FG em 2023, repetidas em 28 cursos
    assert all(i["cursos_equivalentes"] >= 2 for i in d["itens"])


def test_equivalentes_em_outros_cursos(est, uma_questao):
    d = est.get(f"/api/questoes/{uma_questao['id']}/equivalentes").json()
    assert len(d["mesma_questao_em_outros_cursos"]) >= 2


def test_rastreabilidade(est, uma_questao):
    q = est.get(f"/api/questoes/{uma_questao['id']}").json()
    assert q["origem"]["pdf"].endswith(".pdf") and q["origem"]["paginas"][0] >= 1
    assert q["origem"]["url"].startswith("https://download.inep.gov.br/")


# ------------------------------------------------------------------ RF24 / RF25
def test_estudante_nao_ve_gabarito_na_busca_nem_no_detalhe(est, uma_questao):
    d = est.get("/api/busca", params={"q": "ética", "por_pagina": 50}).json()
    assert all("gabarito" not in i and "padrao_resposta" not in i for i in d["itens"])
    q = est.get(f"/api/questoes/{uma_questao['id']}").json()
    assert "gabarito" not in q and "padrao_resposta" not in q


@pytest.mark.parametrize("rota,metodo", [
    ("/api/questoes/{id}/gabarito", "GET"), ("/api/analitico", "GET"), ("/api/carrinho/exportar?formato=json", "GET"),
    ("/api/carrinho/exportar?formato=pdf", "GET"), ("/api/admin/cache", "GET"), ("/api/admin/ingestao", "GET"),
    ("/api/admin/cache/invalidar", "POST"),
])
def test_estudante_rotas_restritas_403(est, uma_questao, rota, metodo):
    r = est.request(metodo, rota.replace("{id}", uma_questao["id"]))
    assert r.status_code == 403, r.text


def test_professor_ve_gabarito(prof, uma_questao):
    r = prof.get(f"/api/questoes/{uma_questao['id']}/gabarito")
    assert r.status_code == 200 and r.json()["gabarito"] in list("ABCDE")


def test_cache_nao_vaza_gabarito_entre_perfis(est, prof):
    p = {"q": "sustentabilidade", "por_pagina": 5}
    prof.get("/api/busca", params=p)  # popula o cache do professor
    d = est.get("/api/busca", params=p).json()
    assert all("gabarito" not in i for i in d["itens"])


# ------------------------------------------------------------------ RF18 / RF19 / RF21
def test_cache_hit_e_invalidacao(prof):
    p = {"q": "inteligência artificial", "ano": 2023}
    prof.get("/api/busca", params=p)
    r = prof.get("/api/busca", params=p)
    assert r.headers["X-Cache"] == "HIT"
    prof.post("/api/admin/cache/invalidar")
    assert prof.get("/api/busca", params=p).headers["X-Cache"] == "MISS"


def test_carrinho_e_exportacao(prof, est, uma_questao):
    qid = uma_questao["id"]
    prof.delete("/api/carrinho")
    assert prof.post(f"/api/carrinho/{qid}").status_code == 201
    assert prof.post("/api/carrinho/inexistente123456789").status_code == 404
    assert prof.get("/api/carrinho").json()["total"] == 1
    # o carrinho é por sessão: o estudante não vê a lista do professor
    assert est.get("/api/carrinho").json()["total"] == 0
    j = prof.get("/api/carrinho/exportar", params={"formato": "json"})
    assert j.status_code == 200 and j.json()["questoes"][0]["gabarito"] in list("ABCDE")
    p = prof.get("/api/carrinho/exportar", params={"formato": "pdf"})
    assert p.status_code == 200 and p.content.startswith(b"%PDF")
    assert prof.delete(f"/api/carrinho/{qid}").status_code == 200
    assert prof.get("/api/carrinho").json()["total"] == 0


# ------------------------------------------------------------------ RF15 / RNF06
def test_agregacoes(prof):
    d = prof.get("/api/analitico").json()
    assert set(d["anos"]) >= {2021, 2022, 2023}
    assert d["competencias_por_ano"] and d["por_curso"]
    assert sum(c["total"] for c in d["por_curso"]) > 1000


def test_health_e_metricas():
    r = httpx.get(f"{API}/health/ready")
    assert r.status_code == 200 and r.json()["status"] == "ok"
    assert "enade_api_requisicao_segundos" in httpx.get(f"{API}/metrics").text
