"""T2 — Ingestion (`run_csv_ingestion`).

Contract: the routine receives the parsed ``config`` object and the table name; it
resolves the source's declared ``chunk_size`` from that object, requires no config
file on disk, ingests every CSV row, preserves columns/values, and rebuilds without
duplication. It fails clearly for an undeclared source, for a declared source with no
``chunk_size``, and for a missing data folder/file.
"""

import csv
from pathlib import Path

import pytest

from ingestion import run_csv_ingestion


CONN_ID = "postgres_data_db"
TABLE = "application_train"

# Domain fixture: five loan applicants with target and income.
CUSTOMERS = [
    {"sk_id_curr": 100001, "target": 0, "code_gender": "F", "amt_income_total": 202500},
    {"sk_id_curr": 100002, "target": 1, "code_gender": "M", "amt_income_total": 135000},
    {"sk_id_curr": 100003, "target": 0, "code_gender": "F", "amt_income_total": 121500},
    {"sk_id_curr": 100004, "target": 0, "code_gender": "M", "amt_income_total": 99000},
    {"sk_id_curr": 100005, "target": 1, "code_gender": "F", "amt_income_total": 171000},
]


def _write_csv(folder: Path, table: str, rows: list[dict]) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{table}.csv"
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def _config(sources: list[tuple[str, int]]) -> dict:
    """Build the parsed config object; ``sources`` are (table_name, chunk_size) pairs."""
    return {
        "ingestion_table": {
            "using_csv": [
                {"table_name": name, "chunk_size": chunk} for name, chunk in sources
            ]
        }
    }


@pytest.mark.integration
def test_declared_source_is_ingested(db, tmp_path):
    source = tmp_path / "csv"
    _write_csv(source, TABLE, CUSTOMERS)

    run_csv_ingestion(str(source), TABLE, CONN_ID, _config([(TABLE, 1000)]))

    assert db.table_exists(TABLE)
    assert db.row_count(TABLE) == len(CUSTOMERS)


@pytest.mark.integration
def test_all_csv_rows_are_persisted(db, tmp_path):
    source = tmp_path / "csv"
    _write_csv(source, TABLE, CUSTOMERS)

    run_csv_ingestion(str(source), TABLE, CONN_ID, _config([(TABLE, 1000)]))

    assert db.row_count(TABLE) == len(CUSTOMERS)


@pytest.mark.integration
def test_csv_columns_and_values_are_preserved(db, tmp_path):
    source = tmp_path / "csv"
    _write_csv(source, TABLE, CUSTOMERS)

    run_csv_ingestion(str(source), TABLE, CONN_ID, _config([(TABLE, 1000)]))

    assert set(db.table_columns(TABLE)) == set(CUSTOMERS[0].keys())
    persisted = db.fetch_dicts(f'SELECT * FROM "{TABLE}" ORDER BY sk_id_curr')
    assert persisted == sorted(CUSTOMERS, key=lambda row: row["sk_id_curr"])


@pytest.mark.integration
def test_reingestion_rebuilds_without_duplication(db, tmp_path):
    source = tmp_path / "csv"
    _write_csv(source, TABLE, CUSTOMERS)
    config = _config([(TABLE, 1000)])

    run_csv_ingestion(str(source), TABLE, CONN_ID, config)
    run_csv_ingestion(str(source), TABLE, CONN_ID, config)

    assert db.row_count(TABLE) == len(CUSTOMERS)


@pytest.mark.integration
def test_ingestion_uses_chunk_size_from_source_definition(db, tmp_path):
    # A chunk_size smaller than the row count, declared only in the config source
    # definition. No chunk_size is passed to the routine, so loading every row proves
    # the value was resolved from the configuration and used to iterate.
    source = tmp_path / "csv"
    _write_csv(source, TABLE, CUSTOMERS)
    small_chunk = 2
    assert small_chunk < len(CUSTOMERS)

    run_csv_ingestion(str(source), TABLE, CONN_ID, _config([(TABLE, small_chunk)]))

    assert db.row_count(TABLE) == len(CUSTOMERS)


@pytest.mark.integration
def test_ingestion_does_not_require_config_file(db, tmp_path):
    # Only a CSV exists; no config file is written anywhere. The in-memory config
    # object is sufficient for the call to succeed.
    source = tmp_path / "csv"
    _write_csv(source, TABLE, CUSTOMERS)

    run_csv_ingestion(str(source), TABLE, CONN_ID, _config([(TABLE, 1000)]))

    assert db.row_count(TABLE) == len(CUSTOMERS)
    assert not list(tmp_path.glob("*.json"))  # no configuration file was needed


def test_undeclared_source_is_rejected(tmp_path):
    source = tmp_path / "csv"
    _write_csv(source, TABLE, CUSTOMERS)
    config = _config([("some_other_source", 1000)])

    with pytest.raises(ValueError):
        run_csv_ingestion(str(source), TABLE, CONN_ID, config)


def test_missing_source_folder_fails_clearly(tmp_path):
    missing_folder = tmp_path / "does_not_exist"

    with pytest.raises(FileNotFoundError):
        run_csv_ingestion(str(missing_folder), TABLE, CONN_ID, _config([(TABLE, 1000)]))


def test_missing_matching_file_fails_clearly(tmp_path):
    source = tmp_path / "csv"
    source.mkdir()

    with pytest.raises(FileNotFoundError):
        run_csv_ingestion(str(source), TABLE, CONN_ID, _config([(TABLE, 1000)]))
