"""Executa a predição sobre um bundle já carregado e uma entrada já preparada.

Corpo migrado de model_service.py:74-79 (PredictionService.predict), trocando
self.model/self.decision_threshold por bundle.estimator/bundle.decision_threshold —
etapa 1.5 do plano de bundle. Coexiste com o PredictionService antigo de
model_service.py até a etapa 8 apagar esse arquivo.
"""
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
