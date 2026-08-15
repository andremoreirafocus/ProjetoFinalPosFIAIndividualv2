import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from Model.artifact_bundle_contract import MANIFEST_FILE_NAME
from Model.artifact_bundle_publisher import publish_bundle
from MLOps.app.api.artifact_bundle_loader import ArtifactBundleLoader
from MLOps.app.api.credit_policy import CreditPolicy
from MLOps.app.api.explanation_service import ExplanationService
from MLOps.app.api.feature_input_processor import FeatureInputProcessor
from MLOps.app.api.main import app
from MLOps.app.api.model_bundle_manager import ModelBundleManager
from MLOps.app.api.prediction_service import PredictionService
from MLOps.tests.fakes import FakeFeatureService, FakeModel
from MLOps.tests.fixtures import build_artifact, build_feature_reference


def _db_error() -> OperationalError:
    return OperationalError("SELECT 1", {}, Exception("conexão indisponível"))


@pytest.fixture
def client_factory(request):
    """Exercita a camada HTTP com um bundle publicado de verdade pelo fluxo real.

    O ``TestClient`` é usado sem ``with`` de propósito: assim o ``lifespan`` não roda e
    nenhum serviço real (engine de banco, laço de atualização) é criado. O manager e o
    loader são reais, operando sobre um bundle publicado por ``publish_bundle`` (etapa 3.2)
    num diretório temporário — só o estimador e o acesso às features usam implementações
    determinísticas de teste.
    """

    def build(
        feature_service: FakeFeatureService | None = None,
        *,
        score: float = 0.55,
        threshold: float = 0.5,
        bundle_available: bool = True,
    ) -> TestClient:
        temporary_directory = tempfile.TemporaryDirectory()
        request.addfinalizer(temporary_directory.cleanup)
        artifacts_dir = Path(temporary_directory.name)
        manifest_path = artifacts_dir / MANIFEST_FILE_NAME

        if bundle_available:
            publish_bundle(
                build_artifact(
                    model=FakeModel(positive_proba=score),
                    threshold=threshold,
                ),
                build_feature_reference(),
                artifacts_dir,
            )

        manager = ModelBundleManager(manifest_path, ArtifactBundleLoader())
        manager.refresh_if_changed()

        app.state.bundle_manager = manager
        app.state.feature_input_processor = FeatureInputProcessor()
        app.state.prediction_service = PredictionService()
        app.state.explanation_service = ExplanationService()
        app.state.feature_service = feature_service or FakeFeatureService(
            features={"ext_source_1": 0.5, "occupation_type": "Laborers"}
        )
        app.state.credit_policy = CreditPolicy(0.50, 0.60, "test-v1")

        client = TestClient(app)
        request.addfinalizer(client.close)
        return client

    return build


# --- /health ---------------------------------------------------------
def test_health_ok_when_model_loaded(client_factory) -> None:
    client = client_factory()
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["model_loaded"] is True


def test_health_unavailable_when_bundle_refresh_fails(client_factory) -> None:
    client = client_factory(bundle_available=False)
    response = client.get("/health")
    assert response.status_code == 503
    detail = response.json()["detail"]
    assert detail["message"] == "Modelo e referências ainda não estão disponíveis."
    assert MANIFEST_FILE_NAME in detail["last_error"]


# --- /model/features -------------------------------------------------
def test_model_features_lists_expected_features(client_factory) -> None:
    client = client_factory()
    response = client.get("/model/features")
    assert response.status_code == 200
    assert response.json() == ["ext_source_1", "occupation_type"]


# --- /customers/{id}/features ---------------------------------------
def test_customer_features_returns_row(client_factory) -> None:
    client = client_factory(
        feature_service=FakeFeatureService(features={"ext_source_1": 0.5})
    )
    response = client.get("/customers/100002/features")
    assert response.status_code == 200
    body = response.json()
    assert body["customer_id"] == 100002
    assert body["features"] == {"ext_source_1": 0.5}


def test_customer_features_not_found(client_factory) -> None:
    client = client_factory(feature_service=FakeFeatureService(features=None))
    response = client.get("/customers/999/features")
    assert response.status_code == 404


def test_customer_features_database_error(client_factory) -> None:
    client = client_factory(feature_service=FakeFeatureService(error=_db_error()))
    response = client.get("/customers/100002/features")
    assert response.status_code == 503


# --- /predict/features ----------------------------------------------
def test_predict_from_features_contract(client_factory) -> None:
    client = client_factory(score=0.55, threshold=0.5)
    response = client.post(
        "/predict/features",
        json={
            "features": {
                "ext_source_1": 0.5,
                "occupation_type": "Laborers",
            }
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "provided_features"
    assert body["customer_id"] is None
    assert body["risk_score"] == 0.55
    assert body["predicted_class"] == 1
    assert body["model_decision_threshold"] == 0.5
    # 0.55 cai na faixa [0.50, 0.60) -> revisão manual.
    assert body["policy"]["recommendation"] == "manual_review"
    assert body["policy"]["policy_version"] == "test-v1"
    assert body["explanation"] is not None
    assert body["explanation"]["output_scale"] == "raw_score"


def test_predict_from_features_missing_returns_422(client_factory) -> None:
    client = client_factory()
    response = client.post(
        "/predict/features", json={"features": {"ext_source_1": 0.5}}
    )
    assert response.status_code == 422
    assert response.json()["detail"]["missing_features"] == ["occupation_type"]


def test_predict_from_features_bundle_unavailable_returns_503(client_factory) -> None:
    client = client_factory(bundle_available=False)
    response = client.post(
        "/predict/features", json={"features": {"ext_source_1": 0.5}}
    )
    assert response.status_code == 503
    detail = response.json()["detail"]
    assert detail["message"] == "Modelo e referências ainda não estão disponíveis."
    assert MANIFEST_FILE_NAME in detail["last_error"]


# --- /predict/customer/{id} -----------------------------------------
def test_predict_from_database_uses_customer_source(client_factory) -> None:
    client = client_factory(
        feature_service=FakeFeatureService(
            features={
                "ext_source_1": 0.5,
                "occupation_type": "Laborers",
            }
        ),
        score=0.20,
    )
    response = client.post("/predict/customer/100002")
    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "database"
    assert body["customer_id"] == 100002
    # 0.20 < 0.50 -> aprovação.
    assert body["policy"]["recommendation"] == "approve"
    assert body["explanation"] is None


def test_predict_from_database_not_found_returns_404(client_factory) -> None:
    client = client_factory(feature_service=FakeFeatureService(features=None))
    response = client.post("/predict/customer/999")
    assert response.status_code == 404


def test_predict_from_database_error_returns_503(client_factory) -> None:
    client = client_factory(feature_service=FakeFeatureService(error=_db_error()))
    response = client.post("/predict/customer/100002")
    assert response.status_code == 503
