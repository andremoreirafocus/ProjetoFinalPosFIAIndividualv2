#!/usr/bin/env python3
"""Valida a narrativa do LLM e monta o JSON final do relatório."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
from pathlib import Path
from typing import Any
from uuid import uuid4

from script_logging import configure_script_logging


class LlmResponseValidationError(ValueError):
    """Indica que a resposta do LLM viola o contrato do relatório."""


TOP_LEVEL_KEYS = {
    "report_schema_version",
    "report_title",
    "case_summary",
    "policy_context",
    "factors_increasing_score",
    "factors_reducing_score",
    "limitations",
    "human_decision_notice",
}
FACTOR_KEYS = {
    "feature",
    "direction",
    "explanation",
    "contextual_conclusion",
}

logger = logging.getLogger(Path(__file__).stem)

SCRIPT_DIRECTORY = Path(__file__).resolve().parent
CONTEXT_INPUT_FILE_NAME = "sample_agent_context_before_llm.json"
CONTEXT_INPUT_PATH = SCRIPT_DIRECTORY / CONTEXT_INPUT_FILE_NAME
LLM_RESPONSE_INPUT_FILE_NAME = "sample_llm_response_to_report_request.json"
LLM_RESPONSE_INPUT_PATH = SCRIPT_DIRECTORY / LLM_RESPONSE_INPUT_FILE_NAME
AGENT_REPORT_OUTPUT_FILE_NAME = "sample_agent_report.json"
AGENT_REPORT_OUTPUT_PATH = SCRIPT_DIRECTORY / AGENT_REPORT_OUTPUT_FILE_NAME


def _require_object(value: Any, location: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise LlmResponseValidationError(f"{location} deve ser um objeto JSON.")
    return value


def _require_exact_keys(
    value: dict[str, Any], expected: set[str], location: str
) -> None:
    missing = sorted(expected - value.keys())
    extra = sorted(value.keys() - expected)
    if missing or extra:
        raise LlmResponseValidationError(
            f"{location} possui contrato inválido; ausentes={missing}, extras={extra}."
        )


def _require_nonempty_string(value: Any, location: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise LlmResponseValidationError(
            f"{location} deve ser uma string não vazia."
        )
    return value


def _authorized_factors(context: dict[str, Any]) -> list[dict[str, Any]]:
    validation = _require_object(context.get("validation"), "validation")
    if validation.get("ready_for_llm") is not True:
        raise LlmResponseValidationError(
            "O contexto não estava pronto para ser enviado ao LLM."
        )
    llm_context = _require_object(context.get("llm_context"), "llm_context")
    explanation = _require_object(
        llm_context.get("explanation"), "llm_context.explanation"
    )
    factors = explanation.get("authorized_factors")
    if not isinstance(factors, list):
        raise LlmResponseValidationError(
            "llm_context.explanation.authorized_factors deve ser uma lista."
        )
    return [
        _require_object(factor, f"authorized_factors[{index}]")
        for index, factor in enumerate(factors)
    ]


def _validate_factor_list(
    factors: Any,
    *,
    location: str,
    expected_direction: str,
    authorized_by_name: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    if not isinstance(factors, list):
        raise LlmResponseValidationError(f"{location} deve ser uma lista.")
    validated: list[dict[str, Any]] = []
    for index, raw_factor in enumerate(factors):
        factor = _require_object(raw_factor, f"{location}[{index}]")
        _require_exact_keys(factor, FACTOR_KEYS, f"{location}[{index}]")
        feature = _require_nonempty_string(
            factor["feature"], f"{location}[{index}].feature"
        )
        direction = _require_nonempty_string(
            factor["direction"], f"{location}[{index}].direction"
        )
        _require_nonempty_string(
            factor["explanation"], f"{location}[{index}].explanation"
        )
        _require_nonempty_string(
            factor["contextual_conclusion"],
            f"{location}[{index}].contextual_conclusion",
        )
        if feature not in authorized_by_name:
            raise LlmResponseValidationError(
                f"A resposta contém feature não autorizada: {feature!r}."
            )
        original_direction = authorized_by_name[feature]["evidence"]["direction"]
        if direction != expected_direction or direction != original_direction:
            raise LlmResponseValidationError(
                f"A direção da feature {feature!r} foi alterada pelo LLM."
            )
        validated.append(factor)
    return validated


def validate_llm_response(
    prepared_context: dict[str, Any], llm_response: dict[str, Any]
) -> None:
    context = _require_object(prepared_context, "Contexto preparado")
    response = _require_object(llm_response, "Resposta do LLM")
    authorized = _authorized_factors(context)
    authorized_by_name = {factor["feature"]: factor for factor in authorized}
    if len(authorized_by_name) != len(authorized):
        raise LlmResponseValidationError(
            "O contexto contém features autorizadas duplicadas."
        )

    _require_exact_keys(response, TOP_LEVEL_KEYS, "Resposta do LLM")
    _require_nonempty_string(
        response["report_schema_version"], "report_schema_version"
    )
    _require_nonempty_string(response["report_title"], "report_title")

    case_summary = _require_object(response["case_summary"], "case_summary")
    _require_exact_keys(case_summary, {"summary"}, "case_summary")
    _require_nonempty_string(case_summary["summary"], "case_summary.summary")

    policy_context = _require_object(response["policy_context"], "policy_context")
    _require_exact_keys(policy_context, {"explanation"}, "policy_context")
    _require_nonempty_string(
        policy_context["explanation"], "policy_context.explanation"
    )

    increasing = _validate_factor_list(
        response["factors_increasing_score"],
        location="factors_increasing_score",
        expected_direction="increases_risk",
        authorized_by_name=authorized_by_name,
    )
    reducing = _validate_factor_list(
        response["factors_reducing_score"],
        location="factors_reducing_score",
        expected_direction="reduces_risk",
        authorized_by_name=authorized_by_name,
    )
    received_features = [factor["feature"] for factor in increasing + reducing]
    if len(received_features) != len(set(received_features)):
        raise LlmResponseValidationError(
            "A resposta do LLM contém features duplicadas."
        )
    if set(received_features) != set(authorized_by_name):
        raise LlmResponseValidationError(
            "Conjunto de features da resposta não corresponde às features autorizadas."
        )

    limitations = response["limitations"]
    if not isinstance(limitations, list) or len(limitations) < 3:
        raise LlmResponseValidationError(
            "limitations deve conter pelo menos três itens."
        )
    for index, limitation in enumerate(limitations):
        _require_nonempty_string(limitation, f"limitations[{index}]")
    _require_nonempty_string(
        response["human_decision_notice"], "human_decision_notice"
    )


def _assemble_factor(
    source_factor: dict[str, Any], narrative: dict[str, Any]
) -> dict[str, Any]:
    semantic = source_factor["semantic"]
    evidence = source_factor["evidence"]
    return {
        "report_rank": source_factor["report_rank"],
        "original_rank_by_abs_shap": source_factor["original_rank_by_abs_shap"],
        "feature": source_factor["feature"],
        **semantic,
        "customer_value": evidence["value"],
        "shap_value": evidence["shap_value"],
        "direction": evidence["direction"],
        "explanation": narrative["explanation"],
        "contextual_conclusion": narrative["contextual_conclusion"],
        "comparison": evidence["comparison"],
    }


def assemble_report(
    prepared_context: dict[str, Any],
    llm_response: dict[str, Any],
    *,
    report_id: str,
    generated_at: str,
) -> dict[str, Any]:
    """Reassocia a narrativa validada aos dados preservados no contexto."""
    context = prepared_context["llm_context"]
    source_factors = context["explanation"]["authorized_factors"]
    narrative_by_name = {
        factor["feature"]: factor
        for factor in (
            llm_response["factors_increasing_score"]
            + llm_response["factors_reducing_score"]
        )
    }
    assembled = [
        _assemble_factor(factor, narrative_by_name[factor["feature"]])
        for factor in source_factors
    ]
    prediction = context["prediction"]
    policy = context["policy"]
    return {
        "report_schema_version": llm_response["report_schema_version"],
        "report_id": report_id,
        "generated_at": generated_at,
        "report_title": llm_response["report_title"],
        "case_summary": {
            **context["case"],
            "summary": llm_response["case_summary"]["summary"],
        },
        "policy_context": {
            "risk_score": prediction["risk_score"],
            "predicted_class": prediction["predicted_class"],
            "model_decision_threshold": prediction["model_decision_threshold"],
            "recommendation": policy["recommendation"],
            "reason": policy["reason"],
            "approve_max_score": policy["approve_max_score"],
            "manual_review_max_score": policy["manual_review_max_score"],
            "explanation": llm_response["policy_context"]["explanation"],
        },
        "factors_increasing_score": [
            factor
            for factor in assembled
            if factor["direction"] == "increases_risk"
        ],
        "factors_reducing_score": [
            factor for factor in assembled if factor["direction"] == "reduces_risk"
        ],
        "limitations": llm_response["limitations"],
        "human_decision_notice": llm_response["human_decision_notice"],
        "traceability": prepared_context["traceability"],
    }


def load_json_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise LlmResponseValidationError(
            f"Não foi possível ler {path}: {error}"
        ) from error
    return _require_object(value, str(path))


def write_json_exclusive(path: Path, value: dict[str, Any]) -> None:
    try:
        with path.open("x", encoding="utf-8") as output:
            json.dump(value, output, ensure_ascii=False, indent=2)
            output.write("\n")
    except FileExistsError as error:
        raise LlmResponseValidationError(
            f"O arquivo de saída já existe e não será sobrescrito: {path}"
        ) from error


def process_llm_response_files(
    context_path: Path,
    llm_response_path: Path,
    output_path: Path,
) -> dict[str, Any]:
    """Valida a resposta do LLM, reassocia evidências e salva o relatório."""
    if output_path.exists():
        raise LlmResponseValidationError(
            f"O arquivo de saída já existe e não será sobrescrito: {output_path}"
        )

    logger.info(
        "Processando resposta do LLM: context=%s, llm_response=%s.",
        context_path,
        llm_response_path,
    )
    context = load_json_object(context_path)
    response = load_json_object(llm_response_path)
    validate_llm_response(context, response)
    report = assemble_report(
        context,
        response,
        report_id=str(uuid4()),
        generated_at=datetime.now(timezone.utc).isoformat(),
    )
    write_json_exclusive(output_path, report)
    factor_count = (
        len(report["factors_increasing_score"])
        + len(report["factors_reducing_score"])
    )
    logger.info(
        "Relatório consolidado salvo em %s com %d fatores validados.",
        output_path,
        factor_count,
    )
    return report


def main() -> None:
    configure_script_logging(logger, __file__)
    try:
        process_llm_response_files(
            CONTEXT_INPUT_PATH,
            LLM_RESPONSE_INPUT_PATH,
            AGENT_REPORT_OUTPUT_PATH,
        )
    except LlmResponseValidationError as error:
        logger.error("Falha no processamento da resposta do LLM: %s", error)
        raise SystemExit(1) from error
    except Exception as error:
        logger.exception(
            "Falha inesperada no processamento da resposta do LLM: %s",
            error,
        )
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()
