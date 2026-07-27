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
from MLOps.tests.fakes import FakeModel, RetryFakeService
from MLOps.tests.fixtures import build_artifact, build_feature_reference


class LoadModelWithRetryTest(unittest.IsolatedAsyncioTestCase):
    async def test_retries_until_model_loads(self) -> None:
        # ``app`` real e leve (não é mock): só precisa de ``state.model_load_error``.
        app = types.SimpleNamespace(
            state=types.SimpleNamespace(model_load_error=None)
        )
        service = RetryFakeService(failures_before_success=1)

        await _load_model_with_retry(app, service, retry_seconds=0.01)

        # Falhou uma vez (ramo de erro) e carregou na segunda (ramo de sucesso).
        self.assertTrue(service.is_loaded)
        self.assertEqual(service.load_calls, 2)
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


if __name__ == "__main__":
    unittest.main()
