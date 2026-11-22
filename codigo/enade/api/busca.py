"""RF12–RF16 — Construção das consultas ao Elasticsearch (full-text PT-BR, filtros, highlight, agregações)."""
from __future__ import annotations

import time
from typing import Any

from ..config import CFG
from ..esquema import CAMPOS_RESTRITOS
from .estado import M_ES, es

CAMPOS_BUSCA = ["enunciado^3", "texto_base^1.5", "alternativas.texto", "midia.descricao_figuras^0.7", "curso^0.5"]
CAMPOS_HIGHLIGHT = ["enunciado", "texto_base", "alternativas.texto", "midia.descricao_figuras"]
CAMPOS_LISTA = ["id", "ano", "area", "curso", "curso_slug", "grau", "componente", "tipo_questao", "numero",
                "rotulo", "anulada", "gabarito_status", "competencias", "competencias_ids", "objetos_conhecimento",
                "objetos_ids", "origem.pdf", "origem.paginas", "grupo_equivalencia", "enunciado",
                "midia.tem_formula", "extracao.confianca"]
FACETAS = {"area": "area", "curso": "curso_slug", "ano": "ano", "componente": "componente",
           "tipo": "tipo_questao", "competencia": "competencias_ids", "objeto": "objetos_ids", "grau": "grau"}


def excluir_restritos(professor: bool) -> list[str]:
    """Campos nunca devolvidos ao perfil Estudante (RF24), em qualquer rota."""
    return [] if professor else list(CAMPOS_RESTRITOS)


def filtros(f: dict) -> list[dict]:
    out: list[dict] = []
    for nome, campo in FACETAS.items():
        valores = [v for v in (f.get(nome) or []) if v not in (None, "")]
        if valores:
            out.append({"terms": {campo: valores}})
    if f.get("anulada") is not None:
        out.append({"term": {"anulada": bool(f["anulada"])}})
    if f.get("com_formula"):
        out.append({"term": {"midia.tem_formula": True}})
    return out


def consulta(q: str | None, f: dict) -> dict:
    must: list[dict] = []
    should: list[dict] = []
    if q:
        must.append({"multi_match": {"query": q, "fields": CAMPOS_BUSCA, "type": "best_fields",
                                     "operator": "or", "minimum_should_match": "2<70%"}})
        should.append({"multi_match": {"query": q, "fields": ["enunciado^2", "texto_base"],
                                       "type": "phrase", "slop": 2, "boost": 2}})
    return {"bool": {"must": must or [{"match_all": {}}], "should": should, "filter": filtros(f)}}


def _tempo(operacao: str, fn, **kw):
    t = time.perf_counter()
    try:
        return fn(**kw)
    finally:
        M_ES.labels(operacao).observe(time.perf_counter() - t)


def buscar(q: str | None, f: dict, pagina: int, por_pagina: int, professor: bool, colapsar: bool,
           ordenar: str) -> dict[str, Any]:
    corpo: dict[str, Any] = {
        "query": consulta(q, f),
        "from": (pagina - 1) * por_pagina,
        "size": por_pagina,
        "track_total_hits": True,
        "_source": {"includes": CAMPOS_LISTA, "excludes": excluir_restritos(professor)},
        "highlight": {
            "pre_tags": ["<mark>"], "post_tags": ["</mark>"], "encoder": "html",
            "type": "fvh", "fragment_size": 180, "number_of_fragments": 3, "no_match_size": 0,
            "fields": {c: {} for c in CAMPOS_HIGHLIGHT},
        },
        "aggs": {nome: {"terms": {"field": campo, "size": 100}} for nome, campo in FACETAS.items()},
    }
    corpo["aggs"]["curso"]["aggs"] = {"nome": {"terms": {"field": "curso.kw", "size": 1}}}
    if ordenar == "ano":
        corpo["sort"] = [{"ano": "desc"}, {"curso_slug": "asc"}, {"numero": "asc"}]
    elif not q:
        corpo["sort"] = [{"ano": "desc"}, {"curso_slug": "asc"}, {"numero": "asc"}]
    if colapsar:
        corpo["collapse"] = {"field": "grupo_equivalencia",
                             "inner_hits": {"name": "cursos", "size": 0}}
        corpo["aggs"]["grupos"] = {"cardinality": {"field": "grupo_equivalencia"}}
    resp = _tempo("busca", es().search, index=CFG.es_alias, body=corpo)
    total = resp["hits"]["total"]["value"]
    if colapsar:
        total = resp["aggregations"]["grupos"]["value"]
    itens = []
    for h in resp["hits"]["hits"]:
        doc = h["_source"]
        doc["_score"] = h.get("_score")
        doc["destaques"] = [frag for campo in CAMPOS_HIGHLIGHT for frag in h.get("highlight", {}).get(campo, [])]
        if colapsar:
            doc["cursos_equivalentes"] = h.get("inner_hits", {}).get("cursos", {}).get("hits", {}).get("total", {}).get("value")
        itens.append(doc)
    facetas = {nome: [{"valor": b["key"], "total": b["doc_count"],
                       **({"rotulo": b["nome"]["buckets"][0]["key"]} if b.get("nome", {}).get("buckets") else {})}
                      for b in agg["buckets"]]
               for nome, agg in resp["aggregations"].items() if "buckets" in agg}
    return {"total": total, "pagina": pagina, "por_pagina": por_pagina,
            "paginas": max(1, -(-min(total, 10000) // por_pagina)), "tempo_es_ms": resp["took"],
            "itens": itens, "facetas": facetas}


def obter(id_: str, professor: bool) -> dict | None:
    resp = _tempo("get", es().search, index=CFG.es_alias, body={
        "query": {"ids": {"values": [id_]}}, "size": 1,
        "_source": {"excludes": excluir_restritos(professor) + ["kafka"]}})
    hits = resp["hits"]["hits"]
    return hits[0]["_source"] if hits else None


def obter_varios(ids: list[str], professor: bool) -> list[dict]:
    if not ids:
        return []
    resp = _tempo("mget", es().search, index=CFG.es_alias, body={
        "query": {"ids": {"values": ids}}, "size": len(ids),
        "_source": {"excludes": excluir_restritos(professor) + ["kafka"]}})
    por_id = {h["_id"]: h["_source"] for h in resp["hits"]["hits"]}
    return [por_id[i] for i in ids if i in por_id]


def equivalentes(doc: dict, professor: bool, limite: int = 20) -> dict:
    """RF14 — mesma questão em outros cursos (mesmo grupo) + questões semelhantes de outros cursos (MLT)."""
    excl = excluir_restritos(professor) + ["kafka"]
    mesmos = _tempo("equivalentes", es().search, index=CFG.es_alias, body={
        "query": {"bool": {"filter": [{"term": {"grupo_equivalencia": doc["grupo_equivalencia"]}}],
                           "must_not": [{"ids": {"values": [doc["id"]]}}]}},
        "size": 100, "_source": {"includes": ["id", "curso", "curso_slug", "ano", "rotulo", "area"]},
        "sort": [{"curso_slug": "asc"}]})
    semelhantes = _tempo("mlt", es().search, index=CFG.es_alias, body={
        "query": {"bool": {
            "must": [{"more_like_this": {"fields": ["texto_completo"], "like": [{"_index": CFG.es_alias, "_id": doc["id"]}],
                                         "min_term_freq": 1, "min_doc_freq": 2, "max_query_terms": 30,
                                         "minimum_should_match": "30%"}}],
            "must_not": [{"term": {"grupo_equivalencia": doc["grupo_equivalencia"]}},
                         {"term": {"curso_slug": doc["curso_slug"]}}]}},
        "size": limite, "collapse": {"field": "grupo_equivalencia"},
        "_source": {"includes": ["id", "curso", "curso_slug", "ano", "rotulo", "area", "enunciado"], "excludes": excl}})
    return {"mesma_questao_em_outros_cursos": [h["_source"] for h in mesmos["hits"]["hits"]],
            "semelhantes_de_outros_cursos": [dict(h["_source"], _score=h["_score"]) for h in semelhantes["hits"]["hits"]]}


def analitico(f: dict, q: str | None) -> dict:
    """RF15 — histograma de competências por ano e distribuição por curso (respeitando filtros e busca)."""
    corpo = {
        "size": 0, "query": consulta(q, f),
        "aggs": {
            "competencias_por_ano": {"terms": {"field": "competencias_ids", "size": 20, "order": {"_key": "asc"}},
                                     "aggs": {"anos": {"histogram": {"field": "ano", "interval": 1,
                                                                      "min_doc_count": 0}}}},
            "objetos_por_ano": {"terms": {"field": "objetos_ids", "size": 30, "order": {"_key": "asc"}},
                                "aggs": {"anos": {"histogram": {"field": "ano", "interval": 1, "min_doc_count": 0}}}},
            "por_curso": {"terms": {"field": "curso.kw", "size": 200},
                          "aggs": {"componente": {"terms": {"field": "componente"}},
                                   "tipo": {"terms": {"field": "tipo_questao"}},
                                   "anos": {"terms": {"field": "ano"}},
                                   "anuladas": {"filter": {"term": {"anulada": True}}}}},
            "por_area": {"terms": {"field": "area", "size": 50}},
            "anos": {"terms": {"field": "ano", "size": 50, "order": {"_key": "asc"}}},
        },
    }
    r = _tempo("analitico", es().search, index=CFG.es_alias, body=corpo)["aggregations"]
    serie = lambda agg: [{"chave": b["key"], "total": b["doc_count"],  # noqa: E731
                          "por_ano": {int(a["key"]): a["doc_count"] for a in b["anos"]["buckets"]}}
                         for b in agg["buckets"]]
    return {
        "anos": [int(b["key"]) for b in r["anos"]["buckets"]],
        "competencias_por_ano": serie(r["competencias_por_ano"]),
        "objetos_por_ano": serie(r["objetos_por_ano"]),
        "por_curso": [{"curso": b["key"], "total": b["doc_count"],
                       "componente": {x["key"]: x["doc_count"] for x in b["componente"]["buckets"]},
                       "tipo": {x["key"]: x["doc_count"] for x in b["tipo"]["buckets"]},
                       "anos": sorted(int(x["key"]) for x in b["anos"]["buckets"]),
                       "anuladas": b["anuladas"]["doc_count"]} for b in r["por_curso"]["buckets"]],
        "por_area": [{"area": b["key"], "total": b["doc_count"]} for b in r["por_area"]["buckets"]],
    }
