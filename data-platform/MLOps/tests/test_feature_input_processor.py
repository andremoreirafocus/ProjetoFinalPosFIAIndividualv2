"""Testes de FeatureInputProcessor.prepare — etapa 1.4 do plano de bundle.

Corpo migrado de model_service.py:81-100 (prepare_customer), agora recebendo o
bundle por parâmetro em vez de ler de self.artifact.
"""
import pandas as pd
import pytest

from MLOps.app.api.feature_input_processor import FeatureInputProcessor, ModelInputError
from MLOps.tests.fixtures import build_model_bundle


def test_prepare_orders_columns_by_bundle_feature_order() -> None:
    bundle = build_model_bundle(feature_order=["ext_source_1", "occupation_type"])
    features = {
        "occupation_type": "Laborers",
        "unexpected_field": 999,
        "ext_source_1": 0.5,
    }

    prepared = FeatureInputProcessor().prepare(bundle, features)

    assert list(prepared.frame.columns) == ["ext_source_1", "occupation_type"]


def test_prepare_raises_on_missing_required_feature() -> None:
    bundle = build_model_bundle(feature_order=["ext_source_1", "occupation_type"])
    features = {"ext_source_1": 0.5}

    with pytest.raises(ModelInputError) as excinfo:
        FeatureInputProcessor().prepare(bundle, features)

    assert excinfo.value.missing_features == ["occupation_type"]


def test_prepare_restores_categorical_dtype_with_persisted_categories() -> None:
    bundle = build_model_bundle(
        categorical_features=["occupation_type"],
        categories={"occupation_type": ["Laborers", "Managers"]},
    )
    features = {"ext_source_1": 0.5, "occupation_type": "Managers"}

    prepared = FeatureInputProcessor().prepare(bundle, features)

    assert isinstance(prepared.frame["occupation_type"].dtype, pd.CategoricalDtype)
    assert list(prepared.frame["occupation_type"].cat.categories) == [
        "Laborers",
        "Managers",
    ]


def test_prepare_converts_numeric_features() -> None:
    bundle = build_model_bundle()
    features = {"ext_source_1": 0.5, "occupation_type": "Managers"}

    prepared = FeatureInputProcessor().prepare(bundle, features)

    assert pd.api.types.is_numeric_dtype(prepared.frame["ext_source_1"])
