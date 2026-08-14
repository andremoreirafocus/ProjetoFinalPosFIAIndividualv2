import importlib.util
from pathlib import Path

import pandas as pd
import pytest

from Model.predict import load_artifact, predict_score
from MLOps.tests.sample_features import build_features_from_artifact


DATA_PLATFORM_DIR = Path(__file__).resolve().parents[2]
ARTIFACT_PATH = DATA_PLATFORM_DIR / "Model" / "artifacts" / "lightgbm_abt.pkl"
ARTIFACT_READY = (
    ARTIFACT_PATH.is_file() and importlib.util.find_spec("lightgbm") is not None
)


@pytest.fixture(scope="module")
def artifact() -> dict:
    return load_artifact(ARTIFACT_PATH)


@pytest.mark.skipif(
    not ARTIFACT_READY,
    reason="Teste de integração: requer o artefato lightgbm_abt.pkl e o LightGBM instalado.",
)
def test_predicts_single_row(artifact: dict) -> None:
    features = build_features_from_artifact(artifact)
    row = pd.DataFrame([features])
    result = predict_score(row, artifact)

    assert result["risk_score"] >= 0
    assert result["risk_score"] <= 1
    assert result["predicted_class"] in {0, 1}
    assert result["decision_threshold"] == 0.5
