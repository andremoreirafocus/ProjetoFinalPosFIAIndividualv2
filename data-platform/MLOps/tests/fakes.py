"""Fakes reutilizáveis para os testes da API.

Regra do projeto: NUNCA usar monkeypatch/mock ou qualquer interceptação de código.
Aqui só existem implementações reais alternativas (fakes) que respeitam a mesma
interface dos componentes de produção e são injetadas por composição.
"""
from __future__ import annotations

from typing import Any

import numpy as np

from MLOps.app.api.feature_service import CustomerNotFoundError


class FakeModel:
    """Modelo com a mesma interface mínima usada pelo ``PredictionService``.

    Devolve uma probabilidade determinística para a classe positiva e guarda o
    ``DataFrame`` recebido, permitindo verificar o alinhamento de colunas e a
    restauração de categóricas feitos pelo serviço antes do ``predict_proba``.
    """

    def __init__(self, positive_proba: float = 0.6) -> None:
        self.positive_proba = positive_proba
        self.received: Any = None
        self.booster_ = self

    def predict_proba(self, features: Any) -> np.ndarray:
        self.received = features
        p = self.positive_proba
        return np.array([[1.0 - p, p]])

    def predict(self, features: Any, pred_contrib: bool = False) -> np.ndarray:
        self.received = features
        if not pred_contrib:
            raise ValueError("FakeModel suporta apenas pred_contrib=True neste método.")
        # Uma contribuição por feature e o valor-base na última coluna.
        return np.array([[0.25, -0.10, -0.40]])


class FakeFeatureService:
    """Fake do ``CustomerFeatureService`` para os endpoints por cliente.

    Configurável para devolver features, sinalizar cliente inexistente
    (``CustomerNotFoundError``) ou simular falha de banco (erro injetado).
    """

    def __init__(
        self,
        features: dict[str, Any] | None = None,
        error: Exception | None = None,
    ) -> None:
        self._features = features
        self._error = error

    def build(self, customer_id: int) -> dict[str, Any]:
        if self._error is not None:
            raise self._error
        if self._features is None:
            raise CustomerNotFoundError(
                f"Cliente {customer_id} não encontrado em application_abt."
            )
        return dict(self._features)


class FakeNewCustomerFeatureTransformationService:
    """Fake de `NewCustomerFeatureTransformationService` para o endpoint de cliente novo.

    Configurável para devolver as features transformadas ou simular a falha injetada —
    divergência de hash (`TransformationRuleMismatchError`) ou erro de banco. Registra o
    bundle e o registro bruto recebidos, para as asserções que conferem o que o handler
    repassa.
    """

    def __init__(
        self,
        features: dict[str, Any] | None = None,
        error: Exception | None = None,
    ) -> None:
        self._features = features
        self._error = error
        self.received: tuple[Any, dict[str, Any]] | None = None

    def transform(self, bundle: Any, application_record: dict[str, Any]) -> dict[str, Any]:
        self.received = (bundle, application_record)
        if self._error is not None:
            raise self._error
        return dict(self._features or {})
