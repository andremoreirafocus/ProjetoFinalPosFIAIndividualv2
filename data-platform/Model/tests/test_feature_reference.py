import json
import pickle
from pathlib import Path

import pandas as pd
import pytest
from lightgbm import LGBMClassifier

from train import build_feature_reference, save_artifacts


TRAINED_AT_UTC = "2026-07-14T00:00:00+00:00"


@pytest.fixture
def X() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "income": [100.0, 200.0, 300.0, 400.0, 500.0, 600.0],
            "occupation": pd.Categorical(
                ["A", "A", "B", "B", "A", "B"], categories=["A", "B"]
            ),
        }
    )


@pytest.fixture
def y() -> pd.Series:
    return pd.Series([0, 0, 1, 0, 1, 1])


@pytest.fixture
def config() -> dict:
    return {
        "metadata": {"version": "test-v1"},
        "parameters": {
            "random_state": 123,
            "reference": {"shap_sample_size": 4},
        },
    }


@pytest.fixture
def model(X: pd.DataFrame, y: pd.Series) -> LGBMClassifier:
    return LGBMClassifier(
        n_estimators=3,
        num_leaves=3,
        min_child_samples=1,
        verbosity=-1,
        random_state=123,
    ).fit(X, y)


def test_builds_numeric_categorical_score_and_shap_references(
    model: LGBMClassifier, X: pd.DataFrame, y: pd.Series, config: dict
) -> None:
    feature_reference = build_feature_reference(
        model, X, y, ["occupation"], config, TRAINED_AT_UTC
    )

    assert feature_reference["model_version"] == config["metadata"]["version"]
    assert feature_reference["row_count"] == len(X)
    assert "income" in feature_reference["numeric_features"]
    assert feature_reference["categorical_features"]["occupation"]["count"]["A"] == 3
    assert (
        feature_reference["categorical_features"]["occupation"]["frequency"]["A"] == 0.5
    )
    assert (
        feature_reference["global_shap"]["sample_size"]
        == config["parameters"]["reference"]["shap_sample_size"]
    )
    assert len(feature_reference["global_shap"]["feature_importance"]) == len(X.columns)
    shap_feature = feature_reference["global_shap"]["feature_importance"][0]
    assert "p50_abs_shap" in shap_feature
    assert "p99_abs_shap" in shap_feature


def test_percentile_grid_uses_the_published_key_format(
    model: LGBMClassifier, X: pd.DataFrame, y: pd.Series, config: dict
) -> None:
    """O formato das chaves é contrato: a API o interpreta como ``int(key[1:])``."""
    feature_reference = build_feature_reference(
        model, X, y, ["occupation"], config, TRAINED_AT_UTC
    )

    percentiles = feature_reference["numeric_features"]["income"]["percentiles"]

    assert set(percentiles) == {f"p{rank:02d}" for rank in range(101)}


def test_adds_rates_only_to_binary_numeric_features(
    model: LGBMClassifier, X: pd.DataFrame, y: pd.Series, config: dict
) -> None:
    feature_reference = build_feature_reference(
        model, X, y, ["occupation"], config, TRAINED_AT_UTC
    )
    assert "binary_rates" not in feature_reference["numeric_features"]["income"]

    with_flag = X[["income"]].assign(binary_flag=[0, 0, 1, 0, 1, 1])
    binary_model = LGBMClassifier(
        n_estimators=3,
        min_child_samples=1,
        verbosity=-1,
        random_state=123,
    ).fit(with_flag, y)
    binary_reference = build_feature_reference(
        binary_model, with_flag, y, [], config, TRAINED_AT_UTC
    )

    assert binary_reference["numeric_features"]["binary_flag"]["binary_rates"] == {
        "overall": 0.5,
        "target_0": 0.0,
        "target_1": 1.0,
    }


def test_save_artifacts_persists_model_artifact_as_received_and_writes_reference(
    model: LGBMClassifier, X: pd.DataFrame, y: pd.Series, config: dict, tmp_path: Path
) -> None:
    feature_reference = build_feature_reference(
        model, X, y, ["occupation"], config, TRAINED_AT_UTC
    )
    model_artifact = {
        "model": model,
        "algorithm": "LightGBM",
        "hyperparameters": {},
        "decision_threshold": 0.5,
        "trained_at_utc": TRAINED_AT_UTC,
    }
    eval_model_metrics = {"roc_auc": 0.75}
    output_path = tmp_path / "model.pkl"

    save_artifacts(model_artifact, eval_model_metrics, feature_reference, output_path)

    saved_reference = json.loads(
        (tmp_path / "feature_reference.json").read_text(encoding="utf-8")
    )
    saved_eval_model_metrics = json.loads(
        (tmp_path / "eval_model_metrics.json").read_text(encoding="utf-8")
    )
    with output_path.open("rb") as file:
        saved_model_artifact = pickle.load(file)

    assert saved_reference["model_version"] == feature_reference["model_version"]
    assert saved_eval_model_metrics["test_metrics"] == eval_model_metrics
    assert sorted(saved_model_artifact) == sorted(model_artifact)
    assert output_path.is_file()
