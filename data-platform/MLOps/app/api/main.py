import asyncio
from contextlib import asynccontextmanager
from contextlib import suppress
from dataclasses import asdict
import json
import logging
from pathlib import Path
from threading import RLock

from fastapi import FastAPI, HTTPException, Request
from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError

from .config import settings
from .credit_policy import CreditPolicy
from .explanation_service import ExplanationService
from .feature_service import CustomerFeatureService, CustomerNotFoundError
from .model_service import ModelInputError, PredictionService
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

    prediction_service = PredictionService(settings.model_path)
    explanation_service = ExplanationService(prediction_service)
    database_engine = create_engine(settings.database_url, pool_pre_ping=True)
    feature_service = CustomerFeatureService(database_engine)
    credit_policy = CreditPolicy(
        approve_max_score=settings.approve_max_score,
        manual_review_max_score=settings.manual_review_max_score,
        version=settings.policy_version,
    )

    app.state.prediction_service = prediction_service
    app.state.explanation_service = explanation_service
    app.state.feature_service = feature_service
    app.state.credit_policy = credit_policy
    app.state.model_load_error = None
    app.state.model_bundle_signature = None
    app.state.model_bundle_lock = RLock()

    model_load_task = asyncio.create_task(
        _load_model_with_retry(
            app,
            prediction_service,
            settings.model_load_retry_seconds,
            explanation_service,
        )
    )

    try:
        yield
    finally:
        model_load_task.cancel()
        with suppress(asyncio.CancelledError):
            await model_load_task
        database_engine.dispose()


async def _load_model_with_retry(
    app: FastAPI,
    prediction_service: PredictionService,
    retry_seconds: float,
    explanation_service: ExplanationService,
) -> None:
    while not prediction_service.is_loaded:
        try:
            await asyncio.to_thread(
                _refresh_model_bundle,
                app,
                prediction_service,
                explanation_service,
            )
        except Exception as error:
            app.state.model_load_error = str(error)
            logger.error(
                "Falha ao carregar o modelo %s: %s. Nova tentativa em %.1f segundos.",
                prediction_service.model_path,
                error,
                retry_seconds,
            )
            await asyncio.sleep(retry_seconds)
        else:
            app.state.model_load_error = None
            print(
                f"Modelo carregado com sucesso: {prediction_service.model_path}",
                flush=True,
            )
            logger.info(
                "Modelo carregado com sucesso: %s",
                prediction_service.model_path,
            )


def _file_signature(path: Path) -> tuple[int, int]:
    stat = path.stat()
    return stat.st_mtime_ns, stat.st_size


def _bundle_signature(
    prediction_service: PredictionService,
    explanation_service: ExplanationService,
) -> tuple[tuple[int, int], tuple[int, int]]:
    return (
        _file_signature(prediction_service.model_path),
        _file_signature(explanation_service.reference_path),
    )


def _refresh_model_bundle(
    app: FastAPI,
    prediction_service: PredictionService,
    explanation_service: ExplanationService,
) -> bool:
    """Recarrega modelo e referências juntos quando os arquivos forem alterados."""
    with app.state.model_bundle_lock:
        try:
            signature_before = _bundle_signature(
                prediction_service, explanation_service
            )
            if signature_before == app.state.model_bundle_signature:
                return False

            artifact = prediction_service.read_artifact()
            reference = explanation_service.read_reference()
            signature_after = _bundle_signature(
                prediction_service, explanation_service
            )
            if signature_before != signature_after:
                raise RuntimeError("Os artefatos foram alterados durante a carga.")
            if reference["model_version"] != artifact.get("config_version"):
                raise ValueError(
                    "A versão das referências diverge da versão do modelo."
                )
            if reference["trained_at_utc"] != artifact.get("trained_at_utc"):
                raise ValueError(
                    "O instante de treinamento das referências diverge do modelo."
                )
            explanation_service.validate_feature_coverage(
                reference,
                artifact["features"],
            )
        except Exception as error:
            app.state.model_load_error = str(error)
            if prediction_service.is_loaded and explanation_service.reference is not None:
                logger.warning(
                    "Novos artefatos ainda não formam um conjunto válido; "
                    "mantendo a versão carregada: %s",
                    error,
                )
                return False
            raise

        prediction_service.artifact = artifact
        explanation_service.reference = reference
        app.state.model_bundle_signature = signature_after
        app.state.model_load_error = None
        logger.info(
            "Modelo e referências carregados em conjunto: versão=%s, treino=%s",
            artifact.get("config_version"),
            artifact.get("trained_at_utc"),
        )
        return True


app = FastAPI(
    title="API de Risco de Crédito",
    description=(
        "Expõe o modelo por features prontas ou por cliente armazenado no banco. "
        "A recomendação final é produzida por uma política separada do modelo."
    ),
    version="1.0.0",
    lifespan=lifespan,
)


@app.get("/health", response_model=HealthResponse)
def health(request: Request) -> HealthResponse:
    service: PredictionService = request.app.state.prediction_service
    _ensure_model_bundle_available(request)

    return HealthResponse(
        status="ok",
        model_loaded=service.is_loaded,
        model_path=str(service.model_path),
    )


@app.get("/model/features", response_model=list[str])
def model_features(request: Request) -> list[str]:
    service: PredictionService = request.app.state.prediction_service
    _ensure_model_bundle_available(request)
    with request.app.state.model_bundle_lock:
        return service.expected_features


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

def _ensure_model_bundle_available(request: Request) -> None:
    prediction_service: PredictionService = request.app.state.prediction_service
    explanation_service: ExplanationService = request.app.state.explanation_service
    try:
        _refresh_model_bundle(
            request.app, prediction_service, explanation_service
        )
    except Exception as error:
        raise HTTPException(
            status_code=503,
            detail={
                "message": "Modelo e referências ainda não estão disponíveis.",
                "last_error": str(error),
            },
        ) from error

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
    prediction_service: PredictionService = request.app.state.prediction_service
    explanation_service: ExplanationService = request.app.state.explanation_service
    credit_policy: CreditPolicy = request.app.state.credit_policy

    _ensure_model_bundle_available(request)

    with request.app.state.model_bundle_lock:
        try:
            risk_score, predicted_class = prediction_service.predict(features)
            print(
                f"Predição realizada com sucesso. "
                f"Score: {risk_score:.4f}, Classe: {predicted_class}",
                flush=True,
            )
        except ModelInputError as error:
            raise HTTPException(
                status_code=422,
                detail={
                    "message": "Features obrigatórias ausentes.",
                    "missing_features": error.missing_features,
                },
            ) from error

        policy_decision = credit_policy.evaluate(risk_score)
        explanation = None
        if policy_decision.recommendation == "manual_review":
            explanation = explanation_service.explain(features)

        return PredictionResponse(
            source=source,
            customer_id=customer_id,
            risk_score=risk_score,
            predicted_class=predicted_class,
            model_decision_threshold=prediction_service.decision_threshold,
            policy=asdict(policy_decision),
            explanation=explanation,
        )
