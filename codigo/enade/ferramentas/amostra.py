"""RNF03 — Sorteio reprodutível da amostra de validação manual da extração.

Amostragem estratificada por (ano, componente, tipo de questão) com semente fixa, proporcional ao tamanho
de cada estrato e com pelo menos 1 questão por estrato. Grava /dados/validacao/amostra.json.

Uso: python -m enade.ferramentas.amostra --n 60 --semente 2026
"""
from __future__ import annotations

import argparse
import json
import random
from collections import defaultdict
from pathlib import Path

from ..config import CFG


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=60)
    ap.add_argument("--semente", type=int, default=2026)
    a = ap.parse_args(argv)
    base = Path(CFG.dados_dir)
    estratos: dict[tuple, list[str]] = defaultdict(list)
    for arq in sorted((base / "extraidos").glob("*/*.jsonl")):
        for linha in arq.read_text(encoding="utf-8").splitlines():
            d = json.loads(linha)
            estratos[(d["ano"], d["componente"], d["tipo_questao"])].append(d["id"])
    total = sum(len(v) for v in estratos.values())
    rng = random.Random(a.semente)
    escolhidos = []
    for chave in sorted(estratos):
        ids = sorted(estratos[chave])
        k = max(1, round(a.n * len(ids) / total))
        escolhidos += [{"id": i, "estrato": list(chave)} for i in rng.sample(ids, min(k, len(ids)))]
    rng.shuffle(escolhidos)
    saida = base / "validacao" / "amostra.json"
    saida.parent.mkdir(parents=True, exist_ok=True)
    saida.write_text(json.dumps({"semente": a.semente, "n_solicitado": a.n, "populacao": total,
                                 "estratos": {"|".join(map(str, k)): len(v) for k, v in sorted(estratos.items())},
                                 "itens": escolhidos}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"amostra com {len(escolhidos)} questões de {total} gravada em {saida}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
