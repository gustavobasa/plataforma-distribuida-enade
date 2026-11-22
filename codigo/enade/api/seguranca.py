"""RF23/RF24/RF25 — Login por bind direto no LDAP, sessão no Redis e autorização por perfil no backend.

* O usuário informa uid e senha; a API faz bind no OpenLDAP com o DN `uid=<uid>,ou=usuarios,dc=enade,dc=local`
  (a senha nunca é armazenada pela API). O perfil vem da participação nos grupos `cn=professores` ou
  `cn=estudantes` (consultada com a conta somente leitura).
* A sessão é um token aleatório (256 bits) guardado no Redis com TTL; enviado em cookie HttpOnly
  (navegador) ou cabeçalho `Authorization: Bearer` (clientes de API/testes).
* Bloqueio após 5 falhas de login em 5 minutos (HTTP 429), por usuário.
"""
from __future__ import annotations

import json
import re
import secrets
import time
from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request, status
from ldap3 import NONE, Connection, Server
from ldap3.core.exceptions import LDAPBindError, LDAPException
from ldap3.utils.conv import escape_filter_chars

from ..config import CFG, ldap_readonly_password
from .estado import redis_cli

COOKIE = "enade_sessao"
RE_UID = re.compile(r"^[a-z0-9._-]{1,32}$")
GRUPOS = {"professores": "professor", "estudantes": "estudante"}
MAX_FALHAS, JANELA_FALHAS = 5, 300


@dataclass
class Usuario:
    uid: str
    nome: str
    perfil: str  # estudante | professor
    token: str

    @property
    def professor(self) -> bool:
        return self.perfil == "professor"


def _servidor() -> Server:
    return Server(CFG.ldap_url, get_info=NONE, connect_timeout=5)


def autenticar_ldap(uid: str, senha: str) -> tuple[str, str]:
    """Retorna (nome, perfil) ou lança HTTPException 401/403/503."""
    if not RE_UID.match(uid or "") or not senha:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "usuário ou senha inválidos")
    dn = f"uid={uid},ou=usuarios,{CFG.ldap_base}"
    try:
        conn = Connection(_servidor(), user=dn, password=senha, auto_bind=True, receive_timeout=5)
    except LDAPBindError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "usuário ou senha inválidos")
    except LDAPException as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, f"LDAP indisponível: {type(exc).__name__}")
    try:
        conn.search(dn, "(objectClass=inetOrgPerson)", attributes=["cn"])
        nome = str(conn.entries[0].cn) if conn.entries else uid
    finally:
        conn.unbind()
    ro = Connection(_servidor(), user=f"cn=readonly,{CFG.ldap_base}", password=ldap_readonly_password(),
                    auto_bind=True, receive_timeout=5)
    try:
        ro.search(f"ou=grupos,{CFG.ldap_base}", f"(&(objectClass=groupOfNames)(member={escape_filter_chars(dn)}))",
                  attributes=["cn"])
        grupos = {str(e.cn) for e in ro.entries}
    finally:
        ro.unbind()
    for grupo in ("professores", "estudantes"):  # professor prevalece se estiver nos dois
        if grupo in grupos:
            return nome, GRUPOS[grupo]
    raise HTTPException(status.HTTP_403_FORBIDDEN, "usuário sem perfil autorizado na plataforma")


def registrar_falha(uid: str) -> None:
    chave = f"login:falhas:{uid}"
    n = redis_cli().incr(chave)
    if n == 1:
        redis_cli().expire(chave, JANELA_FALHAS)


def verificar_bloqueio(uid: str) -> None:
    n = int(redis_cli().get(f"login:falhas:{uid}") or 0)
    if n >= MAX_FALHAS:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "muitas tentativas; aguarde alguns minutos")


def criar_sessao(uid: str, nome: str, perfil: str) -> str:
    token = secrets.token_urlsafe(32)
    dados = {"uid": uid, "nome": nome, "perfil": perfil, "criada_em": int(time.time())}
    redis_cli().setex(f"sessao:{token}", CFG.sessao_ttl, json.dumps(dados))
    redis_cli().delete(f"login:falhas:{uid}")
    return token


def encerrar_sessao(token: str) -> None:
    redis_cli().delete(f"sessao:{token}", f"carrinho:{token}")


def _token(request: Request) -> str | None:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return request.cookies.get(COOKIE)


def usuario_atual(request: Request) -> Usuario:
    token = _token(request)
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "autenticação necessária",
                            headers={"WWW-Authenticate": "Bearer"})
    bruto = redis_cli().get(f"sessao:{token}")
    if not bruto:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "sessão expirada ou inválida",
                            headers={"WWW-Authenticate": "Bearer"})
    d = json.loads(bruto)
    # sessão deslizante: renova TTL da sessão e do carrinho a cada uso
    redis_cli().expire(f"sessao:{token}", CFG.sessao_ttl)
    redis_cli().expire(f"carrinho:{token}", CFG.sessao_ttl)
    request.state.perfil = d["perfil"]
    return Usuario(d["uid"], d["nome"], d["perfil"], token)


def exige_professor(u: Usuario = Depends(usuario_atual)) -> Usuario:
    """RF24/RF25: rotas restritas. Estudante autenticado recebe HTTP 403 (não 404, não 401)."""
    if not u.professor:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "acesso restrito ao perfil Professor")
    return u
