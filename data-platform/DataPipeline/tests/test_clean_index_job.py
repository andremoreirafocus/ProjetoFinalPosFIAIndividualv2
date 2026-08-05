"""T6 — Clean index job (`run_abt_indexes`).

Receives the full config and resolves the clean tables from ``config["database"]``.
Each clean table gets an index on ``sk_id_curr``; re-running does not duplicate; it
creates no raw indexes. An empty/None table name raises ``ValueError``.
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


def _create_clean_tables(db, db_config=CLEAN_DB_CONFIG):
    for table in db_config.values():
        db.create_table(table, {"sk_id_curr": "BIGINT"})


def _index_name(table: str) -> str:
    return f"idx_abt_{table}_sk_id_curr"


@pytest.mark.integration
def test_clean_job_resolves_tables_from_config_database(db):
    _create_clean_tables(db)

    run_abt_indexes(CONN_ID, {"database": CLEAN_DB_CONFIG})

    for table in CLEAN_DB_CONFIG.values():
        assert _index_name(table) in db.indexes(table)


@pytest.mark.integration
def test_clean_job_indexes_each_clean_table_on_sk_id_curr(db):
    _create_clean_tables(db)

    run_abt_indexes(CONN_ID, {"database": CLEAN_DB_CONFIG})

    for table in CLEAN_DB_CONFIG.values():
        definitions = db.indexes(table).values()
        assert any("(sk_id_curr)" in definition for definition in definitions)


@pytest.mark.integration
def test_all_four_clean_tables_receive_indexes(db):
    _create_clean_tables(db)

    run_abt_indexes(CONN_ID, {"database": CLEAN_DB_CONFIG})

    indexed_tables = {table for table in CLEAN_DB_CONFIG.values() if db.indexes(table)}
    assert indexed_tables == set(CLEAN_DB_CONFIG.values())


@pytest.mark.integration
def test_clean_index_creation_is_idempotent(db):
    _create_clean_tables(db)

    run_abt_indexes(CONN_ID, {"database": CLEAN_DB_CONFIG})
    after_first_run = db.all_public_indexes()
    run_abt_indexes(CONN_ID, {"database": CLEAN_DB_CONFIG})
    after_second_run = db.all_public_indexes()

    assert after_second_run == after_first_run


@pytest.mark.integration
def test_clean_job_does_not_create_raw_indexes(db):
    _create_clean_tables(db)

    run_abt_indexes(CONN_ID, {"database": CLEAN_DB_CONFIG})

    index_names = set(db.all_public_indexes())
    assert all(name.startswith("idx_abt_") for name in index_names)


@pytest.mark.integration
def test_clean_job_raises_when_table_name_is_empty(db):
    config = {"database": {**CLEAN_DB_CONFIG, "output_table": ""}}

    with pytest.raises(ValueError):
        run_abt_indexes(CONN_ID, config)
