"""RF02/RF03 — Leitura do gabarito definitivo (PDF *_GB_*) e do padrão de resposta das discursivas.

Formato observado (2021–2023): pares "QUESTÃO N" -> letra (A–E), "ANULADA" ou "***" (discursiva).
Discursivas aparecem como "QUESTÃO DISCURSIVA N" -> "***".
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import pymupdf

from .texto import normalizar

RE_PAR = re.compile(
    r"QUEST[AÃ]O\s+(DISCURSIVA\s+)?0?(\d{1,2})\s*[\n ]\s*"
    r"(ANULAD[AO]|[A-E](?:\s*(?:,|e|ou|/)\s*[A-E])*|\*{1,5}|-)",
    re.I,
)


@dataclass
class ItemGabarito:
    tipo: str  # objetiva | discursiva
    numero: int
    valor: str | None  # letra(s) ou None
    anulada: bool
    bruto: str


def _texto(caminho: str | Path) -> str:
    doc = pymupdf.open(str(caminho))
    return "\n".join(normalizar(l) for p in doc for l in p.get_text("text").splitlines() if normalizar(l))


def ler_gabarito(caminho: str | Path) -> dict[tuple[str, int], ItemGabarito]:
    texto = _texto(caminho)
    itens: dict[tuple[str, int], ItemGabarito] = {}
    for m in RE_PAR.finditer(texto):
        tipo = "discursiva" if m.group(1) else "objetiva"
        num = int(m.group(2))
        bruto = m.group(3).strip()
        anulada = bruto.upper().startswith("ANULAD")
        valor = None
        if re.fullmatch(r"[A-E](?:\s*(?:,|e|ou|/)\s*[A-E])*", bruto, re.I):
            valor = re.sub(r"\s+", " ", bruto.upper())
        itens[(tipo, num)] = ItemGabarito(tipo, num, valor, anulada, bruto)
    return itens


RE_PR_CAB = re.compile(r"(?:QUEST[AÃ]O\s+DISCURSIVA\s+0?(\d{1,2}))", re.I)


def ler_padrao_resposta(caminho: str | Path) -> dict[int, str]:
    """Divide o PDF de padrão de resposta por cabeçalho 'QUESTÃO DISCURSIVA N'. Conteúdo restrito (Professor)."""
    texto = _texto(caminho)
    partes = RE_PR_CAB.split(texto)
    resultado: dict[int, str] = {}
    # split -> [prefixo, num1, corpo1, num2, corpo2, ...]
    for i in range(1, len(partes) - 1, 2):
        num = int(partes[i])
        corpo = partes[i + 1].strip()
        m = re.search(r"PADR[AÃ]O\s+DE\s+RESPOSTA", corpo, re.I)
        if m:
            corpo = corpo[m.end():].strip(" :\n")
        if corpo and len(corpo) > len(resultado.get(num, "")):
            resultado[num] = corpo[:20000]
    return resultado
