"""`get_database_engine` — o Engine do SQLAlchemy consumido pelos notebooks.

É a única função de banco do componente que nenhuma outra suíte alcança: seus consumidores
são `Model/validacao_modelos.ipynb`, `DataPipeline/exp_analysis_raw.ipynb` e
`DataPipeline/exp_analysis_abt.ipynb`, que não são exercitados por teste algum. Sem este
teste, uma alteração na função só apareceria ao abrir um notebook.

Contrato: o Engine é ligado ao banco nomeado pela string recebida — nada vem do
ambiente —, e é capaz de executar consulta e de alimentar `pandas.read_sql`, que é o uso
real nos três notebooks.
"""

import pandas as pd
import pytest
from sqlalchemy import text

from db import get_database_engine, get_db_connection_str_from_env


CLIENTES = [
    {"sk_id_curr": 100001, "target": 0},
    {"sk_id_curr": 100002, "target": 1},
]
TABELA = "application_abt"

DESTINO_DECLARADO = {
    "user": "analista_de_credito",
    "password": "senha_do_analista",
    "host": "postgres.rede-do-compose",
    "port": 6543,
    "dbname": "data_de_outro_ambiente",
}


def test_engine_aponta_para_o_banco_nomeado_na_string_recebida():
    """O destino vem do argumento, não do ambiente da suíte de testes."""
    connection_str = (
        f"postgresql://{DESTINO_DECLARADO['user']}:{DESTINO_DECLARADO['password']}"
        f"@{DESTINO_DECLARADO['host']}:{DESTINO_DECLARADO['port']}"
        f"/{DESTINO_DECLARADO['dbname']}"
    )

    engine = get_database_engine(connection_str, silent=True)

    assert (engine.url.host, engine.url.port, engine.url.database) == (
        DESTINO_DECLARADO["host"],
        DESTINO_DECLARADO["port"],
        DESTINO_DECLARADO["dbname"],
    )


@pytest.mark.integration
def test_engine_executa_consulta_no_banco_configurado(test_db, ambiente_do_banco_de_teste):
    test_db.create_table(TABELA, {"sk_id_curr": "BIGINT", "target": "BIGINT"})
    test_db.insert(TABELA, CLIENTES)

    engine = get_database_engine(get_db_connection_str_from_env(), silent=True)

    with engine.connect() as conexao:
        total = conexao.execute(text(f'SELECT COUNT(*) FROM "{TABELA}"')).scalar()

    assert total == len(CLIENTES)


@pytest.mark.integration
def test_engine_alimenta_read_sql_como_nos_notebooks(test_db, ambiente_do_banco_de_teste):
    test_db.create_table(TABELA, {"sk_id_curr": "BIGINT", "target": "BIGINT"})
    test_db.insert(TABELA, CLIENTES)

    engine = get_database_engine(get_db_connection_str_from_env(), silent=True)
    frame = pd.read_sql(f'SELECT * FROM "{TABELA}" ORDER BY sk_id_curr', engine)

    assert frame.to_dict("records") == CLIENTES
