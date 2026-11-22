"""Reconstrução de linhas de texto a partir do PDF (PyMuPDF rawdict), com correções específicas dos PDFs do INEP.

Problemas observados nos PDFs oficiais e tratados aqui:
  * ligaduras "ti"/"fi" (fonte Calibri) extraídas com um espaço espúrio ("Insti tuto"): o espaço tem caixa
    sobreposta ao caractere anterior -> descartado;
  * caractere "Ɵ" usado como ligadura "ti";
  * fonte Symbol com codificação própria ("Î" = ∈, "Û" = ⇔, "¹" = ≠ ...) -> mapeada para Unicode;
  * índices e expoentes (fonte menor, linha de base deslocada) -> preservados como LaTeX `$a_{n}$`.
"""
from __future__ import annotations

import re
import statistics
import unicodedata
from collections import Counter
from dataclasses import dataclass, field

# Codificação Adobe Symbol -> Unicode (somente para spans cuja fonte contém "Symbol")
SYMBOL_MAP = {
    "Î": "∈", "Ï": "∉", "Û": "⇔", "Þ": "⇒", "Ü": "⇐", "Ý": "⇑", "ß": "⇓", "«": "↔", "®": "→", "¬": "←",
    "¹": "≠", "£": "≤", "³": "≥", "´": "×", "¸": "÷", "¥": "∞", "±": "±", "»": "≈", "º": "≡", "µ": "∝",
    "Ù": "∧", "Ú": "∨", "Ø": "¬", "Æ": "∅", "Ç": "∩", "È": "∪", "É": "⊃", "Ê": "⊇", "Ë": "⊄", "Ì": "⊂",
    "Í": "⊆", "Ñ": "∇", "¶": "∂", "å": "∑", "ò": "∫", "Ö": "√", "¢": "′", "²": "″", "°": "°", "×": "⋅",
    "\"": "∀", "$": "∃", "\\": "∴", "^": "⊥", "Å": "⊕", "Ä": "⊗", "Ð": "∠", "×": "⋅",
    "a": "α", "b": "β", "g": "γ", "d": "δ", "e": "ε", "z": "ζ", "h": "η", "q": "θ", "i": "ι", "k": "κ",
    "l": "λ", "m": "μ", "n": "ν", "x": "ξ", "p": "π", "r": "ρ", "s": "σ", "t": "τ", "u": "υ", "f": "φ",
    "c": "χ", "y": "ψ", "w": "ω", "j": "ϕ", "v": "ϖ",
    "G": "Γ", "D": "Δ", "Q": "Θ", "L": "Λ", "X": "Ξ", "P": "Π", "S": "Σ", "U": "Υ", "F": "Φ", "Y": "Ψ",
    "W": "Ω",
}

LATEX_MAP = {
    "∈": r"\in", "∉": r"\notin", "⇔": r"\Leftrightarrow", "⇒": r"\Rightarrow", "⇐": r"\Leftarrow",
    "↔": r"\leftrightarrow", "→": r"\to", "←": r"\leftarrow", "≠": r"\neq", "≤": r"\leq", "≥": r"\geq",
    "×": r"\times", "÷": r"\div", "∞": r"\infty", "±": r"\pm", "≈": r"\approx", "≡": r"\equiv",
    "∝": r"\propto", "∧": r"\land", "∨": r"\lor", "¬": r"\neg", "∅": r"\emptyset", "∩": r"\cap",
    "∪": r"\cup", "⊃": r"\supset", "⊇": r"\supseteq", "⊄": r"\not\subset", "⊂": r"\subset",
    "⊆": r"\subseteq", "∇": r"\nabla", "∂": r"\partial", "∑": r"\sum", "∫": r"\int", "√": r"\sqrt{}",
    "∀": r"\forall", "∃": r"\exists", "∴": r"\therefore", "⊥": r"\perp", "⊕": r"\oplus",
    "⊗": r"\otimes", "∠": r"\angle", "⋅": r"\cdot", "′": "'", "″": "''", "°": r"^{\circ}",
    "α": r"\alpha", "β": r"\beta", "γ": r"\gamma", "δ": r"\delta", "ε": r"\varepsilon", "ζ": r"\zeta",
    "η": r"\eta", "θ": r"\theta", "ι": r"\iota", "κ": r"\kappa", "λ": r"\lambda", "μ": r"\mu",
    "ν": r"\nu", "ξ": r"\xi", "π": r"\pi", "ρ": r"\rho", "σ": r"\sigma", "τ": r"\tau", "υ": r"\upsilon",
    "φ": r"\phi", "χ": r"\chi", "ψ": r"\psi", "ω": r"\omega", "ϕ": r"\varphi", "Γ": r"\Gamma",
    "Δ": r"\Delta", "∆": r"\Delta", "Θ": r"\Theta", "Λ": r"\Lambda", "Ξ": r"\Xi", "Π": r"\Pi",
    "Σ": r"\Sigma", "Υ": r"\Upsilon", "Φ": r"\Phi", "Ψ": r"\Psi", "Ω": r"\Omega", "−": "-",
    "∙": r"\cdot", "≅": r"\cong", "∼": r"\sim", "⟹": r"\implies", "ℝ": r"\mathbb{R}", "ℕ": r"\mathbb{N}",
    "ℤ": r"\mathbb{Z}", "ℚ": r"\mathbb{Q}",
}
FONTES_MATEMATICAS = ("euclid", "math", "symbol", "mt extra", "cmmi", "cmsy", "stix")
SIMBOLOS_MATEMATICOS = set(LATEX_MAP) - {"°", "′", "″", "−"}
LATEX_ESCAPE = {"%": r"\%", "&": r"\&", "#": r"\#", "_": r"\_", "{": r"\{", "}": r"\}", "$": r"\$"}


@dataclass
class Linha:
    pagina: int  # 1-based
    x0: float
    y0: float
    x1: float
    y1: float
    texto: str  # texto plano normalizado (para busca)
    markdown: str  # texto com fórmulas inline em LaTeX ($...$)
    tamanho: float
    negrito: bool
    tem_formula: bool = False
    tipo: str = "texto"  # texto | tabela
    coluna: int = 0  # 0 = coluna única/esquerda, 1 = coluna direita (páginas em duas colunas)
    extra: dict = field(default_factory=dict)


def normalizar(texto: str) -> str:
    texto = texto.replace("Ɵ", "ti").replace("­", "").replace("�", "")
    texto = unicodedata.normalize("NFKC", texto)
    texto = texto.replace("\t", " ")
    return re.sub(r"[  ]{2,}", " ", texto).strip()


def _palavra_latex(chars: list[tuple[str, str]]) -> str:
    """chars: lista de (caractere, papel) com papel em {'n','sub','sup'} -> LaTeX."""
    saida, papel_atual, grupo = [], "n", []

    def fecha():
        if not grupo:
            return
        conteudo = "".join(grupo)
        if papel_atual == "sub":
            saida.append("_{" + conteudo + "}")
        elif papel_atual == "sup":
            saida.append("^{" + conteudo + "}")
        else:
            saida.append(conteudo)

    for c, papel in chars:
        tok = LATEX_MAP.get(c)
        if tok is None:
            tok = LATEX_ESCAPE.get(c, c)
        elif tok[0] == "\\" and tok[-1].isalpha():
            tok += " "
        if papel == "m":
            papel = "n"
        if papel != papel_atual:
            fecha()
            grupo, papel_atual = [], papel
        grupo.append(tok)
    fecha()
    return "".join(saida).strip()


def _formula_inline(palavras: list[str]) -> str:
    """Une palavras matemáticas em `$...$`, deixando pontuação final fora do modo matemático."""
    corpo = " ".join(palavras)
    m = re.match(r"^(.*?)([.,;:]*)$", corpo, re.S)
    corpo, pont = (m.group(1), m.group(2)) if m and m.group(1) else (corpo, "")
    return f"${corpo}${pont}"


def linhas_da_pagina(pagina, numero: int) -> list[Linha]:
    """Extrai as linhas de uma página PyMuPDF, corrigindo ligaduras, fonte Symbol e índices/expoentes."""
    raw = pagina.get_text("rawdict", flags=0)
    resultado: list[Linha] = []
    for bloco in raw.get("blocks", []):
        for ln in bloco.get("lines", []):
            spans = [s for s in ln.get("spans", []) if s.get("chars")]
            if not spans:
                continue
            tamanhos = [s["size"] for s in spans for _ in s["chars"]]
            base = statistics.median(tamanhos)
            # linha de base dominante (origem y dos spans de tamanho normal)
            bases = [s["origin"][1] for s in spans if s["size"] >= 0.85 * base] or [spans[0]["origin"][1]]
            baseline = statistics.median(bases)
            chars: list[tuple[str, str]] = []
            ultimo_x1 = None
            negrito = all(("Bold" in s["font"] or s["flags"] & 16) for s in spans)
            for s in spans:
                fonte = s["font"].lower()
                simbolo = "symbol" in fonte
                papel = "m" if any(f in fonte for f in FONTES_MATEMATICAS) else "n"
                if s["size"] < 0.85 * base and s["chars"][0]["c"].strip():
                    desloc = s["origin"][1] - baseline
                    if desloc < -0.12 * base:
                        papel = "sup"
                    elif desloc > 0.08 * base:
                        papel = "sub"
                for ch in s["chars"]:
                    c = ch["c"]
                    x0, x1 = ch["bbox"][0], ch["bbox"][2]
                    if c == " " and ultimo_x1 is not None and x0 < ultimo_x1 - 0.5:
                        continue  # espaço espúrio de ligadura (sobreposto ao glifo anterior)
                    if simbolo:
                        c = SYMBOL_MAP.get(c, c)
                    chars.append((c, papel if c.strip() else "n"))
                    if c.strip():
                        ultimo_x1 = x1
            texto_bruto = "".join(c for c, _ in chars)
            texto = normalizar(texto_bruto)
            if not texto:
                continue
            # markdown: palavras com índice/expoente ou símbolo matemático viram LaTeX inline
            palavras, atual = [], []
            for c, papel in chars:
                if c.isspace():
                    if atual:
                        palavras.append(atual)
                        atual = []
                else:
                    atual.append((normalizar(c) or c, papel))
            if atual:
                palavras.append(atual)
            partes, tem_formula, formula_aberta = [], False, []
            for p in palavras:
                if any(papel != "n" for _, papel in p) or any(c in SIMBOLOS_MATEMATICOS for c, _ in p):
                    formula_aberta.append(_palavra_latex(p))  # palavras matemáticas vizinhas formam uma fórmula
                    tem_formula = True
                    continue
                if formula_aberta:
                    partes.append(_formula_inline(formula_aberta))
                    formula_aberta = []
                partes.append("".join(c for c, _ in p))
            if formula_aberta:
                partes.append(_formula_inline(formula_aberta))
            x0, y0, x1, y1 = ln["bbox"]
            resultado.append(Linha(numero, x0, y0, x1, y1, texto, " ".join(partes), base, negrito, tem_formula))
    _atribuir_colunas(resultado, pagina.rect.width)
    resultado.sort(key=lambda l: (l.coluna, round(l.y0, 0), l.x0))
    return _mesclar_mesma_altura(resultado)


def _atribuir_colunas(linhas: list[Linha], largura: float) -> bool:
    """Detecta páginas em duas colunas (comuns em 2021/2022) e marca a coluna de cada linha.
    Critério: muitas linhas inteiramente à direita do meio da página, com margem esquerda recorrente,
    e poucas linhas atravessando o meio."""
    meio = largura / 2
    esq = [l for l in linhas if l.x1 <= meio + 15]
    dire = [l for l in linhas if l.x0 >= meio - 15]
    atravessam = [l for l in linhas if l.x0 < meio - 15 and l.x1 > meio + 15]
    margens = Counter(round(l.x0) for l in dire)
    duas = (len(esq) >= 5 and len(dire) >= 5 and margens and margens.most_common(1)[0][1] >= 4
            and len(atravessam) <= 0.35 * len(linhas))
    if duas:
        for l in dire:
            l.coluna = 1
    return bool(duas)


def _mesclar_mesma_altura(linhas: list[Linha]) -> list[Linha]:
    """Une fragmentos na mesma linha visual (ex.: letra da alternativa e texto em blocos distintos)."""
    out: list[Linha] = []
    for l in linhas:
        if out:
            a = out[-1]
            mesma = (a.coluna == l.coluna and abs(a.y0 - l.y0) < 2.5 and abs(a.y1 - l.y1) < 3.5
                     and l.x0 >= a.x1 - 1)
            if mesma:
                a.texto = normalizar(a.texto + " " + l.texto)
                a.markdown = (a.markdown + " " + l.markdown).strip()
                a.x1 = max(a.x1, l.x1)
                a.tem_formula = a.tem_formula or l.tem_formula
                a.negrito = a.negrito and l.negrito
                continue
        out.append(l)
    return out
