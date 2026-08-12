"""Shared test fixtures for the DataPipeline Phase 1 suite.

The production functions receive an open connection from whoever calls them — the
Airflow task opens it through the ``PostgresHook``; the suite opens it against a
*dedicated test database* and injects it through the very same parameter, so no
call is mocked, patched or intercepted.

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


def _connect(dbname: str, autocommit: bool = True):
    conn = psycopg2.connect(
        host=TEST_DB_HOST,
        port=TEST_DB_PORT,
        user=TEST_DB_USER,
        password=TEST_DB_PASSWORD,
        dbname=dbname,
    )
    conn.autocommit = autocommit
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
def ambiente_do_banco_de_teste():
    """Declara as ``POSTGRES_*`` apontando para o banco de teste, e restaura ao fim.

    Só os testes de `get_db_connection_str_from_env` — a única fronteira que lê o
    ambiente — precisam dela. Nenhuma função de produção lê ambiente, então a suíte não
    escreve mais nessas variáveis de forma global.
    """
    variaveis = {
        "POSTGRES_HOST": TEST_DB_HOST,
        "POSTGRES_PORT": TEST_DB_PORT,
        "POSTGRES_USER": TEST_DB_USER,
        "POSTGRES_PASSWORD": TEST_DB_PASSWORD,
        "POSTGRES_DATA_DB": TEST_DB_NAME,
    }
    anteriores = {nome: os.environ.get(nome) for nome in variaveis}
    os.environ.update(variaveis)
    try:
        yield
    finally:
        for nome, valor in anteriores.items():
            if valor is None:
                os.environ.pop(nome, None)
            else:
                os.environ[nome] = valor


@pytest.fixture
def conexao(_verify_test_database):
    """Conexão DBAPI com o banco de teste — o que a task da DAG entrega em produção.

    Sem ``autocommit``: as funções do pipeline chamam ``commit()`` e ``rollback()``
    explicitamente, e com autocommit ligado o rollback não teria efeito observável, de modo
    que o teste mentiria sobre o comportamento transacional.

    Deve ser declarada **depois** de ``test_db`` na assinatura do teste: assim é finalizada
    antes dele, e a transação em aberto não bloqueia o DROP TABLE da limpeza.
    """
    conn = _connect(TEST_DB_NAME, autocommit=False)
    try:
        yield conn
    finally:
        conn.close()


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
