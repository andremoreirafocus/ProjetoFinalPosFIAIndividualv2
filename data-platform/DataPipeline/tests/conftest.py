"""Shared test fixtures for the DataPipeline Phase 1 suite.

The production functions obtain their own connection through
``utils.get_database_connection``, which — outside Airflow and outside Docker —
builds a SQLAlchemy engine from the ``POSTGRES_*`` environment variables and
connects to ``localhost``. We drive the real functions against a *dedicated test
database* by setting those variables here from an explicit test configuration
file, so no call is mocked, patched or intercepted.

Configuration is explicit and deterministic: it is read from
``tests/test_database.ini`` and every key is required — there is no environment
fallback and no inline default. A guard refuses to run unless the target is a
``*_test`` database distinct from the pipeline database, so the suite can never
create, recreate or drop tables in the real pipeline database.
"""

from __future__ import annotations

import configparser
import os
import sys
from pathlib import Path

import psycopg2
import pytest


# --- make the production modules importable (utils, ingestion, ...) -----------
DATAPIPELINE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DATAPIPELINE_DIR))


# --- explicit, required test database configuration (no fallbacks) ------------
TEST_DB_CONFIG_PATH = Path(__file__).resolve().parent / "test_database.ini"
_REQUIRED_KEYS = ("host", "port", "user", "password", "dbname", "pipeline_dbname")


def _load_test_db_config() -> dict[str, str]:
    if not TEST_DB_CONFIG_PATH.is_file():
        raise pytest.UsageError(
            f"Missing test database configuration file: {TEST_DB_CONFIG_PATH}"
        )
    parser = configparser.ConfigParser(interpolation=None)
    parser.read(TEST_DB_CONFIG_PATH)
    if not parser.has_section("test_database"):
        raise pytest.UsageError(
            f"Missing [test_database] section in {TEST_DB_CONFIG_PATH}"
        )
    section = parser["test_database"]
    missing = [key for key in _REQUIRED_KEYS if not section.get(key)]
    if missing:
        raise pytest.UsageError(
            f"Missing required keys in [test_database] of {TEST_DB_CONFIG_PATH}: {missing}"
        )
    return {key: section[key] for key in _REQUIRED_KEYS}


_CONFIG = _load_test_db_config()
TEST_DB_HOST = _CONFIG["host"]
TEST_DB_PORT = _CONFIG["port"]
TEST_DB_USER = _CONFIG["user"]
TEST_DB_PASSWORD = _CONFIG["password"]
TEST_DB_NAME = _CONFIG["dbname"]
PIPELINE_DB_NAME = _CONFIG["pipeline_dbname"]

if TEST_DB_NAME == PIPELINE_DB_NAME or not TEST_DB_NAME.endswith("_test"):
    raise pytest.UsageError(
        f"Refusing to run: the test database '{TEST_DB_NAME}' must differ from the "
        f"pipeline database '{PIPELINE_DB_NAME}' and end with '_test'."
    )

# Point the production code's get_database_connection at the test database
# (it reads POSTGRES_*). Values come from the test config file above, never from
# the ambient environment.
os.environ.pop("AIRFLOW_HOME", None)  # force the SQLAlchemy path deterministically
os.environ["POSTGRES_HOST"] = TEST_DB_HOST
os.environ["POSTGRES_PORT"] = TEST_DB_PORT
os.environ["POSTGRES_USER"] = TEST_DB_USER
os.environ["POSTGRES_PASSWORD"] = TEST_DB_PASSWORD
os.environ["POSTGRES_DATA_DB"] = TEST_DB_NAME


def _connect(dbname: str):
    conn = psycopg2.connect(
        host=TEST_DB_HOST,
        port=TEST_DB_PORT,
        user=TEST_DB_USER,
        password=TEST_DB_PASSWORD,
        dbname=dbname,
    )
    conn.autocommit = True
    return conn


@pytest.fixture(scope="session")
def _verify_test_database():
    """Verify the dedicated test database is reachable by the least-privilege role.

    Provisioning — the ``data_test_user`` role, the ``data_test`` database it owns,
    and the revoke that blocks non-superusers from the pipeline database — is done
    once, out of band, by ``postgres/init/02-create-test-role-and-db.sql`` (run
    automatically on a fresh volume, or by hand on an existing one). The suite never
    creates databases: the test role is intentionally ``NOCREATEDB`` and cannot reach
    the pipeline database, so isolation cannot be undone from within the tests.

    Not autouse: only tests that request the ``test_db`` fixture touch the database, so the
    pure input-validation tests can run without PostgreSQL.
    """
    try:
        conn = _connect(TEST_DB_NAME)
    except psycopg2.OperationalError as exc:
        raise pytest.UsageError(
            f"Cannot connect to the test database '{TEST_DB_NAME}' as "
            f"'{TEST_DB_USER}'. Provision it once with "
            f"postgres/init/02-create-test-role-and-db.sql — e.g. "
            f"`docker compose exec postgres psql -U airflow -d airflow "
            f"-f /docker-entrypoint-initdb.d/02-create-test-role-and-db.sql`. "
            f"Original error: {exc}"
        ) from exc
    conn.close()
    yield


class DB:
    """Thin helper to arrange fixtures and assert observable database state."""

    def __init__(self, conn) -> None:
        self.conn = conn

    def execute(self, sql: str, params=None) -> None:
        with self.conn.cursor() as cur:
            cur.execute(sql, params)

    def create_table(self, name: str, columns: dict[str, str]) -> None:
        cols = ", ".join(f'"{col}" {type_}' for col, type_ in columns.items())
        self.execute(f'DROP TABLE IF EXISTS "{name}" CASCADE;')
        self.execute(f'CREATE TABLE "{name}" ({cols});')

    def insert(self, name: str, rows: list[dict]) -> None:
        for row in rows:
            cols = list(row.keys())
            col_list = ", ".join(f'"{c}"' for c in cols)
            placeholders = ", ".join(["%s"] * len(cols))
            self.execute(
                f'INSERT INTO "{name}" ({col_list}) VALUES ({placeholders})',
                [row[c] for c in cols],
            )

    def scalar(self, sql: str, params=None):
        with self.conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchone()[0]

    def fetch_dicts(self, sql: str, params=None) -> list[dict]:
        with self.conn.cursor() as cur:
            cur.execute(sql, params)
            columns = [d[0] for d in cur.description]
            return [dict(zip(columns, row)) for row in cur.fetchall()]

    def row_count(self, table: str) -> int:
        return int(self.scalar(f'SELECT COUNT(*) FROM "{table}"'))

    def table_columns(self, table: str) -> list[str]:
        rows = self.fetch_dicts(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = %s ORDER BY ordinal_position",
            (table,),
        )
        return [r["column_name"] for r in rows]

    def indexes(self, table: str) -> dict[str, str]:
        rows = self.fetch_dicts(
            "SELECT indexname, indexdef FROM pg_indexes "
            "WHERE schemaname = 'public' AND tablename = %s",
            (table,),
        )
        return {r["indexname"]: r["indexdef"] for r in rows}

    def all_public_indexes(self) -> dict[str, str]:
        rows = self.fetch_dicts(
            "SELECT indexname, indexdef FROM pg_indexes WHERE schemaname = 'public'"
        )
        return {r["indexname"]: r["indexdef"] for r in rows}

    def table_exists(self, name: str) -> bool:
        return self.scalar("SELECT to_regclass(%s) IS NOT NULL", (f"public.{name}",))


def _drop_all_public_tables(conn) -> None:
    with conn.cursor() as cur:
        cur.execute("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
        tables = [row[0] for row in cur.fetchall()]
        for table in tables:
            cur.execute(f'DROP TABLE IF EXISTS "{table}" CASCADE;')


@pytest.fixture
def test_db(_verify_test_database):
    """A helper bound to the test database, with a clean public schema."""
    conn = _connect(TEST_DB_NAME)
    _drop_all_public_tables(conn)
    helper = DB(conn)
    try:
        yield helper
    finally:
        _drop_all_public_tables(conn)
        conn.close()
