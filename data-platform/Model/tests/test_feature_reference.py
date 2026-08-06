import json
import pickle
import tempfile
import unittest
from pathlib import Path

import pandas as pd
from lightgbm import LGBMClassifier

from Model.train import build_feature_reference, save_artifacts


class FeatureReferenceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.X = pd.DataFrame(
            {
                "income": [100.0, 200.0, 300.0, 400.0, 500.0, 600.0],
                "occupation": pd.Categorical(
                    ["A", "A", "B", "B", "A", "B"], categories=["A", "B"]
                ),
            }
        )
        self.y = pd.Series([0, 0, 1, 0, 1, 1])
        self.model = LGBMClassifier(
            n_estimators=3,
            num_leaves=3,
            min_child_samples=1,
            verbosity=-1,
            random_state=123,
        ).fit(self.X, self.y)
        self.config = {
            "metadata": {"version": "test-v1"},
            "parameters": {
                "random_state": 123,
                "reference": {"shap_sample_size": 4},
            },
        }

    def test_builds_numeric_categorical_score_and_shap_references(self) -> None:
        feature_reference = build_feature_reference(
            self.model,
            self.X,
            self.y,
            ["occupation"],
            self.config,
            "2026-07-14T00:00:00+00:00",
        )

        self.assertEqual(feature_reference["model_version"], "test-v1")
        self.assertEqual(feature_reference["row_count"], 6)
        self.assertIn("income", feature_reference["numeric_features"])
        self.assertEqual(
            len(feature_reference["numeric_features"]["income"]["percentiles"]), 101
        )
        self.assertEqual(
            feature_reference["categorical_features"]["occupation"]["count"]["A"], 3
        )
        self.assertEqual(
            feature_reference["categorical_features"]["occupation"]["frequency"]["A"],
            0.5,
        )
        self.assertEqual(feature_reference["global_shap"]["sample_size"], 4)
        self.assertEqual(
            len(feature_reference["global_shap"]["feature_importance"]), 2
        )
        shap_feature = feature_reference["global_shap"]["feature_importance"][0]
        self.assertIn("p50_abs_shap", shap_feature)
        self.assertIn("p99_abs_shap", shap_feature)

    def test_adds_rates_only_to_binary_numeric_features(self) -> None:
        self.X["binary_flag"] = [0, 0, 1, 0, 1, 1]
        feature_reference = build_feature_reference(
            self.model,
            self.X[["income", "occupation"]],
            self.y,
            ["occupation"],
            self.config,
            "2026-07-14T00:00:00+00:00",
        )
        self.assertNotIn(
            "binary_rates", feature_reference["numeric_features"]["income"]
        )

        binary_model = LGBMClassifier(
            n_estimators=3,
            min_child_samples=1,
            verbosity=-1,
            random_state=123,
        ).fit(self.X[["income", "binary_flag"]], self.y)
        binary_reference = build_feature_reference(
            binary_model,
            self.X[["income", "binary_flag"]],
            self.y,
            [],
            self.config,
            "2026-07-14T00:00:00+00:00",
        )
        self.assertEqual(
            binary_reference["numeric_features"]["binary_flag"]["binary_rates"],
            {"overall": 0.5, "target_0": 0.0, "target_1": 1.0},
        )

    def test_save_artifacts_persists_model_artifact_as_received_and_writes_reference(self) -> None:
        feature_reference = build_feature_reference(
            self.model,
            self.X,
            self.y,
            ["occupation"],
            self.config,
            "2026-07-14T00:00:00+00:00",
        )
        model_artifact = {
            "model": self.model,
            "algorithm": "LightGBM",
            "hyperparameters": {},
            "decision_threshold": 0.5,
            "trained_at_utc": "2026-07-14T00:00:00+00:00",
        }
        eval_model_metrics = {"roc_auc": 0.75}

        with tempfile.TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "model.pkl"
            save_artifacts(
                model_artifact, eval_model_metrics, feature_reference, output_path
            )
            saved_reference = json.loads(
                (Path(tmp) / "feature_reference.json").read_text(encoding="utf-8")
            )
            saved_eval_model_metrics = json.loads(
                (Path(tmp) / "eval_model_metrics.json").read_text(encoding="utf-8")
            )
            with output_path.open("rb") as file:
                saved_model_artifact = pickle.load(file)

            self.assertEqual(
                saved_reference["model_version"],
                feature_reference["model_version"],
            )
            self.assertEqual(
                saved_eval_model_metrics["test_metrics"], eval_model_metrics
            )
            self.assertEqual(sorted(saved_model_artifact), sorted(model_artifact))
            self.assertTrue(output_path.is_file())


if __name__ == "__main__":
    unittest.main()
