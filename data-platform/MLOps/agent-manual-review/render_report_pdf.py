#!/usr/bin/env python3
"""Renderiza em PDF o relatório JSON consolidado pelo agente."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from dotenv import dotenv_values
from jinja2 import Environment, FileSystemLoader, StrictUndefined, TemplateError

from script_logging import configure_script_logging


class ReportRenderingError(RuntimeError):
    """Indica que o contrato de renderização do relatório não foi atendido."""


logger = logging.getLogger(Path(__file__).stem)

SCRIPT_DIRECTORY = Path(__file__).resolve().parent
SCRIPT_ENV_PATH = SCRIPT_DIRECTORY / ".env"
AGENT_REPORT_INPUT_FILE_NAME = "sample_agent_report.json"
AGENT_REPORT_INPUT_PATH = SCRIPT_DIRECTORY / AGENT_REPORT_INPUT_FILE_NAME
FINAL_PDF_OUTPUT_FILE_NAME = "sample_credit_review_report_v4.pdf"
FINAL_PDF_OUTPUT_PATH = SCRIPT_DIRECTORY / FINAL_PDF_OUTPUT_FILE_NAME


def load_json_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ReportRenderingError(f"Não foi possível ler {path}: {error}") from error
    if not isinstance(value, dict):
        raise ReportRenderingError(f"{path} deve conter um objeto JSON.")
    return value


def load_report_template_name(env_path: Path) -> str:
    if not env_path.is_file():
        raise ReportRenderingError(
            f"O arquivo de configuração do renderizador não existe: {env_path}"
        )
    try:
        values = dotenv_values(
            dotenv_path=env_path,
            encoding="utf-8",
            interpolate=False,
        )
    except OSError as error:
        raise ReportRenderingError(
            f"Não foi possível ler o arquivo de configuração {env_path}: {error}"
        ) from error

    configured_name = values.get("REPORT_TEMPLATE")
    if not isinstance(configured_name, str) or not configured_name.strip():
        raise ReportRenderingError(
            f"REPORT_TEMPLATE não está definida no arquivo {env_path}."
        )

    template_name = configured_name.strip()
    if (
        template_name in {".", ".."}
        or "/" in template_name
        or "\\" in template_name
        or Path(template_name).is_absolute()
    ):
        raise ReportRenderingError(
            "REPORT_TEMPLATE deve conter somente o nome de arquivo do template."
        )
    return template_name


def resolve_template_path(template_directory: Path, template_name: str) -> Path:
    template_path = template_directory / template_name
    if not template_path.is_file():
        raise ReportRenderingError(
            f"O template configurado não existe: {template_path}"
        )
    return template_path


def render_html(report: dict[str, Any], template_path: Path) -> str:
    environment = Environment(
        loader=FileSystemLoader(str(template_path.parent)),
        autoescape=True,
        undefined=StrictUndefined,
    )
    try:
        template = environment.get_template(template_path.name)
        return template.render(report=report)
    except (OSError, TemplateError) as error:
        raise ReportRenderingError(
            f"Não foi possível renderizar o template {template_path}: {error}"
        ) from error


def convert_html_to_pdf(html: str, base_url: Path) -> bytes:
    """Converte o HTML renderizado em PDF usando WeasyPrint."""
    try:
        from weasyprint import HTML
    except ImportError as error:
        raise ReportRenderingError(
            "WeasyPrint não está instalado. Instale agent-requirements.txt."
        ) from error

    try:
        pdf = HTML(string=html, base_url=str(base_url)).write_pdf()
    except (OSError, TypeError, ValueError) as error:
        raise ReportRenderingError(
            f"O renderizador não conseguiu gerar o PDF: {error}"
        ) from error
    if not isinstance(pdf, bytes):
        raise ReportRenderingError(
            "O renderizador não devolveu o conteúdo binário do PDF."
        )
    return pdf


def write_pdf_exclusive(output_path: Path, pdf: bytes) -> None:
    try:
        with output_path.open("xb") as output:
            output.write(pdf)
    except FileExistsError as error:
        raise ReportRenderingError(
            f"O arquivo de saída já existe e não será sobrescrito: {output_path}"
        ) from error
    except OSError as error:
        raise ReportRenderingError(
            f"Não foi possível gravar o PDF em {output_path}: {error}"
        ) from error


def render_report_pdf(
    report: dict[str, Any],
    *,
    template_path: Path,
    output_path: Path,
) -> None:
    if output_path.exists():
        raise ReportRenderingError(
            f"O arquivo de saída já existe e não será sobrescrito: {output_path}"
        )

    html = render_html(report, template_path)
    pdf = convert_html_to_pdf(html, template_path.parent)
    if not pdf.startswith(b"%PDF-"):
        raise ReportRenderingError(
            "O renderizador não devolveu um documento PDF válido."
        )
    write_pdf_exclusive(output_path, pdf)


def generate_pdf_file(
    report_path: Path,
    env_path: Path,
    template_directory: Path,
    output_path: Path,
) -> None:
    """Carrega o relatório e a configuração e gera o PDF final."""
    if output_path.exists():
        raise ReportRenderingError(
            f"O arquivo de saída já existe e não será sobrescrito: {output_path}"
        )

    logger.info(
        "Renderizando relatório: report=%s, config=%s.",
        report_path,
        env_path,
    )
    template_name = load_report_template_name(env_path)
    template_path = resolve_template_path(template_directory, template_name)
    report = load_json_object(report_path)
    render_report_pdf(
        report,
        template_path=template_path,
        output_path=output_path,
    )
    logger.info(
        "PDF salvo em %s usando o template %s.",
        output_path,
        template_name,
    )


def main() -> None:
    configure_script_logging(logger, __file__)
    try:
        generate_pdf_file(
            AGENT_REPORT_INPUT_PATH,
            SCRIPT_ENV_PATH,
            SCRIPT_DIRECTORY,
            FINAL_PDF_OUTPUT_PATH,
        )
    except ReportRenderingError as error:
        logger.error("Falha na geração do PDF: %s", error)
        raise SystemExit(1) from error
    except Exception as error:
        logger.exception("Falha inesperada na geração do PDF: %s", error)
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()
