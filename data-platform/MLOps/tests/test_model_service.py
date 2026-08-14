import pickle
import tempfile
from pathlib import Path

import pandas as pd
import pytest

from MLOps.app.api.model_service import ModelInputError, PredictionService
from MLOps.tests.fakes import FakeModel
from MLOps.tests.fixtures import build_artifact, write_artifact_pickle


def test_load_success_exposes_contract() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = write_artifact_pickle(Path(tmp), build_artifact(threshold=0.4))
        service = PredictionService(path)
        service.load()

        assert service.is_loaded
        assert service.expected_features == ["ext_source_1", "occupation_type"]
        assert service.decision_threshold == 0.4


def test_load_missing_file_raises() -> None:
    service = PredictionService(Path("/caminho/inexistente/model.pkl"))
    with pytest.raises(FileNotFoundError):
        service.load()


@pytest.mark.parametrize("case", ["sem_model", "sem_features"])
def test_load_missing_required_keys_raises(case: str) -> None:
    incomplete_artifacts = {
        "sem_model": {k: v for k, v in build_artifact().items() if k != "model"},
        "sem_features": {
            k: v for k, v in build_artifact().items() if k != "features"
        },
    }
    artifact = incomplete_artifacts[case]
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "artifact.pkl"
        with path.open("wb") as file:
            pickle.dump(artifact, file)
        with pytest.raises(ValueError):
            PredictionService(path).load()


def test_load_rejects_input_features_as_replacement_for_features() -> None:
    artifact = build_artifact()
    artifact["input_features"] = artifact.pop("features")
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "artifact.pkl"
        with path.open("wb") as file:
            pickle.dump(artifact, file)

        with pytest.raises(ValueError):
            PredictionService(path).load()


def test_property_access_before_load_raises() -> None:
    service = PredictionService(Path("/qualquer/model.pkl"))
    with pytest.raises(RuntimeError):
        _ = service.expected_features
    with pytest.raises(RuntimeError):
        _ = service.decision_threshold
    with pytest.raises(RuntimeError):
        service.predict({"ext_source_1": 0.0})


def _loaded_service(model: FakeModel, **kwargs) -> PredictionService:
    service = PredictionService(Path("/loaded/in/memory.pkl"))
    service.artifact = build_artifact(model=model, **kwargs)
    return service


@pytest.mark.parametrize("proba,expected_class", [(0.6, 1), (0.4, 0)])
def test_predict_returns_score_and_class_by_threshold(
    proba: float, expected_class: int
) -> None:
    service = _loaded_service(FakeModel(positive_proba=proba))
    score, predicted_class = service.predict(
        {"ext_source_1": 0.5, "occupation_type": "Managers"}
    )
    assert score == pytest.approx(proba)
    assert predicted_class == expected_class


def test_predict_rejects_missing_features() -> None:
    service = _loaded_service(FakeModel())
    with pytest.raises(ModelInputError) as excinfo:
        service.predict({"ext_source_1": 0.5})
    assert "occupation_type" in excinfo.value.missing_features


def test_predict_restores_categorical_dtype() -> None:
    model = FakeModel()
    service = _loaded_service(model)
    service.predict({"ext_source_1": 0.5, "occupation_type": "Managers"})

    received = model.received
    assert isinstance(received, pd.DataFrame)
    assert isinstance(received["occupation_type"].dtype, pd.CategoricalDtype)
    assert list(received["occupation_type"].cat.categories) == [
        "Laborers",
        "Managers",
    ]
    # Feature não-categórica é convertida para numérico.
    assert pd.api.types.is_numeric_dtype(received["ext_source_1"])
