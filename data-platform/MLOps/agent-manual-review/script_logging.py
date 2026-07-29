"""Configuração comum de logging para os scripts do protótipo."""

from __future__ import annotations

import logging
from pathlib import Path
import sys


LOG_FORMAT = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"


def configure_script_logging(
    application_logger: logging.Logger,
    script_path: str | Path,
) -> Path:
    """Envia logs ao terminal e ao arquivo homônimo do script."""
    resolved_script_path = Path(script_path).resolve()
    log_path = resolved_script_path.with_suffix(".log")
    formatter = logging.Formatter(LOG_FORMAT)

    for handler in list(application_logger.handlers):
        application_logger.removeHandler(handler)
        handler.close()

    terminal_handler = logging.StreamHandler(sys.stdout)
    terminal_handler.setFormatter(formatter)

    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(formatter)

    application_logger.setLevel(logging.INFO)
    application_logger.propagate = False
    application_logger.addHandler(terminal_handler)
    application_logger.addHandler(file_handler)
    return log_path
