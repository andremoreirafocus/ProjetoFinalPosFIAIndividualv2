import pandas as pd
import pytest

from feature_reference import build_feature_reference
from train import train


@pytest.fixture
def X() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "income": [
                100.0, 200.0, 300.0, 400.0, 500.0, 600.0, 150.0, 250.0,
            ],
            "occupation": pd.Categorical(
                ["A", "A", "B", "B", "A", "B", "A", "B"], categories=["A", "B"]
            ),
        }
    )


@pytest.fixture
def y() -> pd.Series:
    return pd.Series([0, 0, 1, 0, 1, 1, 0, 1])


@pytest.fixture
def config() -> dict:
    return {
        "metadata": {"version": "test-v1"},
        "variables": {"categorical_features": ["occupation"]},
        "parameters": {
            "random_state": 123,
            "split": {"test_size": 0.25, "stratify": True},
            "classifier": {
                "algorithm": "LightGBM",
                "hyperparameters": {
                    "n_estimators": 3,
                    "num_leaves": 3,
                    "min_child_samples": 1,
                },
            },
            "inference": {"decision_threshold": 0.5},
            "reference": {"shap_sample_size": 4},
        },
    }


def test_train_receives_data_ready_and_does_not_read_the_database(
    config: dict, X: pd.DataFrame, y: pd.Series
) -> None:
    """``train()`` recebe ``X, y`` prontos; nada aqui abre conexão com o banco."""
    model_artifact, eval_model_metrics = train(config, X, y)

    assert model_artifact["config_version"] == config["metadata"]["version"]
    assert model_artifact["features"] == list(X.columns)
    assert model_artifact["categorical_features"] == ["occupation"]
    assert set(eval_model_metrics) == {
        "roc_auc", "gini", "ks", "average_precision", "brier"
    }


def test_feature_reference_built_from_trains_output_describes_the_same_population(
    config: dict, X: pd.DataFrame, y: pd.Series
) -> None:
    """O baseline montado a partir do artefato de ``train()`` descreve a mesma
    população usada no ajuste do modelo final, não um recorte diferente."""
    model_artifact, _ = train(config, X, y)

    feature_reference = build_feature_reference(
        model_artifact["model"],
        X,
        y,
        model_artifact["categorical_features"],
        config["metadata"]["version"],
        model_artifact["trained_at_utc"],
        config["parameters"]["reference"]["shap_sample_size"],
        config["parameters"]["random_state"],
    )

    assert feature_reference["row_count"] == len(X)
    assert feature_reference["target_rate"] == pytest.approx(y.mean())
    assert feature_reference["model_version"] == model_artifact["config_version"]
    assert feature_reference["trained_at_utc"] == model_artifact["trained_at_utc"]
