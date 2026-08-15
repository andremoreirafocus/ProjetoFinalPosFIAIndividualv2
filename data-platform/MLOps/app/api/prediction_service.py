"""Executa a predição sobre um bundle já carregado e uma entrada já preparada."""
from __future__ import annotations

from .model_bundle import ModelBundle, PredictionResult, PreparedModelInput


class PredictionService:
    """Sem estado de carregamento: opera inteiramente sobre o bundle recebido."""

    def predict(
        self, bundle: ModelBundle, prepared_input: PreparedModelInput
    ) -> PredictionResult:
        risk_score = float(
            bundle.estimator.predict_proba(prepared_input.frame)[0, 1]
        )
        predicted_class = int(risk_score >= bundle.decision_threshold)
        return PredictionResult(risk_score=risk_score, predicted_class=predicted_class)
