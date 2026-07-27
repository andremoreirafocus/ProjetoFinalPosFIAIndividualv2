import pickle
from pathlib import Path
from typing import Any

import pandas as pd


class ModelInputError(ValueError):
    def __init__(self, missing_features: list[str]) -> None:
        self.missing_features = missing_features
        super().__init__(f"Features ausentes: {', '.join(missing_features)}")


class PredictionService:
    """Carrega o artefato e oferece uma interface única de scoring."""

    REQUIRED_ARTIFACT_KEYS = {
        "model",
        "features",
        "decision_threshold",
        "metrics",
    }

    def __init__(self, model_path: Path) -> None:
        self.model_path = model_path
        self.artifact: dict[str, Any] | None = None

    def read_artifact(self) -> dict[str, Any]:
        """Lê e valida o artefato sem substituir o modelo em memória."""
        if not self.model_path.is_file():
            raise FileNotFoundError(f"Modelo não encontrado: {self.model_path}")

        with self.model_path.open("rb") as file:
            artifact = pickle.load(file)
        missing_keys = self.REQUIRED_ARTIFACT_KEYS.difference(artifact)
        if missing_keys:
            raise ValueError(
                f"Artefato inválido. Chaves ausentes: {sorted(missing_keys)}"
            )

        return artifact

    def load(self) -> None:
        self.artifact = self.read_artifact()

    @property
    def is_loaded(self) -> bool:
        return self.artifact is not None

    @property
    def expected_features(self) -> list[str]:
        self._ensure_loaded()
        return list(self.artifact["features"])

    @property
    def decision_threshold(self) -> float:
        self._ensure_loaded()
        return float(self.artifact["decision_threshold"])

    @property
    def model(self) -> Any:
        self._ensure_loaded()
        return self.artifact["model"]

    @property
    def config_version(self) -> str | None:
        self._ensure_loaded()
        return self.artifact.get("config_version")

    @property
    def trained_at_utc(self) -> str | None:
        self._ensure_loaded()
        return self.artifact.get("trained_at_utc")

    def predict(self, features: dict[str, Any]) -> tuple[float, int]:
        self._ensure_loaded()
        customer = self.prepare_customer(features)
        risk_score = float(self.model.predict_proba(customer)[0, 1])
        predicted_class = int(risk_score >= self.decision_threshold)
        return risk_score, predicted_class

    def prepare_customer(self, features: dict[str, Any]) -> pd.DataFrame:
        """Restaura ordem, tipos e categorias usados no treinamento."""
        missing_features = sorted(set(self.expected_features).difference(features))
        if missing_features:
            raise ModelInputError(missing_features)

        # Reindex garante ordem idêntica à do treinamento e ignora campos extras.
        customer = pd.DataFrame([features]).reindex(columns=self.expected_features)
        categorical_features = self.artifact.get("categorical_features", [])
        saved_categories = self.artifact.get("categories", {})
        categorical_set = set(categorical_features)
        for column in customer.columns:
            if column in categorical_set:
                customer[column] = pd.Categorical(
                    customer[column],
                    categories=saved_categories.get(column),
                )
            else:
                customer[column] = pd.to_numeric(customer[column], errors="coerce")
        return customer

    def _ensure_loaded(self) -> None:
        if self.artifact is None:
            raise RuntimeError("O modelo ainda não foi carregado.")
