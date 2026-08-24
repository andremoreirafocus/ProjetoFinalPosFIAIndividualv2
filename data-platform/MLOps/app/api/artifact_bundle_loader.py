"""Lê, confere e recusa o conjunto de artefatos publicado.

Sem estado mutável: cada chamada de ``load`` é independente das anteriores.
"""
from __future__ import annotations

import hashlib
import json
import logging
import pickle
from pathlib import Path
from typing import Any

from Model.artifact_bundle_contract import (
    REQUIRED_ARTIFACT_KEYS,
    REQUIRED_TRANSFORMATION_CONTRACT_KEYS,
)

from .model_bundle import ModelBundle


logger = logging.getLogger(__name__)


REQUIRED_MANIFEST_KEYS = frozenset(
    {
        "schema_version",
        "bundle_id",
        "model_version",
        "trained_at_utc",
        "model",
        "feature_reference",
        "transformation_contract",
    }
)
REQUIRED_ARTIFACT_DECLARATION_KEYS = frozenset({"path", "sha256"})

REQUIRED_REFERENCE_KEYS = frozenset(
    {
        "model_version",
        "trained_at_utc",
        "target_rate",
        "numeric_features",
        "categorical_features",
        "global_shap",
    }
)
"""Não faz parte da seção 12 (chaves do artefato) nem do contrato do Model: é a forma da
referência que o serving consome, e mantém-se onde já mora hoje (serviço de explicação).
"""


class ArtifactBundleLoader:
    """Sem estado mutável: cada chamada de ``load`` é independente das anteriores."""

    def load(self, manifest_path: Path) -> ModelBundle:
        manifest = self._read_manifest(manifest_path)

        model_path = self._resolve_declared_path(manifest_path, manifest["model"])
        reference_path = self._resolve_declared_path(
            manifest_path, manifest["feature_reference"]
        )
        transformation_contract_path = self._resolve_declared_path(
            manifest_path, manifest["transformation_contract"]
        )

        self._verify_checksum(model_path, manifest["model"]["sha256"])
        self._verify_checksum(reference_path, manifest["feature_reference"]["sha256"])
        self._verify_checksum(
            transformation_contract_path, manifest["transformation_contract"]["sha256"]
        )

        with model_path.open("rb") as file:
            artifact = pickle.load(file)
        reference = json.loads(reference_path.read_text(encoding="utf-8"))
        transformation_contract = json.loads(
            transformation_contract_path.read_text(encoding="utf-8")
        )

        self._validate_required_keys(artifact, REQUIRED_ARTIFACT_KEYS, "artefato")
        self._validate_required_keys(reference, REQUIRED_REFERENCE_KEYS, "referência")
        self._validate_identity(manifest, artifact, reference)
        self._validate_feature_coverage(reference, artifact["features"])
        self._validate_transformation_contract(transformation_contract)

        return ModelBundle(
            bundle_id=manifest["bundle_id"],
            schema_version=str(manifest["schema_version"]),
            model_version=manifest["model_version"],
            trained_at_utc=manifest["trained_at_utc"],
            model_path=model_path,
            estimator=artifact["model"],
            feature_order=artifact["features"],
            categorical_features=artifact["categorical_features"],
            categories=artifact["categories"],
            decision_threshold=float(artifact["decision_threshold"]),
            target_rate=float(reference["target_rate"]),
            numeric_references=reference["numeric_features"],
            categorical_references=reference["categorical_features"],
            global_shap=reference["global_shap"],
            transformation_contract=transformation_contract,
        )

    @staticmethod
    def _read_manifest(manifest_path: Path) -> dict[str, Any]:
        if not manifest_path.is_file():
            raise FileNotFoundError(f"Manifesto não encontrado: {manifest_path}")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        missing = REQUIRED_MANIFEST_KEYS.difference(manifest)
        if missing:
            raise ValueError(f"Manifesto inválido. Chaves ausentes: {sorted(missing)}")
        for declaration_name in ("model", "feature_reference", "transformation_contract"):
            declaration_missing = REQUIRED_ARTIFACT_DECLARATION_KEYS.difference(
                manifest[declaration_name]
            )
            if declaration_missing:
                raise ValueError(
                    f"Manifesto inválido. Declaração de '{declaration_name}' sem "
                    f"chaves: {sorted(declaration_missing)}"
                )
        return manifest

    @staticmethod
    def _resolve_declared_path(manifest_path: Path, declaration: dict[str, Any]) -> Path:
        resolved = manifest_path.parent / declaration["path"]
        if not resolved.is_file():
            raise FileNotFoundError(f"Artefato declarado não encontrado: {resolved}")
        return resolved

    @staticmethod
    def _verify_checksum(path: Path, expected_sha256: str) -> None:
        actual_sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual_sha256 != expected_sha256:
            raise ValueError(
                f"Checksum divergente para {path}: esperado {expected_sha256}, "
                f"obtido {actual_sha256}."
            )

    @staticmethod
    def _validate_required_keys(
        content: dict[str, Any], required_keys: frozenset, label: str
    ) -> None:
        missing = required_keys.difference(content)
        if missing:
            raise ValueError(
                f"{label.capitalize()} inválido(a). Chaves ausentes: {sorted(missing)}"
            )

    @staticmethod
    def _validate_identity(
        manifest: dict[str, Any], artifact: dict[str, Any], reference: dict[str, Any]
    ) -> None:
        if (
            manifest["model_version"] != artifact["config_version"]
            or manifest["model_version"] != reference["model_version"]
        ):
            raise ValueError(
                "A versão do modelo diverge entre manifesto, artefato e referência."
            )
        if (
            manifest["trained_at_utc"] != artifact["trained_at_utc"]
            or manifest["trained_at_utc"] != reference["trained_at_utc"]
        ):
            raise ValueError(
                "O instante de treinamento diverge entre manifesto, artefato e referência."
            )

    @staticmethod
    def _validate_feature_coverage(
        reference: dict[str, Any], expected_features: list[str]
    ) -> None:
        expected = set(expected_features)
        numeric = set(reference["numeric_features"])
        categorical = set(reference["categorical_features"])
        shap_features = {
            item["feature"] for item in reference["global_shap"]["feature_importance"]
        }

        missing_statistics = expected.difference(numeric | categorical)
        duplicated_types = expected.intersection(numeric & categorical)
        missing_shap = expected.difference(shap_features)

        errors = []
        if missing_statistics:
            errors.append(
                f"features sem referência estatística: {sorted(missing_statistics)}"
            )
        if duplicated_types:
            errors.append(
                "features simultaneamente numéricas e categóricas: "
                f"{sorted(duplicated_types)}"
            )
        if missing_shap:
            errors.append(f"features sem referência SHAP global: {sorted(missing_shap)}")
        if errors:
            raise ValueError(
                "Referências incompatíveis com o modelo: " + "; ".join(errors)
            )

        extra_features = (numeric | categorical | shap_features).difference(expected)
        if extra_features:
            logger.warning(
                "Referências sem correspondência no modelo foram ignoradas: %s",
                sorted(extra_features),
            )

    @staticmethod
    def _validate_transformation_contract(contract: dict[str, Any]) -> None:
        """Valida a forma do contrato, sem nomear nenhuma estatística: quais chaves
        existem dentro de `stats` não é assunto do loader — quem confere cobertura é o
        serviço de transformação, contra o `.sql` que já lê."""
        ArtifactBundleLoader._validate_required_keys(
            contract, REQUIRED_TRANSFORMATION_CONTRACT_KEYS, "contrato de transformação"
        )

        errors = []

        stats = contract["stats"]
        if not isinstance(stats, dict):
            errors.append("'stats' não é um dicionário")
        else:
            not_numeric = sorted(
                name
                for name, value in stats.items()
                if isinstance(value, bool) or not isinstance(value, (int, float))
            )
            if not_numeric:
                errors.append(f"estatísticas não numéricas em 'stats': {not_numeric}")

        for key in ("valid_orgs", "valid_incs"):
            value = contract[key]
            if not isinstance(value, list) or not all(
                isinstance(item, str) for item in value
            ):
                errors.append(f"'{key}' não é uma lista de strings")

        for key in (
            "application_sanitization_projection_sha256",
            "application_abt_record_projection_sha256",
        ):
            value = contract[key]
            if not isinstance(value, str) or not value:
                errors.append(f"'{key}' vazio ou ausente")

        if errors:
            raise ValueError("Contrato de transformação inválido: " + "; ".join(errors))
