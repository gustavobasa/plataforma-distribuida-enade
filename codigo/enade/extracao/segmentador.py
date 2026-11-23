"""RF02/RF03/RF04/RF06 — Segmentação de um caderno de prova do ENADE em questões.

Estratégia (determinística, sem LLM):
  1. reconstrói linhas por página (texto.py) e remove ruído: marca d'água VALIDINEP, códigos de barras,
     cabeçalho/rodapé corrente, área de rascunho;
  2. detecta tabelas com bordas (PyMuPDF `find_tables`) e as converte em Markdown;
  3. detecta figuras (imagens raster e agrupamentos de desenhos vetoriais) e recorta um PNG de cada uma;
  4. percorre as linhas em ordem: cabeçalhos de seção (FORMAÇÃO GERAL / COMPONENTE ESPECÍFICO) definem FG/CE;
     cabeçalhos "QUESTÃO NN" / "QUESTÃO DISCURSIVA NN" abrem uma nova questão; o questionário de percepção encerra;
  5. em cada questão objetiva, localiza as alternativas A–E (busca reversa por sequência ordenada) e separa
     texto-base (até a última referência bibliográfica "Disponível em/Acesso em/(adaptado)") do enunciado.
Cada questão registra as páginas de origem (1-based).
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf

from .texto import Linha, linhas_da_pagina, normalizar

RE_DISCURSIVA = re.compile(r"^QUEST[AÃ]O\s+DISCURSIVA\s+0?(\d{1,2})\b", re.I)
RE_OBJETIVA = re.compile(r"^QUEST[AÃ]O\s+0?(\d{1,2})\s*$", re.I)
RE_SECAO_FG = re.compile(r"^FORMA[CÇ][AÃ]O\s+GERAL\s*$", re.I)
RE_SECAO_CE = re.compile(r"^COMPONENTE\s+ESPEC[IÍ]FICO\s*$", re.I)
RE_FIM = re.compile(r"QUESTION[AÁ]RIO\s+DE\s+PERCEP|AVALIA[CÇ][AÃ]O\s+GLOBAL\s+DA\s+PROVA|PERCEP[CÇ][AÃ]O\s+DA\s+PROVA", re.I)
RE_BARRAS = re.compile(r"^\*[A-Z0-9]+\*?$")
RE_ALT = re.compile(r"^([A-E])(?:\s+(.*))?$")
RE_CITACAO = re.compile(r"Dispon[ií]vel em|Acesso em|\(adaptado\)|^[A-ZÁÉÍÓÚÂÊÔÃÕÇ]{2,}[A-ZÁÉÍÓÚÂÊÔÃÕÇ\s]*,\s+[A-Z]")
RE_ITEM = re.compile(r"^(?:[IVX]{1,4}\.|\d{1,2}[.)]|[a-z]\)|•|–|-)\s")
# nota de rodapé de texto-base: "1 Bebop: gênero musical…", "* Cf. …"
RE_RODAPE = re.compile(r"^(?:\d{1,2}|\*)\s*[A-ZÀ-Úa-zà-ú][^:]{0,40}:\s")
# início de comando da questão (a partir daqui é enunciado)
RE_COMANDO = re.compile(
    r"^(?:Considerando|Com base|A partir d|Nesse contexto|Nessa situação|Nesse caso|Nesse sentido|"
    r"Nessa perspectiva|Diante d|De acordo com|Tendo em vista|Acerca d|A respeito d|Em relação|Com relação|"
    r"No que se refere|No que concerne|Quanto a|Assinale|Avalie|Julgue|Analise|Com referência|Levando em conta|"
    r"Levando-se em conta|Em face d|Sob essa|Sob a perspectiva|"
    r"Com o objetivo|Para responder)", re.I)
RE_COMANDO_MEIO = re.compile(r"assinale|avalie as|julgue|permite concluir|é correto afirmar|pode-se afirmar|"
                             r"conclui-se|é correto o que se afirma", re.I)


@dataclass
class Figura:
    pagina: int
    bbox: tuple[float, float, float, float]
    tipo: str  # imagem | vetorial
    png: bytes | None = None


@dataclass
class QuestaoBruta:
    numero: int
    tipo: str  # objetiva | discursiva
    componente: str | None  # FG | CE | None
    linhas: list[Linha] = field(default_factory=list)
    fechada: bool = False  # após "RASCUNHO" nada mais pertence à questão
    inicio: tuple[int, int, float] = (0, 0, 0.0)  # (página, coluna, y)


@dataclass
class QuestaoExtraida:
    numero: int
    tipo: str
    componente: str | None
    texto_base: str
    enunciado: str
    alternativas: list[dict]
    texto_base_md: str
    enunciado_md: str
    paginas: list[int]
    tabelas_md: list[str]
    figuras: list[Figura]
    tem_formula: bool
    formulas_latex: list[str]
    alertas: list[str]


@dataclass
class ProvaExtraida:
    arquivo: str
    paginas: int
    curso_nome: str | None
    questoes: list[QuestaoExtraida]
    alertas: list[str]


RE_CAPA_OBJ = re.compile(r"(Forma[cç][aã]o\s+Geral|Componente\s+Espec[ií]fico)\s*:?\s*Objetivas?\s+0?(\d{1,2})\s+a\s+0?(\d{1,2})", re.I)
RE_CAPA_DISC = re.compile(r"(Forma[cç][aã]o\s+Geral|Componente\s+Espec[ií]fico)\s*:?\s*Discursivas?\s+D(\d)(?:\s*(?:e|a)\s*D(\d))?", re.I)


def ler_capa(linhas: list[Linha]) -> dict[tuple[str, int], str]:
    """Lê a tabela de distribuição da capa ("Formação Geral: Objetivas 1 a 8" ...) -> {(tipo, n): FG|CE}."""
    texto = " ".join(l.texto for l in linhas)
    mapa: dict[tuple[str, int], str] = {}
    for m in RE_CAPA_OBJ.finditer(texto):
        comp = "FG" if m.group(1).lower().startswith("forma") else "CE"
        for n in range(int(m.group(2)), int(m.group(3)) + 1):
            mapa[("objetiva", n)] = comp
    for m in RE_CAPA_DISC.finditer(texto):
        comp = "FG" if m.group(1).lower().startswith("forma") else "CE"
        a = int(m.group(2))
        b = int(m.group(3)) if m.group(3) else a
        for n in range(a, b + 1):
            mapa[("discursiva", n)] = comp
    return mapa


def componente_capa(capa: dict, tipo: str, numero: int) -> str | None:
    return capa.get((tipo, numero))


def nome_do_curso(paginas_linhas: list[list[Linha]], alturas: list[float]) -> str | None:
    """Nome do curso = texto mais frequente na faixa extrema de cabeçalho/rodapé (ex.: "Engenharia de Computação"
    em 2023, "CIÊNCIA DA COMPUTAÇÃO" em 2021), ignorando códigos de barras, marca d'água, nº de página e rótulos
    de diagramação. Nomes só em maiúsculas são convertidos para caixa de título."""
    ignorar = {"MATÉRIA", "MATERIA", "ÁREA LIVRE", "AREA LIVRE", "RASCUNHO", "LOGO"}
    cont: Counter[str] = Counter()
    for linhas, h in zip(paginas_linhas[1:], alturas[1:]):
        vistos = set()
        for l in linhas:
            if not (l.y0 < 45 or l.y0 > h - 40):
                continue
            t = re.sub(r"\s*\d+\s*", " ", l.texto).strip()
            tu = t.upper()
            if ("*" in t or "VALIDINEP" in tu or tu in ignorar or len(re.findall(r"[A-Za-zÀ-ú]", t)) < 4
                    or RE_OBJETIVA.match(tu) or RE_DISCURSIVA.match(tu)):
                continue
            if t not in vistos:
                vistos.add(t)
                cont[t] += 1
    if not cont:
        return None
    # prefere a grafia com minúsculas quando o mesmo nome aparece nas duas formas
    nome, n = max(cont.items(), key=lambda kv: (kv[1] + (0.5 if kv[0].upper() != kv[0] else 0)))
    if n < 3:
        return None
    if nome.upper() == nome:
        minusculas = {"de", "da", "do", "das", "dos", "e", "em", "a", "o"}
        nome = " ".join(p.lower() if p.lower() in minusculas and i else p.capitalize()
                        for i, p in enumerate(nome.lower().split()))
    return nome


def _cabecalhos_correntes(paginas_linhas: list[list[Linha]], alturas: list[float]) -> set[str]:
    """Textos que se repetem nas margens de muitas páginas (cabeçalho/rodapé corrente)."""
    cont: Counter[str] = Counter()
    for linhas, h in zip(paginas_linhas, alturas):
        vistos = set()
        for l in linhas:
            if l.y0 < 75 or l.y0 > h - 120:
                chave = re.sub(r"\d+", "", l.texto).strip().lower()
                if chave and chave not in vistos:
                    vistos.add(chave)
                    cont[chave] += 1
    limite = max(3, int(0.4 * len(paginas_linhas)))
    return {k for k, n in cont.items() if n >= limite}


def _dentro(l: Linha, r: tuple[float, float, float, float], folga: float = 2.0) -> bool:
    cx, cy = (l.x0 + l.x1) / 2, (l.y0 + l.y1) / 2
    return r[0] - folga <= cx <= r[2] + folga and r[1] - folga <= cy <= r[3] + folga


def _tabelas(pagina, numero: int, linhas: list[Linha]) -> tuple[list[Linha], list[tuple]]:
    try:
        achadas = pagina.find_tables().tables
    except Exception:  # find_tables pode falhar em páginas com desenho degenerado; segue sem tabelas
        return linhas, []
    rects = []
    for t in achadas:
        if t.row_count < 2 or t.col_count < 2:
            continue
        md = t.to_markdown(clean=False).strip()
        if not md:
            continue
        r = tuple(t.bbox)
        larg, alt = pagina.rect.width, pagina.rect.height
        if (r[3] - r[1]) > 0.55 * alt or (r[2] - r[0]) * (r[3] - r[1]) > 0.4 * larg * alt:
            continue  # moldura da página detectada como tabela
        dentro = [l for l in linhas if _dentro(l, r)]
        if dentro and all(re.fullmatch(r"\d{1,2}", l.texto) for l in dentro):
            continue  # grade numerada do rascunho
        if any(RE_OBJETIVA.match(l.texto.upper()) or RE_DISCURSIVA.match(l.texto.upper()) for l in dentro):
            continue
        celulas = [c for linha in (t.extract() or []) for c in linha if c]
        if celulas and sum(len(c) for c in celulas) / len(celulas) > 160:
            continue  # caixa de texto corrido, não tabela
        plano = normalizar(" ".join(l.texto for l in dentro))
        linhas = [l for l in linhas if not _dentro(l, r)]
        col = 1 if any(l.coluna == 1 for l in linhas) and r[0] >= pagina.rect.width / 2 - 15 else 0
        linhas.append(Linha(numero, r[0], r[1], r[2], r[3], plano, md, 12.0, False, False, "tabela", col))
        rects.append(r)
    linhas.sort(key=lambda l: (l.coluna, round(l.y0, 0), l.x0))
    return linhas, rects


def _agrupar(itens: list[list], dist: float = 6.0) -> list[list]:
    """Agrupa retângulos [x0,y0,x1,y1,n_itens,curvas] que se tocam (distância <= dist)."""
    grupos = [list(i) for i in itens]
    mudou = True
    while mudou:
        mudou = False
        out: list[list] = []
        for g in grupos:
            for o in out:
                if not (g[0] > o[2] + dist or g[2] < o[0] - dist or g[1] > o[3] + dist or g[3] < o[1] - dist):
                    o[0], o[1], o[2], o[3] = min(o[0], g[0]), min(o[1], g[1]), max(o[2], g[2]), max(o[3], g[3])
                    o[4] += g[4]
                    o[5] += g[5]
                    mudou = True
                    break
            else:
                out.append(g)
        grupos = out
    return grupos


def _figuras(pagina, numero: int, h: float, tabelas: list[tuple]) -> list[Figura]:
    """Figuras = imagens raster e agrupamentos de desenhos vetoriais (gráficos, circuitos, diagramas).
    Exclui a moldura da página, linhas separadoras e caixas simples de texto (um único retângulo)."""
    w = pagina.rect.width
    util = lambda r: r[1] >= 70 and r[3] <= h - 40  # noqa: E731 (fora de cabeçalho/rodapé)
    imgs = [[*i["bbox"], 1, 0] for i in pagina.get_image_info() if util(i["bbox"])]
    desenhos = []
    for d in pagina.get_drawings():
        r = d["rect"]
        if not util((r.x0, r.y0, r.x1, r.y1)):
            continue
        if (r.width > 0.8 * w and (r.height > 0.5 * h or r.height < 3)) or (r.height > 0.6 * h and r.width < 3):
            continue  # moldura da página ou linha separadora
        curvas = sum(1 for it in d["items"] if it[0] == "c")
        desenhos.append([r.x0, r.y0, r.x1, r.y1, len(d["items"]), curvas])
    figs: list[Figura] = []
    for tipo, grupos in (("imagem", _agrupar(imgs)), ("vetorial", _agrupar(desenhos))):
        for x0, y0, x1, y1, n, curvas in grupos:
            if (x1 - x0) < 50 or (y1 - y0) < 30 or (x1 - x0) * (y1 - y0) < 2500:
                continue
            if tipo == "vetorial" and n < 4 and curvas == 0:
                continue  # caixa simples ao redor de texto
            if any(not (x1 < t[0] or x0 > t[2] or y1 < t[1] or y0 > t[3]) for t in tabelas):
                continue
            if any(not (x1 < f.bbox[0] or x0 > f.bbox[2] or y1 < f.bbox[1] or y0 > f.bbox[3]) for f in figs):
                continue
            figs.append(Figura(numero, (x0, y0, x1, y1), tipo))
    return figs


def _paragrafos(linhas: list[Linha], md: bool) -> str:
    partes: list[str] = []
    anterior: Linha | None = None
    for l in linhas:
        txt = l.markdown if md else l.texto
        if l.tipo == "tabela":
            partes.append(("\n\n" + txt + "\n\n") if md else ("\n" + txt + "\n"))
            anterior = None
            continue
        if anterior is None:
            partes.append(txt)
        else:
            novo_par = (l.pagina != anterior.pagina and RE_ITEM.match(l.texto)) or \
                (l.pagina == anterior.pagina and l.y0 - anterior.y1 > 0.4 * max(l.tamanho, 8)) or \
                bool(RE_ITEM.match(l.texto))
            partes.append(("\n\n" if md else "\n") + txt if novo_par else " " + txt)
        anterior = l
    texto = "".join(partes)
    return re.sub(r"\n{3,}", "\n\n", texto).strip()


def _localizar_alternativas(linhas: list[Linha], letras: str) -> dict[str, int] | None:
    """Busca reversa: a última linha iniciada pela última letra, depois a anterior a ela, etc.
    Assim, frases do texto-base que começam com "A " não são confundidas com a alternativa A."""
    idx: dict[str, int] = {}
    limite = len(linhas)
    for letra in reversed(letras):
        achou = None
        for i in range(limite - 1, -1, -1):
            l = linhas[i]
            m = RE_ALT.match(l.texto)
            if m and m.group(1) == letra and l.tipo == "texto":
                achou = i
                break
        if achou is None:
            return None
        idx[letra] = achou
        limite = achou
    return idx


def _separar(q: QuestaoBruta) -> QuestaoExtraida:
    alertas: list[str] = []
    linhas = [l for l in q.linhas if l.texto]
    alternativas: list[dict] = []
    corpo = linhas
    if q.tipo == "objetiva":
        # 5 alternativas (A–E) é o padrão; algumas provas (ex.: Medicina 2023, componente específico) usam A–D.
        letras = "ABCDE"
        idx = _localizar_alternativas(linhas, letras)
        if idx is None:
            letras = "ABCD"
            idx = _localizar_alternativas(linhas, letras)
            if idx is not None:
                alertas.append("quatro_alternativas")
        if idx is not None:
            ordem = [idx[c] for c in letras] + [len(linhas)]
            for k, letra in enumerate(letras):
                trecho = linhas[ordem[k]:ordem[k + 1]]
                plano = re.sub(r"^[A-E]\s*", "", _paragrafos(trecho, False), count=1)
                md = re.sub(r"^[A-E]\s*", "", _paragrafos(trecho, True), count=1)
                alternativas.append({"letra": letra, "texto": plano, "texto_md": md})
            corpo = linhas[: idx["A"]]
        else:
            alertas.append("alternativas_nao_detectadas")
    # separação texto-base x enunciado (v1.1, revisada após a validação manual):
    #  1) o texto-base vai, no mínimo, até a última referência bibliográfica ou nota de rodapé;
    #  2) depois dela (ou desde o início, se não houver citação), o enunciado começa no primeiro parágrafo de
    #     comando ("Considerando…", "Com base…", "Nesse contexto…", "Assinale…", "Avalie…"); o contexto antes
    #     dele (situação-problema, dados, casos clínicos) também é texto-base.
    ult_cit = -1
    for i, l in enumerate(corpo):
        if l.tipo == "texto" and (RE_CITACAO.search(l.texto) or RE_RODAPE.match(l.texto)):
            ult_cit = i
    inicio_enun = ult_cit + 1
    for i in range(max(ult_cit + 1, 1), len(corpo)):
        l, ant = corpo[i], corpo[i - 1]
        inicio_frase = ant.tipo == "tabela" or ant.texto.rstrip().endswith((".", ":", "?", ")")) or \
            (l.pagina == ant.pagina and l.y0 - ant.y1 > 0.4 * max(l.tamanho, 8))
        if l.tipo == "texto" and inicio_frase and RE_COMANDO.match(l.texto):
            inicio_enun = i
            break
    else:
        # reserva: última frase (início de linha) que contenha verbo de comando
        for i in range(len(corpo) - 1, max(ult_cit + 1, 1) - 1, -1):
            l, ant = corpo[i], corpo[i - 1]
            if l.tipo == "texto" and ant.texto.rstrip().endswith((".", ":", "?", ")")) and \
                    RE_COMANDO_MEIO.search(l.texto) and not RE_ITEM.match(l.texto):
                inicio_enun = i
                break
    if 0 < inicio_enun < len(corpo):
        base, enun = corpo[:inicio_enun], corpo[inicio_enun:]
    else:
        base, enun = [], corpo
        if ult_cit == len(corpo) - 1 and corpo:
            alertas.append("citacao_no_fim_do_corpo")
    if not enun:
        alertas.append("enunciado_vazio")
    paginas = sorted({l.pagina for l in q.linhas})
    tem_formula = any(l.tem_formula for l in q.linhas)
    formulas = sorted({m for l in q.linhas for m in re.findall(r"\$[^$]+\$", l.markdown)})
    return QuestaoExtraida(
        numero=q.numero, tipo=q.tipo, componente=q.componente,
        texto_base=_paragrafos(base, False), enunciado=_paragrafos(enun, False), alternativas=alternativas,
        texto_base_md=_paragrafos(base, True), enunciado_md=_paragrafos(enun, True),
        paginas=paginas, tabelas_md=[l.markdown for l in q.linhas if l.tipo == "tabela"],
        figuras=[], tem_formula=tem_formula, formulas_latex=formulas[:50], alertas=alertas,
    )


def extrair_prova(caminho: str | Path, recortar_figuras: bool = True) -> ProvaExtraida:
    doc = pymupdf.open(str(caminho))
    paginas_linhas, alturas, figuras_pag, tabelas_pag, larguras, colunas_pag = [], [], [], [], [], []
    for i, pagina in enumerate(doc):
        n = i + 1
        h = pagina.rect.height
        linhas = linhas_da_pagina(pagina, n)
        linhas, rects_tab = _tabelas(pagina, n, linhas)
        paginas_linhas.append(linhas)
        alturas.append(h)
        larguras.append(pagina.rect.width)
        colunas_pag.append(any(l.coluna == 1 for l in linhas))
        tabelas_pag.append(rects_tab)
        figuras_pag.append(_figuras(pagina, n, h, rects_tab))
    correntes = _cabecalhos_correntes(paginas_linhas, alturas)
    capa = ler_capa(paginas_linhas[0] if paginas_linhas else [])
    curso_nome = nome_do_curso(paginas_linhas, alturas)

    questoes: list[QuestaoBruta] = []
    alertas_prova: list[str] = []
    componente: str | None = None
    atual: QuestaoBruta | None = None
    encerrou = False
    for linhas, h in zip(paginas_linhas, alturas):
        if encerrou:
            break
        ultima: Linha | None = None
        for l in linhas:
            t = l.texto
            tu = t.upper()
            if "VALIDINEP" in tu or RE_BARRAS.match(t) or tu in ("LOGO", "ÁREA LIVRE", "AREA LIVRE"):
                continue
            if l.y0 > h - 40 and l.tipo == "texto":
                continue  # faixa de rodapé (nº de página, nome do curso, rótulos de diagramação como "MATÉRIA")
            if ultima and t == ultima.texto and abs(l.y0 - ultima.y0) < 5:
                continue  # sombra/duplicata do mesmo texto
            ultima = l
            chave = re.sub(r"\d+", "", t).strip().lower()
            if chave in correntes and (l.y0 < 75 or l.y0 > h - 120):
                continue
            if RE_FIM.search(tu) and questoes:
                encerrou = True
                break
            if RE_SECAO_FG.match(tu):
                componente = "FG"
                continue
            if RE_SECAO_CE.match(tu):
                componente = "CE"
                continue
            m_d, m_o = RE_DISCURSIVA.match(tu), RE_OBJETIVA.match(tu)
            if m_d or m_o:
                tipo = "discursiva" if m_d else "objetiva"
                num = int((m_d or m_o).group(1))
                comp = componente_capa(capa, tipo, num) or componente
                atual = QuestaoBruta(num, tipo, comp, inicio=(l.pagina, l.coluna, l.y0))
                questoes.append(atual)
                continue
            if atual is None:
                continue
            if tu.startswith("RASCUNHO"):
                atual.fechada = True
                continue
            if atual.fechada:
                continue
            if l.y0 > h - 60 and re.fullmatch(r"\d{1,3}", t):
                continue  # número de página isolado
            atual.linhas.append(l)

    # figuras: atribuídas à questão cuja região (início até início da próxima) contém a figura
    extraidas: list[QuestaoExtraida] = []
    for k, q in enumerate(questoes):
        qx = _separar(q)
        fim = questoes[k + 1].inicio if k + 1 < len(questoes) else (10_000, 0, 0.0)
        for figs, larg in zip(figuras_pag, larguras):
            for f in figs:
                col = 1 if colunas_pag[f.pagina - 1] and f.bbox[0] >= larg / 2 - 15 else 0
                pos = (f.pagina, col, f.bbox[1])
                if q.inicio <= pos < fim and (not q.linhas or f.pagina in qx.paginas):
                    if recortar_figuras:
                        pg = doc[f.pagina - 1]
                        clip = pymupdf.Rect(f.bbox) & pg.rect
                        if not clip.is_empty:
                            f.png = pg.get_pixmap(clip=clip, dpi=110).tobytes("png")
                    qx.figuras.append(f)
        extraidas.append(qx)

    vistos = Counter((q.tipo, q.numero) for q in extraidas)
    for (tipo, num), n in vistos.items():
        if n > 1:
            alertas_prova.append(f"numero_repetido:{tipo}:{num}")
    if not extraidas:
        alertas_prova.append("nenhuma_questao_encontrada")
    return ProvaExtraida(arquivo=Path(caminho).name, paginas=len(doc), curso_nome=curso_nome,
                         questoes=extraidas, alertas=alertas_prova)
