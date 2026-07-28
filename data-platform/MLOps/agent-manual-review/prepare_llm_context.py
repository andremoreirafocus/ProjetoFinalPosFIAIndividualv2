#!/usr/bin/env python3
"""Prepara o contexto governado que poderá ser enviado ao LLM."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


class ContextPreparationError(ValueError):
    """Indica violação do contrato de preparação do contexto."""


SEMANTIC_FIELDS = (
    "label",
    "description",
    "type",
    "format",
    "unit",
    "value_semantics",
    "calculation",
    "special_values",
)


def _require_object(value: Any, location: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ContextPreparationError(f"{location} deve ser um objeto JSON.")
    return value


def _require_list(value: Any, location: str) -> list[Any]:
    if not isinstance(value, list):
        raise ContextPreparationError(f"{location} deve ser uma lista JSON.")
    return value


def _require_keys(
    value: dict[str, Any], required: set[str], location: str
) -> None:
    missing = sorted(required - value.keys())
    if missing:
        raise ContextPreparationError(
            f"{location} não contém as chaves obrigatórias: {', '.join(missing)}."
        )


def _version_or_none(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        return None
    return value


def _semantic_from_catalog(
    feature: str, catalog_entry: dict[str, Any]
) -> dict[str, Any]:
    required = {
        "label",
        "description",
        "type",
        "format",
        "unit",
        "value_semantics",
        "allowed_in_report",
    }
    _require_keys(catalog_entry, required, f"Catálogo da feature {feature!r}")
    if not isinstance(catalog_entry["allowed_in_report"], bool):
        raise ContextPreparationError(
            f"allowed_in_report da feature {feature!r} deve ser booleano."
        )
    return {
        field: catalog_entry[field]
        for field in SEMANTIC_FIELDS
        if field in catalog_entry
    }


def prepare_context(
    api_response: dict[str, Any],
    feature_catalog: dict[str, Any],
    *,
    api_source: str,
    catalog_source: str,
    prompt_version: str | None,
) -> dict[str, Any]:
    """Combina resposta da API e catálogo sem enviar dados ao LLM."""
    api = _require_object(api_response, "Resposta da API")
    catalog = _require_object(feature_catalog, "Catálogo de features")
    _require_keys(
        api,
        {
            "source",
            "customer_id",
            "risk_score",
            "predicted_class",
            "model_decision_threshold",
            "policy",
            "explanation",
        },
        "Resposta da API",
    )
    _require_keys(catalog, {"catalog_version", "features"}, "Catálogo de features")

    policy = _require_object(api["policy"], "policy")
    _require_keys(
        policy,
        {
            "recommendation",
            "reason",
            "policy_version",
            "approve_max_score",
            "manual_review_max_score",
        },
        "policy",
    )
    explanation = _require_object(api["explanation"], "explanation")
    _require_keys(
        explanation, {"base_value", "output_scale", "top_factors"}, "explanation"
    )
    factors = _require_list(explanation["top_factors"], "explanation.top_factors")
    catalog_features = _require_object(catalog["features"], "features")

    received_names: list[str] = []
    for position, raw_factor in enumerate(factors, start=1):
        factor = _require_object(
            raw_factor, f"explanation.top_factors[{position - 1}]"
        )
        _require_keys(
            factor,
            {"feature", "value", "shap_value", "direction", "comparison"},
            f"explanation.top_factors[{position - 1}]",
        )
        feature = factor["feature"]
        if not isinstance(feature, str) or not feature:
            raise ContextPreparationError(
                f"Feature inválida na posição {position} de top_factors."
            )
        if feature in received_names:
            raise ContextPreparationError(
                f"Feature repetida na resposta da API: {feature!r}."
            )
        received_names.append(feature)

    missing_catalog_features = [
        feature for feature in received_names if feature not in catalog_features
    ]
    if missing_catalog_features:
        raise ContextPreparationError(
            "Features da explicação ausentes do catálogo: "
            + ", ".join(missing_catalog_features)
            + "."
        )

    authorized_factors: list[dict[str, Any]] = []
    excluded_factors: list[dict[str, Any]] = []
    for original_rank, factor in enumerate(factors, start=1):
        feature = factor["feature"]
        catalog_entry = _require_object(
            catalog_features[feature], f"Catálogo da feature {feature!r}"
        )
        semantic = _semantic_from_catalog(feature, catalog_entry)
        if catalog_entry["allowed_in_report"]:
            authorized_factors.append(
                {
                    "report_rank": len(authorized_factors) + 1,
                    "original_rank_by_abs_shap": original_rank,
                    "feature": feature,
                    "semantic": semantic,
                    "evidence": {
                        "value": factor["value"],
                        "shap_value": factor["shap_value"],
                        "direction": factor["direction"],
                        "comparison": factor["comparison"],
                    },
                }
            )
            continue

        reason = catalog_entry.get("governance_note")
        if not isinstance(reason, str) or not reason.strip():
            raise ContextPreparationError(
                f"Feature não autorizada {feature!r} não possui governance_note."
            )
        excluded_factors.append(
            {
                "feature": feature,
                "original_rank_by_abs_shap": original_rank,
                "reason": reason,
            }
        )

    model_version = _version_or_none(api.get("model_version"))
    policy_version = _version_or_none(policy.get("policy_version"))
    catalog_version = _version_or_none(catalog.get("catalog_version"))
    normalized_prompt_version = _version_or_none(prompt_version)
    blocking_issues: list[str] = []
    if model_version is None:
        blocking_issues.append(
            "model_version não está disponível no contrato atual da API."
        )
    if policy_version is None:
        blocking_issues.append("policy_version não está disponível na política.")
    if catalog_version is None:
        blocking_issues.append("catalog_version não está disponível no catálogo.")
    if normalized_prompt_version is None:
        blocking_issues.append(
            "prompt_version ainda não foi definido porque o system prompt não foi "
            "implementado."
        )

    return {
        "context_schema_version": "1.0.0",
        "stage": "pre_llm_context_preparation",
        "source_files": {
            "api_response": api_source,
            "feature_catalog": catalog_source,
        },
        "llm_context": {
            "case": {
                "source": api["source"],
                "customer_id": api["customer_id"],
            },
            "prediction": {
                "risk_score": api["risk_score"],
                "predicted_class": api["predicted_class"],
                "model_decision_threshold": api["model_decision_threshold"],
                "score_interpretation": (
                    "Medida de ordenação de risco; não representa uma "
                    "probabilidade calibrada de inadimplência."
                ),
            },
            "policy": {
                "recommendation": policy["recommendation"],
                "reason": policy["reason"],
                "policy_version": policy["policy_version"],
                "approve_max_score": policy["approve_max_score"],
                "manual_review_max_score": policy["manual_review_max_score"],
            },
            "explanation": {
                "base_value": explanation["base_value"],
                "output_scale": explanation["output_scale"],
                "authorized_factors": authorized_factors,
            },
            "report_objective": (
                "Explicar por que o caso foi encaminhado à revisão manual, quais "
                "evidências autorizadas elevaram ou reduziram o score e como os "
                "valores do cliente se comparam à população de treinamento."
            ),
            "required_content": [
                "Contextualizar o score na faixa da política de crédito.",
                "Apresentar separadamente fatores que elevaram e reduziram o score.",
                (
                    "Relacionar cada fator ao valor do cliente e à comparação "
                    "populacional disponível."
                ),
                (
                    "Explicitar as limitações da explicação e preservar a decisão "
                    "final humana."
                ),
            ],
            "interpretation_constraints": [
                "Não recalcular o score nem alterar a recomendação da política.",
                "Não interpretar contribuições SHAP como relações causais.",
                "Não criar evidências ou conclusões ausentes do contexto.",
                (
                    "Não apresentar o score como probabilidade calibrada de "
                    "inadimplência."
                ),
                "Não tomar ou recomendar uma decisão final de crédito.",
            ],
        },
        "traceability": {
            "model_version": model_version,
            "policy_version": policy_version,
            "catalog_version": catalog_version,
            "prompt_version": normalized_prompt_version,
        },
        "agent_processing": {
            "join_key": "feature",
            "governance_rule": (
                "Somente fatores com allowed_in_report = true integram llm_context."
            ),
            "received_factor_count": len(factors),
            "authorized_factor_count": len(authorized_factors),
            "excluded_factor_count": len(excluded_factors),
            "excluded_evidence_for_audit_only": excluded_factors,
            "excluded_evidence_is_part_of_llm_context": False,
        },
        "validation": {
            "explanation_present": True,
            "all_factors_found_in_catalog": True,
            "missing_catalog_features": [],
            "ready_for_llm": not blocking_issues,
            "blocking_issues": blocking_issues,
        },
    }


def load_json_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ContextPreparationError(f"Não foi possível ler {path}: {error}") from error
    return _require_object(value, str(path))


def write_json_exclusive(path: Path, value: dict[str, Any]) -> None:
    try:
        with path.open("x", encoding="utf-8") as output:
            json.dump(value, output, ensure_ascii=False, indent=2)
            output.write("\n")
    except FileExistsError as error:
        raise ContextPreparationError(
            f"O arquivo de saída já existe e não será sobrescrito: {path}"
        ) from error


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Prepara o contexto governado para o LLM."
    )
    parser.add_argument("--api-response", required=True, type=Path)
    parser.add_argument("--feature-catalog", required=True, type=Path)
    parser.add_argument("--prompt-version")
    parser.add_argument("--output", required=True, type=Path)
    return parser


def main() -> None:
    parser = build_argument_parser()
    args = parser.parse_args()
    if args.output.exists():
        parser.error(
            f"O arquivo de saída já existe e não será sobrescrito: {args.output}"
        )
    try:
        context = prepare_context(
            load_json_object(args.api_response),
            load_json_object(args.feature_catalog),
            api_source=str(args.api_response),
            catalog_source=str(args.feature_catalog),
            prompt_version=args.prompt_version,
        )
        write_json_exclusive(args.output, context)
    except ContextPreparationError as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
