"""T4 — Clean index job (`run_abt_indexes`).

Contract: the job receives the parsed ``config`` object and creates exactly the
indexes declared in ``config["indexes"]["clean"]`` (Apêndice A of the
implementation plan), each resolved by ``table_ref`` against
``config["database"]``. Re-running does not duplicate; no raw-table indexes are
created. A `table_ref` that resolves to an empty table name fails clearly.
"""

import pytest

from data_sanitization_index import run_abt_indexes


CONN_ID = "postgres_data_db"

CLEAN_DB_CONFIG = {
    "output_table": "application_clean",
    "output_prev_table": "previous_application_clean",
    "output_bureau_table": "bureau_clean",
    "output_installments_table": "installments_clean",
}

# Domain fixture: Apêndice A — one clean index per treated table, keyed by sk_id_curr.
CLEAN_INDEXES = [
    {"name": "idx_abt_application_clean_sk_id_curr", "table_ref": "output_table", "columns": ["sk_id_curr"]},
    {"name": "idx_abt_previous_application_clean_sk_id_curr", "table_ref": "output_prev_table", "columns": ["sk_id_curr"]},
    {"name": "idx_abt_bureau_clean_sk_id_curr", "table_ref": "output_bureau_table", "columns": ["sk_id_curr"]},
    {"name": "idx_abt_installments_clean_sk_id_curr", "table_ref": "output_installments_table", "columns": ["sk_id_curr"]},
]


def _config(db_config=CLEAN_DB_CONFIG, clean_indexes=CLEAN_INDEXES) -> dict:
    return {"database": db_config, "indexes": {"clean": clean_indexes}}


def _create_clean_tables(test_db, db_config=CLEAN_DB_CONFIG):
    for table in db_config.values():
        test_db.create_table(table, {"sk_id_curr": "BIGINT"})


@pytest.mark.integration
def test_clean_job_creates_configured_clean_indexes(test_db):
    _create_clean_tables(test_db)

    run_abt_indexes(CONN_ID, _config())

    for entry in CLEAN_INDEXES:
        table = CLEAN_DB_CONFIG[entry["table_ref"]]
        assert entry["name"] in test_db.indexes(table)


@pytest.mark.integration
def test_clean_table_refs_resolve_database_tables(test_db):
    renamed_db_config = {**CLEAN_DB_CONFIG, "output_table": "application_clean_renamed"}
    _create_clean_tables(test_db, renamed_db_config)

    run_abt_indexes(CONN_ID, _config(db_config=renamed_db_config))

    assert CLEAN_INDEXES[0]["name"] in test_db.indexes("application_clean_renamed")
    assert test_db.indexes("application_clean") == {}


@pytest.mark.integration
def test_clean_index_creation_is_idempotent(test_db):
    _create_clean_tables(test_db)

    run_abt_indexes(CONN_ID, _config())
    after_first_run = test_db.all_public_indexes()
    run_abt_indexes(CONN_ID, _config())
    after_second_run = test_db.all_public_indexes()

    assert after_second_run == after_first_run


@pytest.mark.integration
def test_clean_job_does_not_create_raw_indexes(test_db):
    _create_clean_tables(test_db)

    run_abt_indexes(CONN_ID, _config())

    index_names = set(test_db.all_public_indexes())
    raw_index_names = {name for name in index_names if not name.startswith("idx_abt_")}
    assert raw_index_names == set()


@pytest.mark.integration
def test_clean_job_raises_when_table_ref_resolves_to_empty_name(test_db):
    config = _config(db_config={**CLEAN_DB_CONFIG, "output_table": ""})

    with pytest.raises(ValueError):
        run_abt_indexes(CONN_ID, config)
