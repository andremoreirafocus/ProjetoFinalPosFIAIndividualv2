"""Teste de ExplanationService.explain(bundle, prepared_input).

A classe recebe bundle e entrada preparada em vez de PredictionService e caminho de
referência lido de arquivo (etapa 2 do plano de bundle). Renomeado de
test_bundle_explanation_service.py na etapa 8, quando explanation_service_v2.py virou
explanation_service.py e a classe antiga foi removida.
"""
from MLOps.app.api.explanation_service import ExplanationService
from MLOps.app.api.feature_input_processor import FeatureInputProcessor
from MLOps.tests.fakes import FakeModel
from MLOps.tests.fixtures import build_feature_reference, build_model_bundle


def test_explain_returns_ranked_local_shap_contributions() -> None:
    reference = build_feature_reference()
    bundle = build_model_bundle(
        estimator=FakeModel(),
        feature_order=["ext_source_1", "occupation_type"],
        categorical_features=["occupation_type"],
        categories={"occupation_type": ["Laborers", "Managers"]},
        target_rate=reference["target_rate"],
        numeric_references=reference["numeric_features"],
        categorical_references=reference["categorical_features"],
        global_shap=reference["global_shap"],
    )
    prepared_input = FeatureInputProcessor().prepare(
        bundle, {"ext_source_1": 0.5, "occupation_type": "Managers"}
    )

    explanation = ExplanationService().explain(bundle, prepared_input)

    assert explanation["base_value"] == -0.4
    assert explanation["output_scale"] == "raw_score"
    assert [factor["feature"] for factor in explanation["top_factors"]] == [
        "ext_source_1",
        "occupation_type",
    ]
    assert explanation["top_factors"][0]["direction"] == "increases_risk"
    assert explanation["top_factors"][1]["direction"] == "reduces_risk"
    numeric = explanation["top_factors"][0]["comparison"]["numeric"]
    assert numeric["training_percentile_low"] == 50.0
    assert numeric["training_percentile_high"] == 50.0
    shap = explanation["top_factors"][0]["comparison"]["shap"]
    assert shap["abs_shap_percentile_low"] == 75
    assert shap["abs_shap_percentile_high"] == 90
    categorical = explanation["top_factors"][1]["comparison"]["categorical"]
    assert categorical["category_count"] == 40
    assert categorical["category_default_rate"] == 0.05
