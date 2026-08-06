"""Calcula o baseline populacional e a referência TreeSHAP global de um modelo treinado.

Recebe o modelo já ajustado e a população usada nesse ajuste; não acessa banco de dados
nem conhece o schema de configuração de nenhum componente. Quem invoca decide sobre que
população o baseline descreve — hoje, sempre a mesma usada no ajuste final do modelo.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from lightgbm import LGBMClassifier


def distribution_statistics(values: pd.Series | np.ndarray) -> dict[str, Any]:
    """Resume uma distribuição numérica em valores serializáveis como JSON."""
    series = pd.Series(values, dtype="float64").replace([np.inf, -np.inf], np.nan)
    valid = series.dropna()
    quantiles = valid.quantile([0.01, 0.05, 0.25, 0.50, 0.75, 0.95, 0.99])
    percentile_grid = valid.quantile(np.linspace(0, 1, 101))
    return {
        "count": int(valid.size),
        "missing_count": int(series.isna().sum()),
        "mean": float(valid.mean()),
        "std": float(valid.std()),
        "min": float(valid.min()),
        "p01": float(quantiles.loc[0.01]),
        "p05": float(quantiles.loc[0.05]),
        "p25": float(quantiles.loc[0.25]),
        "median": float(quantiles.loc[0.50]),
        "p75": float(quantiles.loc[0.75]),
        "p95": float(quantiles.loc[0.95]),
        "p99": float(quantiles.loc[0.99]),
        "max": float(valid.max()),
        "percentiles": {
            f"p{percentile:02d}": float(value)
            for percentile, value in enumerate(percentile_grid.to_numpy())
        },
    }


def build_numeric_references(
    X: pd.DataFrame, y: pd.Series, categorical_features: list[str]
) -> dict[str, Any]:
    """Calcula distribuição geral e medianas por target das features numéricas."""
    references = {}
    categorical_set = set(categorical_features)
    for feature in X.columns:
        if feature in categorical_set:
            continue
        values = pd.to_numeric(X[feature], errors="coerce")
        stats = distribution_statistics(values)
        stats["target_0_median"] = float(values[y == 0].median())
        stats["target_1_median"] = float(values[y == 1].median())
        unique_values = set(values.dropna().unique())
        if unique_values and unique_values.issubset({0, 1}):
            stats["binary_rates"] = {
                "overall": float(values.mean()),
                "target_0": float(values[y == 0].mean()),
                "target_1": float(values[y == 1].mean()),
            }
        references[feature] = stats
    return references


def build_categorical_references(
    X: pd.DataFrame, y: pd.Series, categorical_features: list[str]
) -> dict[str, Any]:
    """Calcula frequência e taxa histórica de inadimplência por categoria."""
    references = {}
    for feature in categorical_features:
        values = X[feature].astype("object").where(X[feature].notna(), "__MISSING__")
        values = values.astype(str)
        frame = pd.DataFrame({"category": values.to_numpy(), "target": y.to_numpy()})
        frequency = frame["category"].value_counts(normalize=True, dropna=False)
        default_rate = frame.groupby("category", dropna=False)["target"].mean()
        references[feature] = {
            "count": {
                str(k): int(v)
                for k, v in frame["category"].value_counts(dropna=False).items()
            },
            "frequency": {str(k): float(v) for k, v in frequency.items()},
            "default_rate": {str(k): float(v) for k, v in default_rate.items()},
        }
    return references


def build_global_shap_reference(
    model: LGBMClassifier,
    X: pd.DataFrame,
    sample_size: int,
    random_state: int,
) -> dict[str, Any]:
    """Resume TreeSHAP global em uma amostra reproduzível da base de treino."""
    size = min(sample_size, len(X))
    sample = X.sample(n=size, random_state=random_state)
    contributions = np.asarray(
        model.booster_.predict(sample, pred_contrib=True), dtype=float
    )
    if contributions.ndim != 2 or contributions.shape[1] != X.shape[1] + 1:
        raise RuntimeError("Formato inesperado das contribuições TreeSHAP globais.")

    absolute_contributions = np.abs(contributions[:, :-1])
    mean_abs = absolute_contributions.mean(axis=0)
    shap_quantiles = np.quantile(
        absolute_contributions,
        [0.50, 0.75, 0.90, 0.95, 0.99],
        axis=0,
    )
    importance = sorted(
        (
            {
                "feature": feature,
                "mean_abs_shap": float(mean_abs[index]),
                "p50_abs_shap": float(shap_quantiles[0, index]),
                "p75_abs_shap": float(shap_quantiles[1, index]),
                "p90_abs_shap": float(shap_quantiles[2, index]),
                "p95_abs_shap": float(shap_quantiles[3, index]),
                "p99_abs_shap": float(shap_quantiles[4, index]),
            }
            for index, feature in enumerate(X.columns)
        ),
        key=lambda item: item["mean_abs_shap"],
        reverse=True,
    )
    return {
        "sample_size": size,
        "base_value": float(contributions[:, -1].mean()),
        "output_scale": "raw_score",
        "feature_importance": importance,
    }


def build_feature_reference(
    model: LGBMClassifier,
    X: pd.DataFrame,
    y: pd.Series,
    categorical_features: list[str],
    model_version: str,
    trained_at_utc: str,
    shap_sample_size: int,
    random_state: int,
) -> dict[str, Any]:
    """Monta o baseline versionado consumível pela API e por agentes."""
    scores = model.predict_proba(X)[:, 1]
    return {
        "model_version": model_version,
        "trained_at_utc": trained_at_utc,
        "row_count": int(len(X)),
        "target_rate": float(y.mean()),
        "numeric_features": build_numeric_references(X, y, categorical_features),
        "categorical_features": build_categorical_references(
            X, y, categorical_features
        ),
        "score_distribution": distribution_statistics(scores),
        "global_shap": build_global_shap_reference(
            model,
            X,
            sample_size=int(shap_sample_size),
            random_state=int(random_state),
        ),
    }
