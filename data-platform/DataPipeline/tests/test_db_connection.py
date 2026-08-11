"""Fronteira de configuração da conexão fora do Airflow.

Duas responsabilidades separadas: `get_db_connection_str_from_env` lê o ambiente e
monta a string de conexão; `get_pg_database_connection` abre a conexão a partir da
string recebida, sem consultar ambiente algum.

O contrato exercitado aqui inclui o que a resolução anterior violava: `POSTGRES_HOST`
vale sempre — o arranjo usa deliberadamente um host que não é `localhost` — e a
ausência de qualquer variável obrigatória falha nomeando qual, em vez de compor uma
string com `None`.
"""

import os

import pytest

from conftest import TEST_DB_NAME
from db import get_db_connection_str_from_env, get_pg_database_connection


VARIAVEIS_DE_CONEXAO = {
    "POSTGRES_USER": "analista_de_credito",
    "POSTGRES_PASSWORD": "senha_do_analista",
    "POSTGRES_HOST": "postgres.rede-do-compose",
    "POSTGRES_PORT": "6543",
    "POSTGRES_DATA_DB": "data_de_outro_ambiente",
}

CLIENTES = [
    {"sk_id_curr": 100001, "target": 0},
    {"sk_id_curr": 100002, "target": 1},
]
TABELA = "application_abt"


@pytest.fixture
def ambiente_de_conexao():
    """Arranja as variáveis `POSTGRES_*` e restaura o ambiente anterior ao fim.

    `get_db_connection_str_from_env` é, por contrato, a fronteira que lê o ambiente:
    arranjá-lo é preparar a entrada real da função, não interceptar sua execução.
    """
    anteriores = {nome: os.environ.get(nome) for nome in VARIAVEIS_DE_CONEXAO}

    def arranjar(variaveis: dict) -> None:
        for nome in VARIAVEIS_DE_CONEXAO:
            os.environ.pop(nome, None)
        os.environ.update(variaveis)

    yield arranjar

    for nome, valor in anteriores.items():
        if valor is None:
            os.environ.pop(nome, None)
        else:
            os.environ[nome] = valor


def test_monta_a_string_com_as_cinco_variaveis_do_ambiente(ambiente_de_conexao):
    ambiente_de_conexao(VARIAVEIS_DE_CONEXAO)

    connection_str = get_db_connection_str_from_env()

    assert connection_str == (
        f"postgresql://{VARIAVEIS_DE_CONEXAO['POSTGRES_USER']}"
        f":{VARIAVEIS_DE_CONEXAO['POSTGRES_PASSWORD']}"
        f"@{VARIAVEIS_DE_CONEXAO['POSTGRES_HOST']}"
        f":{VARIAVEIS_DE_CONEXAO['POSTGRES_PORT']}"
        f"/{VARIAVEIS_DE_CONEXAO['POSTGRES_DATA_DB']}"
    )


@pytest.mark.parametrize("ausente", sorted(VARIAVEIS_DE_CONEXAO))
def test_variavel_obrigatoria_ausente_falha_nomeando_qual(ambiente_de_conexao, ausente):
    ambiente_de_conexao(
        {nome: valor for nome, valor in VARIAVEIS_DE_CONEXAO.items() if nome != ausente}
    )

    with pytest.raises(ValueError) as erro:
        get_db_connection_str_from_env()

    assert ausente in str(erro.value)


@pytest.mark.integration
def test_conexao_abre_no_banco_nomeado_pela_string_recebida(test_db):
    test_db.create_table(TABELA, {"sk_id_curr": "BIGINT", "target": "BIGINT"})
    test_db.insert(TABELA, CLIENTES)

    conn = get_pg_database_connection(get_db_connection_str_from_env(), silent=True)
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT current_database()")
            banco = cursor.fetchone()[0]
            cursor.execute(f'SELECT COUNT(*) FROM "{TABELA}"')
            total = cursor.fetchone()[0]
    finally:
        conn.close()

    assert banco == TEST_DB_NAME
    assert total == len(CLIENTES)
