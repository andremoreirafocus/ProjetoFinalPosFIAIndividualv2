import json
import tempfile
import unittest
from pathlib import Path
from threading import RLock

from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from MLOps.app.api.credit_policy import CreditPolicy
from MLOps.app.api.explanation_service import ExplanationService
from MLOps.app.api.main import app
from MLOps.app.api.model_service import PredictionService
from MLOps.tests.fakes import FakeFeatureService, FakeModel
from MLOps.tests.fixtures import (
    build_artifact,
    build_feature_reference,
    write_artifact_pickle,
)


def _db_error() -> OperationalError:
    return OperationalError("SELECT 1", {}, Exception("conexão indisponível"))


class ApiEndpointsTest(unittest.TestCase):
    """Exercita a camada HTTP com um bundle temporário carregado pelo fluxo real.

    O ``TestClient`` é usado sem ``with`` de propósito: assim o ``lifespan`` não
    roda e nenhum serviço real (engine de banco, tarefa de carga) é criado. Os
    serviços de modelo e explicação são reais; somente o estimador e o acesso às
    features usam implementações determinísticas de teste.
    """

    def _client(
        self,
        feature_service: FakeFeatureService | None = None,
        *,
        score: float = 0.55,
        threshold: float = 0.5,
        bundle_available: bool = True,
    ) -> TestClient:
        temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(temporary_directory.cleanup)
        directory = Path(temporary_directory.name)
        model_path = directory / "artifact.pkl"
        reference_path = directory / "feature_reference.json"

        if bundle_available:
            write_artifact_pickle(
                directory,
                build_artifact(
                    model=FakeModel(positive_proba=score),
                    threshold=threshold,
                ),
            )
            reference_path.write_text(
                json.dumps(build_feature_reference()),
                encoding="utf-8",
            )

        prediction_service = PredictionService(model_path)
        explanation_service = ExplanationService(
            prediction_service,
            reference_path,
        )
        app.state.prediction_service = prediction_service
        app.state.explanation_service = explanation_service
        app.state.feature_service = feature_service or FakeFeatureService(
            features={"ext_source_1": 0.5, "occupation_type": "Laborers"}
        )
        app.state.credit_policy = CreditPolicy(0.50, 0.60, "test-v1")
        app.state.model_load_error = None
        app.state.model_bundle_lock = RLock()
        app.state.model_bundle_auto_refresh = True
        app.state.model_bundle_signature = None

        client = TestClient(app)
        self.addCleanup(client.close)
        return client

    # --- /health ---------------------------------------------------------
    def test_health_ok_when_model_loaded(self) -> None:
        client = self._client()
        response = client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["model_loaded"], True)

    def test_health_unavailable_when_bundle_refresh_fails(self) -> None:
        client = self._client(bundle_available=False)
        response = client.get("/health")
        self.assertEqual(response.status_code, 503)
        detail = response.json()["detail"]
        self.assertEqual(
            detail["message"],
            "Modelo e referências ainda não estão disponíveis.",
        )
        self.assertIn("artifact.pkl", detail["last_error"])

    # --- /model/features -------------------------------------------------
    def test_model_features_lists_expected_features(self) -> None:
        client = self._client()
        response = client.get("/model/features")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), ["ext_source_1", "occupation_type"])

    # --- /customers/{id}/features ---------------------------------------
    def test_customer_features_returns_row(self) -> None:
        client = self._client(
            feature_service=FakeFeatureService(features={"ext_source_1": 0.5})
        )
        response = client.get("/customers/100002/features")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["customer_id"], 100002)
        self.assertEqual(body["features"], {"ext_source_1": 0.5})

    def test_customer_features_not_found(self) -> None:
        client = self._client(feature_service=FakeFeatureService(features=None))
        response = client.get("/customers/999/features")
        self.assertEqual(response.status_code, 404)

    def test_customer_features_database_error(self) -> None:
        client = self._client(
            feature_service=FakeFeatureService(error=_db_error())
        )
        response = client.get("/customers/100002/features")
        self.assertEqual(response.status_code, 503)

    # --- /predict/features ----------------------------------------------
    def test_predict_from_features_contract(self) -> None:
        client = self._client(score=0.55, threshold=0.5)
        response = client.post(
            "/predict/features",
            json={
                "features": {
                    "ext_source_1": 0.5,
                    "occupation_type": "Laborers",
                }
            },
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["source"], "provided_features")
        self.assertIsNone(body["customer_id"])
        self.assertEqual(body["risk_score"], 0.55)
        self.assertEqual(body["predicted_class"], 1)
        self.assertEqual(body["model_decision_threshold"], 0.5)
        # 0.55 cai na faixa [0.50, 0.60) -> revisão manual.
        self.assertEqual(body["policy"]["recommendation"], "manual_review")
        self.assertEqual(body["policy"]["policy_version"], "test-v1")
        self.assertIsNotNone(body["explanation"])
        self.assertEqual(body["explanation"]["output_scale"], "raw_score")

    def test_predict_from_features_missing_returns_422(self) -> None:
        client = self._client()
        response = client.post(
            "/predict/features", json={"features": {"ext_source_1": 0.5}}
        )
        self.assertEqual(response.status_code, 422)
        self.assertEqual(
            response.json()["detail"]["missing_features"],
            ["occupation_type"],
        )

    def test_predict_from_features_bundle_unavailable_returns_503(self) -> None:
        client = self._client(bundle_available=False)
        response = client.post(
            "/predict/features", json={"features": {"ext_source_1": 0.5}}
        )
        self.assertEqual(response.status_code, 503)
        detail = response.json()["detail"]
        self.assertEqual(
            detail["message"],
            "Modelo e referências ainda não estão disponíveis.",
        )
        self.assertIn("artifact.pkl", detail["last_error"])

    # --- /predict/customer/{id} -----------------------------------------
    def test_predict_from_database_uses_customer_source(self) -> None:
        client = self._client(
            feature_service=FakeFeatureService(
                features={
                    "ext_source_1": 0.5,
                    "occupation_type": "Laborers",
                }
            ),
            score=0.20,
        )
        response = client.post("/predict/customer/100002")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["source"], "database")
        self.assertEqual(body["customer_id"], 100002)
        # 0.20 < 0.50 -> aprovação.
        self.assertEqual(body["policy"]["recommendation"], "approve")
        self.assertIsNone(body["explanation"])

    def test_predict_from_database_not_found_returns_404(self) -> None:
        client = self._client(feature_service=FakeFeatureService(features=None))
        response = client.post("/predict/customer/999")
        self.assertEqual(response.status_code, 404)

    def test_predict_from_database_error_returns_503(self) -> None:
        client = self._client(
            feature_service=FakeFeatureService(error=_db_error())
        )
        response = client.post("/predict/customer/100002")
        self.assertEqual(response.status_code, 503)


if __name__ == "__main__":
    unittest.main()
