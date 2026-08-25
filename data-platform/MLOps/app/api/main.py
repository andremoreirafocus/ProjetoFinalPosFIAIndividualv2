import asyncio
from contextlib import asynccontextmanager
from contextlib import suppress
from dataclasses import asdict
import json
import logging

from fastapi import FastAPI, HTTPException, Request
from sqlalchemy.exc import SQLAlchemyError

from infra.db import get_database_engine

from .artifact_bundle_loader import ArtifactBundleLoader
from .config import DATA_PLATFORM_DIR, settings
from .credit_policy import CreditPolicy
from .explanation_service import ExplanationService
from .feature_input_processor import FeatureInputProcessor, ModelInputError
from .feature_service import CustomerFeatureService, CustomerNotFoundError
from .model_bundle import ModelBundle
from .model_bundle_manager import ModelBundleManager
from .new_customer_feature_transformation_service import (
    NewCustomerFeatureTransformationService,
)
from .prediction_service import PredictionService
from .schemas import (
    CustomerFeaturesResponse,
    FeaturePredictionRequest,
    HealthResponse,
    PredictionResponse,
)


logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.validate()

    loader = ArtifactBundleLoader()
    manager = ModelBundleManager(settings.manifest_path, loader)
    database_engine = get_database_engine(settings.database_url, pool_pre_ping=True)
    feature_service = CustomerFeatureService(database_engine)
    credit_policy = CreditPolicy(
        approve_max_score=settings.approve_max_score,
        manual_review_max_score=settings.manual_review_max_score,
        version=settings.policy_version,
    )
    new_customer_feature_transformation_service = NewCustomerFeatureTransformationService(
        database_engine, DATA_PLATFORM_DIR / "DataPipeline" / "sql"
    )

    app.state.bundle_manager = manager
    app.state.feature_service = feature_service
    app.state.feature_input_processor = FeatureInputProcessor()
    app.state.prediction_service = PredictionService()
    app.state.explanation_service = ExplanationService()
    app.state.credit_policy = credit_policy
    app.state.new_customer_feature_transformation_service = (
        new_customer_feature_transformation_service
    )

    refresh_seconds = float(settings.model_bundle_refresh_seconds)
    refresh_task = asyncio.create_task(_refresh_loop(manager, refresh_seconds))

    try:
        yield
    finally:
        refresh_task.cancel()
        with suppress(asyncio.CancelledError):
            await refresh_task
        database_engine.dispose()


async def _refresh_loop(manager: ModelBundleManager, refresh_seconds: float) -> None:
    """Um único laço contínuo por processo: atualiza, espera, repete até o shutdown.

    O manager nunca propaga exceção de candidato inválido — preserva o bundle anterior e
    registra o erro em seu próprio estado, consultável por ``status()``.
    """
    while True:
        await asyncio.to_thread(manager.refresh_if_changed)
        await asyncio.sleep(refresh_seconds)


app = FastAPI(
    title="API de Risco de Crédito",
    description=(
        "Expõe o modelo por features prontas ou por cliente armazenado no banco. "
        "A recomendação final é produzida por uma política separada do modelo."
    ),
    version="1.0.0",
    lifespan=lifespan,
)


def _require_active_bundle(request: Request) -> ModelBundle:
    manager: ModelBundleManager = request.app.state.bundle_manager
    try:
        return manager.require_active()
    except RuntimeError as error:
        status = manager.status()
        raise HTTPException(
            status_code=503,
            detail={
                "message": "Modelo e referências ainda não estão disponíveis.",
                "last_error": status.last_error or str(error),
            },
        ) from error


@app.get("/health", response_model=HealthResponse)
def health(request: Request) -> HealthResponse:
    bundle = _require_active_bundle(request)
    return HealthResponse(status="ok", model_loaded=True, model_path=str(bundle.model_path))


@app.get("/model/features", response_model=list[str])
def model_features(request: Request) -> list[str]:
    bundle = _require_active_bundle(request)
    return bundle.feature_order


@app.get("/customers/{customer_id}/features", response_model=CustomerFeaturesResponse)
def customer_features(customer_id: int, request: Request) -> CustomerFeaturesResponse:
    feature_service: CustomerFeatureService = request.app.state.feature_service

    try:
        features = feature_service.build(customer_id)
    except CustomerNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except SQLAlchemyError as error:
        raise HTTPException(
            status_code=503,
            detail="Não foi possível consultar as fontes de dados do cliente.",
        ) from error

    return CustomerFeaturesResponse(customer_id=customer_id, features=features)


@app.post("/predict/features", response_model=PredictionResponse)
def predict_from_features(
    payload: FeaturePredictionRequest, request: Request
) -> PredictionResponse:
    _log_request_json(
        "POST /predict/features",
        {"features": payload.features},
    )
    return _predict(
        features=payload.features,
        source="provided_features",
        request=request,
    )


@app.post("/predict/customer/{customer_id}", response_model=PredictionResponse)
def predict_from_database(customer_id: int, request: Request) -> PredictionResponse:
    feature_service: CustomerFeatureService = request.app.state.feature_service

    try:
        features = feature_service.build(customer_id)
    except CustomerNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except SQLAlchemyError as error:
        raise HTTPException(
            status_code=503,
            detail="Não foi possível consultar as fontes de dados do cliente.",
        ) from error

    _log_request_json(
        f"POST /predict/customer/{customer_id}",
        {"customer_id": customer_id, "features": features},
    )
    return _predict(
        features=features,
        source="database",
        customer_id=customer_id,
        request=request,
    )


def _log_request_json(endpoint: str, payload: dict) -> None:
    print(
        f"Request JSON {endpoint}: "
        f"{json.dumps(payload, ensure_ascii=False, default=str)}",
        flush=True,
    )


def _predict(
    features: dict,
    source: str,
    request: Request,
    customer_id: int | None = None,
) -> PredictionResponse:
    bundle = _require_active_bundle(request)
    feature_input_processor: FeatureInputProcessor = (
        request.app.state.feature_input_processor
    )
    prediction_service: PredictionService = request.app.state.prediction_service
    explanation_service: ExplanationService = request.app.state.explanation_service
    credit_policy: CreditPolicy = request.app.state.credit_policy

    try:
        prepared_input = feature_input_processor.prepare(bundle, features)
    except ModelInputError as error:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "Features obrigatórias ausentes.",
                "missing_features": error.missing_features,
            },
        ) from error

    result = prediction_service.predict(bundle, prepared_input)
    print(
        f"Predição realizada com sucesso. "
        f"Score: {result.risk_score:.4f}, Classe: {result.predicted_class}",
        flush=True,
    )

    policy_decision = credit_policy.evaluate(result.risk_score)
    explanation = None
    if policy_decision.recommendation == "manual_review":
        explanation = explanation_service.explain(bundle, prepared_input)

    return PredictionResponse(
        source=source,
        customer_id=customer_id,
        risk_score=result.risk_score,
        predicted_class=result.predicted_class,
        model_decision_threshold=bundle.decision_threshold,
        policy=asdict(policy_decision),
        explanation=explanation,
    )
