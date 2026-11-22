"""RF21 — Exportação da lista de questões (simulado) em JSON ou PDF.

O PDF é gerado com ReportLab: capa, questões (texto-base, enunciado, alternativas, figuras recortadas
do PDF original, origem PDF/página) e, ao final, a folha de respostas (gabarito) — apenas para Professor.
Limitação: fórmulas aparecem em notação LaTeX textual ($...$); a interface web é que as renderiza (KaTeX).
"""
from __future__ import annotations

import io
import re
from datetime import datetime, timezone
from html import escape
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Image, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from ..config import CFG

DIR_FIGURAS = Path(CFG.dados_dir) / "figuras"


def _p(texto: str) -> str:
    """Texto plano -> parágrafo ReportLab seguro (escapa HTML, preserva quebras)."""
    return escape(texto or "").replace("\n", "<br/>")


def _md_tabela_para_linhas(md: str) -> list[list[str]]:
    linhas = [l.strip() for l in md.strip().splitlines() if l.strip().startswith("|")]
    out = []
    for l in linhas:
        if re.fullmatch(r"\|[\s:|-]+\|?", l):
            continue
        out.append([c.strip().replace("<br>", " ") for c in l.strip("|").split("|")])
    return out


def gerar_pdf(questoes: list[dict], usuario: str, incluir_gabarito: bool) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=2 * cm, rightMargin=2 * cm, topMargin=1.8 * cm,
                            bottomMargin=1.8 * cm, title="Simulado ENADE", author=usuario)
    ss = getSampleStyleSheet()
    corpo = ParagraphStyle("corpo", parent=ss["BodyText"], fontSize=10, leading=13.5)
    peq = ParagraphStyle("peq", parent=corpo, fontSize=8, textColor=colors.HexColor("#555555"))
    tit = ParagraphStyle("tit", parent=ss["Title"], alignment=TA_CENTER)
    h = ParagraphStyle("h", parent=ss["Heading3"], spaceBefore=10)
    el = [Paragraph("Simulado ENADE", tit),
          Paragraph(f"{len(questoes)} questões · gerado em {datetime.now(timezone.utc):%d/%m/%Y %H:%M} UTC "
                    f"por {escape(usuario)}", peq),
          Paragraph("Fonte: provas oficiais do INEP (download.inep.gov.br). Cada questão indica o PDF e a página "
                    "de origem.", peq), Spacer(1, 12)]
    for i, q in enumerate(questoes, 1):
        el.append(Paragraph(f"{i}. {escape(q.get('rotulo', ''))} — {escape(q.get('curso', ''))} ({q.get('ano')}) · "
                            f"{q.get('componente')} · {q.get('tipo_questao')}"
                            + (" · <b>ANULADA</b>" if q.get("anulada") else ""), h))
        if q.get("texto_base"):
            el.append(Paragraph(_p(q["texto_base"]), corpo))
            el.append(Spacer(1, 4))
        for f in (q.get("midia") or {}).get("figuras", []):
            arq = f.get("arquivo")
            caminho = DIR_FIGURAS / arq if arq else None
            if caminho and caminho.is_file():
                img = Image(str(caminho))
                escala = min(1.0, (15 * cm) / img.imageWidth, (9 * cm) / img.imageHeight)
                img.drawWidth, img.drawHeight = img.imageWidth * escala, img.imageHeight * escala
                el.append(img)
        for md in (q.get("midia") or {}).get("tabelas_md", []):
            dados = _md_tabela_para_linhas(md)
            if dados:
                t = Table([[Paragraph(_p(c), peq) for c in linha] for linha in dados], repeatRows=1)
                t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
                                       ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eeeeee"))]))
                el.append(t)
        el.append(Paragraph(_p(q.get("enunciado", "")), corpo))
        for a in q.get("alternativas", []):
            el.append(Paragraph(f"<b>{a['letra']})</b> {_p(a['texto'])}", corpo))
        orig = q.get("origem", {})
        el.append(Paragraph(f"Origem: {escape(orig.get('pdf', ''))}, página(s) "
                            f"{', '.join(str(p) for p in orig.get('paginas', []))}", peq))
        el.append(Spacer(1, 8))
    if incluir_gabarito:
        el += [PageBreak(), Paragraph("Gabarito (restrito ao perfil Professor)", tit)]
        linhas = [["#", "Questão", "Curso/Ano", "Resposta"]]
        for i, q in enumerate(questoes, 1):
            resp = "ANULADA" if q.get("anulada") else (q.get("gabarito") or
                                                        ("ver padrão de resposta" if q.get("tipo_questao") == "discursiva" else "—"))
            linhas.append([str(i), q.get("rotulo", ""), f"{q.get('curso', '')} ({q.get('ano')})", resp])
        t = Table(linhas, colWidths=[1 * cm, 4 * cm, 8 * cm, 3.5 * cm], repeatRows=1)
        t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.4, colors.grey), ("FONTSIZE", (0, 0), (-1, -1), 8),
                               ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eeeeee"))]))
        el.append(t)
        for i, q in enumerate(questoes, 1):
            if q.get("padrao_resposta"):
                el += [Paragraph(f"Padrão de resposta — item {i} ({escape(q.get('rotulo', ''))})", h),
                       Paragraph(_p(q["padrao_resposta"][:6000]), peq)]
    doc.build(el)
    return buf.getvalue()
