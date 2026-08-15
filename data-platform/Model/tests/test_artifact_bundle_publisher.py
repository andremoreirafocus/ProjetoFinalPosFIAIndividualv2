"""Testes de publish_bundle — etapa 3.2 do plano de bundle.

Comportamento novo, não migrado de train.py: publicação atômica do modelo e das
referências, com o manifesto escrito por último (seção 5.2 do plano). train.py não
muda nesta etapa — continua gravando os arquivos fixos até a etapa 6.
"""
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from artifact_bundle_publisher import publish_bundle


def _model_artifact(
    config_version: str = "test-v1",
    trained_at_utc: str = "2026-07-14T00:00:00+00:00",
) -> dict[str, Any]:
    return {
        "model": {"placeholder": "estimator"},
        "algorithm": "LightGBM",
        "hyperparameters": {},
        "features": ["ext_source_1", "occupation_type"],
        "categorical_features": ["occupation_type"],
        "categories": {"occupation_type": ["Laborers", "Managers"]},
        "decision_threshold": 0.5,
        "config_version": config_version,
        "trained_at_utc": trained_at_utc,
    }


def _feature_reference(
    model_version: str = "test-v1",
    trained_at_utc: str = "2026-07-14T00:00:00+00:00",
) -> dict[str, Any]:
    return {
        "model_version": model_version,
        "trained_at_utc": trained_at_utc,
        "target_rate": 0.08,
        "numeric_features": {},
        "categorical_features": {},
        "global_shap": {"feature_importance": []},
    }


def test_publish_bundle_writes_schema_valid_manifest(tmp_path: Path) -> None:
    manifest = publish_bundle(_model_artifact(), _feature_reference(), tmp_path)

    saved = json.loads((tmp_path / "current_bundle.json").read_text(encoding="utf-8"))

    assert saved["schema_version"] == manifest.schema_version
    assert saved["bundle_id"] == manifest.bundle_id
    assert saved["model_version"] == "test-v1"
    assert saved["trained_at_utc"] == "2026-07-14T00:00:00+00:00"
    assert saved["model"]["path"] and saved["model"]["sha256"]
    assert saved["feature_reference"]["path"] and saved["feature_reference"]["sha256"]


def test_publish_bundle_declares_paths_relative_to_manifest_directory(
    tmp_path: Path,
) -> None:
    manifest = publish_bundle(_model_artifact(), _feature_reference(), tmp_path)

    assert (tmp_path / manifest.model.path).is_file()
    assert (tmp_path / manifest.feature_reference.path).is_file()


def test_publish_bundle_computes_correct_checksums(tmp_path: Path) -> None:
    manifest = publish_bundle(_model_artifact(), _feature_reference(), tmp_path)

    model_bytes = (tmp_path / manifest.model.path).read_bytes()
    reference_bytes = (tmp_path / manifest.feature_reference.path).read_bytes()

    assert manifest.model.sha256 == hashlib.sha256(model_bytes).hexdigest()
    assert manifest.feature_reference.sha256 == hashlib.sha256(
        reference_bytes
    ).hexdigest()


def test_publish_bundle_creates_versioned_directory(tmp_path: Path) -> None:
    manifest = publish_bundle(_model_artifact(), _feature_reference(), tmp_path)

    bundle_directory = tmp_path / "bundles" / manifest.bundle_id
    assert sorted(entry.name for entry in bundle_directory.iterdir()) == [
        "feature_reference.json",
        "lightgbm_abt.pkl",
    ]


@pytest.mark.parametrize(
    "diverging_feature_reference",
    [
        _feature_reference(model_version="another-version"),
        _feature_reference(trained_at_utc="2020-01-01T00:00:00+00:00"),
    ],
    ids=["config_version_diverge", "trained_at_utc_diverge"],
)
def test_publish_bundle_rejects_diverging_identity_and_preserves_previous_manifest(
    tmp_path: Path, diverging_feature_reference: dict
) -> None:
    first_manifest = publish_bundle(_model_artifact(), _feature_reference(), tmp_path)

    with pytest.raises(ValueError):
        publish_bundle(_model_artifact(), diverging_feature_reference, tmp_path)

    saved = json.loads((tmp_path / "current_bundle.json").read_text(encoding="utf-8"))
    assert saved["bundle_id"] == first_manifest.bundle_id
    assert sorted(entry.name for entry in (tmp_path / "bundles").iterdir()) == [
        first_manifest.bundle_id
    ]
