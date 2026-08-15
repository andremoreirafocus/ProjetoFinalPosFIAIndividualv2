"""Publica atomicamente o conjunto de artefatos de um treino — etapa 3.2 do plano de bundle.

Comportamento do produtor: grava modelo e referência num diretório temporário no mesmo
filesystem, calcula os checksums, publica o diretório versionado e só então o manifesto,
por último. Nada aqui é migrado de ``train.py`` — ele continua gravando os arquivos fixos
até a etapa 6, que troca o produtor para usar este publicador.
"""
from __future__ import annotations

import hashlib
import json
import pickle
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    # Execução "nua": Model/ diretamente no sys.path (Airflow, suíte do próprio Model).
    from artifact_bundle_contract import (
        MANIFEST_FILE_NAME,
        MANIFEST_SCHEMA_VERSION,
        ArtifactDeclaration,
        BundleManifest,
    )
except ImportError:
    # Execução como pacote: data-platform/ no sys.path, Model importado como
    # Model.artifact_bundle_publisher (suíte do MLOps, que exercita o publicador real).
    from Model.artifact_bundle_contract import (
        MANIFEST_FILE_NAME,
        MANIFEST_SCHEMA_VERSION,
        ArtifactDeclaration,
        BundleManifest,
    )


def publish_bundle(
    model_artifact: dict[str, Any],
    feature_reference: dict[str, Any],
    artifacts_dir: Path,
) -> BundleManifest:
    """Publica modelo e referência atomicamente, com o manifesto escrito por último.

    Recusa publicar um par cujo artefato e referência não pertençam ao mesmo
    treinamento; nesse caso, nada é escrito.
    """
    config_version = model_artifact["config_version"]
    trained_at_utc = model_artifact["trained_at_utc"]
    if config_version != feature_reference["model_version"]:
        raise ValueError("A versão da referência diverge da versão do artefato.")
    if trained_at_utc != feature_reference["trained_at_utc"]:
        raise ValueError(
            "O instante de treinamento da referência diverge do artefato."
        )

    bundle_id = f"model-{config_version}-{_compact_timestamp(trained_at_utc)}"

    artifacts_dir.mkdir(parents=True, exist_ok=True)
    bundles_dir = artifacts_dir / "bundles"
    bundles_dir.mkdir(exist_ok=True)

    temporary_directory = Path(
        tempfile.mkdtemp(dir=bundles_dir, prefix=f".{bundle_id}-")
    )
    model_path = temporary_directory / "lightgbm_abt.pkl"
    reference_path = temporary_directory / "feature_reference.json"
    with model_path.open("wb") as file:
        pickle.dump(model_artifact, file)
    reference_path.write_text(
        json.dumps(feature_reference, ensure_ascii=False, allow_nan=False),
        encoding="utf-8",
    )

    model_sha256 = hashlib.sha256(model_path.read_bytes()).hexdigest()
    reference_sha256 = hashlib.sha256(reference_path.read_bytes()).hexdigest()

    versioned_directory = bundles_dir / bundle_id
    temporary_directory.replace(versioned_directory)

    manifest = BundleManifest(
        schema_version=MANIFEST_SCHEMA_VERSION,
        bundle_id=bundle_id,
        model_version=config_version,
        trained_at_utc=trained_at_utc,
        model=ArtifactDeclaration(
            path=f"bundles/{bundle_id}/lightgbm_abt.pkl", sha256=model_sha256
        ),
        feature_reference=ArtifactDeclaration(
            path=f"bundles/{bundle_id}/feature_reference.json",
            sha256=reference_sha256,
        ),
    )

    manifest_temporary_path = artifacts_dir / f".{MANIFEST_FILE_NAME}.tmp"
    manifest_temporary_path.write_text(
        json.dumps(_manifest_to_dict(manifest), ensure_ascii=False), encoding="utf-8"
    )
    manifest_temporary_path.replace(artifacts_dir / MANIFEST_FILE_NAME)

    return manifest


def _compact_timestamp(trained_at_utc: str) -> str:
    """``2026-07-28T14:30:00+00:00`` -> ``20260728T143000Z``."""
    moment = datetime.fromisoformat(trained_at_utc)
    offset = moment.utcoffset()
    if offset is None or offset.total_seconds() != 0:
        raise ValueError("trained_at_utc precisa declarar o instante em UTC.")
    return moment.strftime("%Y%m%dT%H%M%SZ")


def _manifest_to_dict(manifest: BundleManifest) -> dict[str, Any]:
    return {
        "schema_version": manifest.schema_version,
        "bundle_id": manifest.bundle_id,
        "model_version": manifest.model_version,
        "trained_at_utc": manifest.trained_at_utc,
        "model": {"path": manifest.model.path, "sha256": manifest.model.sha256},
        "feature_reference": {
            "path": manifest.feature_reference.path,
            "sha256": manifest.feature_reference.sha256,
        },
    }
