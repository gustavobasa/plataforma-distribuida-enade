"""RNF03 — Validação MANUAL da extração (feita por uma pessoa, perfil Professor).

A tela /validacao mostra, para cada questão da amostra sorteada, a página original do PDF (renderizada a
partir do arquivo oficial) ao lado dos campos extraídos. O avaliador marca cada critério como correto,
incorreto ou "não se aplica". As respostas ficam no Redis (persistência AOF) e podem ser exportadas em CSV.
"""
from __future__ import annotations

import csv
import io
import json
import re
import time
from functools import lru_cache
from pathlib import Path
from typing import Literal

import pymupdf
from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel

from ..config import CFG
from . import busca
from .estado import redis_cli
from .seguranca import Usuario, exige_professor

router = APIRouter(tags=["validação"])
BASE = Path(CFG.dados_dir)
CRITERIOS = {
    "segmentacao": "Limites da questão corretos (nada faltando, nada de outra questão)",
    "texto": "Texto-base/enunciado fiéis ao PDF (sem trechos perdidos ou palavras corrompidas)",
    "alternativas": "Alternativas completas e separadas corretamente",
    "gabarito": "Gabarito/anulação igual ao gabarito oficial",
    "metadados": "Componente (FG/CE), tipo, número e páginas de origem corretos",
    "midia": "Fórmulas, tabelas e figuras preservadas de forma utilizável",
}
CHAVE = "validacao:respostas"
Valor = Literal["ok", "erro", "na"]


class Avaliacao(BaseModel):
    criterios: dict[str, Valor]
    observacao: str = ""


@lru_cache(maxsize=1)
def _amostra() -> dict:
    arq = BASE / "validacao" / "amostra.json"
    if not arq.is_file():
        raise HTTPException(404, "amostra não gerada; execute python -m enade.ferramentas.amostra")
    return json.loads(arq.read_text(encoding="utf-8"))


@router.get("/validacao", include_in_schema=False)
def tela():
    return FileResponse(Path(__file__).parent / "web" / "validacao.html", headers={"Cache-Control": "no-cache"})


@router.get("/api/validacao/amostra")
def amostra(u: Usuario = Depends(exige_professor)):
    a = _amostra()
    ids = [i["id"] for i in a["itens"]]
    docs = {d["id"]: d for d in busca.obter_varios(ids, professor=True)}
    respostas = redis_cli().hgetall(CHAVE)
    return {"criterios": CRITERIOS, "semente": a["semente"], "populacao": a["populacao"],
            "itens": [{"doc": docs.get(i), "avaliacao": json.loads(respostas[i]) if i in respostas else None}
                      for i in ids]}


@router.get("/api/validacao/pagina/{ano}/{pdf}/{pagina}.png")
def pagina(ano: int, pdf: str, pagina: int, u: Usuario = Depends(exige_professor)):
    if not re.fullmatch(r"20\d\d_[A-Za-z0-9_]+\.pdf", pdf) or not (1 <= pagina <= 200):
        raise HTTPException(400, "parâmetros inválidos")
    caminho = BASE / "pdfs" / str(ano) / pdf
    if not caminho.is_file():
        raise HTTPException(404, "PDF não encontrado no acervo")
    with pymupdf.open(str(caminho)) as doc:
        if pagina > len(doc):
            raise HTTPException(404, "página inexistente")
        png = doc[pagina - 1].get_pixmap(dpi=100).tobytes("png")
    return Response(png, media_type="image/png", headers={"Cache-Control": "private, max-age=3600"})


@router.put("/api/validacao/{qid}")
def avaliar(qid: str, a: Avaliacao, u: Usuario = Depends(exige_professor)):
    if qid not in {i["id"] for i in _amostra()["itens"]}:
        raise HTTPException(404, "questão fora da amostra")
    if set(a.criterios) - set(CRITERIOS):
        raise HTTPException(422, "critério desconhecido")
    registro = {"criterios": a.criterios, "observacao": a.observacao[:1000], "avaliador": u.uid,
                "em": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    redis_cli().hset(CHAVE, qid, json.dumps(registro, ensure_ascii=False))
    return {"ok": True}


@router.get("/api/validacao/resultado")
def resultado(formato: Literal["json", "csv"] = "json", u: Usuario = Depends(exige_professor)):
    ids = [i["id"] for i in _amostra()["itens"]]
    respostas = {k: json.loads(v) for k, v in redis_cli().hgetall(CHAVE).items() if k in ids}
    por_criterio = {}
    for c in CRITERIOS:
        vals = [r["criterios"].get(c) for r in respostas.values() if r["criterios"].get(c) in ("ok", "erro")]
        por_criterio[c] = {"avaliadas": len(vals), "corretas": vals.count("ok"),
                           "taxa_acerto": round(vals.count("ok") / len(vals), 4) if vals else None}
    completas = [r for r in respostas.values() if all(r["criterios"].get(c) in ("ok", "erro", "na") for c in CRITERIOS)]
    todas_ok = [r for r in completas if all(r["criterios"][c] != "erro" for c in CRITERIOS)]
    res = {"amostra": len(ids), "avaliadas": len(respostas), "completas": len(completas),
           "questoes_sem_nenhum_erro": len(todas_ok),
           "taxa_acerto_por_questao": round(len(todas_ok) / len(completas), 4) if completas else None,
           "por_criterio": por_criterio}
    if formato == "json":
        return res
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["id"] + list(CRITERIOS) + ["observacao", "avaliador", "em"])
    for qid in ids:
        r = respostas.get(qid)
        if r:
            w.writerow([qid] + [r["criterios"].get(c, "") for c in CRITERIOS] + [r["observacao"], r["avaliador"], r["em"]])
    return Response(buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": 'attachment; filename="validacao-extracao.csv"'})
