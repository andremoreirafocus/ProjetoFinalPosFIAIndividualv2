"""Transforma o dicionário de features do cliente na entrada aceita pelo estimador.

Corpo migrado de model_service.py:81-100 (PredictionService.prepare_customer), com o
bundle recebido por parâmetro em vez de lido de estado interno — etapa 1.4 do plano de
bundle. ``ModelInputError`` é uma classe nova, não importada de ``model_service.py``:
esse arquivo é apagado por inteiro na etapa 8, e nada deve depender dele além do fluxo
antigo que ele já serve.
"""
from __future__ import annotations

from typing import Any

import pandas as pd

from .model_bundle import ModelBundle, PreparedModelInput


class ModelInputError(ValueError):
    def __init__(self, missing_features: list[str]) -> None:
        self.missing_features = missing_features
        super().__init__(f"Features ausentes: {', '.join(missing_features)}")


class FeatureInputProcessor:
    """Sem estado: cada chamada de ``prepare`` é independente das anteriores."""

    def prepare(
        self, bundle: ModelBundle, features: dict[str, Any]
    ) -> PreparedModelInput:
        missing_features = sorted(set(bundle.feature_order).difference(features))
        if missing_features:
            raise ModelInputError(missing_features)

        # Reindex garante ordem idêntica à do treinamento e ignora campos extras.
        frame = pd.DataFrame([features]).reindex(columns=bundle.feature_order)
        categorical_set = set(bundle.categorical_features)
        for column in frame.columns:
            if column in categorical_set:
                frame[column] = pd.Categorical(
                    frame[column],
                    categories=bundle.categories.get(column),
                )
            else:
                frame[column] = pd.to_numeric(frame[column], errors="coerce")
        return PreparedModelInput(frame=frame)
