"""Harness de teste de banco, compartilhado pelas suítes da plataforma.

As funções de produção recebem uma conexão aberta de quem as chama — a task do Airflow
abre pelo `PostgresHook`; a suíte abre contra um **banco de testes dedicado** e a injeta
pelo mesmo parâmetro. Nenhuma chamada é interceptada, adiada ou substituída.

A configuração é explícita e determinística: vem de `infra/test_database.ini`, com todas as
chaves obrigatórias, sem fallback de ambiente e sem default embutido. Um guard recusa
executar se o alvo não for um banco `*_test` distinto do banco do pipeline, de modo que a
suíte não pode criar, recriar ou remover tabelas no banco de produção.

**A configuração é lida sob demanda**, dentro da fixture de sessão, e não no import: assim
uma suíte que não toca o banco — como a do `Model`, que injeta conexões falsas — roda sem
exigir o arquivo nem o PostgreSQL.

Uso pelas suítes, no `conftest.py` de cada componente:

    pytest_plugins = ["infra.testing"]

Contrato de ordem: **`conexao` deve ser declarada depois de `test_db`** na assinatura do
teste. A ordem determina a finalização — `conexao` é fechada antes —, e sem isso a
transação em aberto trava o `DROP TABLE` da limpeza feita pelo `test_db`.
"""

from __future__ import annotations

import configparser
import os
from pathlib import Path

import psycopg2
import pytest


TEST_DB_CONFIG_PATH = Path(__file__).resolve().parent / "test_database.ini"
_REQUIRED_KEYS = ("host", "port", "user", "password", "dbname", "pipeline_dbname")

_config_cache: dict[str, str] | None = None


def configuracao_do_banco_de_teste() -> dict[str, str]:
    """Lê e valida `test_database.ini`, aplicando o guard de isolamento.

    Chamada pelas fixtures e pelos testes que precisam dos valores. O resultado é
    memorizado: o arquivo é lido uma vez por execução da suíte.
    """
    global _config_cache
    if _config_cache is not None:
        return _config_cache

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

    config = {key: section[key] for key in _REQUIRED_KEYS}
    if config["dbname"] == config["pipeline_dbname"] or not config["dbname"].endswith("_test"):
        raise pytest.UsageError(
            f"Refusing to run: the test database '{config['dbname']}' must differ from the "
            f"pipeline database '{config['pipeline_dbname']}' and end with '_test'."
        )

    _config_cache = config
    return config


def connect(dbname: str, autocommit: bool = True):
    """Abre uma conexão psycopg2 com o banco informado, usando o papel de teste."""
    config = configuracao_do_banco_de_teste()
    conn = psycopg2.connect(
        host=config["host"],
        port=config["port"],
        user=config["user"],
        password=config["password"],
        dbname=dbname,
    )
    conn.autocommit = autocommit
    return conn


@pytest.fixture(scope="session")
def _verify_test_database():
    """Verifica que o banco de teste dedicado responde ao papel de menor privilégio.

    O provisionamento — o papel ``data_test_user``, o banco ``data_test`` que ele possui e
    o revoke que impede não-superusuários de alcançar o banco do pipeline — é feito uma vez,
    fora da suíte, por ``postgres/init/02-create-test-role-and-db.sql``. A suíte nunca cria
    bancos: o papel de teste é ``NOCREATEDB`` e não alcança o banco do pipeline, de modo que
    o isolamento não pode ser desfeito de dentro dos testes.

    Não é autouse: só os testes que pedem ``test_db`` ou ``conexao`` tocam o banco, então as
    validações puras rodam sem PostgreSQL.
    """
    config = configuracao_do_banco_de_teste()
    try:
        conn = connect(config["dbname"])
    except psycopg2.OperationalError as exc:
        raise pytest.UsageError(
            f"Cannot connect to the test database '{config['dbname']}' as "
            f"'{config['user']}'. Provision it once with "
            f"postgres/init/02-create-test-role-and-db.sql — e.g. "
            f"`docker compose exec postgres psql -U airflow -d airflow "
            f"-f /docker-entrypoint-initdb.d/02-create-test-role-and-db.sql`. "
            f"Original error: {exc}"
        ) from exc
    conn.close()
    yield


class DB:
    """Auxiliar para arranjar fixtures e observar o estado do banco nas asserções."""

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
    """Declara as `POSTGRES_*` apontando para o banco de teste, e restaura ao fim.

    Só os testes de `get_db_connection_str_from_env` — a única fronteira que lê o
    ambiente — precisam dela. Nenhuma função de produção lê ambiente, então a suíte não
    escreve nessas variáveis de forma global.
    """
    config = configuracao_do_banco_de_teste()
    variaveis = {
        "POSTGRES_HOST": config["host"],
        "POSTGRES_PORT": config["port"],
        "POSTGRES_USER": config["user"],
        "POSTGRES_PASSWORD": config["password"],
        "POSTGRES_DATA_DB": config["dbname"],
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

    Sem `autocommit`: as funções de produção chamam `commit()` e `rollback()`
    explicitamente, e com autocommit ligado o rollback não teria efeito observável, de modo
    que o teste mentiria sobre o comportamento transacional.

    Deve ser declarada **depois** de `test_db` na assinatura do teste: assim é finalizada
    antes dele, e a transação em aberto não bloqueia o `DROP TABLE` da limpeza.
    """
    conn = connect(configuracao_do_banco_de_teste()["dbname"], autocommit=False)
    try:
        yield conn
    finally:
        conn.close()


@pytest.fixture
def test_db(_verify_test_database):
    """Auxiliar ligado ao banco de teste, com o schema público limpo."""
    conn = connect(configuracao_do_banco_de_teste()["dbname"])
    _drop_all_public_tables(conn)
    helper = DB(conn)
    try:
        yield helper
    finally:
        _drop_all_public_tables(conn)
        conn.close()
