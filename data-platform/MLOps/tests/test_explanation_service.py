import json
import tempfile
from pathlib import Path

import pytest

from MLOps.app.api.explanation_service import ExplanationService
from MLOps.app.api.model_service import PredictionService
from MLOps.tests.fakes import FakeModel
from MLOps.tests.fixtures import build_artifact, build_feature_reference


def _service(directory: Path) -> ExplanationService:
    prediction_service = PredictionService(Path("/loaded/in/memory.pkl"))
    prediction_service.artifact = build_artifact(model=FakeModel())
    reference_path = directory / "feature_reference.json"
    reference_path.write_text(
        json.dumps(build_feature_reference()), encoding="utf-8"
    )
    return ExplanationService(prediction_service, reference_path)


def test_returns_ranked_local_shap_contributions() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        explanation = _service(Path(tmp)).explain(
            {"ext_source_1": 0.5, "occupation_type": "Managers"}
        )

    assert explanation["base_value"] == -0.4
    assert explanation["output_scale"] == "raw_score"
    assert [factor["feature"] for factor in explanation["top_factors"]] == [
        "ext_source_1",
        "occupation_type",
    ]
    assert explanation["top_factors"][0]["direction"] == "increases_risk"
    assert explanation["top_factors"][1]["direction"] == "reduces_risk"
    numeric = explanation["top_factors"][0]["comparison"]["numeric"]
    assert numeric["training_percentile_low"] == 50.0
    assert numeric["training_percentile_high"] == 50.0
    shap = explanation["top_factors"][0]["comparison"]["shap"]
    assert shap["abs_shap_percentile_low"] == 75
    assert shap["abs_shap_percentile_high"] == 90
    categorical = explanation["top_factors"][1]["comparison"]["categorical"]
    assert categorical["category_count"] == 40
    assert categorical["category_default_rate"] == 0.05


def test_rejects_reference_from_another_model_version() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        service = _service(Path(tmp))
        service.load_reference()
        service.reference["model_version"] = "another-version"
        with pytest.raises(ValueError):
            service.explain({"ext_source_1": 0.5, "occupation_type": "Managers"})
