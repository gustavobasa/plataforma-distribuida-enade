"""Pipeline de extração: PDFs do acervo (manifesto da coleta + PDFs locais) -> JSONL de questões.

Uso:
  python -m enade.extracao --anos 2021 2022 2023            # usa /dados/pdfs/manifesto.json
  python -m enade.extracao --local /dados/locais/prova.pdf --ano 2023 --curso meu_curso [--gabarito gb.pdf]

Saídas:
  /dados/extraidos/{ano}/{curso}.jsonl  – um documento por questão (esquema enade.esquema.Questao)
  /dados/figuras/{ano}/{id}-{k}.png      – recortes das figuras
  /dados/extraidos/relatorio_extracao.json – contagens, alertas e tempo
"""
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from ..config import CFG
from ..esquema import grupo_equivalencia, id_questao, validar
from ..logs import evento, obter_logger
from .gabarito import ItemGabarito, ler_gabarito, ler_padrao_resposta
from .metadados import area_do_curso, classificar, grau_do_curso
from .segmentador import extrair_prova

LOG = obter_logger("extracao")
VERSAO = "1.0"


def _titulo(slug: str) -> str:
    return slug.replace("_", " ").capitalize()


def montar_documentos(pv: Path, ano: int, slug: str, url: str | None, sha: str | None,
                      gb: Path | None, gb_url: str | None, pr: Path | None, dir_figuras: Path) -> tuple[list[dict], dict]:
    prova = extrair_prova(pv)
    gabarito: dict[tuple[str, int], ItemGabarito] = ler_gabarito(gb) if gb else {}
    padroes = ler_padrao_resposta(pr) if pr else {}
    curso = prova.curso_nome or _titulo(slug)
    agora = datetime.now(timezone.utc).isoformat(timespec="seconds")
    docs, invalidos = [], []
    for q in prova.questoes:
        qid = id_questao(ano, slug, q.tipo, q.numero)
        alertas = list(q.alertas)
        g = gabarito.get((q.tipo, q.numero))
        if q.tipo == "discursiva":
            status, valor, anulada = "discursiva", None, bool(g and g.anulada)
        elif g is None:
            status, valor, anulada = "indisponivel", None, False
            alertas.append("gabarito_nao_encontrado")
        elif g.anulada:
            status, valor, anulada = "anulada", None, True
        else:
            status, valor, anulada = "definitivo", g.valor, False
        if q.componente is None:
            alertas.append("componente_inferido_por_ausencia_de_secao")
        componente = q.componente or "CE"
        figuras = []
        for k, f in enumerate(q.figuras, 1):
            arq = None
            if f.png:
                destino = dir_figuras / str(ano) / f"{qid}-{k}.png"
                destino.parent.mkdir(parents=True, exist_ok=True)
                destino.write_bytes(f.png)
                arq = f"{ano}/{qid}-{k}.png"
            figuras.append({"pagina": f.pagina, "bbox": [round(v, 1) for v in f.bbox], "tipo": f.tipo, "arquivo": arq})
        pendencias = []
        if figuras:
            pendencias.append("figura/diagrama preservado como imagem PNG; conversão para Mermaid não realizada (sem LLM)")
        cls = classificar(q.texto_base, q.enunciado, q.alternativas, bool(figuras), bool(q.tabelas_md), q.tipo)
        if "alternativas_nao_detectadas" in alertas or "enunciado_vazio" in alertas:
            confianca = "baixa"
        elif alertas:
            confianca = "media"
        else:
            confianca = "alta"
        rotulo = f"Questão Discursiva {q.numero}" if q.tipo == "discursiva" else f"Questão {q.numero:02d}"
        doc = {
            "id": qid, "ano": ano, "area": area_do_curso(slug), "curso": curso, "curso_slug": slug,
            "grau": grau_do_curso(slug), "componente": componente, "tipo_questao": q.tipo, "numero": q.numero,
            "rotulo": rotulo, "texto_base": q.texto_base, "enunciado": q.enunciado or q.texto_base,
            "alternativas": q.alternativas, "texto_base_md": q.texto_base_md, "enunciado_md": q.enunciado_md,
            "gabarito": valor, "gabarito_status": status, "anulada": anulada,
            "padrao_resposta": padroes.get(q.numero) if q.tipo == "discursiva" else None,
            "competencias": cls["competencias"], "competencias_ids": cls["competencias_ids"],
            "objetos_conhecimento": cls["objetos_conhecimento"], "objetos_ids": cls["objetos_ids"],
            "classificacao_metodo": cls["metodo"],
            "midia": {"tem_formula": q.tem_formula, "formulas_latex": q.formulas_latex, "tabelas_md": q.tabelas_md,
                      "figuras": figuras, "mermaid": [], "pendencias": pendencias},
            "origem": {"pdf": pv.name, "url": url, "paginas": q.paginas or [0], "sha256": sha,
                       "gabarito_pdf": gb.name if gb else None, "gabarito_url": gb_url,
                       "padrao_resposta_pdf": pr.name if pr else None},
            "grupo_equivalencia": grupo_equivalencia(q.enunciado, q.alternativas),
            "extracao": {"versao": VERSAO, "confianca": confianca, "alertas": alertas, "extraido_em": agora},
        }
        ok, erro = validar(doc)
        if ok:
            docs.append(ok)
        else:
            doc["_erro_validacao"] = erro
            invalidos.append(doc)
    resumo = {"pdf": pv.name, "ano": ano, "curso": curso, "curso_slug": slug, "paginas": prova.paginas,
              "questoes": len(prova.questoes), "validas": len(docs), "invalidas": len(invalidos),
              "objetivas": sum(1 for d in docs if d["tipo_questao"] == "objetiva"),
              "discursivas": sum(1 for d in docs if d["tipo_questao"] == "discursiva"),
              "anuladas": sum(1 for d in docs if d["anulada"]),
              "com_gabarito": sum(1 for d in docs if d["gabarito"]),
              "gabarito_itens": len(gabarito), "alertas_prova": prova.alertas,
              "confianca": {c: sum(1 for d in docs if d["extracao"]["confianca"] == c) for c in ("alta", "media", "baixa")}}
    return docs + invalidos, resumo


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--anos", type=int, nargs="*", default=[2021, 2022, 2023])
    ap.add_argument("--cursos", nargs="*")
    ap.add_argument("--local", help="PDF local de prova (fora do manifesto)")
    ap.add_argument("--gabarito", help="PDF local de gabarito (opcional)")
    ap.add_argument("--ano", type=int)
    ap.add_argument("--curso")
    args = ap.parse_args(argv)

    base = Path(CFG.dados_dir)
    saida, dir_fig = base / "extraidos", base / "figuras"
    trabalhos = []
    if args.local:
        if not (args.ano and args.curso):
            ap.error("--local exige --ano e --curso")
        gb = Path(args.gabarito) if args.gabarito else None
        trabalhos.append((Path(args.local), args.ano, args.curso, None, None, gb, None, None))
    else:
        man = json.loads((base / "pdfs" / "manifesto.json").read_text(encoding="utf-8"))
        idx = {(m["ano"], m["curso_slug"], m["tipo"]): m for m in man}
        for (ano, slug, tipo), m in sorted(idx.items()):
            if tipo != "PV" or ano not in args.anos or (args.cursos and slug not in args.cursos):
                continue
            gb, pr = idx.get((ano, slug, "GB")), idx.get((ano, slug, "PR"))
            trabalhos.append((base / "pdfs" / m["arquivo"], ano, slug, m["url"], m["sha256"],
                              base / "pdfs" / gb["arquivo"] if gb else None, gb["url"] if gb else None,
                              base / "pdfs" / pr["arquivo"] if pr else None))
    relatorio, t0 = [], time.perf_counter()
    for pv, ano, slug, url, sha, gb, gb_url, pr in trabalhos:
        t = time.perf_counter()
        try:
            docs, resumo = montar_documentos(pv, ano, slug, url, sha, gb, gb_url, pr, dir_fig)
        except Exception as exc:  # um PDF problemático não interrompe o lote; fica registrado
            evento(LOG, "falha na extração", nivel=40, pdf=str(pv), erro=repr(exc))
            relatorio.append({"pdf": pv.name, "ano": ano, "curso_slug": slug, "erro": repr(exc)})
            continue
        resumo["segundos"] = round(time.perf_counter() - t, 2)
        destino = saida / str(ano) / f"{slug}.jsonl"
        destino.parent.mkdir(parents=True, exist_ok=True)
        with destino.open("w", encoding="utf-8") as fh:
            for d in docs:
                fh.write(json.dumps(d, ensure_ascii=False) + "\n")
        relatorio.append(resumo)
        evento(LOG, "prova extraída", **{k: resumo[k] for k in ("pdf", "questoes", "validas", "com_gabarito", "segundos")})
    total = {"provas": len(relatorio), "questoes_validas": sum(r.get("validas", 0) for r in relatorio),
             "questoes_invalidas": sum(r.get("invalidas", 0) for r in relatorio),
             "falhas": sum(1 for r in relatorio if "erro" in r), "segundos": round(time.perf_counter() - t0, 1)}
    (saida / "relatorio_extracao.json").parent.mkdir(parents=True, exist_ok=True)
    nome_rel = ("relatorio_extracao_local.json" if args.local else
                "relatorio_extracao_parcial.json" if args.cursos else "relatorio_extracao.json")
    (saida / nome_rel).write_text(json.dumps({"total": total, "provas": relatorio}, ensure_ascii=False, indent=1),
                                  encoding="utf-8")
    evento(LOG, "extração concluída", **total)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
