"""T2 — Ingestion (`run_csv_ingestion`).

Data contract: all CSV rows reach the table; columns/values preserved;
re-ingestion rebuilds without duplication; a smaller ``chunk_size`` still loads
every row; a missing folder/file fails clearly.
Internal-parsing contract (config_file): a declared source is accepted; an
undeclared source is rejected.
"""

import csv
import json
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


def _write_config(path: Path, table_names: list[str]) -> str:
    config = {
        "ingestion_table": {
            "using_csv": [
                {"table_name": name, "chunk_size": 1000} for name in table_names
            ]
        }
    }
    path.write_text(json.dumps(config))
    return str(path)


@pytest.mark.integration
def test_all_csv_rows_are_persisted(db, tmp_path):
    source = tmp_path / "csv"
    _write_csv(source, TABLE, CUSTOMERS)
    config_file = _write_config(tmp_path / "config_pipeline.json", [TABLE])

    run_csv_ingestion(str(source), TABLE, CONN_ID, config_file, chunk_size=1000)

    assert db.row_count(TABLE) == len(CUSTOMERS)


@pytest.mark.integration
def test_csv_columns_and_values_are_preserved(db, tmp_path):
    source = tmp_path / "csv"
    _write_csv(source, TABLE, CUSTOMERS)
    config_file = _write_config(tmp_path / "config_pipeline.json", [TABLE])

    run_csv_ingestion(str(source), TABLE, CONN_ID, config_file, chunk_size=1000)

    assert set(db.table_columns(TABLE)) == set(CUSTOMERS[0].keys())
    persisted = db.fetch_dicts(f'SELECT * FROM "{TABLE}" ORDER BY sk_id_curr')
    assert persisted == sorted(CUSTOMERS, key=lambda row: row["sk_id_curr"])


@pytest.mark.integration
def test_reingestion_rebuilds_without_duplication(db, tmp_path):
    source = tmp_path / "csv"
    _write_csv(source, TABLE, CUSTOMERS)
    config_file = _write_config(tmp_path / "config_pipeline.json", [TABLE])

    run_csv_ingestion(str(source), TABLE, CONN_ID, config_file, chunk_size=1000)
    run_csv_ingestion(str(source), TABLE, CONN_ID, config_file, chunk_size=1000)

    assert db.row_count(TABLE) == len(CUSTOMERS)


@pytest.mark.integration
def test_small_chunk_size_loads_every_row(db, tmp_path):
    source = tmp_path / "csv"
    _write_csv(source, TABLE, CUSTOMERS)
    config_file = _write_config(tmp_path / "config_pipeline.json", [TABLE])

    run_csv_ingestion(str(source), TABLE, CONN_ID, config_file, chunk_size=2)

    assert db.row_count(TABLE) == len(CUSTOMERS)


@pytest.mark.integration
def test_declared_source_is_accepted(db, tmp_path):
    source = tmp_path / "csv"
    _write_csv(source, TABLE, CUSTOMERS)
    config_file = _write_config(tmp_path / "config_pipeline.json", [TABLE])

    run_csv_ingestion(str(source), TABLE, CONN_ID, config_file, chunk_size=1000)

    assert db.table_exists(TABLE)


def test_missing_source_folder_fails_clearly(tmp_path):
    config_file = _write_config(tmp_path / "config_pipeline.json", [TABLE])
    missing_folder = tmp_path / "does_not_exist"

    with pytest.raises(FileNotFoundError):
        run_csv_ingestion(str(missing_folder), TABLE, CONN_ID, config_file, 1000)


def test_missing_matching_file_fails_clearly(tmp_path):
    source = tmp_path / "csv"
    source.mkdir()
    config_file = _write_config(tmp_path / "config_pipeline.json", [TABLE])

    with pytest.raises(FileNotFoundError):
        run_csv_ingestion(str(source), TABLE, CONN_ID, config_file, 1000)


def test_undeclared_source_is_rejected(tmp_path):
    source = tmp_path / "csv"
    _write_csv(source, TABLE, CUSTOMERS)
    config_file = _write_config(tmp_path / "config_pipeline.json", ["some_other_source"])

    with pytest.raises(ValueError):
        run_csv_ingestion(str(source), TABLE, CONN_ID, config_file, 1000)
