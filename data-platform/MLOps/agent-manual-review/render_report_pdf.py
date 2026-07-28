#!/usr/bin/env python3
"""Renderiza em PDF o relatório JSON consolidado pelo agente."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Protocol

from dotenv import dotenv_values
from jinja2 import Environment, FileSystemLoader, StrictUndefined, TemplateError


class ReportRenderingError(RuntimeError):
    """Indica que o contrato de renderização do relatório não foi atendido."""


class PdfRenderer(Protocol):
    """Fronteira do componente responsável por converter HTML em PDF."""

    def render(self, html: str, *, base_url: Path) -> bytes:
        """Converte HTML em um documento PDF."""


SCRIPT_DIRECTORY = Path(__file__).resolve().parent
SCRIPT_ENV_PATH = SCRIPT_DIRECTORY / ".env"


class WeasyPrintRenderer:
    """Converte HTML em PDF usando WeasyPrint."""

    def render(self, html: str, *, base_url: Path) -> bytes:
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
    renderer: PdfRenderer,
) -> None:
    if output_path.exists():
        raise ReportRenderingError(
            f"O arquivo de saída já existe e não será sobrescrito: {output_path}"
        )

    html = render_html(report, template_path)
    pdf = renderer.render(html, base_url=template_path.parent)
    if not pdf.startswith(b"%PDF-"):
        raise ReportRenderingError(
            "O renderizador não devolveu um documento PDF válido."
        )
    write_pdf_exclusive(output_path, pdf)


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Renderiza em PDF o relatório JSON consolidado pelo agente."
    )
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    return parser


def main() -> None:
    parser = build_argument_parser()
    args = parser.parse_args()
    try:
        template_name = load_report_template_name(SCRIPT_ENV_PATH)
        template_path = resolve_template_path(SCRIPT_DIRECTORY, template_name)
        report = load_json_object(args.report)
        render_report_pdf(
            report,
            template_path=template_path,
            output_path=args.output,
            renderer=WeasyPrintRenderer(),
        )
    except ReportRenderingError as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
