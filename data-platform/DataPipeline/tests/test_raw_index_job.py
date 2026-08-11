"""T3 — Raw index job (`run_create_indexes`).

Contract: the job receives the parsed ``config`` object and creates exactly the
indexes declared in ``config["indexes"]["raw"]`` (Apêndice A of the
implementation plan), each resolved by ``table_ref`` against
``config["database"]``. Re-running does not duplicate; no clean-table indexes
are created.
"""

import pytest

from ingestion_index import run_create_indexes


CONN_ID = "postgres_data_db"

RAW_DB_CONFIG = {
    "input_table": "application_train",
    "input_prev_table": "previous_application",
    "input_bureau_table": "bureau",
    "input_installments_table": "installments_payments",
}

# Domain fixture: Apêndice A — the join/filter keys the pipeline relies on per
# raw source, one entry per index actually created.
RAW_INDEXES = [
    {"name": "idx_app_sk_id_curr", "table_ref": "input_table", "columns": ["sk_id_curr"]},
    {"name": "idx_app_org_type", "table_ref": "input_table", "columns": ["organization_type"]},
    {"name": "idx_app_inc_type", "table_ref": "input_table", "columns": ["name_income_type"]},
    {"name": "idx_app_flag_car", "table_ref": "input_table", "columns": ["flag_own_car"]},
    {"name": "idx_prev_sk_id_prev", "table_ref": "input_prev_table", "columns": ["sk_id_prev"]},
    {"name": "idx_prev_sk_id_curr", "table_ref": "input_prev_table", "columns": ["sk_id_curr"]},
    {"name": "idx_bur_sk_id_bureau", "table_ref": "input_bureau_table", "columns": ["sk_id_bureau"]},
    {"name": "idx_bur_sk_id_curr", "table_ref": "input_bureau_table", "columns": ["sk_id_curr"]},
    {"name": "idx_inst_sk_id_curr", "table_ref": "input_installments_table", "columns": ["sk_id_curr"]},
    {"name": "idx_inst_sk_id_prev", "table_ref": "input_installments_table", "columns": ["sk_id_prev"]},
]


def _config(db_config=RAW_DB_CONFIG, raw_indexes=RAW_INDEXES) -> dict:
    return {"database": db_config, "indexes": {"raw": raw_indexes}}


def _create_raw_tables(test_db, db_config=RAW_DB_CONFIG, raw_indexes=RAW_INDEXES):
    columns_by_table: dict[str, set] = {}
    for entry in raw_indexes:
        table = db_config[entry["table_ref"]]
        columns_by_table.setdefault(table, set()).update(entry["columns"])
    for table, columns in columns_by_table.items():
        schema = {col: ("BIGINT" if col.startswith("sk_") else "TEXT") for col in columns}
        test_db.create_table(table, schema)


@pytest.mark.integration
def test_raw_job_creates_configured_raw_indexes(test_db):
    _create_raw_tables(test_db)

    run_create_indexes(CONN_ID, _config())

    for entry in RAW_INDEXES:
        table = RAW_DB_CONFIG[entry["table_ref"]]
        assert entry["name"] in test_db.indexes(table)


@pytest.mark.integration
def test_raw_table_ref_resolves_database_table(test_db):
    test_db.create_table("application_train", {"sk_id_curr": "BIGINT"})  # old physical name, untouched
    renamed_db_config = {**RAW_DB_CONFIG, "input_table": "application_train_renamed"}
    _create_raw_tables(test_db, renamed_db_config)

    run_create_indexes(CONN_ID, _config(db_config=renamed_db_config))

    assert RAW_INDEXES[0]["name"] in test_db.indexes("application_train_renamed")
    assert test_db.indexes("application_train") == {}


@pytest.mark.integration
def test_raw_index_creation_is_idempotent(test_db):
    _create_raw_tables(test_db)

    run_create_indexes(CONN_ID, _config())
    after_first_run = test_db.all_public_indexes()
    run_create_indexes(CONN_ID, _config())
    after_second_run = test_db.all_public_indexes()

    assert after_second_run == after_first_run


@pytest.mark.integration
def test_raw_job_does_not_create_clean_indexes(test_db):
    _create_raw_tables(test_db)

    run_create_indexes(CONN_ID, _config())

    index_names = set(test_db.all_public_indexes())
    clean_index_names = {name for name in index_names if name.startswith("idx_abt_")}
    assert clean_index_names == set()
