"""Testes dos objetos de dados que atravessam predição e explicação.

Sem comportamento próprio: cada teste constrói a instância e confirma que os campos
voltam exatamente como passados.
"""
from pathlib import Path

import pandas as pd

from MLOps.app.api.model_bundle import ModelBundle, PredictionResult, PreparedModelInput


def test_model_bundle_exposes_all_its_fields() -> None:
    estimator = object()
    bundle = ModelBundle(
        bundle_id="bundle-2026-08-14",
        schema_version="1",
        model_version="model-v1",
        trained_at_utc="2026-08-14T00:00:00+00:00",
        model_path=Path("/bundles/bundle-2026-08-14/lightgbm_abt.pkl"),
        estimator=estimator,
        feature_order=["ext_source_1", "occupation_type"],
        categorical_features=["occupation_type"],
        categories={"occupation_type": ["Laborers", "Managers"]},
        decision_threshold=0.5,
        target_rate=0.08,
        numeric_references={"ext_source_1": {"mean": 0.5}},
        categorical_references={"occupation_type": {"count": {"Laborers": 60}}},
        global_shap={"feature_importance": []},
        transformation_contract={"stats": {"median_es1": 0.5}},
    )

    assert bundle.bundle_id == "bundle-2026-08-14"
    assert bundle.schema_version == "1"
    assert bundle.model_version == "model-v1"
    assert bundle.trained_at_utc == "2026-08-14T00:00:00+00:00"
    assert bundle.model_path == Path("/bundles/bundle-2026-08-14/lightgbm_abt.pkl")
    assert bundle.estimator is estimator
    assert bundle.feature_order == ["ext_source_1", "occupation_type"]
    assert bundle.categorical_features == ["occupation_type"]
    assert bundle.categories == {"occupation_type": ["Laborers", "Managers"]}
    assert bundle.decision_threshold == 0.5
    assert bundle.target_rate == 0.08
    assert bundle.numeric_references == {"ext_source_1": {"mean": 0.5}}
    assert bundle.categorical_references == {
        "occupation_type": {"count": {"Laborers": 60}}
    }
    assert bundle.global_shap == {"feature_importance": []}
    assert bundle.transformation_contract == {"stats": {"median_es1": 0.5}}


def test_prepared_model_input_exposes_its_frame() -> None:
    frame = pd.DataFrame([{"ext_source_1": 0.5, "occupation_type": "Managers"}])

    prepared_input = PreparedModelInput(frame=frame)

    assert prepared_input.frame is frame


def test_prediction_result_exposes_score_and_class() -> None:
    result = PredictionResult(risk_score=0.55, predicted_class=1)

    assert result.risk_score == 0.55
    assert result.predicted_class == 1
