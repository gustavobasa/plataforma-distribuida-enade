"""Testes unitários (sem infraestrutura): normalização, LaTeX, gabarito, esquema, id, taxonomia, cache.

Executar: docker compose run --rm --no-deps ingestor python -m pytest -q testes/test_unitarios.py
"""
from __future__ import annotations

import copy

import pytest

from enade.esquema import grupo_equivalencia, id_questao, validar
from enade.extracao.gabarito import RE_PAR
from enade.extracao.metadados import area_do_curso, classificar, grau_do_curso
from enade.extracao.segmentador import RE_ALT, RE_DISCURSIVA, RE_OBJETIVA, ler_capa
from enade.extracao.texto import Linha, _formula_inline, _palavra_latex, normalizar


def doc_valido() -> dict:
    return {
        "id": id_questao(2023, "engenharia_da_computacao", "objetiva", 12),
        "ano": 2023, "area": "Computação e Tecnologia da Informação", "curso": "Engenharia de Computação",
        "curso_slug": "engenharia_da_computacao", "grau": "Bacharelado", "componente": "CE",
        "tipo_questao": "objetiva", "numero": 12, "rotulo": "Questão 12", "enunciado": "Assinale a opção correta.",
        "alternativas": [{"letra": l, "texto": f"alt {l}"} for l in "ABCDE"],
        "gabarito": "A", "gabarito_status": "definitivo",
        "origem": {"pdf": "2023_PV_engenharia_da_computacao.pdf", "paginas": [16]},
        "grupo_equivalencia": "x" * 16,
        "extracao": {"versao": "1.0", "confianca": "alta", "alertas": [], "extraido_em": "2026-11-22T00:00:00+00:00"},
    }


def test_normalizar_ligadura_e_espacos():
    assert normalizar("HepaƟte  A­") == "Hepatite A"
    assert normalizar("ﬁ") == "fi"


def test_latex_subscrito_e_simbolos():
    assert _palavra_latex([("a", "n"), ("n", "sub")]) == "a_{n}"
    assert _palavra_latex([("x", "n"), ("2", "sup")]) == "x^{2}"
    assert _palavra_latex([("≠", "n")]) == r"\neq"
    assert _formula_inline(["a_{n}", "=", "b_{m},"]) == "$a_{n} = b_{m}$,"


def test_cabecalhos_de_questao():
    assert int(RE_OBJETIVA.match("QUESTÃO 09").group(1)) == 9
    assert RE_OBJETIVA.match("QUESTÃO 09 QUESTÃO 10") is None  # duas colunas não podem ser mescladas
    assert int(RE_DISCURSIVA.match("QUESTÃO DISCURSIVA 03").group(1)) == 3
    assert RE_ALT.match("E II, III e IV").group(1) == "E"


def test_capa_define_componente():
    l = lambda t: Linha(1, 0, 0, 0, 0, t, t, 12, False)  # noqa: E731
    capa = ler_capa([l("Formação Geral: Discursivas D1 e D2 40%"), l("Formação Geral: Objetivas 1 a 8 60%"),
                     l("Componente Específico: Discursivas D3 a D5 15%"), l("Componente Específico: Objetivas 9 a 35 85%")])
    assert capa[("objetiva", 8)] == "FG" and capa[("objetiva", 9)] == "CE"
    assert capa[("discursiva", 2)] == "FG" and capa[("discursiva", 4)] == "CE"


def test_gabarito_regex():
    texto = "QUESTÃO DISCURSIVA 1\n***\nQUESTÃO 1\nD\nQUESTÃO 8 \nANULADA\nQUESTÃO 9\nE"
    itens = {(bool(m.group(1)), int(m.group(2))): m.group(3) for m in RE_PAR.finditer(texto)}
    assert itens[(False, 1)] == "D" and itens[(False, 8)] == "ANULADA" and itens[(True, 1)] == "***"


def test_id_estavel_e_grupo():
    a = id_questao(2023, "x", "objetiva", 1)
    assert a == id_questao(2023, "x", "objetiva", 1) != id_questao(2023, "x", "objetiva", 2)
    alts = [{"texto": "Á"}]
    assert grupo_equivalencia("Ética  e cidadania", alts) == grupo_equivalencia("etica e cidadania", [{"texto": "a"}])


def test_validacao_esquema():
    ok, erro = validar(doc_valido())
    assert ok and erro is None
    ruim = copy.deepcopy(doc_valido()); ruim["id"] = "outro-id-qualquer"
    assert validar(ruim)[0] is None
    ruim = copy.deepcopy(doc_valido()); ruim["alternativas"] = ruim["alternativas"][:3]
    assert validar(ruim)[0] is None
    ruim = copy.deepcopy(doc_valido()); del ruim["origem"]
    assert validar(ruim)[0] is None
    ruim = copy.deepcopy(doc_valido()); ruim["componente"] = "XX"
    assert validar(ruim)[0] is None


@pytest.mark.parametrize("slug,area,grau", [
    ("engenharia_da_computacao", "Engenharias e Arquitetura", "Bacharelado"),
    ("licenciatura_pedagogia", "Ciências Humanas", "Licenciatura"),
    ("tecnologia_redes_computadores", "Computação e Tecnologia da Informação", "Tecnologia"),
    ("medicina_veterinaria", "Ciências Agrárias", "Bacharelado"),
    ("direito", "Ciências Sociais Aplicadas", "Bacharelado"),
])
def test_area_e_grau(slug, area, grau):
    assert area_do_curso(slug) == area and grau_do_curso(slug) == grau


def test_classificador_temas():
    r = classificar("A fome e a insegurança alimentar ... produção de alimentos e agricultura familiar",
                    "Considerando o texto, avalie as asserções a seguir. PORQUE", [], False, False, "objetiva")
    assert "T07" in r["objetos_ids"]
    assert "C7" in r["competencias_ids"]


def test_campo_desconhecido_vai_para_dlq():
    ruim = copy.deepcopy(doc_valido())
    ruim["campo_inexistente"] = "x"
    doc, erro = validar(ruim)
    assert doc is None and "extra_forbidden" in erro


def test_quatro_alternativas_aceitas():
    d = copy.deepcopy(doc_valido())
    d["alternativas"] = d["alternativas"][:4]
    assert validar(d)[0] is not None
