import asyncio
from contextlib import suppress
import json
import pickle
import tempfile
import threading
import types
import unittest
from pathlib import Path

from MLOps.app.api.explanation_service import ExplanationService
from MLOps.app.api.main import _load_model_with_retry, _refresh_model_bundle
from MLOps.app.api.model_service import PredictionService
from MLOps.tests.fakes import FakeModel
from MLOps.tests.fixtures import build_artifact, build_feature_reference


class LoadModelWithRetryTest(unittest.IsolatedAsyncioTestCase):
    async def test_retries_until_complete_bundle_loads(self) -> None:
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
                self.assertIsNotNone(app.state.model_load_error)

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

            self.assertTrue(prediction_service.is_loaded)
            self.assertIsNotNone(explanation_service.reference)
            self.assertEqual(
                explanation_service.reference["model_version"],
                prediction_service.config_version,
            )
            self.assertIsNone(app.state.model_load_error)


class RefreshModelBundleTest(unittest.TestCase):
    def _write_pair(
        self,
        model_path: Path,
        reference_path: Path,
        trained_at_utc: str,
    ) -> None:
        artifact = build_artifact(model=FakeModel())
        artifact["trained_at_utc"] = trained_at_utc
        with model_path.open("wb") as file:
            pickle.dump(artifact, file)
        reference = build_feature_reference()
        reference["trained_at_utc"] = trained_at_utc
        reference_path.write_text(json.dumps(reference), encoding="utf-8")

    def test_keeps_previous_pair_until_both_new_files_match(self) -> None:
        first_training = "2026-07-14T00:00:00+00:00"
        second_training = "2026-07-15T00:00:00+00:00"
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            model_path = directory / "lightgbm_abt.pkl"
            reference_path = directory / "feature_reference.json"
            self._write_pair(
                model_path, reference_path, first_training
            )
            prediction_service = PredictionService(model_path)
            explanation_service = ExplanationService(
                prediction_service, reference_path
            )
            app = types.SimpleNamespace(
                state=types.SimpleNamespace(
                    model_bundle_lock=threading.RLock(),
                    model_bundle_signature=None,
                    model_load_error=None,
                )
            )

            self.assertTrue(
                _refresh_model_bundle(
                    app, prediction_service, explanation_service
                )
            )

            artifact = build_artifact(model=FakeModel())
            artifact["trained_at_utc"] = second_training
            with model_path.open("wb") as file:
                pickle.dump(artifact, file)

            self.assertFalse(
                _refresh_model_bundle(
                    app, prediction_service, explanation_service
                )
            )
            self.assertEqual(
                prediction_service.trained_at_utc, first_training
            )

            reference = build_feature_reference()
            reference["trained_at_utc"] = second_training
            reference_path.write_text(json.dumps(reference), encoding="utf-8")

            self.assertTrue(
                _refresh_model_bundle(
                    app, prediction_service, explanation_service
                )
            )
            self.assertEqual(
                prediction_service.trained_at_utc, second_training
            )
            self.assertEqual(
                explanation_service.reference["trained_at_utc"], second_training
            )

    def test_keeps_loaded_bundle_when_one_file_is_temporarily_missing(self) -> None:
        trained_at_utc = "2026-07-14T00:00:00+00:00"
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            model_path = directory / "lightgbm_abt.pkl"
            reference_path = directory / "feature_reference.json"
            self._write_pair(model_path, reference_path, trained_at_utc)
            prediction_service = PredictionService(model_path)
            explanation_service = ExplanationService(
                prediction_service, reference_path
            )
            app = types.SimpleNamespace(
                state=types.SimpleNamespace(
                    model_bundle_lock=threading.RLock(),
                    model_bundle_signature=None,
                    model_load_error=None,
                )
            )

            self.assertTrue(
                _refresh_model_bundle(
                    app, prediction_service, explanation_service
                )
            )

            reference_path.unlink()

            self.assertFalse(
                _refresh_model_bundle(
                    app, prediction_service, explanation_service
                )
            )
            self.assertEqual(
                prediction_service.trained_at_utc, trained_at_utc
            )
            self.assertEqual(
                explanation_service.reference["trained_at_utc"],
                trained_at_utc,
            )
            self.assertIn(
                "feature_reference.json",
                app.state.model_load_error,
            )


if __name__ == "__main__":
    unittest.main()
