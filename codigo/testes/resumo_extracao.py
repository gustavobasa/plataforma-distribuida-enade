"""Resumo quantitativo do acervo extraído (volume, qualidade estrutural). Uso: python testes/resumo_extracao.py"""
import collections
import glob
import json

r = json.load(open("/dados/extraidos/relatorio_extracao.json", encoding="utf-8"))
print("TOTAL", r["total"])
conf, alertas, anos, comp, area = (collections.Counter() for _ in range(5))
figs = forms = tabs = semgab = alts4 = 0
for f in glob.glob("/dados/extraidos/*/*.jsonl"):
    for l in open(f, encoding="utf-8"):
        d = json.loads(l)
        conf[d["extracao"]["confianca"]] += 1
        anos[(d["ano"], d["tipo_questao"])] += 1
        comp[d["componente"]] += 1
        area[d["area"]] += 1
        for a in d["extracao"]["alertas"]:
            alertas[a] += 1
        figs += bool(d["midia"]["figuras"]); forms += d["midia"]["tem_formula"]; tabs += bool(d["midia"]["tabelas_md"])
        semgab += d["gabarito_status"] == "indisponivel"
print("provas por ano", collections.Counter(p["ano"] for p in r["provas"]))
print("confianca", dict(conf)); print("alertas", dict(alertas))
print("ano/tipo", sorted(anos.items())); print("componente", dict(comp)); print("area", dict(area))
print("questoes com figura", figs, "| com formula LaTeX", forms, "| com tabela Markdown", tabs)
print("anuladas", sum(p.get("anuladas", 0) for p in r["provas"]), "| objetivas sem gabarito", semgab)
