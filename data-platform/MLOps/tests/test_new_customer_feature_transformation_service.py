"""Equivalência entre o pipeline (tabela inteira) e o serviço da API (registro a registro).

`NewCustomerFeatureTransformationService` aplica as duas projeções compartilhadas com o
pipeline — `application_sanitization_projection.sql` e `application_abt_record_projection.sql`
— a um único registro bruto, por `SELECT` sobre `VALUES`. Este é o teste de equivalência que
é o contrato desta etapa (plano, Etapa 7): as mesmas linhas passam pelos dois executores, com
o mesmo contrato, e precisam produzir valores idênticos. Isso prova duas coisas ao mesmo
tempo — que a regra de cada projeção continua a mesma dos dois lados, e que a composição (a
ordem das projeções e a ligação das origens, conhecimento exclusivo da API) continua correta.

`DataPipeline.data_sanitization` e `DataPipeline.abt_transform` são importados com o prefixo
do pacote — o nome nu não resolve pelo `pythonpath` deste componente (`. ..`), que não inclui
`DataPipeline/` diretamente.
"""
import hashlib
from pathlib import Path
from typing import Any

import pytest

from DataPipeline.abt_transform import (
    create_agg_bureau,
    create_agg_installments,
    create_agg_previous_application,
    run_abt_generation,
)
from DataPipeline.data_sanitization import run_sanitization
from infra.db import get_database_engine
from infra.testing import configuracao_do_banco_de_teste

from MLOps.app.api.new_customer_feature_transformation_service import (
    NewCustomerFeatureTransformationService,
    TransformationRuleMismatchError,
)
from MLOps.tests.fixtures import build_model_bundle, build_transformation_contract


SQL_DIRECTORY = Path(__file__).resolve().parents[2] / "DataPipeline" / "sql"

# Mesmas 28 colunas de DataPipeline/tests/test_sanitization_app.py::APPLICATION_SCHEMA — a
# referência única dos tipos de `application_train` que a §5.4 do plano nomeia.
APPLICATION_SCHEMA = {
    "sk_id_curr": "BIGINT",
    "target": "BIGINT",
    "ext_source_1": "DOUBLE PRECISION",
    "ext_source_2": "DOUBLE PRECISION",
    "ext_source_3": "DOUBLE PRECISION",
    "days_last_phone_change": "DOUBLE PRECISION",
    "cnt_fam_members": "DOUBLE PRECISION",
    "amt_annuity": "DOUBLE PRECISION",
    "amt_income_total": "DOUBLE PRECISION",
    "own_car_age": "DOUBLE PRECISION",
    "flag_own_car": "TEXT",
    "organization_type": "TEXT",
    "name_income_type": "TEXT",
    "region_rating_client_w_city": "BIGINT",
    "days_id_publish": "BIGINT",
    "days_registration": "BIGINT",
    "reg_city_not_work_city": "BIGINT",
    "reg_city_not_live_city": "BIGINT",
    "live_city_not_work_city": "BIGINT",
    "def_60_cnt_social_circle": "DOUBLE PRECISION",
    "amt_req_credit_bureau_year": "DOUBLE PRECISION",
    "cnt_children": "BIGINT",
    "amt_credit": "DOUBLE PRECISION",
    "occupation_type": "TEXT",
    "name_education_type": "TEXT",
    "code_gender": "TEXT",
    "days_birth": "BIGINT",
    "days_employed": "BIGINT",
}

RAW_APPLICATION_RECORD = {
    "ext_source_1": 0.62,
    "ext_source_2": 0.48,
    "ext_source_3": 0.55,
    "days_last_phone_change": -300.0,
    "cnt_fam_members": 3.0,
    "amt_annuity": 28000.0,
    "amt_income_total": 180000.0,
    "own_car_age": 5.0,
    "flag_own_car": "Y",
    "organization_type": "Business Entity Type 3",
    "name_income_type": "Working",
    "region_rating_client_w_city": 2,
    "days_id_publish": -2500,
    "days_registration": -3500,
    "reg_city_not_work_city": 1,
    "reg_city_not_live_city": 0,
    "live_city_not_work_city": 0,
    "def_60_cnt_social_circle": 1.0,
    "amt_req_credit_bureau_year": 2.0,
    "cnt_children": 1,
    "amt_credit": 450000.0,
    "occupation_type": "Laborers",
    "name_education_type": "Secondary / secondary special",
    "code_gender": "F",
    "days_birth": -13000,
    "days_employed": -1800,
}

TRANSFORMATION_CONTRACT_EXCLUDED_COLUMNS = {
    "valid_orgs", "valid_incs", "cardinalidade_min_freq", "income_winsor_q",
    "application_sanitization_projection_sha256", "run_at",
}


def _run_pipeline_for_one_customer(test_db, conexao, sk_id_curr: int, record: dict) -> dict:
    """Materializa o registro pelas tabelas reais do pipeline — sanitização, as três
    agregações (vazias, como um cliente sem histórico em nenhuma fonte) e a ABT —, e devolve
    a linha final de `application_abt`."""
    test_db.create_table("application_train", APPLICATION_SCHEMA)
    test_db.insert("application_train", [{"sk_id_curr": sk_id_curr, "target": 0, **record}])
    run_sanitization(
        conexao, "application_train", "application_clean",
        "application_sanitization_last_run",
        cardinalidade_min_freq=1, income_winsor_q=0.99,
    )

    test_db.create_table(
        "previous_application_clean",
        {"sk_id_curr": "BIGINT", "sk_id_prev": "BIGINT", "name_contract_status": "TEXT"},
    )
    create_agg_previous_application(conexao, "previous_application_clean")

    test_db.create_table(
        "bureau_clean",
        {
            "sk_id_curr": "BIGINT", "sk_id_bureau": "BIGINT", "days_credit": "NUMERIC",
            "credit_active": "TEXT", "amt_credit_sum": "NUMERIC",
            "amt_credit_sum_debt": "NUMERIC", "credit_day_overdue": "NUMERIC",
        },
    )
    create_agg_bureau(conexao, "bureau_clean")

    test_db.create_table(
        "installments_clean",
        {
            "sk_id_curr": "BIGINT", "days_instalment": "DOUBLE PRECISION",
            "days_entry_payment": "DOUBLE PRECISION",
        },
    )
    create_agg_installments(conexao, "installments_clean")

    run_abt_generation(
        conexao,
        {
            "output_table": "application_clean",
            "abt_table": "application_abt",
            "abt_generation_last_run_table": "application_abt_generation_last_run",
        },
    )

    return test_db.fetch_dicts(
        'SELECT * FROM "application_abt" WHERE sk_id_curr = %s', (sk_id_curr,)
    )[0]


def _transformation_contract_from_pipeline(test_db) -> dict[str, Any]:
    """O mesmo contrato que `load_transformation_contract` monta (Model/train.py), lido das
    duas tabelas que o pipeline acabou de gravar — sem reimplementar a montagem aqui."""
    sanitization_row = test_db.fetch_dicts(
        'SELECT * FROM "application_sanitization_last_run"'
    )[0]
    abt_row = test_db.fetch_dicts(
        'SELECT * FROM "application_abt_generation_last_run"'
    )[0]
    return {
        "stats": {
            name: value
            for name, value in sanitization_row.items()
            if name not in TRANSFORMATION_CONTRACT_EXCLUDED_COLUMNS
        },
        "valid_orgs": sanitization_row["valid_orgs"],
        "valid_incs": sanitization_row["valid_incs"],
        "cardinalidade_min_freq": sanitization_row["cardinalidade_min_freq"],
        "income_winsor_q": sanitization_row["income_winsor_q"],
        "application_sanitization_projection_sha256": sanitization_row[
            "application_sanitization_projection_sha256"
        ],
        "application_abt_record_projection_sha256": abt_row[
            "application_abt_record_projection_sha256"
        ],
    }


def _assert_transformed_matches_pipeline(transformed: dict, abt_row: dict) -> None:
    for column in abt_row:
        if column in {"sk_id_curr", "target"}:
            continue
        pipeline_value = abt_row[column]
        service_value = transformed[column]
        if isinstance(pipeline_value, float):
            assert service_value == pytest.approx(pipeline_value), column
        else:
            assert service_value == pipeline_value, column


@pytest.fixture
def engine():
    config = configuracao_do_banco_de_teste()
    database_engine = get_database_engine(
        f"postgresql://{config['user']}:{config['password']}"
        f"@{config['host']}:{config['port']}/{config['dbname']}"
    )
    try:
        yield database_engine
    finally:
        database_engine.dispose()


@pytest.mark.integration
def test_service_produces_the_same_features_as_the_pipeline(test_db, conexao, engine):
    abt_row = _run_pipeline_for_one_customer(
        test_db, conexao, sk_id_curr=1, record=RAW_APPLICATION_RECORD
    )
    transformation_contract = _transformation_contract_from_pipeline(test_db)
    bundle = build_model_bundle(transformation_contract=transformation_contract)

    service = NewCustomerFeatureTransformationService(engine, SQL_DIRECTORY)
    transformed = service.transform(bundle, RAW_APPLICATION_RECORD)

    _assert_transformed_matches_pipeline(transformed, abt_row)
    assert len(transformed) == 42 + 1  # as 42 features, mais o sk_id_curr fabricado


@pytest.mark.integration
@pytest.mark.parametrize(
    "overrides",
    [
        {"ext_source_1": None, "ext_source_2": None, "ext_source_3": None},
        {"flag_own_car": None, "own_car_age": None},
        {"organization_type": "Uma organização qualquer"},
    ],
    ids=["optional_scores_absent", "flag_own_car_absent", "distinct_organization_value"],
)
def test_service_matches_pipeline_with_optional_fields_varied(
    test_db, conexao, engine, overrides
):
    record = {**RAW_APPLICATION_RECORD, **overrides}
    abt_row = _run_pipeline_for_one_customer(test_db, conexao, sk_id_curr=1, record=record)
    transformation_contract = _transformation_contract_from_pipeline(test_db)
    bundle = build_model_bundle(transformation_contract=transformation_contract)

    service = NewCustomerFeatureTransformationService(engine, SQL_DIRECTORY)
    transformed = service.transform(bundle, record)

    _assert_transformed_matches_pipeline(transformed, abt_row)


@pytest.mark.integration
def test_transformation_is_refused_when_sanitization_hash_diverges(engine):
    contract = build_transformation_contract()
    contract["application_sanitization_projection_sha256"] = "0" * 64
    bundle = build_model_bundle(transformation_contract=contract)
    service = NewCustomerFeatureTransformationService(engine, SQL_DIRECTORY)

    with pytest.raises(
        TransformationRuleMismatchError, match="application_sanitization_projection.sql"
    ):
        service.transform(bundle, RAW_APPLICATION_RECORD)


@pytest.mark.integration
def test_transformation_is_refused_when_abt_hash_diverges(engine):
    contract = build_transformation_contract()
    contract["application_sanitization_projection_sha256"] = hashlib.sha256(
        (SQL_DIRECTORY / "application_sanitization_projection.sql").read_bytes()
    ).hexdigest()
    contract["application_abt_record_projection_sha256"] = "0" * 64
    bundle = build_model_bundle(transformation_contract=contract)
    service = NewCustomerFeatureTransformationService(engine, SQL_DIRECTORY)

    with pytest.raises(
        TransformationRuleMismatchError, match="application_abt_record_projection.sql"
    ):
        service.transform(bundle, RAW_APPLICATION_RECORD)


@pytest.mark.integration
def test_transformation_is_refused_when_sql_references_a_statistic_missing_from_the_contract(
    tmp_path, engine
):
    """Um `.sql` com uma referência `stats.<nome>` a mais é recusado nomeando essa
    estatística, sem tocar em código Python — é o teste que fixa a derivação dos nomes a
    partir do arquivo."""
    modified_text = (
        (SQL_DIRECTORY / "application_sanitization_projection.sql").read_text(encoding="utf-8")
        + "\n-- stats.median_nao_existente\n"
    )
    modified_path = tmp_path / "application_sanitization_projection.sql"
    modified_path.write_text(modified_text, encoding="utf-8")
    abt_copy_path = tmp_path / "application_abt_record_projection.sql"
    abt_copy_path.write_text(
        (SQL_DIRECTORY / "application_abt_record_projection.sql").read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    contract = build_transformation_contract()
    contract["application_sanitization_projection_sha256"] = hashlib.sha256(
        modified_path.read_bytes()
    ).hexdigest()
    contract["application_abt_record_projection_sha256"] = hashlib.sha256(
        abt_copy_path.read_bytes()
    ).hexdigest()
    bundle = build_model_bundle(transformation_contract=contract)

    service = NewCustomerFeatureTransformationService(engine, tmp_path)

    with pytest.raises(TransformationRuleMismatchError, match="median_nao_existente"):
        service.transform(bundle, RAW_APPLICATION_RECORD)
