"""RF04 — Conversão das figuras recortadas (diagramas, gráficos, tabelas e fórmulas em imagem) com LLM multimodal.

Cada figura recortada do PDF oficial é enviada ao Claude (Messages API, via Batches = 50% do preço) com um
trecho do enunciado como contexto. A resposta segue um esquema JSON fixo (structured outputs):
  * diagrama (fluxograma, grafo, árvore, estados, sequência, ER, organograma, mapa conceitual) -> Mermaid
  * gráfico                -> tabela Markdown com os valores legíveis
  * tabela em imagem       -> tabela Markdown
  * fórmula em imagem      -> LaTeX
  * circuito, foto, mapa…  -> descrição textual em Markdown (não há representação Mermaid fiel)
Validação: todo código Mermaid é compilado com o mermaid-cli 10.9.1 (mesma versão da interface web); o que não
compila é descartado e sinalizado (``mermaid_invalido``). A correção semântica é medida na validação manual.
Custos e tokens de cada lote ficam em /dados/llm/relatorio.json.

Uso (contêiner ingestor, com ANTHROPIC_API_KEY no .env):
  python -m enade.extracao.figuras_llm enviar [--limite N] [--semente S] [--modelo claude-opus-5-5]
  python -m enade.extracao.figuras_llm coletar --lote <id>
  python -m enade.extracao.figuras_llm exportar-mermaid      # gera .mmd para o validador
  python -m enade.extracao.figuras_llm aplicar               # incorpora ao JSONL (depois: enade.produtor)
  python -m enade.extracao.figuras_llm relatorio
"""
from __future__ import annotations

import argparse
import base64
import json
import random
import time
from datetime import datetime, timezone
from pathlib import Path

import pymupdf

from ..config import CFG

BASE = Path(CFG.dados_dir)
DIR_LLM = BASE / "llm"
RESULTADOS = DIR_LLM / "resultados.jsonl"
VALIDACAO = DIR_LLM / "mmd" / "validacao.txt"
MODELO_PADRAO = "claude-opus-5-5"
# US$ por milhão de tokens (preço padrão da API; o Batches cobra 50%). Fonte: tabela de modelos da Anthropic.
PRECOS = {"claude-opus-5-5": (4.00, 20.00), "claude-sonnet-5-5": (2.00, 10.00), "claude-haiku-5-5": (0.10, 0.50)}
DESCONTO_BATCH = 0.5

CLASSES = ["diagrama", "grafico", "tabela", "formula", "circuito_esquema", "foto_ilustracao", "mapa", "outro"]
ESQUEMA = {
    "type": "object",
    "properties": {
        "classe": {"type": "string", "enum": CLASSES},
        "legivel": {"type": "boolean"},
        "mermaid": {"type": "string"},
        "markdown": {"type": "string"},
        "latex": {"type": "string"},
        "observacao": {"type": "string"},
    },
    "required": ["classe", "legivel", "mermaid", "markdown", "latex", "observacao"],
    "additionalProperties": False,
}
SISTEMA = """Você converte figuras de provas do ENADE (exame brasileiro) em representações textuais fiéis.
Você recebe UMA figura recortada do PDF oficial e, como contexto, o início do enunciado da questão.

Classifique a figura e preencha os campos:
- classe "diagrama" (fluxograma, grafo, árvore, máquina de estados, diagrama de sequência, de classes ou entidade-
  relacionamento, organograma, mapa conceitual, linha do tempo): escreva em "mermaid" um código Mermaid 10.9 que
  reproduza nós, rótulos e ligações da figura. Use apenas sintaxe válida (ex.: `flowchart TD`, `graph LR`,
  `stateDiagram-v2`, `sequenceDiagram`, `classDiagram`, `erDiagram`, `timeline`); coloque rótulos entre aspas
  duplas quando tiverem espaços, acentos ou símbolos. Em "markdown", uma frase descrevendo o diagrama.
- classe "grafico": em "markdown", uma tabela Markdown com os valores que estão legíveis (eixos, séries,
  unidades) e uma frase sobre o tipo de gráfico. "mermaid" vazio.
- classe "tabela": em "markdown", a tabela em Markdown, célula a célula.
- classe "formula": em "latex", a fórmula em LaTeX (sem delimitadores $); em "markdown", uma frase.
- demais classes (circuito/esquema técnico, foto, ilustração, charge, mapa, outro): em "markdown", uma descrição
  objetiva de até 120 palavras com todos os textos, números e rótulos visíveis. "mermaid" vazio.
Regras: transcreva apenas o que está na imagem; não invente rótulos, valores nem ligações; não resolva a questão.
Se algo estiver ilegível, escreva [ilegível] no lugar e use "legivel": false quando a figura não puder ser
convertida com fidelidade. Campos que não se aplicam ficam como string vazia. "observacao": dúvidas, ou vazio."""


def _cliente():
    import anthropic

    return anthropic.Anthropic()  # credencial do ambiente (ANTHROPIC_API_KEY); nunca gravada no código


def _figuras(limite: int, semente: int, ja_feitas: set[str]) -> list[dict]:
    itens = []
    for arq in sorted((BASE / "extraidos").glob("*/*.jsonl")):
        for linha in arq.read_text(encoding="utf-8").splitlines():
            d = json.loads(linha)
            for f in d["midia"]["figuras"]:
                if f.get("arquivo") and f["arquivo"] not in ja_feitas:
                    itens.append({"figura": f, "doc": {k: d[k] for k in ("id", "ano", "enunciado", "texto_base")},
                                  "pdf": d["origem"]["pdf"], "estrato": (d["ano"], f["tipo"])})
    if limite and limite < len(itens):  # amostra estratificada (ano x tipo de figura), reprodutível
        rng = random.Random(semente)
        por_estrato: dict = {}
        for it in itens:
            por_estrato.setdefault(it["estrato"], []).append(it)
        escolhidos = []
        for chave in sorted(por_estrato):
            grupo = por_estrato[chave]
            k = max(1, round(limite * len(grupo) / len(itens)))
            escolhidos += rng.sample(grupo, min(k, len(grupo)))
        itens = escolhidos[:limite]
    return itens


def _imagem(item: dict, dpi: int = 150) -> str:
    """Re-renderiza o recorte a partir do PDF oficial em resolução maior que a da interface (legibilidade)."""
    f = item["figura"]
    with pymupdf.open(str(BASE / "pdfs" / str(item["doc"]["ano"]) / item["pdf"])) as doc:
        pg = doc[f["pagina"] - 1]
        clip = pymupdf.Rect(f["bbox"]) + (-4, -4, 4, 4)
        png = pg.get_pixmap(clip=clip & pg.rect, dpi=dpi).tobytes("png")
    return base64.standard_b64encode(png).decode("ascii")


def _custom_id(arquivo: str) -> str:
    return arquivo.replace("/", "_").removesuffix(".png")  # custom_id aceita [a-zA-Z0-9_-]


def _params(item: dict, modelo: str, esforco: str) -> dict:
    contexto = (item["doc"]["texto_base"][-400:] + "\n" + item["doc"]["enunciado"][:500]).strip()
    return {
        "model": modelo,
        "max_tokens": 8000,
        "system": SISTEMA,
        "output_config": {"effort": esforco, "format": {"type": "json_schema", "schema": ESQUEMA}},
        "messages": [{"role": "user", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": _imagem(item)}},
            {"type": "text", "text": f"Contexto (início do enunciado, apenas para referência):\n{contexto}"},
        ]}],
    }


def _feitas() -> set[str]:
    if not RESULTADOS.exists():
        return set()
    return {json.loads(l)["arquivo"] for l in RESULTADOS.read_text(encoding="utf-8").splitlines() if l.strip()}


def enviar(limite: int, semente: int, modelo: str, esforco: str) -> str:
    from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
    from anthropic.types.messages.batch_create_params import Request

    itens = _figuras(limite, semente, _feitas())
    if not itens:
        print("nenhuma figura pendente")
        return ""
    reqs = [Request(custom_id=_custom_id(it["figura"]["arquivo"]),
                    params=MessageCreateParamsNonStreaming(**_params(it, modelo, esforco))) for it in itens]
    lote = _cliente().messages.batches.create(requests=reqs)
    DIR_LLM.joinpath("lotes").mkdir(parents=True, exist_ok=True)
    (DIR_LLM / "lotes" / f"{lote.id}.json").write_text(json.dumps({
        "lote": lote.id, "modelo": modelo, "esforco": esforco, "criado_em": datetime.now(timezone.utc).isoformat(),
        "limite": limite, "semente": semente,
        "figuras": {_custom_id(it["figura"]["arquivo"]): it["figura"]["arquivo"] for it in itens}}, indent=1),
        encoding="utf-8")
    print(f"lote {lote.id} criado com {len(reqs)} figuras ({modelo}, effort={esforco})")
    return lote.id


def coletar(lote_id: str, intervalo: int = 30) -> None:
    cli = _cliente()
    meta = json.loads((DIR_LLM / "lotes" / f"{lote_id}.json").read_text(encoding="utf-8"))
    while True:
        lote = cli.messages.batches.retrieve(lote_id)
        if lote.processing_status == "ended":
            break
        print(f"status={lote.processing_status} processando={lote.request_counts.processing}", flush=True)
        time.sleep(intervalo)
    novos = 0
    with RESULTADOS.open("a", encoding="utf-8") as fh:
        for r in cli.messages.batches.results(lote_id):
            arquivo = meta["figuras"].get(r.custom_id)
            reg = {"arquivo": arquivo, "lote": lote_id, "modelo": meta["modelo"], "tipo_resultado": r.result.type}
            if r.result.type == "succeeded":
                msg = r.result.message
                reg["stop_reason"] = msg.stop_reason
                reg["uso"] = {"entrada": msg.usage.input_tokens, "saida": msg.usage.output_tokens}
                if msg.stop_reason == "refusal":
                    reg["erro"] = "recusa"
                else:
                    texto = next((b.text for b in msg.content if b.type == "text"), "")
                    try:
                        reg["conversao"] = json.loads(texto)
                    except json.JSONDecodeError as exc:  # max_tokens etc.: registrado como falha, não descartado
                        reg["erro"] = f"json_invalido: {exc}"
            elif r.result.type == "errored":
                reg["erro"] = r.result.error.type
            fh.write(json.dumps(reg, ensure_ascii=False) + "\n")
            novos += 1
    print(f"{novos} resultados gravados em {RESULTADOS}")


def _resultados() -> dict[str, dict]:
    if not RESULTADOS.exists():
        return {}
    out = {}
    for l in RESULTADOS.read_text(encoding="utf-8").splitlines():
        if l.strip():
            r = json.loads(l)
            if "conversao" in r or r["arquivo"] not in out:
                out[r["arquivo"]] = r  # o último resultado bem-sucedido prevalece
    return out


def exportar_mermaid() -> int:
    destino = DIR_LLM / "mmd"
    destino.mkdir(parents=True, exist_ok=True)
    n = 0
    for arquivo, r in _resultados().items():
        codigo = (r.get("conversao") or {}).get("mermaid", "").strip()
        if codigo:
            (destino / f"{_custom_id(arquivo)}.mmd").write_text(codigo + "\n", encoding="utf-8")
            n += 1
    print(f"{n} diagramas Mermaid exportados para {destino}")
    return n


def _validos() -> dict[str, bool]:
    if not VALIDACAO.exists():
        return {}
    out = {}
    for l in VALIDACAO.read_text(encoding="utf-8").splitlines():
        if " " in l:
            status, nome = l.split(" ", 1)
            out[nome.strip().removesuffix(".mmd")] = status == "OK"
    return out


def aplicar_no_documento(doc: dict, resultados: dict[str, dict], validos: dict[str, bool]) -> bool:
    """Incorpora as conversões às figuras do documento. Retorna True se algo mudou."""
    midia = doc["midia"]
    mudou, mermaids, textos = False, [], []
    for f in midia["figuras"]:
        r = resultados.get(f.get("arquivo") or "")
        c = (r or {}).get("conversao")
        if not c:
            continue
        mmd = c["mermaid"].strip()
        mmd_ok = bool(mmd) and validos.get(_custom_id(f["arquivo"]), False)
        f.update({"classe_llm": c["classe"], "descricao_md": c["markdown"].strip(),
                  "latex": c["latex"].strip(), "mermaid": mmd if mmd_ok else "",
                  "legivel": c["legivel"], "modelo_llm": r["modelo"]})
        if mmd and not mmd_ok and "mermaid_invalido" not in doc["extracao"]["alertas"]:
            doc["extracao"]["alertas"].append("mermaid_invalido")
        if mmd_ok:
            mermaids.append(mmd)
        textos.append(c["markdown"].strip())
        mudou = True
    if mudou:
        midia["mermaid"] = mermaids
        midia["descricao_figuras"] = "\n\n".join(t for t in textos if t)
        convertidas = sum(1 for f in midia["figuras"] if f.get("classe_llm"))
        midia["pendencias"] = [p for p in midia["pendencias"] if "Mermaid" not in p]
        if convertidas < len([f for f in midia["figuras"] if f.get("arquivo")]):
            midia["pendencias"].append("há figuras ainda não convertidas pelo LLM")
    return mudou


def aplicar() -> None:
    from ..esquema import validar

    resultados, validos = _resultados(), _validos()
    total = alterados = invalidos = 0
    for arq in sorted((BASE / "extraidos").glob("*/*.jsonl")):
        linhas = []
        for linha in arq.read_text(encoding="utf-8").splitlines():
            d = json.loads(linha)
            total += 1
            if aplicar_no_documento(d, resultados, validos):
                alterados += 1
                if validar(d)[0] is None:
                    invalidos += 1
            linhas.append(json.dumps(d, ensure_ascii=False))
        arq.write_text("\n".join(linhas) + "\n", encoding="utf-8")
    print(f"documentos: {total}; com figuras convertidas: {alterados}; inválidos após aplicar: {invalidos}")


def relatorio() -> dict:
    res = [json.loads(l) for l in RESULTADOS.read_text(encoding="utf-8").splitlines() if l.strip()] \
        if RESULTADOS.exists() else []
    validos = _validos()
    por_classe: dict[str, int] = {}
    custo = entrada = saida = 0.0
    for r in res:
        if r.get("uso"):
            pe, ps = PRECOS.get(r["modelo"], (0, 0))
            entrada += r["uso"]["entrada"]
            saida += r["uso"]["saida"]
            custo += DESCONTO_BATCH * (r["uso"]["entrada"] * pe + r["uso"]["saida"] * ps) / 1e6
        c = r.get("conversao")
        if c:
            por_classe[c["classe"]] = por_classe.get(c["classe"], 0) + 1
    com_mmd = [r for r in res if (r.get("conversao") or {}).get("mermaid", "").strip()]
    ok = sum(1 for r in com_mmd if validos.get(_custom_id(r["arquivo"])))
    rel = {
        "figuras_processadas": len(res),
        "falhas_api_ou_json": sum(1 for r in res if "erro" in r),
        "recusas": sum(1 for r in res if r.get("erro") == "recusa"),
        "ilegiveis": sum(1 for r in res if (r.get("conversao") or {}).get("legivel") is False),
        "por_classe": por_classe,
        "mermaid_gerados": len(com_mmd), "mermaid_validos": ok,
        "taxa_erro_sintaxe_mermaid": round(1 - ok / len(com_mmd), 4) if com_mmd else None,
        "tokens_entrada": int(entrada), "tokens_saida": int(saida),
        "custo_estimado_usd": round(custo, 4),
        "modelos": sorted({r["modelo"] for r in res}),
        "nota": "custo = tokens x preço de tabela x 0,5 (Batches); confira a fatura no Console da Anthropic",
    }
    DIR_LLM.mkdir(parents=True, exist_ok=True)
    (DIR_LLM / "relatorio.json").write_text(json.dumps(rel, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(rel, ensure_ascii=False, indent=1))
    return rel


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("enviar")
    e.add_argument("--limite", type=int, default=0, help="0 = todas as figuras pendentes")
    e.add_argument("--semente", type=int, default=2026)
    e.add_argument("--modelo", default=MODELO_PADRAO)
    e.add_argument("--esforco", default="medium", choices=["low", "medium", "high"])
    c = sub.add_parser("coletar")
    c.add_argument("--lote", required=True)
    sub.add_parser("exportar-mermaid")
    sub.add_parser("aplicar")
    sub.add_parser("relatorio")
    a = ap.parse_args(argv)
    if a.cmd == "enviar":
        enviar(a.limite, a.semente, a.modelo, a.esforco)
    elif a.cmd == "coletar":
        coletar(a.lote)
    elif a.cmd == "exportar-mermaid":
        exportar_mermaid()
    elif a.cmd == "aplicar":
        aplicar()
    else:
        relatorio()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
