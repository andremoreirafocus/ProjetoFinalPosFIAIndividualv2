import pickle
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from MLOps.app.api.model_service import ModelInputError, PredictionService
from MLOps.tests.fakes import FakeModel
from MLOps.tests.fixtures import build_artifact, write_artifact_pickle


class PredictionServiceLoadTest(unittest.TestCase):
    def test_load_success_exposes_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = write_artifact_pickle(Path(tmp), build_artifact(threshold=0.4))
            service = PredictionService(path)
            service.load()

            self.assertTrue(service.is_loaded)
            self.assertEqual(
                service.expected_features, ["ext_source_1", "occupation_type"]
            )
            self.assertEqual(service.decision_threshold, 0.4)

    def test_load_missing_file_raises(self) -> None:
        service = PredictionService(Path("/caminho/inexistente/model.pkl"))
        with self.assertRaises(FileNotFoundError):
            service.load()

    def test_load_missing_required_keys_raises(self) -> None:
        incomplete_artifacts = {
            "sem_model": {k: v for k, v in build_artifact().items() if k != "model"},
            "sem_features": {
                k: v for k, v in build_artifact().items() if k != "features"
            },
        }
        for name, artifact in incomplete_artifacts.items():
            with self.subTest(case=name):
                with tempfile.TemporaryDirectory() as tmp:
                    path = Path(tmp) / "artifact.pkl"
                    with path.open("wb") as file:
                        pickle.dump(artifact, file)
                    with self.assertRaises(ValueError):
                        PredictionService(path).load()

    def test_load_rejects_input_features_as_replacement_for_features(self) -> None:
        artifact = build_artifact()
        artifact["input_features"] = artifact.pop("features")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "artifact.pkl"
            with path.open("wb") as file:
                pickle.dump(artifact, file)

            with self.assertRaises(ValueError):
                PredictionService(path).load()

    def test_property_access_before_load_raises(self) -> None:
        service = PredictionService(Path("/qualquer/model.pkl"))
        with self.assertRaises(RuntimeError):
            _ = service.expected_features
        with self.assertRaises(RuntimeError):
            _ = service.decision_threshold
        with self.assertRaises(RuntimeError):
            service.predict({"ext_source_1": 0.0})


class PredictionServicePredictTest(unittest.TestCase):
    def _loaded_service(self, model: FakeModel, **kwargs) -> PredictionService:
        service = PredictionService(Path("/loaded/in/memory.pkl"))
        service.artifact = build_artifact(model=model, **kwargs)
        return service

    def test_predict_returns_score_and_class_by_threshold(self) -> None:
        cases = [(0.6, 1), (0.4, 0)]  # proba positiva, classe esperada (threshold 0.5)
        for proba, expected_class in cases:
            with self.subTest(proba=proba):
                service = self._loaded_service(FakeModel(positive_proba=proba))
                score, predicted_class = service.predict(
                    {"ext_source_1": 0.5, "occupation_type": "Managers"}
                )
                self.assertAlmostEqual(score, proba)
                self.assertEqual(predicted_class, expected_class)

    def test_predict_rejects_missing_features(self) -> None:
        service = self._loaded_service(FakeModel())
        with self.assertRaises(ModelInputError) as ctx:
            service.predict({"ext_source_1": 0.5})
        self.assertIn("occupation_type", ctx.exception.missing_features)

    def test_predict_restores_categorical_dtype(self) -> None:
        model = FakeModel()
        service = self._loaded_service(model)
        service.predict({"ext_source_1": 0.5, "occupation_type": "Managers"})

        received = model.received
        self.assertIsInstance(received, pd.DataFrame)
        self.assertIsInstance(received["occupation_type"].dtype, pd.CategoricalDtype)
        self.assertEqual(
            list(received["occupation_type"].cat.categories),
            ["Laborers", "Managers"],
        )
        # Feature não-categórica é convertida para numérico.
        self.assertTrue(pd.api.types.is_numeric_dtype(received["ext_source_1"]))

if __name__ == "__main__":
    unittest.main()
