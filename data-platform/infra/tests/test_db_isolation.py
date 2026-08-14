"""Isolation guarantee — the test role cannot reach the pipeline database.

This locks the security contract established by
``postgres/init/02-create-test-role-and-db.sql``: the least-privilege role the
suite runs as (``data_test_user``) may connect to the dedicated test database but
is refused by the pipeline database ``data`` (PUBLIC's CONNECT was revoked and the
role is not a superuser). If a future change re-granted access, this test goes red.
"""

import psycopg2
import pytest

from infra.testing import configuracao_do_banco_de_teste


def _connect(dbname: str):
    config = configuracao_do_banco_de_teste()
    return psycopg2.connect(
        host=config["host"],
        port=config["port"],
        user=config["user"],
        password=config["password"],
        dbname=dbname,
    )


@pytest.mark.integration
def test_test_role_can_connect_to_test_database():
    conn = _connect(configuracao_do_banco_de_teste()["dbname"])
    conn.close()


@pytest.mark.integration
def test_test_role_cannot_connect_to_pipeline_database():
    with pytest.raises(psycopg2.OperationalError):
        _connect(configuracao_do_banco_de_teste()["pipeline_dbname"])
