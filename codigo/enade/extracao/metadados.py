"""RF05 — Metadados: área, curso, grau, componente (FG/CE), competências e objetos de conhecimento.

* Área: mapeamento próprio do slug do curso para a grande área do conhecimento (tabela CAPES/CNPq,
  simplificada). Não é um dado do PDF; é documentado como classificação do projeto.
* Competências (C1–C8) e temas/objetos de conhecimento (T01–T13): taxonomia oficial da Portaria Inep
  289/2023; a atribuição por questão é inferida por classificador léxico (pistas no YAML), pois os PDFs não
  informam a competência de cada questão.
"""
from __future__ import annotations

import re
import unicodedata
from functools import lru_cache
from pathlib import Path

import yaml

RECURSOS = Path(__file__).resolve().parent.parent / "recursos"

# (regex sobre o slug, área). A primeira regra que casar vence.
REGRAS_AREA: list[tuple[str, str]] = [
    (r"engenharia|^arquitetura", "Engenharias e Arquitetura"),
    (r"computa|sistema_?s?_informacao|analise_desenvolvimento_sistemas|redes_computadores|tecnologia_informacao"
     r"|jogos_digitais|ciencia_dados|seguranca_informacao|banco_de_dados", "Computação e Tecnologia da Informação"),
    (r"medicina_veterinaria|agronom|zootecnia|agronegocio|florestal|aquicultura", "Ciências Agrárias"),
    (r"medicina|enfermagem|odontologia|farmacia|fisioterapia|fonoaudiologia|nutricao|biomedicina|educacao_fisica"
     r"|radiologia|gestao_hospitalar|estetica|saude", "Ciências da Saúde"),
    (r"matematica|fisica|quimica|estatistica|geologia", "Ciências Exatas e da Terra"),
    (r"biologic", "Ciências Biológicas"),
    (r"letras|musica|artes|teatro|danca|design(?!_interiores)", "Linguística, Letras e Artes"),
    (r"pedagogia|historia|geografia|filosofia|ciencias_sociais|psicologia|teologia", "Ciências Humanas"),
    (r"administra|direito|contab|economi|com_social|jornalismo|publicidade|rel_internacionais|servico_social"
     r"|secretariado|turismo|comercio_exterior|gestao|logistica|marketing|processos_gerenciais|gastronomia"
     r"|design_interiores|design_moda|design_grafico|recursos_humanos|seguranca_trabalho", "Ciências Sociais Aplicadas"),
]


def area_do_curso(slug: str) -> str:
    for padrao, area in REGRAS_AREA:
        if re.search(padrao, slug):
            return area
    return "Outras"


def grau_do_curso(slug: str) -> str:
    if slug.startswith("licenciatura") or "_licenciatura" in slug:
        return "Licenciatura"
    if slug.startswith("tecnologia"):
        return "Tecnologia"
    return "Bacharelado"


def sem_acento(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", texto.lower()) if not unicodedata.combining(c))


@lru_cache(maxsize=1)
def taxonomia() -> dict:
    return yaml.safe_load((RECURSOS / "formacao_geral_2023.yaml").read_text(encoding="utf-8"))


def _pontuar(texto: str, itens: list[dict]) -> list[tuple[str, str, int]]:
    out = []
    for it in itens:
        acertos = sum(1 for p in it["pistas"] if re.search(r"\b" + re.escape(p), texto))
        if acertos:
            out.append((it["id"], it["nome"], acertos))
    return sorted(out, key=lambda x: -x[2])


def classificar(texto_base: str, enunciado: str, alternativas: list[dict], tem_figura: bool,
                tem_tabela: bool, tipo: str) -> dict:
    """Retorna competências e temas inferidos. Regras:
    temas -> até 3 temas com >= 2 pistas (ou o melhor com 1 pista se nenhum tiver 2);
    competências -> até 3, combinando pistas do enunciado com sinais estruturais (figura/tabela -> C5/C3;
    asserção-razão -> C7; discursiva -> C6)."""
    tax = taxonomia()
    completo = sem_acento(" ".join([texto_base, enunciado] + [a.get("texto", "") for a in alternativas]))
    enun = sem_acento(enunciado)

    temas = _pontuar(completo, tax["temas"])
    fortes = [t for t in temas if t[2] >= 2][:3] or temas[:1]

    comp = {c[0]: c for c in _pontuar(enun + " " + sem_acento(texto_base[-400:]), tax["competencias"])}
    bonus = []
    if tem_figura or tem_tabela:
        bonus.append("C5")
    if tem_tabela or re.search(r"\b(grafico|tabela|dados)\b", enun):
        bonus.append("C3")
    if re.search(r"assercoes|porque", enun):
        bonus.append("C7")
    if tipo == "discursiva":
        bonus.append("C6")
    nomes = {c["id"]: c["nome"] for c in tax["competencias"]}
    for b in bonus:
        cid, nome, n = comp.get(b, (b, nomes[b], 0))
        comp[b] = (cid, nome, n + 2)
    escolhidas = sorted(comp.values(), key=lambda x: -x[2])[:3]
    return {
        "competencias": [f"{c[0]} - {c[1]}" for c in escolhidas],
        "competencias_ids": [c[0] for c in escolhidas],
        "objetos_conhecimento": [f"{t[0]} - {t[1]}" for t in fortes],
        "objetos_ids": [t[0] for t in fortes],
        "metodo": "lexico-v1 (pistas próprias sobre taxonomia da Portaria Inep 289/2023)",
    }
