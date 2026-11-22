#!/bin/sh
# Compila o relatório SBC em um contêiner TeX Live (não exige LaTeX instalado no host).
# Uso (raiz do repositório): docker run --rm -v "$PWD/relatorio:/r" -w /r texlive/texlive:latest-small sh compilar.sh
set -e
tlmgr install pgfplots babel-portuges titlesec caption booktabs tabularx times courier helvetic psnfss etoolbox >/dev/null 2>&1 || true
pdflatex -interaction=nonstopmode -halt-on-error relatorio.tex >/dev/null
bibtex relatorio >/dev/null || true
pdflatex -interaction=nonstopmode -halt-on-error relatorio.tex >/dev/null
pdflatex -interaction=nonstopmode -halt-on-error relatorio.tex | grep -E "Output written|Warning: (Citation|Reference)" || true
