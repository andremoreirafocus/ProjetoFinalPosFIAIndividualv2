"""Fixtures de dados para os testes da API (sem banco nem artefato treinado)."""
from __future__ import annotations

import pickle
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, create_engine, text

from MLOps.tests.fakes import FakeModel


def build_artifact(
    model: Any | None = None,
    features: list[str] | None = None,
    categorical_features: list[str] | None = None,
    categories: dict[str, list[str]] | None = None,
    threshold: float = 0.5,
) -> dict[str, Any]:
    """Monta um dicionário-artefato coerente com o contrato atual do modelo."""
    artifact: dict[str, Any] = {
        "model": model if model is not None else FakeModel(),
        "features": features if features is not None else ["ext_source_1", "occupation_type"],
        "categorical_features": (
            categorical_features
            if categorical_features is not None
            else ["occupation_type"]
        ),
        "categories": (
            categories
            if categories is not None
            else {"occupation_type": ["Laborers", "Managers"]}
        ),
        "decision_threshold": threshold,
        "metrics": {"roc_auc": 0.75},
        "config_version": "test-v1",
        "trained_at_utc": "2026-07-14T00:00:00+00:00",
    }
    return artifact


def build_feature_reference() -> dict[str, Any]:
    return {
        "model_version": "test-v1",
        "trained_at_utc": "2026-07-14T00:00:00+00:00",
        "target_rate": 0.08,
        "numeric_features": {
            "ext_source_1": {
                "mean": 0.50,
                "median": 0.50,
                "p25": 0.25,
                "p75": 0.75,
                "target_0_median": 0.55,
                "target_1_median": 0.40,
                "percentiles": {f"p{i:02d}": i / 100 for i in range(101)},
            }
        },
        "categorical_features": {
            "occupation_type": {
                "count": {"Laborers": 60, "Managers": 40},
                "frequency": {"Laborers": 0.60, "Managers": 0.40},
                "default_rate": {"Laborers": 0.10, "Managers": 0.05},
            }
        },
        "global_shap": {
            "feature_importance": [
                {
                    "feature": "ext_source_1",
                    "mean_abs_shap": 0.20,
                    "p50_abs_shap": 0.10,
                    "p75_abs_shap": 0.20,
                    "p90_abs_shap": 0.30,
                    "p95_abs_shap": 0.40,
                    "p99_abs_shap": 0.50,
                },
                {
                    "feature": "occupation_type",
                    "mean_abs_shap": 0.08,
                    "p50_abs_shap": 0.05,
                    "p75_abs_shap": 0.10,
                    "p90_abs_shap": 0.15,
                    "p95_abs_shap": 0.20,
                    "p99_abs_shap": 0.25,
                },
            ]
        },
    }


def write_artifact_pickle(directory: Path, artifact: dict[str, Any]) -> Path:
    """Persiste um artefato-fixture em ``.pkl`` real para exercitar ``load()``."""
    path = directory / "artifact.pkl"
    with path.open("wb") as file:
        pickle.dump(artifact, file)
    return path


def sqlite_abt_engine() -> Engine:
    """Engine SQLite em memória com ``application_abt`` semeada.

    A linha 100002 traz ``inst_late_payment_rate`` presente (exercita o ramo em
    que ``setdefault`` não sobrescreve) e omite ``has_installments_history`` da
    tabela (exercita o ramo em que ``setdefault`` insere o valor padrão).
    """
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE application_abt ("
                "sk_id_curr INTEGER, target INTEGER, ext_source_1 REAL, "
                "occupation_type TEXT, inst_late_payment_rate REAL)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO application_abt VALUES "
                "(100002, 1, 0.5, 'Laborers', 0.3)"
            )
        )
    return engine
