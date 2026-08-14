import asyncio
from contextlib import suppress
import json
import pickle
import tempfile
import threading
import types
from pathlib import Path

import pytest

from MLOps.app.api.explanation_service import ExplanationService
from MLOps.app.api.main import _load_model_with_retry, _refresh_model_bundle
from MLOps.app.api.model_service import PredictionService
from MLOps.tests.fakes import FakeModel
from MLOps.tests.fixtures import build_artifact, build_feature_reference


@pytest.mark.asyncio
async def test_retries_until_complete_bundle_loads() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        directory = Path(tmp)
        model_path = directory / "lightgbm_abt.pkl"
        reference_path = directory / "feature_reference.json"
        prediction_service = PredictionService(model_path)
        explanation_service = ExplanationService(
            prediction_service,
            reference_path,
        )
        app = types.SimpleNamespace(
            state=types.SimpleNamespace(
                model_bundle_lock=threading.RLock(),
                model_bundle_signature=None,
                model_load_error=None,
            )
        )

        load_task = asyncio.create_task(
            _load_model_with_retry(
                app,
                prediction_service,
                retry_seconds=0.01,
                explanation_service=explanation_service,
            )
        )
        try:
            for _ in range(100):
                if app.state.model_load_error is not None:
                    break
                await asyncio.sleep(0.001)
            assert app.state.model_load_error is not None

            with model_path.open("wb") as file:
                pickle.dump(build_artifact(model=FakeModel()), file)
            reference_path.write_text(
                json.dumps(build_feature_reference()),
                encoding="utf-8",
            )

            await asyncio.wait_for(load_task, timeout=1)
        finally:
            if not load_task.done():
                load_task.cancel()
                with suppress(asyncio.CancelledError):
                    await load_task

        assert prediction_service.is_loaded
        assert explanation_service.reference is not None
        assert (
            explanation_service.reference["model_version"]
            == prediction_service.config_version
        )
        assert app.state.model_load_error is None


def _write_pair(model_path: Path, reference_path: Path, trained_at_utc: str) -> None:
    artifact = build_artifact(model=FakeModel())
    artifact["trained_at_utc"] = trained_at_utc
    with model_path.open("wb") as file:
        pickle.dump(artifact, file)
    reference = build_feature_reference()
    reference["trained_at_utc"] = trained_at_utc
    reference_path.write_text(json.dumps(reference), encoding="utf-8")


def test_keeps_previous_pair_until_both_new_files_match() -> None:
    first_training = "2026-07-14T00:00:00+00:00"
    second_training = "2026-07-15T00:00:00+00:00"
    with tempfile.TemporaryDirectory() as tmp:
        directory = Path(tmp)
        model_path = directory / "lightgbm_abt.pkl"
        reference_path = directory / "feature_reference.json"
        _write_pair(model_path, reference_path, first_training)
        prediction_service = PredictionService(model_path)
        explanation_service = ExplanationService(prediction_service, reference_path)
        app = types.SimpleNamespace(
            state=types.SimpleNamespace(
                model_bundle_lock=threading.RLock(),
                model_bundle_signature=None,
                model_load_error=None,
            )
        )

        assert _refresh_model_bundle(app, prediction_service, explanation_service)

        artifact = build_artifact(model=FakeModel())
        artifact["trained_at_utc"] = second_training
        with model_path.open("wb") as file:
            pickle.dump(artifact, file)

        assert not _refresh_model_bundle(app, prediction_service, explanation_service)
        assert prediction_service.trained_at_utc == first_training

        reference = build_feature_reference()
        reference["trained_at_utc"] = second_training
        reference_path.write_text(json.dumps(reference), encoding="utf-8")

        assert _refresh_model_bundle(app, prediction_service, explanation_service)
        assert prediction_service.trained_at_utc == second_training
        assert explanation_service.reference["trained_at_utc"] == second_training


def test_keeps_loaded_bundle_when_one_file_is_temporarily_missing() -> None:
    trained_at_utc = "2026-07-14T00:00:00+00:00"
    with tempfile.TemporaryDirectory() as tmp:
        directory = Path(tmp)
        model_path = directory / "lightgbm_abt.pkl"
        reference_path = directory / "feature_reference.json"
        _write_pair(model_path, reference_path, trained_at_utc)
        prediction_service = PredictionService(model_path)
        explanation_service = ExplanationService(prediction_service, reference_path)
        app = types.SimpleNamespace(
            state=types.SimpleNamespace(
                model_bundle_lock=threading.RLock(),
                model_bundle_signature=None,
                model_load_error=None,
            )
        )

        assert _refresh_model_bundle(app, prediction_service, explanation_service)

        reference_path.unlink()

        assert not _refresh_model_bundle(app, prediction_service, explanation_service)
        assert prediction_service.trained_at_utc == trained_at_utc
        assert explanation_service.reference["trained_at_utc"] == trained_at_utc
        assert "feature_reference.json" in app.state.model_load_error


def _remove_statistical_reference(reference: dict) -> None:
    del reference["numeric_features"]["ext_source_1"]


def _remove_global_shap_reference(reference: dict) -> None:
    reference["global_shap"]["feature_importance"] = [
        item
        for item in reference["global_shap"]["feature_importance"]
        if item["feature"] != "ext_source_1"
    ]


def _duplicate_feature_type(reference: dict) -> None:
    reference["categorical_features"]["ext_source_1"] = {}


@pytest.mark.parametrize(
    "change_reference",
    [
        _remove_statistical_reference,
        _remove_global_shap_reference,
        _duplicate_feature_type,
    ],
    ids=[
        "missing statistical reference",
        "missing global SHAP reference",
        "feature in two reference types",
    ],
)
def test_rejects_reference_incompatible_with_model_features(change_reference) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        directory = Path(tmp)
        model_path = directory / "lightgbm_abt.pkl"
        reference_path = directory / "feature_reference.json"
        with model_path.open("wb") as file:
            pickle.dump(build_artifact(model=FakeModel()), file)
        reference = build_feature_reference()
        change_reference(reference)
        reference_path.write_text(json.dumps(reference), encoding="utf-8")
        prediction_service = PredictionService(model_path)
        explanation_service = ExplanationService(prediction_service, reference_path)
        app = types.SimpleNamespace(
            state=types.SimpleNamespace(
                model_bundle_lock=threading.RLock(),
                model_bundle_signature=None,
                model_load_error=None,
            )
        )

        with pytest.raises(ValueError):
            _refresh_model_bundle(app, prediction_service, explanation_service)

        assert not prediction_service.is_loaded
        assert explanation_service.reference is None


def test_accepts_extra_references_and_logs_warning(caplog) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        directory = Path(tmp)
        model_path = directory / "lightgbm_abt.pkl"
        reference_path = directory / "feature_reference.json"
        with model_path.open("wb") as file:
            pickle.dump(build_artifact(model=FakeModel()), file)
        reference = build_feature_reference()
        reference["numeric_features"]["legacy_feature"] = {}
        reference["global_shap"]["feature_importance"].append(
            {"feature": "legacy_feature"}
        )
        reference_path.write_text(json.dumps(reference), encoding="utf-8")
        prediction_service = PredictionService(model_path)
        explanation_service = ExplanationService(prediction_service, reference_path)
        app = types.SimpleNamespace(
            state=types.SimpleNamespace(
                model_bundle_lock=threading.RLock(),
                model_bundle_signature=None,
                model_load_error=None,
            )
        )

        with caplog.at_level("WARNING"):
            loaded = _refresh_model_bundle(
                app, prediction_service, explanation_service
            )

        assert loaded
        assert prediction_service.is_loaded
        assert explanation_service.reference is not None
        assert any("legacy_feature" in message for message in caplog.messages)
