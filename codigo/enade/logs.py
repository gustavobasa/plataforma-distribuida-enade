"""Logs estruturados em JSON (uma linha por evento) para stdout — coletados por `docker compose logs`."""
from __future__ import annotations

import json
import logging
import sys
import time


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        dados = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created)) + f".{int(record.msecs):03d}Z",
            "nivel": record.levelname,
            "servico": record.name,
            "msg": record.getMessage(),
        }
        extra = getattr(record, "dados", None)
        if isinstance(extra, dict):
            dados.update(extra)
        if record.exc_info:
            dados["erro"] = self.formatException(record.exc_info)
        return json.dumps(dados, ensure_ascii=False, default=str)


def obter_logger(nome: str) -> logging.Logger:
    logger = logging.getLogger(nome)
    if not logger.handlers:
        h = logging.StreamHandler(sys.stdout)
        h.setFormatter(_JsonFormatter())
        logger.addHandler(h)
        logger.setLevel(logging.INFO)
        logger.propagate = False
    return logger


def evento(logger: logging.Logger, msg: str, nivel: int = logging.INFO, **dados) -> None:
    logger.log(nivel, msg, extra={"dados": dados})
