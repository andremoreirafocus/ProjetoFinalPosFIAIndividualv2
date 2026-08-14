import json
import logging
import sys
import tempfile
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

import pytest


SCRIPT_DIR = Path(__file__).resolve().parents[1] / "agent-manual-review"
sys.path.insert(0, str(SCRIPT_DIR))

from invoke_llm import (
    CONTEXT_INPUT_FILE_NAME as INVOKE_CONTEXT_INPUT_FILE_NAME,
    CONTEXT_INPUT_PATH as INVOKE_CONTEXT_INPUT_PATH,
    LLM_MAX_TOKENS,
    LLM_REASONING_EFFORT,
    LLM_REASONING_FORMAT,
    LLM_RESPONSE_OUTPUT_FILE_NAME as INVOKE_RESPONSE_OUTPUT_FILE_NAME,
    LLM_RESPONSE_OUTPUT_PATH as INVOKE_RESPONSE_OUTPUT_PATH,
    LlmInvocationError,
    build_messages,
    create_groq_structured_llm,
    invoke_structured_llm,
    load_groq_api_key,
    write_json_exclusive as write_llm_output,
)
from prepare_llm_context import (
    API_RESPONSE_PATH,
    CONTEXT_OUTPUT_FILE_NAME as PREPARE_CONTEXT_OUTPUT_FILE_NAME,
    CONTEXT_OUTPUT_PATH as PREPARE_CONTEXT_OUTPUT_PATH,
    FEATURE_CATALOG_PATH,
    PROMPT_CONTRACT_PATH,
    ContextPreparationError,
    load_prompt_version,
    prepare_context,
    write_json_exclusive as write_context_output,
)
from process_llm_response import (
    AGENT_REPORT_OUTPUT_FILE_NAME as PROCESS_REPORT_OUTPUT_FILE_NAME,
    AGENT_REPORT_OUTPUT_PATH as PROCESS_REPORT_OUTPUT_PATH,
    CONTEXT_INPUT_FILE_NAME as PROCESS_CONTEXT_INPUT_FILE_NAME,
    CONTEXT_INPUT_PATH as PROCESS_CONTEXT_INPUT_PATH,
    LLM_RESPONSE_INPUT_FILE_NAME as PROCESS_RESPONSE_INPUT_FILE_NAME,
    LLM_RESPONSE_INPUT_PATH as PROCESS_RESPONSE_INPUT_PATH,
    LlmResponseValidationError,
    assemble_report,
    validate_llm_response,
    write_json_exclusive as write_report_output,
)
from render_report_pdf import (
    AGENT_REPORT_INPUT_FILE_NAME as RENDER_REPORT_INPUT_FILE_NAME,
    AGENT_REPORT_INPUT_PATH as RENDER_REPORT_INPUT_PATH,
    FINAL_PDF_OUTPUT_FILE_NAME,
    FINAL_PDF_OUTPUT_PATH,
    ReportRenderingError,
    load_report_template_name,
    render_html,
    render_report_pdf,
    resolve_template_path,
)
from script_logging import configure_script_logging


def api_response_fixture(*, model_version: str | None = "model-v1") -> dict:
    response = {
        "source": "database",
        "customer_id": 42,
        "risk_score": 0.55,
        "predicted_class": 1,
        "model_decision_threshold": 0.5,
        "policy": {
            "recommendation": "manual_review",
            "reason": "Score na faixa intermediária.",
            "policy_version": "policy-v1",
            "approve_max_score": 0.5,
            "manual_review_max_score": 0.6,
        },
        "explanation": {
            "base_value": -0.4,
            "output_scale": "raw_score",
            "top_factors": [
                {
                    "feature": "allowed_numeric",
                    "value": 0.25,
                    "shap_value": 0.2,
                    "direction": "increases_risk",
                    "comparison": {
                        "feature_type": "numeric",
                        "shap": {
                            "global_mean_abs_shap": 0.1,
                            "local_abs_shap": 0.2,
                            "abs_shap_percentile_low": 75,
                            "abs_shap_percentile_high": 90,
                        },
                        "numeric": {
                            "training_percentile_low": 25,
                            "training_percentile_high": 25,
                            "population_mean": 0.5,
                            "population_median": 0.5,
                            "population_p25": 0.25,
                            "population_p75": 0.75,
                            "target_0_median": 0.55,
                            "target_1_median": 0.4,
                            "binary_rates": None,
                        },
                        "categorical": None,
                    },
                },
                {
                    "feature": "restricted_category",
                    "value": "restricted",
                    "shap_value": 0.15,
                    "direction": "increases_risk",
                    "comparison": {
                        "feature_type": "categorical",
                        "shap": {
                            "global_mean_abs_shap": 0.08,
                            "local_abs_shap": 0.15,
                            "abs_shap_percentile_low": 90,
                            "abs_shap_percentile_high": 95,
                        },
                        "numeric": None,
                        "categorical": {
                            "category_count": 10,
                            "category_frequency": 0.1,
                            "category_default_rate": 0.12,
                            "population_default_rate": 0.08,
                        },
                    },
                },
                {
                    "feature": "allowed_category",
                    "value": "A",
                    "shap_value": -0.1,
                    "direction": "reduces_risk",
                    "comparison": {
                        "feature_type": "categorical",
                        "shap": {
                            "global_mean_abs_shap": 0.09,
                            "local_abs_shap": 0.1,
                            "abs_shap_percentile_low": 50,
                            "abs_shap_percentile_high": 75,
                        },
                        "numeric": None,
                        "categorical": {
                            "category_count": 60,
                            "category_frequency": 0.6,
                            "category_default_rate": 0.05,
                            "population_default_rate": 0.08,
                        },
                    },
                },
            ],
        },
    }
    if model_version is not None:
        response["model_version"] = model_version
    return response


def feature_catalog_fixture() -> dict:
    return {
        "catalog_version": "catalog-v1",
        "features": {
            "allowed_numeric": {
                "label": "Feature numérica",
                "description": "Uma feature numérica permitida.",
                "type": "numeric",
                "format": "decimal",
                "unit": "razão",
                "value_semantics": "Valores maiores representam maior intensidade.",
                "sensitive": False,
                "allowed_in_report": True,
            },
            "restricted_category": {
                "label": "Feature restrita",
                "description": "Uma feature restrita.",
                "type": "categorical",
                "format": "category",
                "unit": None,
                "value_semantics": "Categoria restrita à auditoria.",
                "sensitive": True,
                "allowed_in_report": False,
                "governance_note": "Disponível somente para auditoria.",
            },
            "allowed_category": {
                "label": "Feature categórica",
                "description": "Uma feature categórica permitida.",
                "type": "categorical",
                "format": "category",
                "unit": None,
                "value_semantics": "Categorias da fonte.",
                "special_values": {"Unknown": "Valor não informado."},
                "sensitive": False,
                "allowed_in_report": True,
            },
        },
    }


def prepared_context_fixture() -> dict:
    return prepare_context(
        api_response_fixture(),
        feature_catalog_fixture(),
        api_source="api.json",
        catalog_source="catalog.json",
        prompt_version="prompt-v1",
    )


def llm_response_fixture() -> dict:
    return {
        "report_schema_version": "report-v1",
        "report_title": "Relatório de apoio à revisão",
        "case_summary": {"summary": "Síntese do caso."},
        "policy_context": {"explanation": "Explicação da política."},
        "factors_increasing_score": [
            {
                "feature": "allowed_numeric",
                "direction": "increases_risk",
                "explanation": "Explicação da feature numérica.",
                "contextual_conclusion": "Conclusão da feature numérica.",
            }
        ],
        "factors_reducing_score": [
            {
                "feature": "allowed_category",
                "direction": "reduces_risk",
                "explanation": "Explicação da feature categórica.",
                "contextual_conclusion": "Conclusão da feature categórica.",
            }
        ],
        "limitations": [
            "O score não é probabilidade calibrada.",
            "SHAP não demonstra causalidade.",
            "A decisão final permanece humana.",
        ],
        "human_decision_notice": "A decisão final pertence ao analista.",
    }


def prompt_contract_fixture() -> dict:
    return {
        "prompt_version": "prompt-v1",
        "system_prompt": "Use somente o contexto fornecido.",
        "user_prompt_template": "Contexto:\n{{llm_context_json}}",
        "response_schema": {
            "name": "credit_review_report_content",
            "strict": True,
            "schema": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "report_title": {"type": "string"},
                },
                "required": ["report_title"],
            },
        },
    }


class FakeStructuredLlm:
    def __init__(self, response: dict) -> None:
        self.response = response
        self.received_messages: list[tuple[str, str]] | None = None

    def invoke(self, messages: list[tuple[str, str]]) -> dict:
        self.received_messages = messages
        return self.response


# --- script_logging ------------------------------------------------------
def test_writes_the_same_message_to_terminal_and_script_log_file() -> None:
    application_logger = logging.getLogger("script_logging_test")

    with tempfile.TemporaryDirectory() as temporary_directory:
        script_path = Path(temporary_directory) / "example_stage.py"
        terminal_output = StringIO()
        try:
            with redirect_stdout(terminal_output):
                log_path = configure_script_logging(
                    application_logger,
                    script_path,
                )
                application_logger.info("etapa concluída")
                for handler in application_logger.handlers:
                    handler.flush()

            assert log_path == script_path.with_suffix(".log")
            assert "etapa concluída" in terminal_output.getvalue()
            assert "etapa concluída" in log_path.read_text(encoding="utf-8")
        finally:
            for handler in list(application_logger.handlers):
                application_logger.removeHandler(handler)
                handler.close()
            application_logger.setLevel(logging.NOTSET)
            application_logger.propagate = True


# --- prepare_llm_context ---------------------------------------------------
def test_enriches_authorized_factors_and_records_restricted_factors() -> None:
    context = prepared_context_fixture()

    authorized = context["llm_context"]["explanation"]["authorized_factors"]
    assert [factor["feature"] for factor in authorized] == [
        "allowed_numeric",
        "allowed_category",
    ]
    assert [factor["report_rank"] for factor in authorized] == [1, 2]
    assert (
        authorized[0]["semantic"]["label"]
        == feature_catalog_fixture()["features"]["allowed_numeric"]["label"]
    )
    assert (
        authorized[0]["evidence"]["shap_value"]
        == api_response_fixture()["explanation"]["top_factors"][0]["shap_value"]
    )

    processing = context["agent_processing"]
    assert processing["received_factor_count"] == 3
    assert processing["authorized_factor_count"] == 2
    assert processing["excluded_factor_count"] == 1
    assert processing["excluded_evidence_for_audit_only"] == [
        {
            "feature": "restricted_category",
            "original_rank_by_abs_shap": 2,
            "reason": "Disponível somente para auditoria.",
        }
    ]
    assert context["validation"]["ready_for_llm"]


def test_generates_auditable_context_but_blocks_llm_when_version_is_missing() -> None:
    context = prepare_context(
        api_response_fixture(model_version=None),
        feature_catalog_fixture(),
        api_source="api.json",
        catalog_source="catalog.json",
        prompt_version="prompt-v1",
    )

    assert not context["validation"]["ready_for_llm"]
    assert (
        "model_version não está disponível no contrato atual da API."
        in context["validation"]["blocking_issues"]
    )


def test_rejects_factor_absent_from_catalog() -> None:
    response = api_response_fixture()
    response["explanation"]["top_factors"][0]["feature"] = "unknown_feature"

    with pytest.raises(ContextPreparationError, match="unknown_feature"):
        prepare_context(
            response,
            feature_catalog_fixture(),
            api_source="api.json",
            catalog_source="catalog.json",
            prompt_version="prompt-v1",
        )


def test_rejects_duplicate_factor_from_api() -> None:
    response = api_response_fixture()
    response["explanation"]["top_factors"].append(
        response["explanation"]["top_factors"][0].copy()
    )

    with pytest.raises(ContextPreparationError, match="Feature repetida"):
        prepare_context(
            response,
            feature_catalog_fixture(),
            api_source="api.json",
            catalog_source="catalog.json",
            prompt_version="prompt-v1",
        )


# --- invoke_llm --------------------------------------------------------
def test_configures_enough_output_for_the_structured_report() -> None:
    structured_llm = create_groq_structured_llm(
        model="openai/gpt-oss-20b",
        timeout_seconds=60,
        prompt_contract=prompt_contract_fixture(),
        api_key="fixture-key",
        max_tokens=LLM_MAX_TOKENS,
        reasoning_effort=LLM_REASONING_EFFORT,
        reasoning_format=LLM_REASONING_FORMAT,
    )
    configured_model = structured_llm.first.bound

    assert configured_model.max_tokens == 3072
    assert configured_model.reasoning_effort == "low"
    assert configured_model.reasoning_format == "hidden"


def test_loads_groq_api_key_from_explicit_dotenv_file() -> None:
    with tempfile.TemporaryDirectory() as temporary_directory:
        env_path = Path(temporary_directory) / ".env"
        env_path.write_text(
            "UNRELATED=value\nGROQ_API_KEY=groq-key-from-file\n",
            encoding="utf-8",
        )

        assert load_groq_api_key(env_path) == "groq-key-from-file"


def test_invoke_llm_rejects_missing_dotenv_file() -> None:
    with tempfile.TemporaryDirectory() as temporary_directory:
        env_path = Path(temporary_directory) / ".env"

        with pytest.raises(LlmInvocationError, match="não existe"):
            load_groq_api_key(env_path)


def test_rejects_dotenv_without_groq_api_key() -> None:
    with tempfile.TemporaryDirectory() as temporary_directory:
        env_path = Path(temporary_directory) / ".env"
        env_path.write_text("UNRELATED=value\n", encoding="utf-8")

        with pytest.raises(LlmInvocationError, match="GROQ_API_KEY"):
            load_groq_api_key(env_path)


def test_builds_messages_with_only_llm_context() -> None:
    context = prepared_context_fixture()
    messages = build_messages(context, prompt_contract_fixture())

    assert messages[0] == ("system", "Use somente o contexto fornecido.")
    assert '"customer_id": 42' in messages[1][1]
    assert "agent_processing" not in messages[1][1]


def test_invokes_structured_llm_and_returns_its_json() -> None:
    expected = llm_response_fixture()
    llm = FakeStructuredLlm(expected)
    messages = build_messages(prepared_context_fixture(), prompt_contract_fixture())

    result = invoke_structured_llm(llm, messages)

    assert result == expected
    assert llm.received_messages == messages


def test_rejects_context_not_ready_for_llm() -> None:
    context = prepared_context_fixture()
    context["validation"]["ready_for_llm"] = False

    with pytest.raises(LlmInvocationError, match="não está pronto"):
        build_messages(context, prompt_contract_fixture())


def test_rejects_prompt_version_different_from_context() -> None:
    prompt = prompt_contract_fixture()
    prompt["prompt_version"] = "another-prompt"

    with pytest.raises(LlmInvocationError, match="prompt_version"):
        build_messages(prepared_context_fixture(), prompt)


# --- process_llm_response ------------------------------------------------
def test_validates_and_reassociates_narrative_with_original_data() -> None:
    context = prepared_context_fixture()
    response = llm_response_fixture()

    validate_llm_response(context, response)
    report = assemble_report(
        context,
        response,
        report_id="report-id",
        generated_at="2026-07-28T12:00:00+00:00",
    )

    assert report["report_id"] == "report-id"
    assert report["case_summary"]["customer_id"] == 42
    factor = report["factors_increasing_score"][0]
    original = context["llm_context"]["explanation"]["authorized_factors"][0]
    assert factor["feature"] == "allowed_numeric"
    assert factor["customer_value"] == original["evidence"]["value"]
    assert factor["comparison"] == original["evidence"]["comparison"]
    assert (
        factor["explanation"]
        == response["factors_increasing_score"][0]["explanation"]
    )
    assert report["traceability"] == {
        "model_version": "model-v1",
        "policy_version": "policy-v1",
        "catalog_version": "catalog-v1",
        "prompt_version": "prompt-v1",
    }


def test_rejects_feature_not_sent_to_llm() -> None:
    response = llm_response_fixture()
    response["factors_increasing_score"][0]["feature"] = "restricted_category"

    with pytest.raises(LlmResponseValidationError, match="não autorizada"):
        validate_llm_response(prepared_context_fixture(), response)


def test_rejects_direction_changed_by_llm() -> None:
    response = llm_response_fixture()
    response["factors_increasing_score"][0]["direction"] = "reduces_risk"

    with pytest.raises(LlmResponseValidationError, match="direção"):
        validate_llm_response(prepared_context_fixture(), response)


def test_rejects_omitted_authorized_factor() -> None:
    response = llm_response_fixture()
    response["factors_reducing_score"] = []

    with pytest.raises(LlmResponseValidationError, match="Conjunto de features"):
        validate_llm_response(prepared_context_fixture(), response)


# --- render_report_pdf ---------------------------------------------------
def test_loads_report_template_name_from_explicit_dotenv_file() -> None:
    with tempfile.TemporaryDirectory() as temporary_directory:
        env_path = Path(temporary_directory) / ".env"
        expected_template_name = "report.html.j2"
        env_path.write_text(
            f"UNRELATED=value\nREPORT_TEMPLATE={expected_template_name}\n",
            encoding="utf-8",
        )

        assert load_report_template_name(env_path) == expected_template_name


def test_render_report_pdf_rejects_missing_dotenv_file() -> None:
    with tempfile.TemporaryDirectory() as temporary_directory:
        env_path = Path(temporary_directory) / ".env"

        with pytest.raises(ReportRenderingError, match="não existe"):
            load_report_template_name(env_path)


def test_rejects_dotenv_without_report_template() -> None:
    with tempfile.TemporaryDirectory() as temporary_directory:
        env_path = Path(temporary_directory) / ".env"
        env_path.write_text("UNRELATED=value\n", encoding="utf-8")

        with pytest.raises(ReportRenderingError, match="REPORT_TEMPLATE"):
            load_report_template_name(env_path)


def test_rejects_report_template_with_path_components() -> None:
    with tempfile.TemporaryDirectory() as temporary_directory:
        env_path = Path(temporary_directory) / ".env"
        env_path.write_text(
            "REPORT_TEMPLATE=templates/report.html.j2\n",
            encoding="utf-8",
        )

        with pytest.raises(ReportRenderingError, match="nome de arquivo"):
            load_report_template_name(env_path)


def test_rejects_configured_template_that_does_not_exist() -> None:
    with tempfile.TemporaryDirectory() as temporary_directory:
        template_directory = Path(temporary_directory)
        configured_template_name = "missing-report.html.j2"

        with pytest.raises(ReportRenderingError, match=configured_template_name):
            resolve_template_path(template_directory, configured_template_name)


def test_renders_report_data_with_the_configured_template() -> None:
    with tempfile.TemporaryDirectory() as temporary_directory:
        directory = Path(temporary_directory)
        template_path = directory / "report.html.j2"
        report = assemble_report(
            prepared_context_fixture(),
            llm_response_fixture(),
            report_id="report-id",
            generated_at="2026-07-28T12:00:00+00:00",
        )
        template_path.write_text(
            "<h1>{{ report.report_title }}</h1>"
            "<p>{{ report.case_summary.customer_id }}</p>",
            encoding="utf-8",
        )

        html = render_html(report, template_path)

        assert report["report_title"] in html
        assert str(report["case_summary"]["customer_id"]) in html


def test_writes_a_valid_pdf() -> None:
    with tempfile.TemporaryDirectory() as temporary_directory:
        directory = Path(temporary_directory)
        template_path = directory / "report.html.j2"
        output_path = directory / "report.pdf"
        template_path.write_text(
            "<h1>{{ report.report_title }}</h1>",
            encoding="utf-8",
        )

        render_report_pdf(
            {"report_title": "Relatório"},
            template_path=template_path,
            output_path=output_path,
        )

        assert output_path.read_bytes().startswith(b"%PDF-")


def test_rejects_missing_report_field_required_by_template() -> None:
    with tempfile.TemporaryDirectory() as temporary_directory:
        directory = Path(temporary_directory)
        template_path = directory / "report.html.j2"
        output_path = directory / "report.pdf"
        template_path.write_text(
            "{{ report.required_but_absent }}",
            encoding="utf-8",
        )

        with pytest.raises(ReportRenderingError, match="template"):
            render_report_pdf(
                {"report_title": "Relatório"},
                template_path=template_path,
                output_path=output_path,
            )

        assert not output_path.exists()


def test_refuses_existing_output_before_rendering() -> None:
    with tempfile.TemporaryDirectory() as temporary_directory:
        directory = Path(temporary_directory)
        template_path = directory / "report.html.j2"
        output_path = directory / "report.pdf"
        original_content = b"%PDF-1.7\npreserved\n"
        template_path.write_text(
            "{{ report.report_title }}",
            encoding="utf-8",
        )
        output_path.write_bytes(original_content)

        with pytest.raises(ReportRenderingError, match="não será sobrescrito"):
            render_report_pdf(
                {"report_title": "Relatório"},
                template_path=template_path,
                output_path=output_path,
            )

        assert output_path.read_bytes() == original_content


# --- contrato entre estágios do pipeline ----------------------------------
def test_real_sample_matches_model_version_and_is_ready_for_llm() -> None:
    project_directory = Path(__file__).resolve().parents[2]
    model_config_path = project_directory / "Model" / "config_model.json"
    api_response = json.loads(API_RESPONSE_PATH.read_text(encoding="utf-8"))
    feature_catalog = json.loads(FEATURE_CATALOG_PATH.read_text(encoding="utf-8"))
    model_config = json.loads(model_config_path.read_text(encoding="utf-8"))

    assert api_response["model_version"] == model_config["metadata"]["version"]
    context = prepare_context(
        api_response,
        feature_catalog,
        api_source=str(API_RESPONSE_PATH),
        catalog_source=str(FEATURE_CATALOG_PATH),
        prompt_version=load_prompt_version(PROMPT_CONTRACT_PATH),
    )
    assert context["validation"]["ready_for_llm"]


def test_each_stage_uses_the_previous_stage_output_as_its_input() -> None:
    assert PREPARE_CONTEXT_OUTPUT_FILE_NAME == INVOKE_CONTEXT_INPUT_FILE_NAME
    assert PREPARE_CONTEXT_OUTPUT_PATH == INVOKE_CONTEXT_INPUT_PATH
    assert PREPARE_CONTEXT_OUTPUT_FILE_NAME == PROCESS_CONTEXT_INPUT_FILE_NAME
    assert PREPARE_CONTEXT_OUTPUT_PATH == PROCESS_CONTEXT_INPUT_PATH
    assert INVOKE_RESPONSE_OUTPUT_FILE_NAME == PROCESS_RESPONSE_INPUT_FILE_NAME
    assert INVOKE_RESPONSE_OUTPUT_PATH == PROCESS_RESPONSE_INPUT_PATH
    assert PROCESS_REPORT_OUTPUT_FILE_NAME == RENDER_REPORT_INPUT_FILE_NAME
    assert PROCESS_REPORT_OUTPUT_PATH == RENDER_REPORT_INPUT_PATH
    assert FINAL_PDF_OUTPUT_PATH.name == FINAL_PDF_OUTPUT_FILE_NAME


# --- segurança de escrita --------------------------------------------------
def test_all_scripts_refuse_to_overwrite_existing_output() -> None:
    writers = (
        (write_context_output, ContextPreparationError),
        (write_llm_output, LlmInvocationError),
        (write_report_output, LlmResponseValidationError),
    )
    with tempfile.TemporaryDirectory() as temporary_directory:
        directory = Path(temporary_directory)
        for index, (writer, expected_error) in enumerate(writers):
            output = directory / f"existing-{index}.json"
            original_content = '{"preserved": true}\n'
            output.write_text(original_content, encoding="utf-8")

            with pytest.raises(expected_error):
                writer(output, {"replacement": True})

            assert output.read_text(encoding="utf-8") == original_content
