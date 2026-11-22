"""Esquema do documento "questão" (versão 1), identificador estável e validação.

O mesmo validador é usado pelo produtor (antes de publicar) e pelo consumidor (antes de indexar):
mensagens que não passam vão para a DLQ (RF11).
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
from typing import Literal

from pydantic import BaseModel, Field, ValidationError, field_validator

VERSAO_ESQUEMA = 1
CAMPOS_RESTRITOS = ("gabarito", "padrao_resposta")  # visíveis apenas ao perfil Professor (RF24)


def id_questao(ano: int, curso_slug: str, tipo: str, numero: int) -> str:
    """RF10: id determinístico -> reprocessar o mesmo PDF sobrescreve o mesmo documento."""
    chave = f"{ano}|{curso_slug}|{tipo}|{numero}"
    return hashlib.sha256(chave.encode()).hexdigest()[:24]


def grupo_equivalencia(enunciado: str, alternativas: list[dict]) -> str:
    """RF14: questões com o mesmo conteúdo (ex.: Formação Geral repetida em vários cursos) compartilham o grupo."""
    texto = enunciado + "|" + "|".join(a.get("texto", "") for a in alternativas)
    texto = "".join(c for c in unicodedata.normalize("NFKD", texto.lower()) if not unicodedata.combining(c))
    texto = re.sub(r"[^a-z0-9]", "", texto)
    return hashlib.sha1(texto[:1500].encode()).hexdigest()[:16]


class Alternativa(BaseModel):
    letra: Literal["A", "B", "C", "D", "E"]
    texto: str
    texto_md: str = ""


class Figura(BaseModel):
    pagina: int
    bbox: list[float]
    tipo: str
    arquivo: str | None = None


class Midia(BaseModel):
    tem_formula: bool = False
    formulas_latex: list[str] = []
    tabelas_md: list[str] = []
    figuras: list[Figura] = []
    mermaid: list[str] = []
    pendencias: list[str] = []


class Origem(BaseModel):
    pdf: str
    url: str | None = None
    paginas: list[int] = Field(min_length=1)
    sha256: str | None = None
    gabarito_pdf: str | None = None
    gabarito_url: str | None = None
    padrao_resposta_pdf: str | None = None


class Extracao(BaseModel):
    versao: str
    confianca: Literal["alta", "media", "baixa"]
    alertas: list[str] = []
    extraido_em: str


class Questao(BaseModel):
    id: str = Field(min_length=8)
    schema_versao: int = VERSAO_ESQUEMA
    ano: int = Field(ge=2004, le=2100)
    area: str
    curso: str
    curso_slug: str
    grau: str
    componente: Literal["FG", "CE"]
    tipo_questao: Literal["objetiva", "discursiva"]
    numero: int = Field(ge=1, le=60)
    rotulo: str
    texto_base: str = ""
    enunciado: str = Field(min_length=1)
    alternativas: list[Alternativa] = []
    texto_base_md: str = ""
    enunciado_md: str = ""
    gabarito: str | None = None
    gabarito_status: Literal["definitivo", "anulada", "discursiva", "indisponivel"]
    anulada: bool = False
    padrao_resposta: str | None = None
    competencias: list[str] = []
    competencias_ids: list[str] = []
    objetos_conhecimento: list[str] = []
    objetos_ids: list[str] = []
    classificacao_metodo: str = ""
    midia: Midia = Midia()
    origem: Origem
    grupo_equivalencia: str
    extracao: Extracao

    @field_validator("alternativas")
    @classmethod
    def _alternativas(cls, v, info):
        letras = [a.letra for a in v]
        if v and letras != sorted(set(letras)):
            raise ValueError("alternativas fora de ordem ou repetidas")
        return v


def validar(doc: dict) -> tuple[dict | None, str | None]:
    """Retorna (documento normalizado, None) ou (None, motivo do erro)."""
    try:
        q = Questao.model_validate(doc)
    except ValidationError as exc:
        return None, exc.json(include_url=False)[:2000]
    if q.tipo_questao == "objetiva" and q.alternativas and len(q.alternativas) not in (4, 5):
        return None, "questão objetiva deve ter 4 (A–D) ou 5 (A–E) alternativas"
    if q.id != id_questao(q.ano, q.curso_slug, q.tipo_questao, q.numero):
        return None, "id inconsistente com (ano, curso, tipo, número)"
    return q.model_dump(), None
