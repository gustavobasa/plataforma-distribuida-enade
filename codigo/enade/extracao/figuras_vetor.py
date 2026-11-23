"""RF04 — Conversão determinística (sem LLM, custo zero) das figuras do PDF para Mermaid e Markdown.

Os PDFs do INEP guardam muitos diagramas como desenhos vetoriais: caixas, círculos, losangos, linhas e setas,
com o texto dos rótulos posicionado por cima. Este módulo reconstrói a estrutura a partir desses objetos:
  1. nós      = formas fechadas (retângulos, cantos arredondados, elipses, losangos) com texto dentro;
  2. conectores = linhas, curvas, polígonos finos preenchidos (hastes) e pequenas formas preenchidas (pontas
                de seta), unidos em componentes por extremidades próximas;
  3. arestas  = componente que toca ≥ 2 nós (ou 1 nó + ponta de seta apontando para outro nó); a ponta de
                seta define o destino;
  4. rótulo de aresta = texto solto curto perto do meio do conector.
Com ≥ 2 nós rotulados e ≥ 1 aresta gera-se um ``flowchart`` Mermaid (TD ou LR conforme a disposição); caso
contrário a figura é descrita em Markdown com os textos que contém. Toda saída é heurística: o Mermaid é
compilado no mermaid-cli e a fidelidade é medida em amostra manual. Imagens raster não têm texto vetorial e
recebem apenas a marcação "sem texto extraível" (exigiriam OCR/LLM).

Uso: python -m enade.extracao.figuras_vetor [--limite N]    -> /dados/figuras_conv/vetorial.jsonl
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import pymupdf

from ..config import CFG
from .texto import normalizar

BASE = Path(CFG.dados_dir)
SAIDA = BASE / "figuras_conv" / "vetorial.jsonl"
METODO = "deterministico-vetorial-v1"
TOL = 4.5  # pt: distância para considerar que dois traços se tocam / que um traço toca um nó


# ------------------------------------------------------------------------------------------- geometria
def _dentro(p, r, folga=0.0) -> bool:
    return r[0] - folga <= p[0] <= r[2] + folga and r[1] - folga <= p[1] <= r[3] + folga


def _dist_ret(p, r) -> float:
    return math.hypot(max(r[0] - p[0], 0, p[0] - r[2]), max(r[1] - p[1], 0, p[1] - r[3]))


def _pontos(d) -> list[tuple[float, float]]:
    pts = []
    for it in d["items"]:
        if it[0] == "l":
            pts += [(it[1].x, it[1].y), (it[2].x, it[2].y)]
        elif it[0] == "c":
            pts += [(it[1].x, it[1].y), (it[4].x, it[4].y)]
        elif it[0] == "re":
            r = it[1]
            pts += [(r.x0, r.y0), (r.x1, r.y1), (r.x0, r.y1), (r.x1, r.y0)]
        elif it[0] == "qu":
            q = it[1]
            pts += [(q.ul.x, q.ul.y), (q.ur.x, q.ur.y), (q.ll.x, q.ll.y), (q.lr.x, q.lr.y)]
    return pts


def _forma(d) -> str | None:
    """Caminho fechado com tamanho de caixa -> ret | redondo | elipse | losango (ou None)."""
    r = d["rect"]
    w, h = r.width, r.height
    if w < 10 or h < 8:
        return None
    tipos = [it[0] for it in d["items"]]
    if tipos in (["re"], ["qu"]):
        return "ret"
    curvas, linhas = tipos.count("c"), tipos.count("l")
    if curvas >= 4 and linhas == 0:
        return "elipse"
    if curvas >= 4 and linhas >= 2:
        return "redondo"
    if linhas == 3 and curvas == 0 and min(w, h) >= 22:  # triângulo grande = nó (pequeno = ponta de seta)
        return "triangulo"
    if linhas == 4 and curvas == 0 and (d.get("closePath") or d.get("fill")):
        pts = _pontos(d)
        cx, cy = (r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2
        if linhas == 4 and all(min(abs(p[0] - cx), abs(p[1] - cy)) < 0.15 * max(w, h) for p in pts):
            return "losango"
        return "ret"
    return None


def _ponta(d):
    """Pequena forma preenchida (ponta de seta) -> (ponta, centroide) ou None."""
    r = d["rect"]
    if not d.get("fill") or not (2 <= max(r.width, r.height) <= 18) or min(r.width, r.height) < 1.5 \
            or max(r.width, r.height) > 4 * min(r.width, r.height):
        return None
    pts = _pontos(d)
    if not pts:
        return None
    c = (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))
    return max(pts, key=lambda p: math.dist(p, c)), c


def _textos(pagina, clip) -> list[dict]:
    """Linhas de texto do recorte com a mesma correção de ligaduras do extrator principal
    (espaço espúrio sobreposto ao glifo anterior é descartado) e sem fundir rótulos vizinhos."""
    out = []
    for bloco in pagina.get_text("rawdict", clip=clip)["blocks"]:
        for ln in bloco.get("lines", []):
            chars, ult = [], None
            for s in ln["spans"]:
                for ch in s["chars"]:
                    if ch["c"] == " " and ult is not None and ch["bbox"][0] < ult - 0.5:
                        continue
                    chars.append(ch["c"])
                    if ch["c"].strip():
                        ult = ch["bbox"][2]
            t = normalizar("".join(chars))
            b = ln["bbox"]
            largura = max(b[2] - b[0], 0.1)
            dentro = max(0.0, min(b[2], clip.x1) - max(b[0], clip.x0)) / largura
            cortada = dentro < 0.6  # menos de 60% da linha dentro do recorte
            if t and not cortada:  # palavras cortadas na borda do recorte pertencem ao texto da questão
                out.append({"texto": t, "bbox": tuple(b)})
    out.sort(key=lambda l: (round(l["bbox"][1] / 4), l["bbox"][0]))
    return out


def _rotulo_mermaid(t: str) -> str:
    return (t.replace('"', "#quot;").replace("<", "#lt;").replace(">", "#gt;")[:80]) or " "


_CACHE_DESENHOS: dict[tuple[str, int], list] = {}


def _desenhos(pagina) -> list:
    chave = (pagina.parent.name, pagina.number)
    if chave not in _CACHE_DESENHOS:
        if len(_CACHE_DESENHOS) > 50:
            _CACHE_DESENHOS.clear()
        _CACHE_DESENHOS[chave] = pagina.get_drawings()
    return _CACHE_DESENHOS[chave]


def _markdown(textos: list[dict], diagrama: bool) -> str:
    if not textos:
        return ""
    itens = [t["texto"] for t in textos]
    cab = "Diagrama com os rótulos:" if diagrama else "Textos presentes na figura:"
    return cab + "\n\n" + "\n".join(f"- {t}" for t in itens[:60]) + ("\n- …" if len(itens) > 60 else "")


# ------------------------------------------------------------------------------------------- conversão
def converter_figura(pagina, bbox) -> dict:
    clip = pymupdf.Rect(bbox) + (-2, -2, 2, 2)
    textos = _textos(pagina, clip)
    desenhos = [d for d in _desenhos(pagina) if pymupdf.Rect(d["rect"]).intersects(clip)]
    nao_diagrama = lambda obs: {  # noqa: E731
        "classe": "texto_figura" if textos else "sem_texto", "legivel": bool(textos), "mermaid": "", "latex": "",
        "markdown": _markdown(textos, False) or "Figura sem texto extraível (imagem raster ou desenho sem "
                                                 "rótulos); não convertida.", "observacao": obs}
    if len(desenhos) > 2500:  # gráficos densos/ilustrações: sem estrutura de grafo útil
        return nao_diagrama(f"figura vetorial complexa ({len(desenhos)} objetos); estrutura não reconstruída")
    area_fig = clip.width * clip.height

    nos, objetos = [], []  # objetos conectores: {"pts": [...], "ponta": (tip, centro) | None}
    for d in desenhos:
        r = d["rect"]
        if r.width * r.height > 0.6 * area_fig:
            continue  # moldura/fundo
        forma = _forma(d)
        if forma:
            nos.append({"rect": (r.x0, r.y0, r.x1, r.y1), "forma": forma, "textos": []})
            continue
        p = _ponta(d)
        if p:
            objetos.append({"pts": _pontos(d), "ponta": p})
            continue
        curto, longo = min(r.width, r.height), max(r.width, r.height)
        if d.get("fill") and curto < 4 and longo >= 3 * max(curto, 1):  # haste (fina ou grossa) como polígono
            meio = (r.y0 + r.y1) / 2 if r.width >= r.height else (r.x0 + r.x1) / 2
            pts = [(r.x0, meio), (r.x1, meio)] if r.width >= r.height else [(meio, r.y0), (meio, r.y1)]
            objetos.append({"pts": pts, "ponta": None})
            continue
        for it in d["items"]:
            if it[0] == "l":
                objetos.append({"pts": [(it[1].x, it[1].y), (it[2].x, it[2].y)], "ponta": None})
            elif it[0] == "c":
                objetos.append({"pts": [(it[1].x, it[1].y), (it[4].x, it[4].y)], "ponta": None})

    # nós duplicados (contorno + preenchimento) e molduras que contêm outros nós são descartados
    nos.sort(key=lambda n: (n["rect"][2] - n["rect"][0]) * (n["rect"][3] - n["rect"][1]))
    unicos = []
    for n in nos:
        if not any(all(abs(a - b) < 3 for a, b in zip(n["rect"], u["rect"])) for u in unicos):
            unicos.append(n)
    contem = lambda a, b: a is not b and _dentro(b["rect"][:2], a["rect"], 1) and _dentro(b["rect"][2:], a["rect"], 1)  # noqa: E731
    nos = [n for n in unicos if not any(contem(n, m) for m in unicos)]

    soltos = []
    for t in textos:
        c = ((t["bbox"][0] + t["bbox"][2]) / 2, (t["bbox"][1] + t["bbox"][3]) / 2)
        donos = [n for n in nos if _dentro(c, n["rect"], 1)]
        (donos[0]["textos"] if donos else soltos).append(t["texto"] if donos else t)

    # componentes de conectores (union-find com grade espacial)
    pai = list(range(len(objetos)))

    def raiz(i):
        while pai[i] != i:
            pai[i] = pai[pai[i]]
            i = pai[i]
        return i
    grade: dict = {}
    for i, o in enumerate(objetos):
        for p in o["pts"]:
            grade.setdefault((int(p[0] // TOL), int(p[1] // TOL)), []).append((i, p))
    for (gx, gy), lista in grade.items():
        viz = [x for dx in (-1, 0, 1) for dy in (-1, 0, 1) for x in grade.get((gx + dx, gy + dy), [])]
        for i, p in lista:
            sobre_no = any(_dist_ret(p, n["rect"]) <= TOL for n in nos)
            for j, q in viz:
                if i == j or math.dist(p, q) > TOL:
                    continue
                # encontro sobre um nó: o nó é a junção (ex.: duas arestas de uma árvore), não um fio —
                # exceto haste + ponta de seta, que sempre pertencem à mesma aresta
                if sobre_no and not (objetos[i]["ponta"] or objetos[j]["ponta"]):
                    continue
                pai[raiz(i)] = raiz(j)
    # haste que termina dentro da área da ponta de seta pertence à mesma aresta
    for i, o in enumerate(objetos):
        if not o["ponta"]:
            continue
        xs_, ys_ = [p[0] for p in o["pts"]], [p[1] for p in o["pts"]]
        caixa = (min(xs_), min(ys_), max(xs_), max(ys_))
        for j, s in enumerate(objetos):
            if j != i and not s["ponta"] and any(_dentro(p, caixa, TOL) for p in s["pts"]):
                pai[raiz(j)] = raiz(i)
    comps: dict[int, list] = {}
    for i, o in enumerate(objetos):
        comps.setdefault(raiz(i), []).append(o)

    def no_perto(p, excluir=(), lim=TOL):
        melhor = None
        for k, n in enumerate(nos):
            dist = _dist_ret(p, n["rect"])
            if k not in excluir and dist <= lim and (melhor is None or dist < melhor[1]):
                melhor = (k, dist)
        return melhor[0] if melhor else None

    arestas = set()
    for comp in comps.values():
        pts = [p for o in comp for p in o["pts"]]
        fora = [p for p in pts if not any(_dentro(p, n["rect"], -TOL) for n in nos)]
        if not fora or math.dist(min(fora), max(fora)) < 6:
            continue  # traço interno de uma caixa / borda compartilhada
        tocados = {k for p in pts if (k := no_perto(p)) is not None}
        destinos = set()
        for o in comp:
            if o["ponta"]:
                _, centro = o["ponta"]
                # a ponta é o vértice que encosta num nó (vale para triângulos de qualquer proporção)
                tip = min(o["pts"], key=lambda p: min((_dist_ret(p, n["rect"]) for n in nos), default=1e9))
                k = no_perto(tip, lim=5)
                if k is not None:
                    destinos.add(k)
                    tocados.add(k)
                    if len(tocados) == 1:  # haste invisível: procura a origem na direção oposta à ponta
                        vx, vy = centro[0] - tip[0], centro[1] - tip[1]
                        norma = math.hypot(vx, vy) or 1
                        for passo in range(2, 160, 2):
                            q = (centro[0] + vx / norma * passo, centro[1] + vy / norma * passo)
                            s = no_perto(q, excluir={k}, lim=2)
                            if s is not None:
                                tocados.add(s)
                                break
        if len(tocados) < 2:
            continue
        rot = None
        meio = (sum(p[0] for p in fora) / len(fora), sum(p[1] for p in fora) / len(fora))
        for t in soltos:
            c = ((t["bbox"][0] + t["bbox"][2]) / 2, (t["bbox"][1] + t["bbox"][3]) / 2)
            if math.dist(c, meio) < 18 and len(t["texto"]) <= 25:
                rot = t["texto"]
                break
        if destinos:
            for a in tocados - destinos:
                for b in destinos:
                    arestas.add((a, b, True, rot))
        else:  # sem seta: liga os nós tocados em cadeia, na ordem espacial
            ordem = sorted(tocados, key=lambda k: (nos[k]["rect"][0], nos[k]["rect"][1]))
            for a, b in zip(ordem, ordem[1:]):
                arestas.add((min(a, b), max(a, b), False, rot))

    rotulados = sum(1 for n in nos if n["textos"])
    ligados = {a for a, b, *_ in arestas} | {b for a, b, *_ in arestas}
    rot_ligados = sum(1 for k in ligados if nos[k]["textos"])
    # diagrama = maioria dos nós com rótulo E maioria dos nós rotulados participando de ligações
    if not (len(nos) >= 2 and arestas and rotulados >= max(2, 0.6 * len(nos))
            and rot_ligados >= max(2, 0.5 * rotulados)):
        return nao_diagrama(f"nós={len(nos)} rotulados={rotulados} ligados={rot_ligados} arestas={len(arestas)}: "
                            f"não reconhecida como diagrama")
    xs = [(n["rect"][0] + n["rect"][2]) / 2 for n in nos]
    ys = [(n["rect"][1] + n["rect"][3]) / 2 for n in nos]
    niveis = len({round(y / 12) for y in ys})
    direcao = "TD" if niveis >= 3 or (max(xs) - min(xs)) <= 1.3 * (max(ys) - min(ys)) else "LR"
    formas = {"ret": '["{}"]', "redondo": '("{}")', "elipse": '(("{}"))', "losango": '{{"{}"}}',
              "triangulo": r'[/"{}"\]'}
    usados = {a for a, b, *_ in arestas} | {b for a, b, *_ in arestas}
    linhas = [f"flowchart {direcao}"]
    for k, n in enumerate(nos):
        if k in usados or n["textos"]:
            linhas.append(f"  n{k}" + formas[n["forma"]].format(_rotulo_mermaid(" ".join(n["textos"]))))
    for a, b, dirigida, rot in sorted(arestas, key=lambda e: (e[0], e[1])):
        linhas.append(f"  n{a} {'-->' if dirigida else '---'}" + (f'|"{_rotulo_mermaid(rot)}"|' if rot else "")
                      + f" n{b}")
    return {"classe": "diagrama", "legivel": True, "mermaid": "\n".join(linhas), "latex": "",
            "markdown": _markdown(textos, True),
            "observacao": f"heurística vetorial: {len(nos)} nós, {len(arestas)} arestas "
                          f"({sum(1 for e in arestas if e[2])} com seta)"}


# ------------------------------------------------------------------------------------------- lote
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--limite", type=int, default=0)
    ap.add_argument("--arquivos", nargs="*", help="só estas figuras (ex.: 2022/<id>-1.png) — depuração")
    a = ap.parse_args(argv)
    SAIDA.parent.mkdir(parents=True, exist_ok=True)
    abertos: dict[str, pymupdf.Document] = {}
    n, cont = 0, {}
    saida = SAIDA if not a.arquivos else SAIDA.with_name("depuracao.jsonl")
    with saida.open("w", encoding="utf-8") as fh:
        for arq in sorted((BASE / "extraidos").glob("*/*.jsonl")):
            for linha in arq.read_text(encoding="utf-8").splitlines():
                d = json.loads(linha)
                for f in d["midia"]["figuras"]:
                    if not f.get("arquivo") or (a.arquivos and f["arquivo"] not in a.arquivos):
                        continue
                    if a.limite and n >= a.limite:
                        break
                    caminho = str(BASE / "pdfs" / str(d["ano"]) / d["origem"]["pdf"])
                    if caminho not in abertos:
                        abertos[caminho] = pymupdf.open(caminho)
                    conv = converter_figura(abertos[caminho][f["pagina"] - 1], f["bbox"])
                    if f["tipo"] == "imagem" and conv["classe"] != "diagrama":
                        conv["observacao"] += "; imagem raster: texto interno não extraível sem OCR"
                    fh.write(json.dumps({"arquivo": f["arquivo"], "modelo": METODO, "tipo_figura": f["tipo"],
                                         "conversao": conv}, ensure_ascii=False) + "\n")
                    cont[conv["classe"]] = cont.get(conv["classe"], 0) + 1
                    n += 1
    print(json.dumps({"figuras": n, "por_classe": cont, "saida": str(saida)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
