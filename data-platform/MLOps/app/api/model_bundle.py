"""Objetos de dados que atravessam predição e explicação, sem comportamento próprio.

Nenhum serviço aqui: são as instâncias que ``FeatureInputProcessor`` e
``PredictionService`` recebem e devolvem, e que ``ExplanationService`` passa a consumir
a partir da etapa 2.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd


@dataclass(frozen=True)
class ModelBundle:
    """Snapshot logicamente imutável do modelo e das referências de um mesmo treino."""

    bundle_id: str
    schema_version: str
    model_version: str
    trained_at_utc: str
    model_path: Path
    estimator: Any
    feature_order: list[str]
    categorical_features: list[str]
    categories: dict[str, list[str]]
    decision_threshold: float
    target_rate: float
    numeric_references: dict[str, dict[str, Any]]
    categorical_references: dict[str, dict[str, Any]]
    global_shap: dict[str, Any]


@dataclass(frozen=True)
class PreparedModelInput:
    """Entrada já tratada para o estimador: uma linha, colunas na ordem do bundle."""

    frame: pd.DataFrame


@dataclass(frozen=True)
class PredictionResult:
    """Score e classe devolvidos pela predição, com o threshold já aplicado."""

    risk_score: float
    predicted_class: int
