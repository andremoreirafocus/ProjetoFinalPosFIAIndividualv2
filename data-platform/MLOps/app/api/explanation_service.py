import json
import logging
from pathlib import Path
from typing import Any

import numpy as np

from .model_service import PredictionService


logger = logging.getLogger(__name__)


class ExplanationService:
    """Calcula explicações locais usando o mesmo modelo e preparo da predição."""

    REQUIRED_REFERENCE_KEYS = {
        "model_version",
        "trained_at_utc",
        "target_rate",
        "numeric_features",
        "categorical_features",
        "global_shap",
    }

    def __init__(
        self,
        prediction_service: PredictionService,
        reference_path: Path | None = None,
    ) -> None:
        self.prediction_service = prediction_service
        self.reference_path = reference_path or prediction_service.model_path.with_name(
            "feature_reference.json"
        )
        self.reference: dict[str, Any] | None = None

    def read_reference(self) -> dict[str, Any]:
        """Lê e valida o baseline sem substituir a referência em memória."""
        if not self.reference_path.is_file():
            raise FileNotFoundError(
                f"Referências do modelo não encontradas: {self.reference_path}"
            )
        reference = json.loads(self.reference_path.read_text(encoding="utf-8"))
        missing = self.REQUIRED_REFERENCE_KEYS.difference(reference)
        if missing:
            raise ValueError(
                f"Referências inválidas. Chaves ausentes: {sorted(missing)}"
            )
        return reference

    def load_reference(self) -> None:
        """Carrega e valida o baseline gerado junto com o modelo."""
        self.reference = self.read_reference()

    @staticmethod
    def validate_feature_coverage(
        reference: dict[str, Any],
        expected_features: list[str],
    ) -> None:
        """Valida se as referências podem explicar as features do modelo."""
        expected = set(expected_features)
        numeric = set(reference["numeric_features"])
        categorical = set(reference["categorical_features"])
        shap_features = {
            item["feature"]
            for item in reference["global_shap"]["feature_importance"]
        }

        missing_statistics = expected.difference(numeric | categorical)
        duplicated_types = expected.intersection(numeric & categorical)
        missing_shap = expected.difference(shap_features)

        errors = []
        if missing_statistics:
            errors.append(
                "features sem referência estatística: "
                f"{sorted(missing_statistics)}"
            )
        if duplicated_types:
            errors.append(
                "features simultaneamente numéricas e categóricas: "
                f"{sorted(duplicated_types)}"
            )
        if missing_shap:
            errors.append(
                "features sem referência SHAP global: "
                f"{sorted(missing_shap)}"
            )
        if errors:
            raise ValueError(
                "Referências incompatíveis com o modelo: " + "; ".join(errors)
            )

        extra_features = (numeric | categorical | shap_features).difference(
            expected
        )
        if extra_features:
            logger.warning(
                "Referências sem correspondência no modelo foram ignoradas: %s",
                sorted(extra_features),
            )

    def explain(
        self, features: dict[str, Any], max_factors: int = 10
    ) -> dict[str, Any]:
        """Calcula contribuições TreeSHAP locais para um único cliente."""
        self._ensure_reference_loaded()
        self._validate_reference_version()
        customer = self.prediction_service.prepare_customer(features)
        model = self.prediction_service.model
        booster = getattr(model, "booster_", None)
        if booster is None:
            raise RuntimeError("O modelo carregado não oferece explicação TreeSHAP.")

        contributions = np.asarray(
            booster.predict(customer, pred_contrib=True), dtype=float
        )
        expected_features = self.prediction_service.expected_features
        if (
            contributions.ndim != 2
            or contributions.shape[1] != len(expected_features) + 1
        ):
            raise RuntimeError("Formato inesperado das contribuições TreeSHAP.")

        feature_contributions = contributions[0, :-1]
        factors = []
        for feature, shap_value in zip(expected_features, feature_contributions):
            value = customer.iloc[0][feature]
            if hasattr(value, "item"):
                value = value.item()
            factors.append(
                {
                    "feature": feature,
                    "value": value,
                    "shap_value": float(shap_value),
                    "direction": (
                        "increases_risk" if shap_value > 0 else "reduces_risk"
                    ),
                    "comparison": self._build_comparison(
                        feature, value, float(shap_value)
                    ),
                }
            )

        factors.sort(key=lambda item: abs(item["shap_value"]), reverse=True)
        return {
            "base_value": float(contributions[0, -1]),
            "output_scale": "raw_score",
            "top_factors": factors[:max_factors],
        }

    def _ensure_reference_loaded(self) -> None:
        if self.reference is None:
            self.load_reference()

    def _validate_reference_version(self) -> None:
        if self.reference["model_version"] != self.prediction_service.config_version:
            raise ValueError("A versão das referências diverge da versão do modelo.")
        if self.reference["trained_at_utc"] != self.prediction_service.trained_at_utc:
            raise ValueError(
                "O instante de treinamento das referências diverge do modelo."
            )

    def _build_comparison(
        self, feature: str, value: Any, shap_value: float
    ) -> dict[str, Any]:
        numeric = self.reference["numeric_features"].get(feature)
        categorical = self.reference["categorical_features"].get(feature)
        shap_reference = self._shap_references().get(feature)
        if shap_reference is None or (numeric is None and categorical is None):
            raise ValueError(f"Feature sem referência compatível: {feature}")

        comparison: dict[str, Any] = {
            "feature_type": "numeric" if numeric is not None else "categorical",
            "shap": self._build_shap_comparison(shap_value, shap_reference),
            "numeric": None,
            "categorical": None,
        }
        if numeric is not None:
            percentile_low, percentile_high = self._percentile_range(
                float(value), numeric["percentiles"]
            )
            comparison["numeric"] = {
                "training_percentile_low": percentile_low,
                "training_percentile_high": percentile_high,
                "population_mean": numeric["mean"],
                "population_median": numeric["median"],
                "population_p25": numeric["p25"],
                "population_p75": numeric["p75"],
                "target_0_median": numeric["target_0_median"],
                "target_1_median": numeric["target_1_median"],
                "binary_rates": numeric.get("binary_rates"),
            }
        else:
            category = str(value)
            comparison["categorical"] = {
                "category_count": categorical["count"].get(category, 0),
                "category_frequency": categorical["frequency"].get(category, 0.0),
                "category_default_rate": categorical["default_rate"].get(category),
                "population_default_rate": self.reference["target_rate"],
            }
        return comparison

    def _shap_references(self) -> dict[str, dict[str, Any]]:
        return {
            item["feature"]: item
            for item in self.reference["global_shap"]["feature_importance"]
        }

    @staticmethod
    def _percentile_range(
        value: float, percentiles: dict[str, float]
    ) -> tuple[float, float]:
        points = sorted(
            ((int(key[1:]), float(point)) for key, point in percentiles.items()),
            key=lambda item: item[0],
        )
        ranks = np.asarray([item[0] for item in points], dtype=float)
        values = np.asarray([item[1] for item in points], dtype=float)
        left = int(np.searchsorted(values, value, side="left"))
        right = int(np.searchsorted(values, value, side="right"))

        if left < right:
            return float(ranks[left]), float(ranks[right - 1])
        if left == 0:
            return 0.0, 0.0
        if left == len(values):
            return 100.0, 100.0

        lower_value, upper_value = values[left - 1], values[left]
        fraction = (value - lower_value) / (upper_value - lower_value)
        rank = ranks[left - 1] + fraction * (ranks[left] - ranks[left - 1])
        return float(rank), float(rank)

    @staticmethod
    def _build_shap_comparison(
        shap_value: float, reference: dict[str, Any]
    ) -> dict[str, Any]:
        absolute_value = abs(shap_value)
        bands = [
            (50, reference["p50_abs_shap"]),
            (75, reference["p75_abs_shap"]),
            (90, reference["p90_abs_shap"]),
            (95, reference["p95_abs_shap"]),
            (99, reference["p99_abs_shap"]),
        ]
        lower = 0
        upper = 100
        for percentile, threshold in bands:
            if absolute_value <= threshold:
                upper = percentile
                break
            lower = percentile
        return {
            "global_mean_abs_shap": reference["mean_abs_shap"],
            "local_abs_shap": absolute_value,
            "abs_shap_percentile_low": lower,
            "abs_shap_percentile_high": upper,
        }
