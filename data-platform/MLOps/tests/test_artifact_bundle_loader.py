"""Testes de ArtifactBundleLoader.load.

O caminho feliz e o de arquivo ausente usam o publicador real
(`Model.artifact_bundle_publisher.publish_bundle`); os demais escrevem manifesto e
arquivos diretamente, porque exigem estado inconsistente que o publicador real nunca
produz.
"""
import hashlib
import json
import pickle
from pathlib import Path
from typing import Any

import pytest

from Model.artifact_bundle_contract import MANIFEST_FILE_NAME
from Model.artifact_bundle_publisher import publish_bundle
from MLOps.app.api.artifact_bundle_loader import ArtifactBundleLoader
from MLOps.tests.fakes import FakeModel
from MLOps.tests.fixtures import (
    build_artifact,
    build_feature_reference,
    build_transformation_contract,
)


def _write_bundle_files(
    tmp_path: Path,
    artifact: dict[str, Any],
    reference: dict[str, Any],
    transformation_contract: dict[str, Any],
) -> tuple[Path, Path, Path]:
    bundle_directory = tmp_path / "bundles" / "bundle-manual"
    bundle_directory.mkdir(parents=True, exist_ok=True)
    model_path = bundle_directory / "lightgbm_abt.pkl"
    reference_path = bundle_directory / "feature_reference.json"
    transformation_contract_path = bundle_directory / "transformation_contract.json"
    with model_path.open("wb") as file:
        pickle.dump(artifact, file)
    reference_path.write_text(json.dumps(reference), encoding="utf-8")
    transformation_contract_path.write_text(
        json.dumps(transformation_contract), encoding="utf-8"
    )
    return model_path, reference_path, transformation_contract_path


def _write_manifest(
    tmp_path: Path,
    *,
    model_path: Path,
    reference_path: Path,
    transformation_contract_path: Path,
    bundle_id: str = "bundle-manual",
    model_version: str = "test-v1",
    trained_at_utc: str = "2026-07-14T00:00:00+00:00",
    omit_key: str | None = None,
) -> None:
    manifest = {
        "schema_version": 1,
        "bundle_id": bundle_id,
        "model_version": model_version,
        "trained_at_utc": trained_at_utc,
        "model": {
            "path": str(model_path.relative_to(tmp_path)),
            "sha256": hashlib.sha256(model_path.read_bytes()).hexdigest(),
        },
        "feature_reference": {
            "path": str(reference_path.relative_to(tmp_path)),
            "sha256": hashlib.sha256(reference_path.read_bytes()).hexdigest(),
        },
        "transformation_contract": {
            "path": str(transformation_contract_path.relative_to(tmp_path)),
            "sha256": hashlib.sha256(transformation_contract_path.read_bytes()).hexdigest(),
        },
    }
    if omit_key is not None:
        del manifest[omit_key]
    (tmp_path / MANIFEST_FILE_NAME).write_text(json.dumps(manifest), encoding="utf-8")


def _write_bundle_with_transformation_contract(
    tmp_path: Path, transformation_contract: dict[str, Any]
) -> None:
    """Bundle manual com artefato e referência válidos — só o contrato de transformação
    é o que cada teste de validação de forma personaliza."""
    model_path, reference_path, transformation_contract_path = _write_bundle_files(
        tmp_path, build_artifact(), build_feature_reference(), transformation_contract
    )
    _write_manifest(
        tmp_path,
        model_path=model_path,
        reference_path=reference_path,
        transformation_contract_path=transformation_contract_path,
    )


def test_load_returns_bundle_with_all_fields_populated_when_manifest_is_valid(
    tmp_path: Path,
) -> None:
    artifact = build_artifact()
    reference = build_feature_reference()

    manifest = publish_bundle(
        artifact, reference, build_transformation_contract(), tmp_path
    )
    bundle = ArtifactBundleLoader().load(tmp_path / MANIFEST_FILE_NAME)

    assert bundle.bundle_id == manifest.bundle_id
    assert bundle.schema_version == str(manifest.schema_version)
    assert bundle.model_version == "test-v1"
    assert bundle.trained_at_utc == "2026-07-14T00:00:00+00:00"
    assert bundle.model_path == tmp_path / manifest.model.path
    assert isinstance(bundle.estimator, FakeModel)
    assert bundle.feature_order == ["ext_source_1", "occupation_type"]
    assert bundle.categorical_features == ["occupation_type"]
    assert bundle.categories == {"occupation_type": ["Laborers", "Managers"]}
    assert bundle.decision_threshold == 0.5
    assert bundle.target_rate == reference["target_rate"]
    assert bundle.numeric_references == reference["numeric_features"]
    assert bundle.categorical_references == reference["categorical_features"]
    assert bundle.global_shap == reference["global_shap"]
    assert bundle.transformation_contract == build_transformation_contract()


def test_load_raises_when_manifest_file_is_missing(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        ArtifactBundleLoader().load(tmp_path / MANIFEST_FILE_NAME)


def test_load_raises_when_declared_artifact_file_is_missing(tmp_path: Path) -> None:
    manifest = publish_bundle(
        build_artifact(), build_feature_reference(), build_transformation_contract(), tmp_path
    )
    (tmp_path / manifest.model.path).unlink()

    with pytest.raises(FileNotFoundError):
        ArtifactBundleLoader().load(tmp_path / MANIFEST_FILE_NAME)


def test_load_raises_when_checksum_diverges(tmp_path: Path) -> None:
    manifest = publish_bundle(
        build_artifact(), build_feature_reference(), build_transformation_contract(), tmp_path
    )
    model_path = tmp_path / manifest.model.path
    model_path.write_bytes(model_path.read_bytes() + b"corrupted")

    with pytest.raises(ValueError, match="Checksum"):
        ArtifactBundleLoader().load(tmp_path / MANIFEST_FILE_NAME)


def test_load_raises_when_manifest_schema_is_invalid(tmp_path: Path) -> None:
    model_path, reference_path, transformation_contract_path = _write_bundle_files(
        tmp_path, build_artifact(), build_feature_reference(), build_transformation_contract()
    )
    _write_manifest(
        tmp_path,
        model_path=model_path,
        reference_path=reference_path,
        transformation_contract_path=transformation_contract_path,
        omit_key="bundle_id",
    )

    with pytest.raises(ValueError, match="bundle_id"):
        ArtifactBundleLoader().load(tmp_path / MANIFEST_FILE_NAME)


def test_load_raises_when_manifest_is_missing_transformation_contract_declaration(
    tmp_path: Path,
) -> None:
    model_path, reference_path, transformation_contract_path = _write_bundle_files(
        tmp_path, build_artifact(), build_feature_reference(), build_transformation_contract()
    )
    _write_manifest(
        tmp_path,
        model_path=model_path,
        reference_path=reference_path,
        transformation_contract_path=transformation_contract_path,
        omit_key="transformation_contract",
    )

    with pytest.raises(ValueError, match="transformation_contract"):
        ArtifactBundleLoader().load(tmp_path / MANIFEST_FILE_NAME)


def test_load_raises_when_artifact_is_missing_required_keys(tmp_path: Path) -> None:
    incomplete_artifact = {
        key: value for key, value in build_artifact().items() if key != "categories"
    }
    model_path, reference_path, transformation_contract_path = _write_bundle_files(
        tmp_path, incomplete_artifact, build_feature_reference(), build_transformation_contract()
    )
    _write_manifest(
        tmp_path,
        model_path=model_path,
        reference_path=reference_path,
        transformation_contract_path=transformation_contract_path,
    )

    with pytest.raises(ValueError, match="categories"):
        ArtifactBundleLoader().load(tmp_path / MANIFEST_FILE_NAME)


def test_load_raises_when_reference_is_missing_required_keys(tmp_path: Path) -> None:
    incomplete_reference = {
        key: value
        for key, value in build_feature_reference().items()
        if key != "global_shap"
    }
    model_path, reference_path, transformation_contract_path = _write_bundle_files(
        tmp_path, build_artifact(), incomplete_reference, build_transformation_contract()
    )
    _write_manifest(
        tmp_path,
        model_path=model_path,
        reference_path=reference_path,
        transformation_contract_path=transformation_contract_path,
    )

    with pytest.raises(ValueError, match="global_shap"):
        ArtifactBundleLoader().load(tmp_path / MANIFEST_FILE_NAME)


def test_load_raises_when_identity_diverges_between_manifest_and_artifact(
    tmp_path: Path,
) -> None:
    model_path, reference_path, transformation_contract_path = _write_bundle_files(
        tmp_path, build_artifact(), build_feature_reference(), build_transformation_contract()
    )
    _write_manifest(
        tmp_path,
        model_path=model_path,
        reference_path=reference_path,
        transformation_contract_path=transformation_contract_path,
        model_version="another-version",
    )

    with pytest.raises(ValueError, match="versão"):
        ArtifactBundleLoader().load(tmp_path / MANIFEST_FILE_NAME)


def test_load_accepts_extra_references_and_logs_warning(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    reference = build_feature_reference()
    reference["numeric_features"]["legacy_feature"] = reference["numeric_features"][
        "ext_source_1"
    ]
    reference["global_shap"]["feature_importance"].append(
        {
            **reference["global_shap"]["feature_importance"][0],
            "feature": "legacy_feature",
        }
    )
    model_path, reference_path, transformation_contract_path = _write_bundle_files(
        tmp_path, build_artifact(), reference, build_transformation_contract()
    )
    _write_manifest(
        tmp_path,
        model_path=model_path,
        reference_path=reference_path,
        transformation_contract_path=transformation_contract_path,
    )

    with caplog.at_level("WARNING"):
        bundle = ArtifactBundleLoader().load(tmp_path / MANIFEST_FILE_NAME)

    assert bundle is not None
    assert any("legacy_feature" in message for message in caplog.messages)


def test_load_raises_when_declared_transformation_contract_file_is_missing(
    tmp_path: Path,
) -> None:
    manifest = publish_bundle(
        build_artifact(), build_feature_reference(), build_transformation_contract(), tmp_path
    )
    (tmp_path / manifest.transformation_contract.path).unlink()

    with pytest.raises(FileNotFoundError):
        ArtifactBundleLoader().load(tmp_path / MANIFEST_FILE_NAME)


def test_load_raises_when_transformation_contract_checksum_diverges(tmp_path: Path) -> None:
    manifest = publish_bundle(
        build_artifact(), build_feature_reference(), build_transformation_contract(), tmp_path
    )
    transformation_contract_path = tmp_path / manifest.transformation_contract.path
    transformation_contract_path.write_bytes(
        transformation_contract_path.read_bytes() + b"corrupted"
    )

    with pytest.raises(ValueError, match="Checksum"):
        ArtifactBundleLoader().load(tmp_path / MANIFEST_FILE_NAME)


def test_load_raises_when_transformation_contract_is_missing_required_keys(
    tmp_path: Path,
) -> None:
    incomplete_contract = {
        key: value
        for key, value in build_transformation_contract().items()
        if key != "valid_orgs"
    }
    _write_bundle_with_transformation_contract(tmp_path, incomplete_contract)

    with pytest.raises(ValueError, match="valid_orgs"):
        ArtifactBundleLoader().load(tmp_path / MANIFEST_FILE_NAME)


def test_load_raises_when_a_statistic_is_not_numeric(tmp_path: Path) -> None:
    contract = build_transformation_contract()
    contract["stats"]["median_es1"] = "0.5"
    _write_bundle_with_transformation_contract(tmp_path, contract)

    with pytest.raises(ValueError, match="median_es1"):
        ArtifactBundleLoader().load(tmp_path / MANIFEST_FILE_NAME)


def test_load_raises_when_a_statistic_is_null(tmp_path: Path) -> None:
    contract = build_transformation_contract()
    contract["stats"]["median_es1"] = None
    _write_bundle_with_transformation_contract(tmp_path, contract)

    with pytest.raises(ValueError, match="median_es1"):
        ArtifactBundleLoader().load(tmp_path / MANIFEST_FILE_NAME)


def test_load_raises_when_a_statistic_is_a_boolean(tmp_path: Path) -> None:
    """Em Python ``True`` é uma instância de ``int`` — sem exclusão explícita de
    ``bool``, um `true` escrito à mão num arquivo editado manualmente passaria."""
    contract = build_transformation_contract()
    contract["stats"]["median_es1"] = True
    _write_bundle_with_transformation_contract(tmp_path, contract)

    with pytest.raises(ValueError, match="median_es1"):
        ArtifactBundleLoader().load(tmp_path / MANIFEST_FILE_NAME)


def test_load_raises_when_valid_orgs_is_not_a_list(tmp_path: Path) -> None:
    contract = build_transformation_contract()
    contract["valid_orgs"] = "Business Entity Type 3"
    _write_bundle_with_transformation_contract(tmp_path, contract)

    with pytest.raises(ValueError, match="valid_orgs"):
        ArtifactBundleLoader().load(tmp_path / MANIFEST_FILE_NAME)


def test_load_raises_when_a_digest_is_empty(tmp_path: Path) -> None:
    contract = build_transformation_contract()
    contract["application_sanitization_projection_sha256"] = ""
    _write_bundle_with_transformation_contract(tmp_path, contract)

    with pytest.raises(ValueError, match="application_sanitization_projection_sha256"):
        ArtifactBundleLoader().load(tmp_path / MANIFEST_FILE_NAME)


def test_load_reports_every_transformation_contract_defect_in_one_error(
    tmp_path: Path,
) -> None:
    """Sem acumulação, o comportamento regride para reportar só o primeiro defeito
    encontrado, e o segundo passaria despercebido até a próxima tentativa."""
    contract = build_transformation_contract()
    contract["valid_orgs"] = "Business Entity Type 3"
    contract["application_sanitization_projection_sha256"] = ""
    _write_bundle_with_transformation_contract(tmp_path, contract)

    with pytest.raises(ValueError) as error:
        ArtifactBundleLoader().load(tmp_path / MANIFEST_FILE_NAME)

    assert "valid_orgs" in str(error.value)
    assert "application_sanitization_projection_sha256" in str(error.value)


def test_load_accepts_transformation_contract_with_an_extra_statistic(
    tmp_path: Path,
) -> None:
    """Quais estatísticas existem dentro de `stats` não é assunto do loader — quem
    confere cobertura é o serviço de transformação, contra o `.sql` que ele já lê."""
    contract = build_transformation_contract()
    contract["stats"]["median_nova_estatistica"] = 1.23
    _write_bundle_with_transformation_contract(tmp_path, contract)

    bundle = ArtifactBundleLoader().load(tmp_path / MANIFEST_FILE_NAME)

    assert bundle.transformation_contract["stats"]["median_nova_estatistica"] == 1.23
