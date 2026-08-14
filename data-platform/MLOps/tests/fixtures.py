"""Fixtures de dados para os testes da API (sem banco nem artefato treinado)."""
from __future__ import annotations

from dataclasses import dataclass
import pickle
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, create_engine, text

from MLOps.app.api.model_bundle import ModelBundle
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
        "config_version": "test-v1",
        "trained_at_utc": "2026-07-14T00:00:00+00:00",
    }
    return artifact


def build_model_bundle(
    estimator: Any | None = None,
    feature_order: list[str] | None = None,
    categorical_features: list[str] | None = None,
    categories: dict[str, list[str]] | None = None,
    decision_threshold: float = 0.5,
) -> ModelBundle:
    """Monta um ``ModelBundle`` coerente com o contrato da etapa 1 do plano de bundle."""
    return ModelBundle(
        bundle_id="bundle-test-v1",
        schema_version="1",
        model_version="test-v1",
        trained_at_utc="2026-07-14T00:00:00+00:00",
        model_path=Path("/bundles/bundle-test-v1/lightgbm_abt.pkl"),
        estimator=estimator if estimator is not None else FakeModel(),
        feature_order=(
            feature_order if feature_order is not None
            else ["ext_source_1", "occupation_type"]
        ),
        categorical_features=(
            categorical_features
            if categorical_features is not None
            else ["occupation_type"]
        ),
        categories=(
            categories
            if categories is not None
            else {"occupation_type": ["Laborers", "Managers"]}
        ),
        decision_threshold=decision_threshold,
        target_rate=0.08,
        numeric_references={},
        categorical_references={},
        global_shap={"feature_importance": []},
    )


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


@dataclass(frozen=True)
class CustomerFeatureFixture:
    engine: Engine
    selected_customer_id: int
    selected_customer_features: dict[str, Any]
    absent_customer_id: int


def sqlite_customer_feature_fixture() -> CustomerFeatureFixture:
    """Cenário SQLite para busca de um cliente específico na ABT."""
    selected_customer_id = 100002
    selected_customer_features = {
        "numeric_feature": 0.75,
        "categorical_feature": "Managers",
        "nullable_feature": None,
    }
    selected_customer = {
        "sk_id_curr": selected_customer_id,
        "target": 1,
        **selected_customer_features,
    }
    other_customer = {
        "sk_id_curr": 100001,
        "target": 0,
        "numeric_feature": 0.25,
        "categorical_feature": "Laborers",
        "nullable_feature": 1.0,
    }
    absent_customer_id = 999999

    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE application_abt ("
                "sk_id_curr INTEGER, target INTEGER, numeric_feature REAL, "
                "categorical_feature TEXT, nullable_feature REAL)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO application_abt VALUES "
                "(:sk_id_curr, :target, :numeric_feature, "
                ":categorical_feature, :nullable_feature)"
            ),
            [other_customer, selected_customer],
        )
    return CustomerFeatureFixture(
        engine=engine,
        selected_customer_id=selected_customer_id,
        selected_customer_features=selected_customer_features,
        absent_customer_id=absent_customer_id,
    )
