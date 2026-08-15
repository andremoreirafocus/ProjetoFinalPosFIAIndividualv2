"""Teste de predict_for_customer — etapa 9 do plano de bundle.

A inferência em si já está coberta por test_feature_input_processor.py e
test_prediction_service.py; este arquivo fixa que o CLI produz o mesmo contrato, sem
arredondar o score (o script antigo arredondava para 4 casas) e sem rótulo de decisão — a
política é da API, não do CLI.
"""
import pytest

from MLOps.app.api.feature_input_processor import ModelInputError
from MLOps.app.cli.predict import predict_for_customer
from MLOps.tests.fakes import FakeFeatureService, FakeModel
from MLOps.tests.fixtures import build_model_bundle


def test_predict_for_customer_returns_unrounded_score_and_class() -> None:
    bundle = build_model_bundle(estimator=FakeModel(positive_proba=0.123456789))
    feature_service = FakeFeatureService(
        features={"ext_source_1": 0.5, "occupation_type": "Laborers"}
    )

    result = predict_for_customer(100002, bundle, feature_service)

    assert result.risk_score == 0.123456789
    assert result.predicted_class == 0


def test_predict_for_customer_raises_on_missing_feature() -> None:
    bundle = build_model_bundle()
    feature_service = FakeFeatureService(features={"ext_source_1": 0.5})

    with pytest.raises(ModelInputError):
        predict_for_customer(100002, bundle, feature_service)
