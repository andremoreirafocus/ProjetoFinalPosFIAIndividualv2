"""Teste da declaração de contrato do bundle — etapa 3.1 do plano de bundle.

Sem comportamento próprio: confirma que ``BundleManifest`` expõe exatamente os campos
com que foi construído. É o contrato compartilhado entre o produtor (`Model`) e o
consumidor (loader do serving, etapa 4) — não a inferência.
"""
from artifact_bundle_contract import ArtifactDeclaration, BundleManifest


def test_bundle_manifest_exposes_all_its_fields() -> None:
    model_declaration = ArtifactDeclaration(
        path="bundles/model-test-v1-20260714T000000Z/lightgbm_abt.pkl",
        sha256="a" * 64,
    )
    reference_declaration = ArtifactDeclaration(
        path="bundles/model-test-v1-20260714T000000Z/feature_reference.json",
        sha256="b" * 64,
    )

    manifest = BundleManifest(
        schema_version=1,
        bundle_id="model-test-v1-20260714T000000Z",
        model_version="test-v1",
        trained_at_utc="2026-07-14T00:00:00+00:00",
        model=model_declaration,
        feature_reference=reference_declaration,
    )

    assert manifest.schema_version == 1
    assert manifest.bundle_id == "model-test-v1-20260714T000000Z"
    assert manifest.model_version == "test-v1"
    assert manifest.trained_at_utc == "2026-07-14T00:00:00+00:00"
    assert manifest.model is model_declaration
    assert manifest.feature_reference is reference_declaration
    assert manifest.model.path == "bundles/model-test-v1-20260714T000000Z/lightgbm_abt.pkl"
    assert manifest.model.sha256 == "a" * 64
