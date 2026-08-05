"""T3 — Raw index job (`run_create_indexes`).

Contract: each source table gets an index on the join/filter keys the pipeline
uses; re-running does not duplicate; no clean-table indexes are created.
"""

import pytest

from ingestion_index import run_create_indexes


# Domain expectation: the join/filter keys the pipeline relies on per raw source.
RAW_JOIN_FILTER_KEYS = {
    "application_train": ["sk_id_curr", "organization_type", "name_income_type", "flag_own_car"],
    "previous_application": ["sk_id_prev", "sk_id_curr"],
    "bureau": ["sk_id_bureau", "sk_id_curr"],
    "installments_payments": ["sk_id_curr", "sk_id_prev"],
}

CONN_ID = "postgres_data_db"


def _create_raw_tables(db):
    for table, columns in RAW_JOIN_FILTER_KEYS.items():
        schema = {
            col: ("BIGINT" if col.startswith("sk_") else "TEXT") for col in columns
        }
        db.create_table(table, schema)


def _has_single_column_index(indexes: dict, column: str) -> bool:
    return any(f"({column})" in definition for definition in indexes.values())


@pytest.mark.integration
def test_raw_job_creates_expected_join_and_filter_indexes(db):
    _create_raw_tables(db)

    run_create_indexes(CONN_ID)

    for table, columns in RAW_JOIN_FILTER_KEYS.items():
        table_indexes = db.indexes(table)
        for column in columns:
            assert _has_single_column_index(table_indexes, column), (
                f"expected an index on {table}.{column}"
            )


@pytest.mark.integration
def test_raw_index_creation_is_idempotent(db):
    _create_raw_tables(db)

    run_create_indexes(CONN_ID)
    after_first_run = db.all_public_indexes()
    run_create_indexes(CONN_ID)
    after_second_run = db.all_public_indexes()

    assert after_second_run == after_first_run


@pytest.mark.integration
def test_raw_job_does_not_create_clean_indexes(db):
    _create_raw_tables(db)

    run_create_indexes(CONN_ID)

    index_names = set(db.all_public_indexes())
    clean_index_names = {name for name in index_names if name.startswith("idx_abt_")}
    assert clean_index_names == set()
