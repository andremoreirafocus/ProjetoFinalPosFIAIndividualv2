"""Calcula explicações locais TreeSHAP a partir de um bundle e uma entrada preparada.

Corpo migrado da classe antiga de mesmo nome (etapa 2 do plano de bundle), trocando
self.prediction_service e self.reference por bundle.estimator/bundle.feature_order e
bundle.numeric_references/categorical_references/global_shap/target_rate. Sem leitura de
arquivo, sem validação de versão cruzada (bundle unifica modelo e referência num objeto
só, não há mais o que divergir) e sem validate_feature_coverage (responsabilidade do
loader, etapa 4). Renomeado de ``explanation_service_v2.py`` na etapa 8, quando a classe
antiga foi removida.
"""
from __future__ import annotations

import logging
from typing import Any

import numpy as np

from .model_bundle import ModelBundle, PreparedModelInput


logger = logging.getLogger(__name__)


class ExplanationService:
    """Sem estado: cada chamada de ``explain`` é independente das anteriores."""

    def explain(
        self,
        bundle: ModelBundle,
        prepared_input: PreparedModelInput,
        max_factors: int = 10,
    ) -> dict[str, Any]:
        """Calcula contribuições TreeSHAP locais para um único cliente."""
        model = bundle.estimator
        booster = getattr(model, "booster_", None)
        if booster is None:
            raise RuntimeError("O modelo carregado não oferece explicação TreeSHAP.")

        customer = prepared_input.frame
        contributions = np.asarray(
            booster.predict(customer, pred_contrib=True), dtype=float
        )
        expected_features = bundle.feature_order
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
                        bundle, feature, value, float(shap_value)
                    ),
                }
            )

        factors.sort(key=lambda item: abs(item["shap_value"]), reverse=True)
        return {
            "base_value": float(contributions[0, -1]),
            "output_scale": "raw_score",
            "top_factors": factors[:max_factors],
        }

    def _build_comparison(
        self, bundle: ModelBundle, feature: str, value: Any, shap_value: float
    ) -> dict[str, Any]:
        numeric = bundle.numeric_references.get(feature)
        categorical = bundle.categorical_references.get(feature)
        shap_reference = self._shap_references(bundle).get(feature)
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
                "population_default_rate": bundle.target_rate,
            }
        return comparison

    @staticmethod
    def _shap_references(bundle: ModelBundle) -> dict[str, dict[str, Any]]:
        return {
            item["feature"]: item
            for item in bundle.global_shap["feature_importance"]
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
