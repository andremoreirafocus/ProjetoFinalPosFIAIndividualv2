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
from MLOps.app.api.new_customer_feature_transformation_service import (
    TransformationRuleMismatchError,
)
from MLOps.app.api.prediction_service import PredictionService
from MLOps.tests.fakes import (
    FakeFeatureService,
    FakeModel,
    FakeNewCustomerFeatureTransformationService,
)
from MLOps.tests.fixtures import (
    build_artifact,
    build_feature_reference,
    build_transformation_contract,
)


def _db_error() -> OperationalError:
    return OperationalError("SELECT 1", {}, Exception("conexão indisponível"))


# Registro bruto completo de `NewCustomerApplication`, com valores representativos;
# cada teste sobrescreve os campos que precisa deixar como `null`.
VALID_NEW_CUSTOMER_APPLICATION = {
    "amt_credit": 450000.0,
    "region_rating_client_w_city": 2,
    "days_id_publish": -2500,
    "days_registration": -3500,
    "days_birth": -13000,
    "days_employed": -1800,
    "ext_source_1": 0.6,
    "ext_source_2": 0.5,
    "ext_source_3": 0.55,
    "days_last_phone_change": -300.0,
    "cnt_fam_members": 3.0,
    "amt_annuity": 28000.0,
    "amt_income_total": 180000.0,
    "reg_city_not_work_city": 1,
    "reg_city_not_live_city": 0,
    "live_city_not_work_city": 0,
    "def_60_cnt_social_circle": 1.0,
    "amt_req_credit_bureau_year": 2.0,
    "cnt_children": 1,
    "flag_own_car": "Y",
    "own_car_age": 5.0,
    "occupation_type": "Laborers",
    "organization_type": "Business Entity Type 3",
    "name_income_type": "Working",
    "name_education_type": "Secondary",
    "code_gender": "F",
}


@pytest.fixture
def client_factory(request):
    """Exercita a camada HTTP com um bundle publicado de verdade pelo fluxo real.

    O ``TestClient`` é usado sem ``with`` de propósito: assim o ``lifespan`` não roda e
    nenhum serviço real (engine de banco, laço de atualização) é criado. O manager e o
    loader são reais, operando sobre um bundle publicado por ``publish_bundle`` num
    diretório temporário — só o estimador e o acesso às features usam implementações
    determinísticas de teste.
    """

    def build(
        feature_service: FakeFeatureService | None = None,
        *,
        new_customer_feature_transformation_service: (
            FakeNewCustomerFeatureTransformationService | None
        ) = None,
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
                build_transformation_contract(),
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
        app.state.new_customer_feature_transformation_service = (
            new_customer_feature_transformation_service
            or FakeNewCustomerFeatureTransformationService(
                features={"ext_source_1": 0.5, "occupation_type": "Laborers"}
            )
        )

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


# --- /predict/new-customer --------------------------------------------
def test_predict_from_new_customer_contract(client_factory) -> None:
    fake_service = FakeNewCustomerFeatureTransformationService(
        features={"ext_source_1": 0.5, "occupation_type": "Laborers"}
    )
    client = client_factory(
        new_customer_feature_transformation_service=fake_service, score=0.20, threshold=0.5
    )
    response = client.post("/predict/new-customer", json=VALID_NEW_CUSTOMER_APPLICATION)
    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "new_customer_transformed_application"
    assert body["customer_id"] is None
    # 0.20 < 0.50 -> aprovação.
    assert body["policy"]["recommendation"] == "approve"
    assert fake_service.received[1] == VALID_NEW_CUSTOMER_APPLICATION


def test_predict_from_new_customer_missing_employment_is_substituted_with_the_bundles_sentinel(
    client_factory,
) -> None:
    fake_service = FakeNewCustomerFeatureTransformationService(
        features={"ext_source_1": 0.5, "occupation_type": "Laborers"}
    )
    client = client_factory(new_customer_feature_transformation_service=fake_service)
    payload = {**VALID_NEW_CUSTOMER_APPLICATION, "days_employed": None}

    response = client.post("/predict/new-customer", json=payload)

    assert response.status_code == 200
    expected_sentinel = build_transformation_contract()["employment_days_anomaly_sentinel"]
    assert fake_service.received[1]["days_employed"] == expected_sentinel


def test_predict_from_new_customer_employment_zero_is_not_confused_with_no_employment(
    client_factory,
) -> None:
    """`0` é uma resposta real (recém-contratado) — não pode ser tratado como `None`
    (checagem tem que ser `is None`, nunca truthiness)."""
    fake_service = FakeNewCustomerFeatureTransformationService(
        features={"ext_source_1": 0.5, "occupation_type": "Laborers"}
    )
    client = client_factory(new_customer_feature_transformation_service=fake_service)
    payload = {**VALID_NEW_CUSTOMER_APPLICATION, "days_employed": 0}

    response = client.post("/predict/new-customer", json=payload)

    assert response.status_code == 200
    assert fake_service.received[1]["days_employed"] == 0


def test_predict_from_new_customer_missing_required_field_returns_422(client_factory) -> None:
    client = client_factory()
    payload = {
        key: value
        for key, value in VALID_NEW_CUSTOMER_APPLICATION.items()
        if key != "amt_credit"
    }
    response = client.post("/predict/new-customer", json=payload)
    assert response.status_code == 422


def test_predict_from_new_customer_accepts_null_optional_fields(client_factory) -> None:
    fake_service = FakeNewCustomerFeatureTransformationService(
        features={"ext_source_1": 0.5, "occupation_type": "Laborers"}
    )
    client = client_factory(new_customer_feature_transformation_service=fake_service)
    payload = {**VALID_NEW_CUSTOMER_APPLICATION, "ext_source_1": None, "flag_own_car": None}

    response = client.post("/predict/new-customer", json=payload)

    assert response.status_code == 200
    assert response.json()["source"] == "new_customer_transformed_application"
    assert fake_service.received[1]["ext_source_1"] is None
    assert fake_service.received[1]["flag_own_car"] is None


def test_predict_from_new_customer_bundle_unavailable_returns_503(client_factory) -> None:
    client = client_factory(bundle_available=False)
    response = client.post("/predict/new-customer", json=VALID_NEW_CUSTOMER_APPLICATION)
    assert response.status_code == 503
    detail = response.json()["detail"]
    assert detail["message"] == "Modelo e referências ainda não estão disponíveis."


def test_predict_from_new_customer_database_error_returns_503_with_its_own_message(
    client_factory,
) -> None:
    fake_service = FakeNewCustomerFeatureTransformationService(error=_db_error())
    client = client_factory(new_customer_feature_transformation_service=fake_service)

    response = client.post("/predict/new-customer", json=VALID_NEW_CUSTOMER_APPLICATION)

    assert response.status_code == 503
    detail = response.json()["detail"]
    assert detail != "Não foi possível consultar as fontes de dados do cliente."


def test_predict_from_new_customer_hash_mismatch_returns_503_naming_the_file(
    client_factory,
) -> None:
    fake_service = FakeNewCustomerFeatureTransformationService(
        error=TransformationRuleMismatchError(
            "'application_sanitization_projection.sql' da imagem diverge do contrato do "
            "bundle ativo: calculado aaa, publicado bbb."
        )
    )
    client = client_factory(new_customer_feature_transformation_service=fake_service)

    response = client.post("/predict/new-customer", json=VALID_NEW_CUSTOMER_APPLICATION)

    assert response.status_code == 503
    assert "application_sanitization_projection.sql" in response.json()["detail"]
