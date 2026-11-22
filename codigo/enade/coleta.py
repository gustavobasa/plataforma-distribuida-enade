"""RF01 — Coleta das provas e gabaritos oficiais do ENADE no portal do INEP.

Fonte: https://www.gov.br/inep/pt-br/areas-de-atuacao/avaliacao-e-exames-educacionais/enade/provas-e-gabaritos/{ano}
Cada página anual lista links para download.inep.gov.br. O coletor:
  * descobre os links .pdf da página do ano (não inventa URLs);
  * classifica em prova (PV), gabarito (GB) e padrão de resposta (PR);
  * descarta versões acessíveis duplicadas (ampliada, super ampliada, ledor, libras, braille);
  * baixa sequencialmente, registra URL, tamanho, SHA-256 e data em um manifesto JSON.

Uso: python -m enade.coleta --anos 2021 2022 2023 [--cursos engenharia_da_computacao ...] [--limite N]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import tempfile
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

import certifi
import requests

from .config import CFG
from .logs import evento, obter_logger

LOG = obter_logger("coleta")
PAGINA_ANO = "https://www.gov.br/inep/pt-br/areas-de-atuacao/avaliacao-e-exames-educacionais/enade/provas-e-gabaritos/{ano}"
USER_AGENT = "Mozilla/5.0 (compatible; enade-busca-academico/1.0)"
VARIANTES_DESCARTADAS = ("ampliada", "ledor", "libras", "braille", "super_ampliada", "_lp", "_video")
CERTS_EXTRAS = Path(__file__).resolve().parent.parent / "certs"
RE_HREF = re.compile(r'href="(https?://download\.inep\.gov\.br/[^"]+\.pdf)"', re.IGNORECASE)
RE_ARQ = re.compile(r"^(?P<ano>\d{4})_(?P<tipo>PV|GB)_(?P<curso>.+)\.pdf$", re.IGNORECASE)
RE_PR = re.compile(r"^(?P<ano>\d{4})_(?P<curso>.+)\.pdf$", re.IGNORECASE)


@dataclass
class ItemAcervo:
    ano: int
    curso_slug: str
    tipo: str  # PV | GB | PR
    url: str
    arquivo: str
    tamanho: int | None = None
    sha256: str | None = None
    http_status: int | None = None
    baixado_em: str | None = None


def bundle_ca() -> str:
    """download.inep.gov.br envia apenas o certificado folha (cadeia incompleta). Em vez de desativar a
    verificação TLS, acrescentamos a CA intermediária pública (RNP ICPEdu GR46 OV TLS CA 2025, emitida pela
    GlobalSign Root R46, obtida da URL AIA do próprio certificado) ao bundle do certifi."""
    destino = Path(tempfile.gettempdir()) / "enade-ca-bundle.pem"
    partes = [Path(certifi.where()).read_text(encoding="ascii")]
    partes += [c.read_text(encoding="ascii") for c in sorted(CERTS_EXTRAS.glob("*.pem"))]
    destino.write_text("\n".join(partes), encoding="ascii")
    return str(destino)


def descobrir(ano: int, sessao: requests.Session) -> list[ItemAcervo]:
    url = PAGINA_ANO.format(ano=ano)
    resp = sessao.get(url, timeout=60)
    resp.raise_for_status()
    itens: dict[tuple[str, str], ItemAcervo] = {}
    # Ordem do documento preservada: na página, cada linha de curso traz prova, variantes, gabarito e padrão
    # de resposta. Em 2022 o nome do gabarito difere do da prova (ex.: "tecnologia_em_design_de_moda" x
    # "tecnologia_design_moda"); nesses casos o gabarito é pareado com a última prova listada antes dele.
    links = list(dict.fromkeys(l.replace("http://", "https://", 1) for l in RE_HREF.findall(resp.text)))
    provas = {m["curso"].lower() for l in links if (m := RE_ARQ.match(l.rsplit("/", 1)[-1]))
              and m["tipo"].upper() == "PV" and not any(v in l.lower() for v in VARIANTES_DESCARTADAS)}
    ultima_prova = None
    for link in links:
        nome = link.rsplit("/", 1)[-1]
        baixo = nome.lower()
        m = RE_ARQ.match(nome)
        if m and int(m["ano"]) == ano and m["tipo"].upper() == "PV" and any(v in baixo for v in VARIANTES_DESCARTADAS):
            continue
        if any(v in baixo for v in VARIANTES_DESCARTADAS):
            continue
        if m and int(m["ano"]) == ano:
            tipo, curso = m["tipo"].upper(), m["curso"].lower()
        elif "/padrao_resposta/" in link and (m2 := RE_PR.match(nome)) and int(m2["ano"]) == ano:
            tipo, curso = "PR", m2["curso"].lower()
        else:
            continue
        if tipo == "PV":
            ultima_prova = curso
        elif curso not in provas and ultima_prova:
            evento(LOG, "arquivo pareado pela ordem da página", arquivo=nome, curso=ultima_prova)
            curso = ultima_prova
        itens.setdefault((tipo, curso), ItemAcervo(ano=ano, curso_slug=curso, tipo=tipo, url=link,
                                                   arquivo=f"{ano}/{nome}"))
    evento(LOG, "links descobertos", ano=ano, pagina=url, total=len(itens),
           provas=sum(1 for i in itens.values() if i.tipo == "PV"),
           gabaritos=sum(1 for i in itens.values() if i.tipo == "GB"))
    return list(itens.values())


def baixar(item: ItemAcervo, destino: Path, sessao: requests.Session) -> ItemAcervo:
    caminho = destino / item.arquivo
    caminho.parent.mkdir(parents=True, exist_ok=True)
    if caminho.exists() and caminho.stat().st_size > 0:
        dados = caminho.read_bytes()
        item.http_status = None
    else:
        for tentativa in range(1, 5):
            try:
                resp = sessao.get(item.url, timeout=180)
                break
            except requests.ConnectionError:
                if tentativa == 4:
                    raise
                time.sleep(3 * tentativa)  # o servidor do INEP às vezes fecha conexões sob carga
        item.http_status = resp.status_code
        resp.raise_for_status()
        if not resp.content.startswith(b"%PDF"):
            raise ValueError(f"conteúdo não é PDF: {item.url}")
        dados = resp.content
        tmp = caminho.with_suffix(".part")
        tmp.write_bytes(dados)
        tmp.replace(caminho)
        time.sleep(0.5)  # cortesia com o servidor do INEP
    item.tamanho = len(dados)
    item.sha256 = hashlib.sha256(dados).hexdigest()
    item.baixado_em = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return item


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--anos", type=int, nargs="+", default=[2021, 2022, 2023])
    ap.add_argument("--cursos", nargs="*", help="slugs de curso (padrão: todos)")
    ap.add_argument("--limite", type=int, default=0, help="máximo de cursos por ano (0 = todos)")
    ap.add_argument("--destino", default=str(Path(CFG.dados_dir) / "pdfs"))
    args = ap.parse_args(argv)

    destino = Path(args.destino)
    sessao = requests.Session()
    sessao.headers["User-Agent"] = USER_AGENT
    sessao.verify = bundle_ca()
    manifesto_path = destino / "manifesto.json"
    manifesto: dict[str, dict] = {}
    if manifesto_path.exists():
        manifesto = {m["arquivo"]: m for m in json.loads(manifesto_path.read_text(encoding="utf-8"))}

    falhas = 0
    for ano in args.anos:
        itens = descobrir(ano, sessao)
        cursos = sorted({i.curso_slug for i in itens if i.tipo == "PV"})
        if args.cursos:
            cursos = [c for c in cursos if c in set(args.cursos)]
        if args.limite:
            cursos = cursos[: args.limite]
        for item in itens:
            if item.curso_slug not in cursos:
                continue
            try:
                baixar(item, destino, sessao)
                manifesto[item.arquivo] = asdict(item)
                evento(LOG, "arquivo ok", arquivo=item.arquivo, bytes=item.tamanho, sha256=item.sha256[:12])
            except Exception as exc:  # registra e segue: um PDF indisponível não deve parar a coleta
                falhas += 1
                evento(LOG, "falha no download", nivel=40, url=item.url, erro=str(exc))
        manifesto_path.parent.mkdir(parents=True, exist_ok=True)
        manifesto_path.write_text(json.dumps(sorted(manifesto.values(), key=lambda m: m["arquivo"]),
                                             ensure_ascii=False, indent=1), encoding="utf-8")
    evento(LOG, "coleta concluída", arquivos=len(manifesto), falhas=falhas)
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main())
