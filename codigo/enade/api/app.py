"""API REST da plataforma (FastAPI). Documentação OpenAPI em /docs e /openapi.json (RF17)."""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Annotated, Literal

import redis
from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response, status
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel, Field

from ..config import CFG
from ..logs import evento, obter_logger
from . import busca, cache, exportar, monitor, validacao
from .estado import M_REQ, es, redis_cli
from .seguranca import (COOKIE, Usuario, autenticar_ldap, criar_sessao, encerrar_sessao, exige_professor,
                        registrar_falha, usuario_atual, verificar_bloqueio)

LOG = obter_logger("api")
WEB = Path(__file__).resolve().parent / "web"
VENDOR = Path("/app/vendor")
MAX_CARRINHO = 200

TAGS = [
    {"name": "autenticação", "description": "Login via LDAP (bind direto) e sessão no Redis"},
    {"name": "busca", "description": "Busca full-text PT-BR, filtros, paginação, highlight e facetas"},
    {"name": "questões", "description": "Detalhe, gabarito (restrito) e equivalências entre cursos"},
    {"name": "carrinho", "description": "Lista de questões da sessão (Redis) e exportação (Professor)"},
    {"name": "analítico", "description": "Agregações (Professor)"},
    {"name": "operação", "description": "Saúde, métricas, cache e ingestão"},
    {"name": "validação", "description": "Validação manual da extração (RNF03, Professor)"},
]

app = FastAPI(
    title="ENADE — Plataforma Distribuída de Busca",
    version="1.0.0",
    description="Busca e indexação do acervo de provas do ENADE (INEP). Perfis: **Estudante** (sem gabarito) e "
                "**Professor** (gabarito, painel analítico, exportação). Autentique-se em `POST /api/auth/login` e use "
                "o token retornado como `Authorization: Bearer <token>`.",
    openapi_tags=TAGS,
)


@app.middleware("http")
async def medir_e_proteger(request: Request, call_next):
    t = time.perf_counter()
    resp: Response = await call_next(request)
    dur = time.perf_counter() - t
    rota = request.scope.get("route").path if request.scope.get("route") else "desconhecida"
    M_REQ.labels(rota, request.method, str(resp.status_code)).observe(dur)
    resp.headers["X-Tempo-Resposta-ms"] = f"{dur * 1000:.1f}"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "no-referrer"
    if not request.url.path.startswith(("/docs", "/redoc", "/openapi")):
        resp.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; font-src 'self' data:; object-src 'none'; frame-ancestors 'none'")
    if rota.startswith("/api/") and resp.status_code < 500 and request.method == "GET":
        resp.headers.setdefault("Cache-Control", "no-store")
    if request.url.path.startswith("/static/"):
        resp.headers.setdefault("Cache-Control", "no-cache")  # revalida (ETag) para não servir JS/CSS antigo após atualização
    if request.url.path.startswith("/api/") and resp.status_code >= 400:
        evento(LOG, "requisição negada/erro", nivel=30, rota=request.url.path, metodo=request.method,
               status=resp.status_code, perfil=getattr(request.state, "perfil", None))
    return resp


# ======================================================================== autenticação
class Login(BaseModel):
    usuario: str = Field(min_length=1, max_length=32, examples=["estudante1"])
    senha: str = Field(min_length=1, max_length=128)


class Sessao(BaseModel):
    token: str
    usuario: str
    nome: str
    perfil: Literal["estudante", "professor"]
    expira_em_segundos: int


@app.post("/api/auth/login", response_model=Sessao, tags=["autenticação"],
          responses={401: {"description": "Credenciais inválidas"}, 403: {"description": "Sem perfil"},
                     429: {"description": "Bloqueio temporário"}, 503: {"description": "LDAP indisponível"}})
def login(dados: Login, response: Response):
    uid = dados.usuario.strip().lower()
    verificar_bloqueio(uid)
    try:
        nome, perfil = autenticar_ldap(uid, dados.senha)
    except HTTPException as exc:
        if exc.status_code == 401:
            registrar_falha(uid)
        evento(LOG, "login negado", nivel=30, usuario=uid, status=exc.status_code)
        raise
    token = criar_sessao(uid, nome, perfil)
    response.set_cookie(COOKIE, token, max_age=CFG.sessao_ttl, httponly=True, samesite="strict", path="/")
    evento(LOG, "login ok", usuario=uid, perfil=perfil)
    return Sessao(token=token, usuario=uid, nome=nome, perfil=perfil, expira_em_segundos=CFG.sessao_ttl)


@app.post("/api/auth/logout", status_code=204, tags=["autenticação"])
def logout(response: Response, u: Usuario = Depends(usuario_atual)):
    encerrar_sessao(u.token)
    response.delete_cookie(COOKIE, path="/")


@app.get("/api/auth/eu", tags=["autenticação"])
def eu(u: Usuario = Depends(usuario_atual)):
    return {"usuario": u.uid, "nome": u.nome, "perfil": u.perfil}


# ======================================================================== busca
def _filtros(area, curso, ano, componente, tipo, competencia, objeto, grau, anulada, com_formula) -> dict:
    return {"area": area, "curso": curso, "ano": ano, "componente": componente, "tipo": tipo,
            "competencia": competencia, "objeto": objeto, "grau": grau, "anulada": anulada,
            "com_formula": com_formula}


Lista = Annotated[list[str] | None, Query()]


@app.get("/api/busca", tags=["busca"], responses={401: {"description": "Não autenticado"}})
def buscar(response: Response,
           q: Annotated[str | None, Query(max_length=300, description="Texto livre (PT-BR, com stemming e sinônimos)")] = None,
           area: Lista = None, curso: Lista = None, ano: Annotated[list[int] | None, Query()] = None,
           componente: Annotated[list[Literal["FG", "CE"]] | None, Query()] = None,
           tipo: Annotated[list[Literal["objetiva", "discursiva"]] | None, Query()] = None,
           competencia: Lista = None, objeto: Lista = None, grau: Lista = None,
           anulada: bool | None = None, com_formula: bool = False,
           pagina: Annotated[int, Query(ge=1, le=500)] = 1,
           por_pagina: Annotated[int, Query(ge=1, le=50)] = 10,
           colapsar: Annotated[bool, Query(description="Agrupa questões idênticas de cursos diferentes")] = False,
           ordenar: Literal["relevancia", "ano"] = "relevancia",
           cache_ok: Annotated[bool, Query(alias="cache", description="false = ignora o cache (medição)")] = True,
           u: Usuario = Depends(usuario_atual)):
    if pagina * por_pagina > 10000:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "paginação além de 10.000 resultados")
    f = _filtros(area, curso, ano, componente, tipo, competencia, objeto, grau, anulada, com_formula)
    q = (q or "").strip() or None
    params = {"q": q, "f": f, "p": pagina, "n": por_pagina, "c": colapsar, "o": ordenar}
    valor, origem = cache.obter_ou_calcular(
        "busca", u.perfil, params,
        lambda: busca.buscar(q, f, pagina, por_pagina, u.professor, colapsar, ordenar), usar_cache=cache_ok)
    response.headers["X-Cache"] = origem
    return valor


# ======================================================================== questões
@app.get("/api/questoes/{qid}", tags=["questões"], responses={404: {"description": "Não encontrada"}})
def questao(qid: str, u: Usuario = Depends(usuario_atual)):
    doc = busca.obter(qid, u.professor)
    if not doc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "questão não encontrada")
    return doc


@app.get("/api/questoes/{qid}/gabarito", tags=["questões"],
         responses={403: {"description": "Estudante não pode ver gabarito (RF25)"}, 404: {"description": "Não encontrada"}})
def gabarito(qid: str, u: Usuario = Depends(exige_professor)):
    doc = busca.obter(qid, professor=True)
    if not doc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "questão não encontrada")
    return {"id": qid, "gabarito": doc.get("gabarito"), "gabarito_status": doc.get("gabarito_status"),
            "anulada": doc.get("anulada"), "padrao_resposta": doc.get("padrao_resposta"),
            "fonte": doc.get("origem", {}).get("gabarito_pdf")}


@app.get("/api/questoes/{qid}/equivalentes", tags=["questões"])
def equivalentes(qid: str, u: Usuario = Depends(usuario_atual)):
    doc = busca.obter(qid, u.professor)
    if not doc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "questão não encontrada")
    return busca.equivalentes(doc, u.professor)


@app.get("/api/figuras/{ano}/{arquivo}", tags=["questões"], response_class=FileResponse)
def figura(ano: int, arquivo: str, u: Usuario = Depends(usuario_atual)):
    import re
    if not re.fullmatch(r"[0-9a-f]{24}-\d{1,2}\.png", arquivo):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "nome de arquivo inválido")
    caminho = exportar.DIR_FIGURAS / str(ano) / arquivo
    if not caminho.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "figura não encontrada")
    return FileResponse(caminho, media_type="image/png", headers={"Cache-Control": "private, max-age=3600"})


# ======================================================================== carrinho
def _ck(u: Usuario) -> str:
    return f"carrinho:{u.token}"


@app.get("/api/carrinho", tags=["carrinho"])
def carrinho(u: Usuario = Depends(usuario_atual)):
    ids = redis_cli().zrange(_ck(u), 0, -1)
    itens = busca.obter_varios(ids, u.professor)
    return {"total": len(ids), "ttl_segundos": redis_cli().ttl(_ck(u)),
            "itens": [{k: d.get(k) for k in ("id", "rotulo", "curso", "ano", "componente", "tipo_questao", "anulada")}
                      for d in itens]}


@app.post("/api/carrinho/{qid}", status_code=201, tags=["carrinho"],
          responses={404: {"description": "Questão inexistente"}, 409: {"description": "Lista cheia"}})
def adicionar(qid: str, u: Usuario = Depends(usuario_atual)):
    if not busca.obter(qid, u.professor):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "questão não encontrada")
    r = redis_cli()
    if r.zcard(_ck(u)) >= MAX_CARRINHO and r.zscore(_ck(u), qid) is None:
        raise HTTPException(status.HTTP_409_CONFLICT, f"limite de {MAX_CARRINHO} questões")
    r.zadd(_ck(u), {qid: time.time()}, nx=True)
    r.expire(_ck(u), CFG.sessao_ttl)
    return {"total": r.zcard(_ck(u))}


@app.delete("/api/carrinho/{qid}", tags=["carrinho"])
def remover(qid: str, u: Usuario = Depends(usuario_atual)):
    if not redis_cli().zrem(_ck(u), qid):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "questão não está na lista")
    return {"total": redis_cli().zcard(_ck(u))}


@app.delete("/api/carrinho", status_code=204, tags=["carrinho"])
def limpar(u: Usuario = Depends(usuario_atual)):
    redis_cli().delete(_ck(u))


@app.get("/api/carrinho/exportar", tags=["carrinho"],
         responses={403: {"description": "Exportação restrita ao Professor"}, 400: {"description": "Lista vazia"}})
def exportar_lista(formato: Literal["json", "pdf"] = "json", u: Usuario = Depends(exige_professor)):
    ids = redis_cli().zrange(_ck(u), 0, -1)
    if not ids:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "a lista está vazia")
    docs = busca.obter_varios(ids, professor=True)
    nome = f"simulado-enade-{time.strftime('%Y%m%d-%H%M%S')}"
    evento(LOG, "exportação", usuario=u.uid, formato=formato, questoes=len(docs))
    if formato == "json":
        corpo = json.dumps({"gerado_por": u.uid, "gerado_em": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                            "total": len(docs), "questoes": docs}, ensure_ascii=False, indent=1)
        return Response(corpo, media_type="application/json",
                        headers={"Content-Disposition": f'attachment; filename="{nome}.json"'})
    pdf = exportar.gerar_pdf(docs, u.nome, incluir_gabarito=True)
    return Response(pdf, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{nome}.pdf"'})


# ======================================================================== analítico
@app.get("/api/analitico", tags=["analítico"], responses={403: {"description": "Restrito ao Professor"}})
def painel(response: Response, q: str | None = None, area: Lista = None, curso: Lista = None,
           ano: Annotated[list[int] | None, Query()] = None,
           componente: Annotated[list[Literal["FG", "CE"]] | None, Query()] = None,
           tipo: Annotated[list[Literal["objetiva", "discursiva"]] | None, Query()] = None,
           competencia: Lista = None, objeto: Lista = None, grau: Lista = None,
           cache_ok: Annotated[bool, Query(alias="cache")] = True, u: Usuario = Depends(exige_professor)):
    f = _filtros(area, curso, ano, componente, tipo, competencia, objeto, grau, None, False)
    valor, origem = cache.obter_ou_calcular("analitico", u.perfil, {"q": q, "f": f},
                                            lambda: busca.analitico(f, q), usar_cache=cache_ok)
    response.headers["X-Cache"] = origem
    return valor


@app.get("/api/taxonomia", tags=["analítico"])
def taxonomia(u: Usuario = Depends(usuario_atual)):
    from ..extracao.metadados import taxonomia as tax
    t = tax()
    return {"fonte": t["fonte"], "competencias": [{"id": c["id"], "nome": c["nome"]} for c in t["competencias"]],
            "temas": [{"id": c["id"], "nome": c["nome"]} for c in t["temas"]]}


# ======================================================================== operação
@app.get("/health/live", tags=["operação"])
def vivo():
    return {"status": "ok"}


@app.get("/health/ready", tags=["operação"], responses={503: {"description": "Dependência indisponível"}})
def pronto():
    estado: dict[str, dict] = {}
    try:
        h = es().cluster.health()
        estado["elasticsearch"] = {"ok": h["status"] in ("green", "yellow"), "status": h["status"],
                                   "autenticacao": "kerberos/spnego"}
    except Exception as exc:  # health check: qualquer falha vira "indisponível"
        estado["elasticsearch"] = {"ok": False, "erro": type(exc).__name__}
    try:
        estado["redis"] = {"ok": bool(redis_cli().ping())}
    except redis.RedisError as exc:
        estado["redis"] = {"ok": False, "erro": type(exc).__name__}
    estado["ldap"] = monitor.ldap_ok()
    estado["kafka"] = monitor.kafka_ok()
    ok = all(v.get("ok") for v in estado.values())
    return JSONResponse({"status": "ok" if ok else "degradado", "dependencias": estado}, status_code=200 if ok else 503)


@app.get("/metrics", tags=["operação"], include_in_schema=True)
def metricas():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/api/admin/cache", tags=["operação"])
def cache_stats(u: Usuario = Depends(exige_professor)):
    return cache.estatisticas()


@app.post("/api/admin/cache/invalidar", tags=["operação"])
def cache_invalidar(u: Usuario = Depends(exige_professor)):
    return {"versao_indice": cache.invalidar()}


@app.post("/api/admin/cache/zerar-contadores", status_code=204, tags=["operação"])
def cache_zerar(u: Usuario = Depends(exige_professor)):
    cache.zerar_contadores()


@app.get("/api/admin/ingestao", tags=["operação"])
def ingestao(u: Usuario = Depends(exige_professor)):
    return monitor.ingestao()


# ======================================================================== validação manual (RNF03)
app.include_router(validacao.router)

# ======================================================================== interface web
if VENDOR.is_dir():
    app.mount("/vendor", StaticFiles(directory=VENDOR), name="vendor")
app.mount("/static", StaticFiles(directory=WEB), name="static")


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(WEB / "index.html", headers={"Cache-Control": "no-cache"})
