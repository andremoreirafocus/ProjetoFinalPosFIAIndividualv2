"""Isolation guarantee — the test role cannot reach the pipeline database.

This locks the security contract established by
``postgres/init/02-create-test-role-and-db.sql``: the least-privilege role the
suite runs as (``data_test_user``) may connect to the dedicated test database but
is refused by the pipeline database ``data`` (PUBLIC's CONNECT was revoked and the
role is not a superuser). If a future change re-granted access, this test goes red.
"""

import psycopg2
import pytest

from conftest import (
    PIPELINE_DB_NAME,
    TEST_DB_HOST,
    TEST_DB_NAME,
    TEST_DB_PASSWORD,
    TEST_DB_PORT,
    TEST_DB_USER,
)



def _connect(dbname: str):
    return psycopg2.connect(
        host=TEST_DB_HOST,
        port=TEST_DB_PORT,
        user=TEST_DB_USER,
        password=TEST_DB_PASSWORD,
        dbname=dbname,
    )


@pytest.mark.integration
def test_test_role_can_connect_to_test_database():
    conn = _connect(TEST_DB_NAME)
    conn.close()


@pytest.mark.integration
def test_test_role_cannot_connect_to_pipeline_database():
    with pytest.raises(psycopg2.OperationalError):
        _connect(PIPELINE_DB_NAME)
