"""Testes de PredictionService.predict — etapa 1.5 do plano de bundle.

Corpo migrado de model_service.py:74-79 (PredictionService.predict), agora recebendo
bundle e entrada preparada por parâmetro em vez de carregar de arquivo. Coexiste com o
PredictionService antigo de model_service.py até a etapa 8 apagar esse arquivo — nomes
iguais, módulos diferentes, sem ambiguidade de import.
"""
import pandas as pd
import pytest

from MLOps.app.api.model_bundle import PreparedModelInput
from MLOps.app.api.prediction_service import PredictionService
from MLOps.tests.fakes import FakeModel
from MLOps.tests.fixtures import build_model_bundle


def _prepared_input() -> PreparedModelInput:
    frame = pd.DataFrame([{"ext_source_1": 0.5, "occupation_type": "Managers"}])
    return PreparedModelInput(frame=frame)


@pytest.mark.parametrize("proba,expected_class", [(0.6, 1), (0.4, 0)])
def test_predict_returns_score_and_class_by_threshold(
    proba: float, expected_class: int
) -> None:
    bundle = build_model_bundle(
        estimator=FakeModel(positive_proba=proba), decision_threshold=0.5
    )

    result = PredictionService().predict(bundle, _prepared_input())

    assert result.risk_score == pytest.approx(proba)
    assert result.predicted_class == expected_class


def test_predict_uses_the_bundles_threshold_not_a_fixed_one() -> None:
    low_threshold_bundle = build_model_bundle(
        estimator=FakeModel(positive_proba=0.55), decision_threshold=0.5
    )
    high_threshold_bundle = build_model_bundle(
        estimator=FakeModel(positive_proba=0.55), decision_threshold=0.6
    )

    low_result = PredictionService().predict(low_threshold_bundle, _prepared_input())
    high_result = PredictionService().predict(high_threshold_bundle, _prepared_input())

    assert low_result.predicted_class == 1
    assert high_result.predicted_class == 0


def test_predict_passes_the_exact_prepared_frame_to_the_estimator() -> None:
    model = FakeModel()
    bundle = build_model_bundle(estimator=model)
    prepared_input = _prepared_input()

    PredictionService().predict(bundle, prepared_input)

    assert model.received is prepared_input.frame
